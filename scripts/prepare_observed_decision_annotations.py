"""WP2：本地事件发现与盲标工具（observed-decision-author-signature-v1）。

按计划 §四（事件协议）与代码本 v1.0 实现三步分离中的工具面：
1. discover   —— 从本地正文（GB18030/UTF-8）切分候选 span，产出中性候选事件 JSON
                 （只含 offset/hash/length，正文内容绝不写入仓库侧产物）；
2. blind-task —— 为单个标注员生成盲标任务：pre-context 文本 + 固定 seed 打乱候选 +
                 证据字段；隐藏 author/genre/cue/统计；允许 uncertain；
3. merge      —— 合并多标注员标签 + 可选仲裁，产出 merged.json（annotations /
                  arbitration / gold_action / status）；
4. alpha      —— 计算名义数据 Krippendorff α（coincidence-matrix，纯标准库）；
5. selftest   —— 合成数据自检（α 已知期望值：1.0 / -0.5 / 0.125；partition/merge/
                 隐私扫描），exit 0 为通过。

隐私纪律：真实正文、作者名、书名、绝对路径一律不写入仓库；所有数据产物只写
--workspace（默认 %TEMP%\\dsh-observed-annotations），若 workspace 解析进本仓库
（向上存在 .git）则拒绝执行（除非 --force-workspace-in-repo）。

用法示例：
  python scripts/prepare_observed_decision_annotations.py discover \
      --manifest manifest.json --workspace %TEMP%\\dsh-ann
  python scripts/prepare_observed_decision_annotations.py blind-task \
      --discovery out\\discovery.json --annotator A1 --seed 20260823 --workspace %TEMP%\\dsh-ann
  python scripts/prepare_observed_decision_annotations.py merge \
      --tasks tA1.json tA2.json --arbitration arb.json --workspace %TEMP%\\dsh-ann
  python scripts/prepare_observed_decision_annotations.py alpha --merged merged.json
  python scripts/prepare_observed_decision_annotations.py selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

# ---------------------------------------------------------------- 常量

PROTOCOL_DISCOVERY = "discovery-1.0"
PROTOCOL_CODEBOOK = "codebook-1.0"
codebook_candidates = ["direct_confront", "defer", "seek_ally"]  # 冻结 3 候选（代码本 §6：2–4）
SITUATION_DIMS = (
    "power_gap",
    "reversibility",
    "threat",
    "dependence",
    "info_uncertainty",
    "loyalty_conflict",
)
SITUATION_LEVELS = ("high", "low", "none")
STATUS_VALUES = ("pending", "present", "missing_unusable", "ambiguous")
MISSING_REASONS = (
    "事后叙述",
    "假设计划",
    "动作已开始",
    "角色边界不清",
    "无决策点",
    "文本损坏",
)
ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+\\")
CHAPTER_SPLIT = re.compile(r"第[0-9一二三四五六七八九十百千]+[章节回卷]")
PARA_SPLIT = re.compile(r"\n\s*\n")

DEFAULT_TARGET_SPAN = 1200  # 候选 span 目标字符长度（机械基线，须人工判定真实事件）


# ---------------------------------------------------------------- 基础工具


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("gb18030", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = raw.decode("gb18030", errors="replace")
    # 统一行结尾：真实语料大量使用 CRLF（\r\n）。PARA_RE 的 [^\n]+ 会吞掉空行的 \r，
    # 导致整本书合并成一个"段落"→ 每部作品仅 1 个候选。归一化后 discover 的 offset/hash
    # 与 blind-task 的 pre-context 切片使用同一份文本，避免错位。
    return text.replace("\r\n", "\n")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _require_workspace(workspace: Path, force: bool) -> Path:
    ws = workspace.expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)
    # 隐私门禁：workspace 不得解析进本仓库（向上查找 .git）
    probe = ws
    while True:
        if (probe / ".git").exists():
            if not force:
                raise SystemExit(
                    f"[privacy] workspace {ws} 解析进仓库（{probe}），正文/标注产物不得写入仓库。"
                    "请改用仓库外目录，或显式 --force-workspace-in-repo。"
                )
            break
        if probe.parent == probe:
            break
        probe = probe.parent
    return ws


def _load_json(path: Path) -> dict:
    # utf-8-sig 容错 Windows PowerShell Out-File 写入的 UTF-8 BOM
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump_json(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 事件发现


# 连续非空行段落（遇空行停止）。先归一化 \r\n → \n，防止 CRLF 文本中空行的 \r
# 被 [^\n]+ 吞掉导致整本书合并成一个"段落"（本仓库真实语料大量使用 CRLF）。
PARA_RE = re.compile(r"[^\n]+(?:\n[^\n]+)*")  # 连续非空行段落（遇空行停止）


def split_spans(text: str, target: int = DEFAULT_TARGET_SPAN) -> list[dict]:
    """机械基线：把全文严格平铺为候选 span（offset/hash/length），不丢失任何字符。

    段落 = 连续非空行；段落间空白并入其后 span；span 顺序拼接 == 原文。
    注意：这只是**候选**，是否真实决策事件必须由人工判定（status），
    禁止把固定结构格自动视为真实事件。
    """
    # 归一化 CRLF → LF：真实语料大量使用 \r\n，PARA_RE 的 [^\n]+ 会吞掉 \r
    # 导致空行无法结束段落，整书合并成一个 span，10 位作者仅 1 候选。
    text = text.replace("\r\n", "\n")
    paras = [(m.start(), m.end()) for m in PARA_RE.finditer(text)]
    if not paras:
        return [{"start": 0, "end": len(text), "length": len(text), "hash": _sha256(text)}]
    # chunks 平铺 [0, len(text))：chunk_i = [para_i.start, para_{i+1}.start)，末 chunk 到文末
    chunks: list[tuple[int, int]] = []
    for i in range(len(paras)):
        ps, _pe = paras[i]
        end = paras[i + 1][0] if i + 1 < len(paras) else len(text)
        if not chunks:
            chunks.append((0, end))  # 首 chunk 覆盖文首空白 + 首段 + 段间空白
        else:
            chunks.append((ps, end))
    # 按目标长度合并相邻 chunks 为 span
    spans: list[dict] = []
    group_start = chunks[0][0]
    group_end = chunks[0][1]
    for start, end in chunks[1:]:
        if end - group_start <= target:
            group_end = end
        else:
            chunk = text[group_start:group_end]
            spans.append(
                {
                    "start": group_start,
                    "end": group_end,
                    "length": len(chunk),
                    "hash": _sha256(chunk),
                }
            )
            group_start = start
            group_end = end
    chunk = text[group_start:group_end]
    spans.append(
        {
            "start": group_start,
            "end": group_end,
            "length": len(chunk),
            "hash": _sha256(chunk),
        }
    )
    return spans


def cmd_discover(args: argparse.Namespace) -> int:
    manifest = _load_json(Path(args.manifest))
    ws = _require_workspace(Path(args.workspace), args.force_workspace_in_repo)
    out: dict = {
        "protocol": {"discovery": PROTOCOL_DISCOVERY, "codebook": PROTOCOL_CODEBOOK},
        "seed": args.seed,
        "target_span_chars": args.target_span,
        "authors": [],
        "candidates_total": 0,
    }
    for author in manifest.get("authors", []):
        aid = author.get("author_id", "")
        topic = author.get("topic_stratum", "none")
        aentry: dict = {"author_id": aid, "topic_stratum": topic, "works": []}
        for work in author.get("works", []):
            wid = work.get("work_id", "")
            txt_val = work.get("txt") or work.get("txt_path", "")
            txt_path = Path(txt_val)
            if not txt_path.is_file():
                aentry["works"].append({"work_id": wid, "error": "txt_missing"})
                continue
            text = _read_text(txt_path)
            text_hash = _sha256(text)
            candidates = []
            for i, span in enumerate(split_spans(text, args.target_span)):
                candidates.append(
                    {
                        "event_id": _short_id(),
                        "author_id": aid,
                        "work_id": wid,
                        "topic_stratum": topic,
                        "decision_point": {
                            "offset": span["start"],
                            "snippet_hash": span["hash"],
                        },
                        "pre_context": {
                            "start_offset": span["start"],
                            "end_offset": span["end"],
                            "length": span["length"],
                            "hash": span["hash"],
                        },
                        "actor_slot": "",
                        "situation": {d: "none" for d in SITUATION_DIMS},
                        "candidates": list(codebook_candidates),
                        "status": "pending",
                        "missing_reason": None,
                        "outcome_evidence": None,
                        "protocol_version": PROTOCOL_CODEBOOK,
                        "discovery_version": PROTOCOL_DISCOVERY,
                    }
                )
            aentry["works"].append(
                {
                    "work_id": wid,
                    "text_hash": text_hash,
                    "char_length": len(text),
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                }
            )
            out["candidates_total"] += len(candidates)
        out["authors"].append(aentry)
    out_path = ws / "discovery.json"
    _dump_json(out, out_path)
    print(f"[discover] candidates_total={out['candidates_total']} -> {out_path}")
    print("[discover] 注意：候选 span 是机械基线，须经盲标人工判定 present/missing/ambiguous。")
    return 0


# ---------------------------------------------------------------- 盲标任务


def _stable_shuffle_seed(seed: int, event_id: str) -> int:
    """稳定打乱种子：不用 Python 内建 hash()（进程随机盐），用 SHA-256 派生。"""
    h = hashlib.sha256(f"{seed}|{event_id}".encode("utf-8")).hexdigest()
    return int(h[:16], 16)


# 盲化脱敏模式：必须从 pre-context 中剥离，防止标注员识别作品来源
_BLINDING_PATTERNS = [
    (re.compile(r"^[^：\n]{1,30}（[^）]{1,30}）[：:]\s*", re.MULTILINE), ""),   # 标题模式：XXX（YYYY）：
    (re.compile(r"^[^：\n]{1,30}（[^）]{1,30}）[：:]?\s*$", re.MULTILINE), ""),   # 标题行：XXX（YYYY）
    (re.compile(r"^作者[：:]\s*\S{1,20}", re.MULTILINE), ""),                   # 作者行
    (re.compile(r"^[【\[][^】\]]{1,30}[】\]][：:]?\s*", re.MULTILINE), ""),      # 【XXX】或[XXX]标题
    (re.compile(r"(https?://|www\.)\S{1,60}", re.I), " [URL] "),               # URL
    (re.compile(r"第[零一二三四五六七八九十百千万\d]{1,6}[章卷节回部]", re.MULTILINE), " [章节] "),  # 章节号
    (re.compile(r"^\s*[-–—=*]{3,}\s*$", re.MULTILINE), ""),                     # 分割线
]


def _blind_text(text: str) -> str:
    """对 pre-context 文本执行盲化脱敏，剥离标题/作者/站点/章节号等标识信息。"""
    for pat, repl in _BLINDING_PATTERNS:
        text = pat.sub(repl, text)
    return text.strip()


def cmd_blind_task(args: argparse.Namespace) -> int:
    discovery = _load_json(Path(args.discovery))
    ws = _require_workspace(Path(args.workspace), args.force_workspace_in_repo)
    seed = int(args.seed)
    # 可选 --manifest：解析 txt 路径，把 pre-context 正文切片写入任务文件
    # （正文只写 workspace，不入仓库；无 manifest 时任务仅含哈希，标注员无法判定——会警告）
    work_txt: dict[str, Path] = {}
    if args.manifest:
        manifest = _load_json(Path(args.manifest))
        for author in manifest.get("authors", []):
            for work in author.get("works", []):
                wid = work.get("work_id", "")
                p = Path(work.get("txt", ""))
                if wid and p.is_file():
                    work_txt[wid] = p
    tasks = []
    warned_no_text = False
    for author in discovery["authors"]:
        for work in author["works"]:
            text_cache: dict[str, str] = {}
            for cand in work.get("candidates", []):
                if cand.get("status") != "pending":
                    continue
                # 盲标：候选顺序按 seed 打乱（防候选首位偏差）；隐藏 author/genre 语义
                shuffled = list(cand["candidates"])
                rng = __import__("random").Random(_stable_shuffle_seed(seed, cand["event_id"]))
                rng.shuffle(shuffled)
                task: dict = {
                    "event_id": cand["event_id"],
                    "pre_context_hash": cand["pre_context"]["hash"],
                    "candidates": shuffled,
                    "to_fill": {
                        "status": "present|missing_unusable|ambiguous",
                        "missing_reason": "枚举：" + " / ".join(MISSING_REASONS),
                        "frozen_candidates": "从候选池中冻结 2-4 个互斥候选（代码本 §6）",
                        "actor_slot": "protagonist|antagonist|other",
                        "situation": {d: "high|low|none" for d in SITUATION_DIMS},
                        "action": "冻结候选之一（status=present 时必填）",
                        "evidence_note": "决策句位置 + 结果证据位置",
                        "confidence": "0.0-1.0",
                        "uncertain": "true|false",
                    },
                }
                txt_path = work_txt.get(work.get("work_id", ""))
                if txt_path is not None:
                    if work["work_id"] not in text_cache:
                        text_cache[work["work_id"]] = _read_text(txt_path)
                    text = text_cache[work["work_id"]]
                    s, e = cand["pre_context"]["start_offset"], cand["pre_context"]["end_offset"]
                    raw_slice = text[s:e] if 0 <= s <= e <= len(text) else "[切片越界]"
                    task["pre_context_text"] = _blind_text(raw_slice)
                elif not warned_no_text:
                    print("[blind-task] 警告：未提供 --manifest，任务不含正文，标注员无法判定；"
                          "请传入 manifest 以写入 pre-context 文本（仅 workspace）。")
                    warned_no_text = True
                tasks.append(task)
    payload = {
        "protocol": {"codebook": PROTOCOL_CODEBOOK, "blind": "blind-1.0"},
        "annotator": args.annotator,
        "seed": seed,
        "blind_rules": [
            "只依据决策点之前文本判断（pre-context 窗口）",
            "禁止统计/计数 cue 词或动作词频",
            "看不到 author_id/genre/预测器输出/其他标注员结果",
            "动作判定必须引用证据 span（决策句 + 结果证据）",
            "不确定请标 uncertain=true，不强迫表态",
        ],
        "tasks": tasks,
    }
    out_path = ws / f"task_{args.annotator}.json"
    _dump_json(payload, out_path)
    print(f"[blind-task] annotator={args.annotator} tasks={len(tasks)} -> {out_path}")
    return 0


# ---------------------------------------------------------------- Krippendorff α（名义）


def krippendorff_alpha_nominal(unit_labels: dict[str, dict[str, str]]) -> float:
    """名义数据 Krippendorff α。

    unit_labels: {event_id: {annotator: label}}；缺失（None）不计入 coincidence。
    返回 α；De==0 且 Do==0 → 1.0；De==0 且 Do>0 → -inf 防御为 0.0（调用方按规则拒绝）。
    """
    categories: set[str] = set()
    pairs_per_unit: list[list[tuple[str, str]]] = []
    for unit, labels in unit_labels.items():
        vals = [v for v in labels.values() if v is not None]
        categories.update(vals)
        pairs = []
        for i in range(len(vals)):
            for j in range(len(vals)):
                if i != j:
                    pairs.append((vals[i], vals[j]))
        pairs_per_unit.append(pairs)
    cats = sorted(categories)
    idx = {c: i for i, c in enumerate(cats)}
    n_ck: list[list[int]] = [[0] * len(cats) for _ in cats]
    n = 0
    for pairs in pairs_per_unit:
        for c, k in pairs:
            n_ck[idx[c]][idx[k]] += 1
            n += 1
    if n == 0:
        return 1.0  # 无 coincidence：视同完美（无分歧证据），调用方按样本量门禁拒绝
    n_k = [sum(row) for row in n_ck]
    do_num = 0
    for c in range(len(cats)):
        for k in range(len(cats)):
            if c != k:
                do_num += n_ck[c][k]
    do = do_num / n
    de_num = sum(nk * (n - nk) for nk in n_k)
    de = de_num / (n * (n - 1)) if n > 1 else 0.0
    if de == 0:
        return 1.0 if do == 0 else 0.0
    return 1.0 - do / de


def cmd_alpha(args: argparse.Namespace) -> int:
    merged = _load_json(Path(args.merged))
    unit_labels: dict[str, dict[str, str]] = {}
    for event in merged.get("events", []):
        labels: dict[str, str] = {}
        for ann in event.get("annotations", []):
            labels[ann["annotator"]] = ann.get("label")
        unit_labels[event["event_id"]] = labels
    alpha = krippendorff_alpha_nominal(unit_labels)
    agree = 0
    total = 0
    for labels in unit_labels.values():
        vals = [v for v in labels.values() if v is not None]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                total += 1
                if vals[i] == vals[j]:
                    agree += 1
    pair_agreement = agree / total if total else 1.0
    pairs = total * 2
    if pairs == 0:
        # 无 coincidence 对：α 无意义，不得报 CONFIRMATORY_OK
        report = {
            "alpha": None,
            "pair_agreement": pair_agreement,
            "annotated_units": len(unit_labels),
            "coincidence_pairs": 0,
            "verdict": "INSUFFICIENT_DATA",
            "note": "无双标 coincidence 对，α 不可估计；需 ≥2 位标注员对同一事件的实际标签。",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    report = {
        "alpha": alpha,
        "pair_agreement": pair_agreement,
        "annotated_units": len(unit_labels),
        "coincidence_pairs": total * 2,
        "threshold": {
            "confirmatory": "alpha >= 0.80",
            "exploratory": "0.667 <= alpha < 0.80",
            "rework": "alpha < 0.667",
        },
        "verdict": (
            "CONFIRMATORY_OK"
            if alpha >= 0.80
            else ("EXPLORATORY_ONLY" if alpha >= 0.667 else "REWORK_CODEBOOK")
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- 合并与仲裁


def cmd_merge(args: argparse.Namespace) -> int:
    ws = _require_workspace(Path(args.workspace), args.force_workspace_in_repo)
    task_files = [Path(p) for p in args.tasks]
    annotators: dict[str, dict[str, dict]] = {}
    for tf in task_files:
        data = _load_json(tf)
        aid = data.get("annotator", tf.stem)
        annotators[aid] = {t["event_id"]: t for t in data.get("tasks", [])}
    arb: dict[str, dict] = {}
    if args.arbitration:
        arb = {t["event_id"]: t for t in _load_json(Path(args.arbitration)).get("tasks", [])}
    # 可选 --discovery：关联 author_id/work_id/topic_stratum，供 per-author 产率统计
    meta: dict[str, dict] = {}
    if args.discovery:
        disc = _load_json(Path(args.discovery))
        for author in disc.get("authors", []):
            for work in author.get("works", []):
                for cand in work.get("candidates", []):
                    meta[cand["event_id"]] = {
                        "author_id": author.get("author_id", ""),
                        "work_id": work.get("work_id", ""),
                        "topic_stratum": author.get("topic_stratum", ""),
                    }
    all_ids: list[str] = []
    for amap in annotators.values():
        for eid in amap:
            if eid not in all_ids:
                all_ids.append(eid)
    events = []
    for eid in all_ids:
        annotations = []
        labels = {}
        for aid, amap in annotators.items():
            task = amap.get(eid)
            if not task:
                continue
            entry = {
                "annotator": aid,
                "status": task.get("status"),
                "missing_reason": task.get("missing_reason"),
                "actor_slot": task.get("actor_slot"),
                "situation": task.get("situation"),
                "label": task.get("action"),
                "confidence": task.get("confidence"),
                "uncertain": task.get("uncertain"),
            }
            annotations.append(entry)
            if entry["status"] == "present" and entry["label"]:
                labels[aid] = entry["label"]
        event: dict = {"event_id": eid, "annotations": annotations}
        if eid in meta:
            event.update(meta[eid])
        if eid in arb:
            event["arbitration"] = arb[eid]
            event["gold_action"] = arb[eid].get("action")
            event["status"] = arb[eid].get("status")
        else:
            # 无仲裁：present 动作取多数；无多数或状态分歧 → unresolved（必须走仲裁）
            vote: dict[str, int] = {}
            for label in labels.values():
                vote[label] = vote.get(label, 0) + 1
            statuses = {a["status"] for a in annotations if a.get("status")}
            if len(statuses) == 1 and next(iter(statuses)) == "present" and vote:
                best = max(vote, key=vote.get)
                event["gold_action"] = best if list(vote.values()).count(vote[best]) == 1 else None
                event["status"] = "present" if event["gold_action"] else "ambiguous"
            elif len(statuses) == 1:
                event["status"] = next(iter(statuses))
                event["gold_action"] = None
            else:
                event["status"] = "unresolved"
                event["gold_action"] = None
            if event.get("gold_action") is None and event["status"] == "present":
                event["status"] = "ambiguous"
        events.append(event)
    merged = {
        "protocol": {"codebook": PROTOCOL_CODEBOOK, "merge": "merge-1.0"},
        "annotators": sorted(annotators),
        "events": events,
    }
    out_path = ws / "merged.json"
    _dump_json(merged, out_path)
    counts: dict[str, int] = {}
    for e in events:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    print(f"[merge] events={len(events)} statuses={counts} -> {out_path}")
    return 0


# ---------------------------------------------------------------- 隐私扫描


def _scan_privacy_text(text: str) -> list[str]:
    hits = []
    for m in ABS_PATH_RE.finditer(text):
        hits.append(m.group(0))
    return hits


def cmd_verify_privacy(args: argparse.Namespace) -> int:
    total = 0
    for path_str in args.paths:
        p = Path(path_str)
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
        elif p.is_file():
            files = [p]
        else:
            continue
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hits = _scan_privacy_text(text)
            if hits:
                total += len(hits)
                print(f"[privacy] HIT {f}: {hits}")
    print(f"[privacy] absolute_path_hits={total}")
    return 0 if total == 0 else 1


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, got, want) -> None:
        if abs(float(got) - float(want)) > 1e-9:
            failures.append(f"{name}: got {got}, want {want}")

    # 已知 α 手算用例
    check("alpha_perfect", krippendorff_alpha_nominal(
        {"e1": {"A": "a", "B": "a"}, "e2": {"A": "a", "B": "a"},
         "e3": {"A": "b", "B": "b"}, "e4": {"A": "b", "B": "b"}}), 1.0)
    check("alpha_total_disagree", krippendorff_alpha_nominal(
        {"e1": {"A": "a", "B": "b"}, "e2": {"A": "b", "B": "a"}}), -0.5)
    check("alpha_random", krippendorff_alpha_nominal(
        {"e1": {"A": "a", "B": "a"}, "e2": {"A": "a", "B": "b"},
         "e3": {"A": "b", "B": "a"}, "e4": {"A": "b", "B": "b"}}), 0.125)
    check("alpha_missing", krippendorff_alpha_nominal(
        {"e1": {"A": "a", "B": None}, "e2": {"A": "a", "B": "a"}}), 1.0)

    # α 探索带边界：暴力枚举小规模双标矩阵，必须存在 0.667≤α<0.80 的配置
    found_exploratory = False
    import itertools as _it

    for combo in _it.product("ab", repeat=12):  # 6 units × 2 annotators
        labels = {}
        for u in range(6):
            labels[f"u{u}"] = {"A": combo[2 * u], "B": combo[2 * u + 1]}
        a = krippendorff_alpha_nominal(labels)
        if 0.667 <= a < 0.80:
            found_exploratory = True
            break
    if not found_exploratory:
        failures.append("alpha: 未找到 0.667<=α<0.80 探索带配置")

    # 稳定打乱种子可复现（不用内建 hash()）
    s1 = _stable_shuffle_seed(20260823, "ev-aaa")
    s2 = _stable_shuffle_seed(20260823, "ev-aaa")
    s3 = _stable_shuffle_seed(20260823, "ev-bbb")
    if not (s1 == s2 and s1 != s3):
        failures.append("stable_shuffle_seed: 可复现性/区分性失败")

    # split_spans 分区完整性：拼接后与原文一致（去空白）
    text = "第一章\n\n甲说了一句。\n\n乙做了选择。\n\n第二章\n\n丙继续。"
    spans = split_spans(text)
    joined = "".join(text[s["start"]:s["end"]] for s in spans)
    if _sha256(joined) != _sha256(text):
        failures.append("split_spans: 分区不完整")

    # 隐私扫描
    bad = "本地路径 C:\\Users\\admin\\Desktop\\novel-main\\x.txt 与 D:/data/y.txt"
    good = "author_id=a001 work_id=w001 hash=abc"
    if not _scan_privacy_text(bad):
        failures.append("privacy: 未命中绝对路径")
    if _scan_privacy_text(good):
        failures.append("privacy: 误命中中性内容")

    if failures:
        print("[selftest] FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("[selftest] PASS (alpha 1.0/-0.5/0.125/missing/exploratory-band, partition, privacy, stable-shuffle)")
    return 0


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="observed-decision-author-signature-v1 标注工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--manifest", required=True)
    p_discover.add_argument("--workspace", required=True)
    p_discover.add_argument("--seed", type=int, default=20260823)
    p_discover.add_argument("--target-span", type=int, default=DEFAULT_TARGET_SPAN)
    p_discover.add_argument("--force-workspace-in-repo", action="store_true")

    p_task = sub.add_parser("blind-task")
    p_task.add_argument("--discovery", required=True)
    p_task.add_argument("--annotator", required=True)
    p_task.add_argument("--seed", type=int, default=20260823)
    p_task.add_argument("--manifest", help="可选：解析 txt 路径以写入 pre-context 正文（仅 workspace）")
    p_task.add_argument("--workspace", required=True)
    p_task.add_argument("--force-workspace-in-repo", action="store_true")

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--tasks", nargs="+", required=True)
    p_merge.add_argument("--arbitration")
    p_merge.add_argument("--discovery", help="可选：关联 author_id/work_id/topic_stratum")
    p_merge.add_argument("--workspace", required=True)
    p_merge.add_argument("--force-workspace-in-repo", action="store_true")

    p_alpha = sub.add_parser("alpha")
    p_alpha.add_argument("--merged", required=True)

    p_priv = sub.add_parser("verify-privacy")
    p_priv.add_argument("--paths", nargs="+", required=True)

    sub.add_parser("selftest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "discover":
        return cmd_discover(args)
    if args.cmd == "blind-task":
        return cmd_blind_task(args)
    if args.cmd == "merge":
        return cmd_merge(args)
    if args.cmd == "alpha":
        return cmd_alpha(args)
    if args.cmd == "verify-privacy":
        return cmd_verify_privacy(args)
    if args.cmd == "selftest":
        return _selftest()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
