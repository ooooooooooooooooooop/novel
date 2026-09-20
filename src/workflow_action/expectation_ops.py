"""Expectation Ops — dim7 信息缺口/预测管理（read-side 机制）.

两块能力（裁决冻结）：
A. Expectation progression——开放预期是否持续真正推进，而非原地悬置；
   due-event 哨兵 SUSPENSE_BY_WITHHOLDING_REQUIRED_EVENT：
   回答/行动已因果到期 ∧ 无正文真实阻碍 ∧ 未兑现 ∧ 读者状态无有效更新
   → suspense_by_withholding blocking。
B. Prediction baseline——发生 reveal/FLIP 时读者是否有 grounded
   dominant_prediction 可被打破；无基线/依赖隐藏前提只报告不改写。

Grounding 纪律（plan→fact 不混）：ExpectationUpdateIntent 是计划，
ReaderExpectation 的 possibilities/dominant_prediction 只能由
accepted-prose 的 post-prose 抽取更新（evidence 须逐字命中正文）。

冻结核心定义：合法悬念=问题未解但读者可能性/风险/代价/预测有变化；
非法拖延=问题未解+本应发生未发生+读者状态无有效更新。
"""

import json
import re
from typing import Optional

from src.object_state import (
    ReaderExpectation,
    ReaderExpectationLedger,
    ReviewIssue,
)
from src.workflow_action.review import narrative_spans_numbered


# ---------------------------------------------------------------------------
# Post-prose reader-state grounding（accepted prose → ledger 更新）
# ---------------------------------------------------------------------------


def build_reader_state_prompt(
    ledger: ReaderExpectationLedger, prose_text: str
) -> str:
    """post-prose 读者状态抽取 prompt（accepted prose 唯一事实源）."""
    open_items = ledger.open_expectations()
    if not open_items:
        exp_lines = "（无开放预期）"
    else:
        exp_lines = "\n".join(
            f"- [{e.expectation_id}] [{e.mode}] {e.reader_question}"
            + (f"｜当前默认预测：{e.dominant_prediction}" if e.dominant_prediction else "")
            + (f"｜可能性：{'；'.join(e.possibilities)}" if e.possibilities else "")
            + (f"｜代价：{e.stakes}" if e.stakes else "")
            for e in open_items
        )
    return (
        "你是读者状态提取器。给定小说正文与读者预期台账，抽取本章正文"
        "对每条开放预期造成的真实读者状态变化。只抽正文真实发生的事——"
        "计划/意图不是事实；正文没做到的更新不得申报。\n\n"
        "【开放预期台账】\n" + exp_lines + "\n\n"
        "【本章正文】\n" + prose_text[:8000] + "\n\n"
        "【输出 JSON】\n"
        "{\n"
        '  "updates": [{\n'
        '    "expectation_id": "台账中的 id",\n'
        '    "update_kind": "none|narrowed|strengthened|weakened|flipped|resolved——'
        '本章正文对该预期造成的变化：narrowed=可能性空间收窄；'
        'strengthened=读者更倾向某个判断；weakened=当前预测被动摇；'
        'flipped=结果违反了已建立的读者预测；resolved=问题被回答/兑现",\n'
        '    "new_possibilities": ["更新后的读者可能性空间，无变化则空"],\n'
        '    "new_dominant_prediction": "正文建立的读者默认预测，无则null",\n'
        '    "evidence_excerpt": "支撑本次更新的正文原句（逐字摘录，≤80字）"\n'
        "  }],\n"
        '  "new_expectations": [{\n'
        '    "reader_question": "本章新开启的、读者将等待的问题",\n'
        '    "mode": "curiosity|suspense",\n'
        '    "stakes": "suspense 模式的代价/风险，否则null",\n'
        '    "possibilities": ["读者当前合理可能性，可空"],\n'
        '    "evidence_excerpt": "正文原句（逐字摘录，≤80字）"\n'
        "  }]\n"
        "}\n\n"
        "规则：update_kind=none 的行可省略；没有证据摘录的更新一律不得申报；"
        "新预期必须是读者视角真实会等待的问题（重大未解之谜/迫近危险），"
        "不是每件小事。只输出 JSON。"
    )


def parse_reader_state_response(response: str) -> dict:
    """解析 reader-state 抽取响应；失败返回空更新."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {"updates": [], "new_expectations": []}
    if not isinstance(data, dict):
        return {"updates": [], "new_expectations": []}
    return {
        "updates": data.get("updates") or [],
        "new_expectations": data.get("new_expectations") or [],
    }


def _grounded(excerpt: Optional[str], prose_text: str) -> bool:
    """证据摘录须为正文规范化子串（grounding 硬门）."""
    if not excerpt or not excerpt.strip():
        return False
    norm = re.sub(r"\s+", "", excerpt)
    hay = re.sub(r"\s+", "", prose_text)
    return bool(norm) and norm in hay


def apply_reader_state_grounding(
    ledger: ReaderExpectationLedger,
    parsed: dict,
    prose_text: str,
    chapter_ref: str = "",
) -> dict:
    """确定性应用 grounded 更新；返回遥测 {applied, rejected, opened}.

    - evidence_excerpt 非正文子串 → 该条更新整体拒绝（防 plan→fact 污染）
    - strengthened + new_dominant_prediction：仅当 grounded 才落预测
    - flipped：dominant_prediction 被消费（清 None），记推进
    - resolved：status=resolved（保留审计不再追问）
    - 新预期：evidence 须 grounded；source_thread_id=None（非伏笔派生）
    """
    applied = 0
    rejected = 0
    opened = 0
    for u in parsed.get("updates") or []:
        eid = u.get("expectation_id")
        kind = u.get("update_kind")
        entry = ledger.get(eid) if eid else None
        if entry is None or kind in (None, "none"):
            continue
        if not _grounded(u.get("evidence_excerpt"), prose_text):
            rejected += 1
            continue
        applied += 1
        entry.advancement_count += 1
        entry.last_advanced_at = chapter_ref or entry.last_advanced_at
        poss = u.get("new_possibilities") or []
        if isinstance(poss, list) and poss:
            entry.possibilities = [p for p in poss if isinstance(p, str) and p.strip()]
        if kind == "strengthened":
            pred = u.get("new_dominant_prediction")
            if isinstance(pred, str) and pred.strip():
                entry.dominant_prediction = pred.strip()
            entry.status = "advanced"
        elif kind == "weakened":
            entry.dominant_prediction = None
            entry.status = "advanced"
        elif kind == "narrowed":
            entry.status = "advanced"
        elif kind == "flipped":
            entry.dominant_prediction = None
            entry.status = "advanced"
        elif kind == "resolved":
            entry.status = "resolved"
        ev = u.get("evidence_excerpt")
        if ev and ev not in entry.evidence_refs:
            entry.evidence_refs.append(ev[:120])
    for n in parsed.get("new_expectations") or []:
        q = n.get("reader_question")
        if not isinstance(q, str) or not q.strip():
            continue
        if not _grounded(n.get("evidence_excerpt"), prose_text):
            rejected += 1
            continue
        eid = f"re_new_{len(ledger.expectations) + 1}"
        if ledger.get(eid):
            eid = f"re_new_{len(ledger.expectations) + 1}_{opened}"
        mode = n.get("mode") if n.get("mode") in ("curiosity", "suspense") else "curiosity"
        stakes = n.get("stakes")
        poss = [p for p in (n.get("possibilities") or [])
                if isinstance(p, str) and p.strip()]
        ledger.upsert(
            ReaderExpectation(
                expectation_id=eid,
                reader_question=q.strip(),
                source_thread_id=None,
                importance="medium",
                opened_at=chapter_ref or "本章",
                mode=mode,
                possibilities=poss,
                stakes=stakes.strip() if isinstance(stakes, str) and stakes.strip() else None,
                evidence_refs=[n.get("evidence_excerpt", "")[:120]],
            )
        )
        opened += 1
    return {"applied": applied, "rejected": rejected, "opened": opened}


# ---------------------------------------------------------------------------
# Due-event 哨兵（SUSPENSE_BY_WITHHOLDING_REQUIRED_EVENT）+ surprise 基线
# ---------------------------------------------------------------------------


def due_event_candidates(ledger: ReaderExpectationLedger) -> list[dict]:
    """机械候选：全部 OPEN 预期（高召回不定罪；due 信号由仲裁抽事实）.

    裁决冻结的 due 信号（仲裁判断，非机械检测）：被当面问到/相关人物
    物证到场/deadline 到达/前置任务完成/scene goal 直入/承诺到兑现节点。
    """
    return [
        {
            "expectation_id": e.expectation_id,
            "reader_question": e.reader_question,
            "mode": e.mode,
            "status": e.status,
            "has_dominant_prediction": bool(e.dominant_prediction),
        }
        for e in ledger.open_expectations()
    ]


def build_expectation_adjudication_prompt(
    prose_text: str, candidates: list[dict]
) -> str:
    """预期仲裁 prompt：只抽事实不判严重度."""
    spans = narrative_spans_numbered(prose_text)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- [{c['expectation_id']}] {c['reader_question']}"
        f"（mode={c['mode']}, status={c['status']}）"
        for c in candidates
    )
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号；"
        "另给出读者预期台账中的开放预期。对每条预期抽取本章事实。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【开放预期】\n" + cand_lines + "\n\n"
        "【抽取项】对每条预期输出：\n"
        "{\"expectation_id\":\"id\","
        "\"due_signal\":{\"present\":true|false,\"kind\":\"asked_directly|"
        "evidence_present|deadline_reached|prereq_done|scene_goal_direct|"
        "commitment_due 之一或null\",\"evidence\":\"触发句段号或null\"},"
        "\"answer_or_action_available_now\":true|false,"
        "\"causal_preconditions_met\":true|false,"
        "\"delivered\":true|false——本章回答/行动/兑现是否真实发生,"
        "\"legitimate_blocker_present\":true|false——正文真实发生的阻碍"
        "（物证被毁/人物被强制带走/新事实证明问题问错/兑现需要当前不存在"
        "的资源；『作者想留悬念』不是合法阻碍）,"
        "\"blocker_evidence\":\"合法阻碍的正文证据或null\","
        "\"meaningful_expectation_update_present\":true|false——答案虽未给但"
        "读者可能性空间/风险/代价/预测发生了真实变化（如『发现A根本没死』"
        "改变了问题本身）,"
        "\"reveal_or_flip_occurred\":true|false——本章是否发生了对该预期的"
        "重大揭晓/结果反转：揭晓内容须显著超出或违反读者已建立的期待方向"
        "（身份颠覆/立场反转/真相翻盘）；普通问答的如期兑现不算揭晓/反转,"
        "\"hidden_premise_required\":true|false——揭晓/反转是否依赖一个"
        "按 POV/场景逻辑本应可见却被一直藏住的关键前提（仅当 "
        "reveal_or_flip_occurred=true 时填写，否则 null）}\n\n"
        "注意：只输出 JSON：{\"candidates\":[..]}"
    )


def parse_expectation_adjudication(response: str) -> dict:
    """解析预期仲裁响应；失败返回空."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_expectation_adjudication_runs(runs: list[dict]) -> dict:
    """多次仲裁按 expectation_id 对齐取多数事实."""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    by_id: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("candidates") or []:
            eid = c.get("expectation_id")
            if eid:
                by_id.setdefault(eid, []).append(c)
    merged = []
    for eid, cs in by_id.items():
        n = len(cs)

        def _mj(getter):
            return sum(1 for c in cs if getter(c)) > n / 2

        due_present = _mj(lambda c: isinstance(c.get("due_signal"), dict)
                          and c["due_signal"].get("present"))
        due_kind = next(
            (c["due_signal"].get("kind") for c in cs
             if isinstance(c.get("due_signal"), dict)
             and c["due_signal"].get("present")
             and c["due_signal"].get("kind")), None)
        merged.append({
            "expectation_id": eid,
            "due_signal_present": due_present,
            "due_signal_kind": due_kind,
            "answer_or_action_available_now": _mj(
                lambda c: c.get("answer_or_action_available_now")),
            "causal_preconditions_met": _mj(
                lambda c: c.get("causal_preconditions_met")),
            "delivered": _mj(lambda c: c.get("delivered")),
            "legitimate_blocker_present": _mj(
                lambda c: c.get("legitimate_blocker_present")),
            "blocker_evidence": next(
                (c.get("blocker_evidence") for c in cs
                 if c.get("blocker_evidence")), None),
            "meaningful_expectation_update_present": _mj(
                lambda c: c.get("meaningful_expectation_update_present")),
            "reveal_or_flip_occurred": _mj(
                lambda c: c.get("reveal_or_flip_occurred")),
            "hidden_premise_required": _mj(
                lambda c: c.get("hidden_premise_required")),
            "votes": n,
        })
    return {"candidates": merged}


def expectation_verdict(facts: dict, ledger: ReaderExpectationLedger) -> dict:
    """确定性裁决（dim7）.

    - suspense_by_withholding（blocking）：due∧available∧preconditions
      ∧ ¬delivered ∧ ¬legitimate_blocker ∧ ¬meaningful_update
    - surprise_without_prediction_baseline（warning）：reveal/flip 发生
      但此前台账无 grounded dominant_prediction
    - surprise_requires_hidden_premise（warning）：reveal/flip 依赖
      POV 本应可见却被藏的前提
    """
    verdicts: list[dict] = []
    for c in facts.get("candidates") or []:
        eid = c.get("expectation_id")
        if (c.get("due_signal_present")
                and c.get("answer_or_action_available_now")
                and c.get("causal_preconditions_met")
                and not c.get("delivered")
                and not c.get("legitimate_blocker_present")
                and not c.get("meaningful_expectation_update_present")):
            verdicts.append({
                "expectation_id": eid,
                "verdict": "suspense_by_withholding",
                "severity": "blocking",
            })
            continue
        if c.get("reveal_or_flip_occurred"):
            entry = ledger.get(eid) if eid else None
            has_baseline = bool(entry and entry.dominant_prediction)
            if c.get("hidden_premise_required"):
                verdicts.append({
                    "expectation_id": eid,
                    "verdict": "surprise_requires_hidden_premise",
                    "severity": "warning",
                })
            elif not has_baseline:
                verdicts.append({
                    "expectation_id": eid,
                    "verdict": "surprise_without_prediction_baseline",
                    "severity": "warning",
                })
    return {"verdicts": verdicts}


_EXPECTATION_ADJUDICATED_TYPES = frozenset({
    "suspense_by_withholding",
    "surprise_without_prediction_baseline",
    "surprise_requires_hidden_premise",
})
_EXPECTATION_BLOCKING_TYPES = frozenset({"suspense_by_withholding"})


def expectation_verdict_names(verdict_result: dict) -> list[str]:
    return [v["verdict"] for v in (verdict_result or {}).get("verdicts") or []]


def apply_expectation_adjudication(
    issues: list,
    verdict_result: dict,
    ledger: ReaderExpectationLedger | None = None,
) -> tuple[list, list[str]]:
    """把预期裁决应用回 issue 集合；返回 (issues, blocking_verdicts)."""
    issues = list(issues)
    verdicts = (verdict_result or {}).get("verdicts") or []
    if not verdicts:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _EXPECTATION_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical", "warning"))]
        return issues, []
    out_issues = issues
    blocking_names: list[str] = []
    for idx, v in enumerate(verdicts):
        vtype = v["verdict"]
        eid = v.get("expectation_id") or ""
        entry = ledger.get(eid) if ledger else None
        q = entry.reader_question if entry else eid
        severity = "blocking" if vtype in _EXPECTATION_BLOCKING_TYPES else "warning"
        if vtype in _EXPECTATION_BLOCKING_TYPES:
            blocking_names.append(vtype)
        desc = f"expectation adjudicator verdict={vtype} | 预期: 「{q}」"
        if vtype == "suspense_by_withholding":
            desc += ("——回答/行动已因果到期，正文未兑现、无合法阻碍、"
                     "读者状态亦无有效更新（为留悬念推迟本应发生的事件）")
        elif vtype == "surprise_without_prediction_baseline":
            desc += ("——发生揭晓/反转但读者此前无 grounded 默认预测，"
                     "不构成 earned surprise（仅报告不自动改写）")
        else:
            desc += ("——反转依赖 POV 本应可见却被藏住的关键前提"
                     "（仅报告不自动改写）")
        out_issues.append(ReviewIssue(
            issue_id=f"exp_adj_{idx + 1}",
            issue_type=vtype,
            severity=severity,
            location=f"读者预期 {eid}",
            scope_of_impact="信息缺口/预测管理",
            violated_rule="读者预期推进与 earned surprise 基线",
            description=desc,
            suggested_fix=(
                "让本应发生的回答/行动本场真实发生（DELIVER_DUE_ANSWER），"
                "或删除人为延迟手段（REMOVE_ARTIFICIAL_DELAY），"
                "或把已存在证据写入可见层（SURFACE_EXISTING_EVIDENCE）"
            ) if severity == "blocking" else None,
        ))
    return out_issues, blocking_names
