"""Blank Ops — dim8a 计划性留白（intended inference 定向核验）.

与 RCC 的通用认知劳动分配兜底不同：本模块只对「Continue 已声明、
PlotUnit 已冻结」的 InferenceHandoff 做定向核验——声明了留白，
review 只验证不补造（authority：planning owns / continue 实例化 /
prose 消费 / review 只验，禁止事后创建 intention）。

裁决冻结的三态（对已声明且 explicitness != must_explain 的交接点）：
- 证据足 + 结论未明说           → none
- 证据足 + 结论被正文陈述/等价解释 → blank_inference_made_explicit（blocking）
- 证据不足 + 结论未明说          → blank_under_evidenced（blocking）
- 证据不足 + 结论明说            → 主判 MADE_EXPLICIT，证据不足作诊断事实

target（reader_inference）非唯一正确答案：判「合理读者能否凭可见证据
完成该推断」，不是「文本是否唯一推出此答案」。
"""

import json
import pathlib
import re

from src.object_state import PlotUnit, ReviewIssue
from src.workflow_action.review import narrative_spans_numbered


def blank_candidates(plotunit: PlotUnit | None) -> list[dict]:
    """已声明留白的交接点（explicitness != must_explain）。

    must_explain 交接点声明了「读者无法推断、必须明说」——不构成留白，
    不进入本核验。explicit_when_condition 进入核验：条件未满足却说破
    同样算 MADE_EXPLICIT。
    """
    if plotunit is None or not getattr(plotunit, "reader_handoffs", None):
        return []
    cands = []
    for idx, h in enumerate(plotunit.reader_handoffs, 1):
        if getattr(h, "explicitness", "leave_implicit") == "must_explain":
            continue
        if getattr(h, "evidence_sufficiency", "sufficient") == "must_explicit":
            continue
        cands.append({
            "handoff_id": f"h{idx}",
            "evidence": h.evidence,
            "reader_inference": h.reader_inference,
            "explicitness": h.explicitness,
            "explicit_when": getattr(h, "explicit_when", None),
            "evidence_sufficiency": getattr(
                h, "evidence_sufficiency", "sufficient"),
        })
    return cands


def build_blank_adjudication_prompt(
    prose_text: str, candidates: list[dict]
) -> str:
    """留白核验 prompt：只抽事实不判严重度.

    keep_dialogue=True：对白既可承载证据也可把结论说破——剥除引号内容
    会让核验对对白说破/对白证据系统性失明。
    """
    spans = narrative_spans_numbered(prose_text, keep_dialogue=True)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- [{c['handoff_id']}] 计划证据: {c['evidence']}\n"
        f"  读者应自行完成的推断: {c['reader_inference']}\n"
        f"  显式政策: {c['explicitness']}"
        + (f"（显式条件: {c['explicit_when']}）" if c.get("explicit_when") else "")
        for c in candidates
    )
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号；"
        "另给出本章已声明的留白交接点——作者计划呈现某些证据、"
        "故意不把某个推断明说，让读者自己完成最后一步。"
        "对每个交接点抽取本章事实。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【已声明留白交接点】\n" + cand_lines + "\n\n"
        "【抽取项】对每个交接点输出：\n"
        "{\"handoff_id\":\"hN\","
        "\"inference_made_explicit\":true|false——该推断是否在正文中被"
        "直接陈述或等价解释（旁白总结、内心总结、对白把结论说破都算；"
        "陈述推断的核心结论或其关键组成部分也算，不要求全部要素明说；"
        "仅呈现证据让读者自己推不算）,"
        "\"explicit_excerpt\":\"陈述该推断的正文原句（逐字摘录，≤60字）或null\","
        "\"explicit_condition_met\":true|false|null——仅当该交接点声明了"
        "显式条件时判断：条件在正文中是否真实满足（无条件交接点填null）,"
        "\"evidence_present\":true|false——计划证据是否在正文中真实呈现"
        "（须是读者可见的动作/对白/细节，不是仅在计划里写了）,"
        "\"evidence_excerpt\":\"呈现该证据的正文原句（逐字摘录，≤60字）或null\","
        "\"evidence_sufficient\":true|false——仅据当前可见证据，合理读者"
        "能否完成该推断（不要求唯一答案；问的是证据是否足以支撑这一"
        "inferential step，不是读者是否只能推出这一个结论）}\n\n"
        "注意：只输出 JSON：{\"candidates\":[..]}"
    )


def parse_blank_adjudication(response: str) -> dict:
    """解析留白核验响应；失败返回空."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_blank_adjudication_runs(runs: list[dict]) -> dict:
    """多次核验按 handoff_id 对齐取多数事实."""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    by_id: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("candidates") or []:
            hid = c.get("handoff_id")
            if hid:
                by_id.setdefault(hid, []).append(c)
    merged = []
    for hid, cs in by_id.items():

        def _mj(getter):
            return sum(1 for c in cs if getter(c)) > len(cs) / 2

        cond_votes = [c.get("explicit_condition_met") for c in cs
                      if c.get("explicit_condition_met") is not None]
        merged.append({
            "handoff_id": hid,
            "inference_made_explicit": _mj(
                lambda c: c.get("inference_made_explicit")),
            "explicit_excerpt": next(
                (c.get("explicit_excerpt") for c in cs
                 if c.get("explicit_excerpt")), None),
            "explicit_condition_met": (
                sum(1 for v in cond_votes if v) > len(cond_votes) / 2
                if cond_votes else None),
            "evidence_present": _mj(lambda c: c.get("evidence_present")),
            "evidence_excerpt": next(
                (c.get("evidence_excerpt") for c in cs
                 if c.get("evidence_excerpt")), None),
            "evidence_sufficient": _mj(
                lambda c: c.get("evidence_sufficient")),
            "votes": len(cs),
        })
    return {"candidates": merged}


def blank_verdict(facts: dict, candidates: list[dict]) -> dict:
    """确定性裁决（dim8a 冻结三态）.

    - blank_inference_made_explicit（blocking）：结论被明说，且
      explicitness=leave_implicit，或 explicit_when_condition 而条件未满足
    - blank_under_evidenced（blocking）：结论未明说，但计划证据未呈现
      或可见证据不足以让合理读者完成推断
    - 明说 ∧ 证据不足 → 主判 MADE_EXPLICIT，under-evidenced 记为诊断事实
    """
    verdicts: list[dict] = []
    policy = {c["handoff_id"]: c for c in candidates}
    for c in facts.get("candidates") or []:
        hid = c.get("handoff_id")
        spec = policy.get(hid)
        if spec is None:
            continue
        explicit = bool(c.get("inference_made_explicit"))
        allowed_explicit = (
            spec["explicitness"] == "explicit_when_condition"
            and c.get("explicit_condition_met") is True
        )
        under_evidenced = not (
            c.get("evidence_present") and c.get("evidence_sufficient"))
        if explicit and not allowed_explicit:
            verdicts.append({
                "handoff_id": hid,
                "verdict": "blank_inference_made_explicit",
                "severity": "blocking",
                "explicit_excerpt": c.get("explicit_excerpt"),
                "also_under_evidenced": under_evidenced,
            })
        elif not explicit and under_evidenced:
            verdicts.append({
                "handoff_id": hid,
                "verdict": "blank_under_evidenced",
                "severity": "blocking",
                "evidence_excerpt": c.get("evidence_excerpt"),
            })
    return {"verdicts": verdicts}


_BLANK_ADJUDICATED_TYPES = frozenset({
    "blank_inference_made_explicit",
    "blank_under_evidenced",
})


def blank_verdict_names(verdict_result: dict) -> list[str]:
    return [v["verdict"] for v in (verdict_result or {}).get("verdicts") or []]


def apply_blank_adjudication(
    issues: list,
    verdict_result: dict,
    plotunit: PlotUnit | None = None,
) -> tuple[list, list[str]]:
    """把留白裁决应用回 issue 集合；返回 (issues, blocking_verdicts)."""
    issues = list(issues)
    verdicts = (verdict_result or {}).get("verdicts") or []
    if not verdicts:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _BLANK_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical", "warning"))]
        return issues, []
    blocking_names: list[str] = []
    for idx, v in enumerate(verdicts):
        vtype = v["verdict"]
        hid = v.get("handoff_id") or ""
        blocking_names.append(vtype)
        desc = f"blank adjudicator verdict={vtype} | 交接点: {hid}"
        if vtype == "blank_inference_made_explicit":
            desc += (
                "——已声明留白的推断被正文直接陈述/等价解释，"
                "读者预定的推理劳动被取消（太满）"
            )
            if v.get("explicit_excerpt"):
                desc += f"；说破句: 「{v['explicit_excerpt'][:60]}」"
            if v.get("also_under_evidenced"):
                desc += "（诊断事实：计划证据本身也未足量呈现）"
        else:
            desc += (
                "——声明留白但正文未交付足以支撑推断的可见证据，"
                "留下的不是留白而是信息缺失（太少）"
            )
            if v.get("evidence_excerpt"):
                desc += f"；已见证据: 「{v['evidence_excerpt'][:60]}」"
        issues.append(ReviewIssue(
            issue_id=f"blank_adj_{idx + 1}",
            issue_type=vtype,
            severity="blocking",
            location=f"留白交接点 {hid}"
                     + (f"（{plotunit.unit_id}）" if plotunit else ""),
            scope_of_impact="留白/读者推断劳动",
            violated_rule="已声明留白：证据须足、结论须留给读者",
            description=desc,
            suggested_fix=(
                "SUPPRESS_STATED_INFERENCE：删去陈述结论的句子，"
                "让已呈现的证据自己闭合"
                if vtype == "blank_inference_made_explicit"
                else "RESTORE_BLANK_EVIDENCE：把计划中缺失的证据以"
                     "可见动作/对白/细节补出；补不出则不设此留白"
            ),
        ))
    return issues, blocking_names


# ---------- handoff atomicity hard gate（REPAIR_AND_REPILOT 裁决） ----------
#
# 裁决理由：复合 handoff 会让 dim8a verdict 失去原子语义——MADE_EXPLICIT
# 可能只说破其中半个、UNDER_EVIDENCED 只缺半个、SUPPRESS/RESTORE 失去
# 作用对象。9b prompt 软约束被真实生成绕过（pilot U1 2/8 真复合），
# 升级为 prose 前的运行时准入：
#   ATOMIC    → 原对象 byte-preserving 放行
#   COMPOSITE → 拆分 → children 重过同一 gate + 窄 preservation check
#   UNCERTAIN → fail-closed，同样不得原样进入 prose
# 拆分失败/复核不过 → 该 handoff 被拦下（不进 prose），记 telemetry；
# 不静默吞掉 planning intent。

ATOMICITY_VERDICTS = ("ATOMIC", "COMPOSITE", "UNCERTAIN")


def atomicity_eligible(handoff) -> bool:
    """与 blank_candidates 同一过滤口径：只拦留白类交接点."""
    return (
        getattr(handoff, "explicitness", "leave_implicit") != "must_explain"
        and getattr(handoff, "evidence_sufficiency", "sufficient")
        != "must_explicit"
    )


def build_atomicity_prompt(handoffs: list[dict]) -> str:
    """批量原子性判定 prompt（只判结构，不评质量）.

    判的不是「句子有几个分句」，而是该 handoff 是否承载 ≥2 个
    独立的 inferential obligations（可分别陈述、分别需要证据、
    分别真假判定）。premise/evidence 不算第二命题：
    「因为 B 所以推断 A」是单个原子推断；「A 成立，同时 C 也成立」
    且 A/C 可分别真假、分别需要证据 → COMPOSITE。
    """
    lines = "\n".join(
        f"- [{h['handoff_id']}] 证据: {h['evidence']}\n"
        f"  读者应完成的推断: {h['reader_inference']}"
        for h in handoffs
    )
    return (
        "你只判断规划对象的结构，不评价写作质量。下面给出一章声明的"
        "留白交接点，每个交接点声明「正文给某证据、读者自己完成某推断」。"
        "判定每个交接点的「读者应完成的推断」是否只承载一个最小推断单位。"
        "\n\n【已声明交接点】\n" + lines + "\n\n"
        "【判定规则】\n"
        "- ATOMIC：只含一个可独立成立的推断。前提/原因/证据不算第二命题"
        "（「因为B所以A」「A且非B」「X优先于Y」都是单个推断）。\n"
        "- COMPOSITE：含 ≥2 个可分别陈述、分别需要证据、分别真假判定的"
        "命题（「A成立，同时C也成立」「A，而B」且 A/C 各自独立）。\n"
        "- UNCERTAIN：无法确定是否复合。\n\n"
        "只输出 JSON：{\"verdicts\":[{\"handoff_id\":\"hN\","
        "\"verdict\":\"ATOMIC|COMPOSITE|UNCERTAIN\"}]}"
    )


def parse_atomicity(response: str) -> dict:
    """{handoff_id: verdict}；解析失败返回 {}."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}
    out = {}
    for v in (data or {}).get("verdicts") or []:
        hid, vd = v.get("handoff_id"), v.get("verdict")
        if hid and vd in ATOMICITY_VERDICTS:
            out[hid] = vd
    return out


def build_atomicity_split_prompt(handoffs: list[dict]) -> str:
    """复合交接点拆分 prompt（COMPOSITE/UNCERTAIN 共用入口）."""
    lines = "\n".join(
        f"- [{h['handoff_id']}] 证据: {h['evidence']}\n"
        f"  读者应完成的推断: {h['reader_inference']}"
        for h in handoffs
    )
    return (
        "下面的留白交接点被判定为复合/不确定——「读者应完成的推断」"
        "承载了多个可独立成立的命题。把每个交接点拆成若干原子交接点："
        "每个 child 只声明一个可独立陈述、独立需要证据、独立真假判定的"
        "推断。\n\n【待拆交接点】\n" + lines + "\n\n"
        "【约束】\n"
        "- 不许丢掉原交接点的任何推断义务（列出 obligations 并标明每个 "
        "child 覆盖哪几条）。\n"
        "- 不许新增原交接点没有的推断。\n"
        "- 每个 child 自带自己的 evidence（可继承或细化原证据）。\n\n"
        "只输出 JSON：{\"splits\":[{\"handoff_id\":\"hN\","
        "\"obligations\":[\"独立命题1\",\"独立命题2\"],"
        "\"children\":[{\"evidence\":\"...\",\"reader_inference\":\"...\","
        "\"covers\":[1]}],\"no_new_inference\":true}]}"
    )


def parse_atomicity_split(response: str) -> dict:
    """{handoff_id: split_obj}；解析失败返回 {}."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}
    out = {}
    for s in (data or {}).get("splits") or []:
        hid = s.get("handoff_id")
        if hid:
            out[hid] = s
    return out


def validate_atomicity_split(
    split: dict, child_verdicts: dict, parent_hid: str
) -> list[dict] | None:
    """窄 preservation check；通过返回 children 列表，否则 None.

    - children ≥ 2，每个 evidence/reader_inference 非空
    - no_new_inference 必须为 true
    - obligations 每条被 ≥1 个 child.covers 覆盖
    - 每个 child 在重过 gate 后必须是 ATOMIC
    """
    children = (split or {}).get("children") or []
    obligations = (split or {}).get("obligations") or []
    if len(children) < 2 or not obligations:
        return None
    if not (split or {}).get("no_new_inference"):
        return None
    for c in children:
        if not str(c.get("evidence") or "").strip():
            return None
        if not str(c.get("reader_inference") or "").strip():
            return None
    covered = set()
    for c in children:
        covered.update(c.get("covers") or [])
    if any(i not in covered for i in range(1, len(obligations) + 1)):
        return None
    for i, _c in enumerate(children, 1):
        if child_verdicts.get(f"{parent_hid}.{i}") != "ATOMIC":
            return None
    return children


def atomicity_gate_step(plotunit: PlotUnit, output_dir):
    """prose 消费前的 atomicity 运行时准入门（staged）.

    返回 ("waiting", pending_filename) 表示等待 LLM 响应；
    返回 ("done", final_handoffs) 表示门已收敛——final_handoffs
    用于替换 plotunit.reader_handoffs（含被拦下的 handoff 缺席
    + 拆分 children 入位；ineligible 原样保留）。
    """
    from src.object_state.inference_handoff import InferenceHandoff

    output_dir = pathlib.Path(output_dir)
    result_path = output_dir / "atomicity_result.json"
    orig = list(getattr(plotunit, "reader_handoffs", None) or [])

    if result_path.exists():
        data = json.loads(result_path.read_text(encoding="utf-8"))
        return "done", [
            InferenceHandoff.model_validate(h)
            for h in data.get("final_handoffs") or []
        ]

    elig = [(i, h) for i, h in enumerate(orig) if atomicity_eligible(h)]
    if not elig:
        # 无留白类交接点：门零字节通过
        return "done", orig

    def _hid(i):
        return f"h{i + 1}"

    cand_dicts = [
        {"handoff_id": _hid(i), "evidence": h.evidence,
         "reader_inference": h.reader_inference}
        for i, h in elig
    ]

    # round 1：批量原子性判定
    aresp = output_dir / "atomicity_response.txt"
    if not aresp.exists():
        (output_dir / "atomicity_prompt.txt").write_text(
            build_atomicity_prompt(cand_dicts), encoding="utf-8")
        return "waiting", "atomicity_response.txt"
    verdicts = parse_atomicity(aresp.read_text(encoding="utf-8"))

    need_split = [
        (i, h) for i, h in elig
        if verdicts.get(_hid(i)) != "ATOMIC"
    ]

    # round 2：复合/不确定统一拆分（单调用）
    splits: dict = {}
    if need_split:
        sresp = output_dir / "atomicity_split_response.txt"
        if not sresp.exists():
            (output_dir / "atomicity_split_prompt.txt").write_text(
                build_atomicity_split_prompt([
                    {"handoff_id": _hid(i), "evidence": h.evidence,
                     "reader_inference": h.reader_inference}
                    for i, h in need_split
                ]), encoding="utf-8")
            return "waiting", "atomicity_split_response.txt"
        splits = parse_atomicity_split(
            sresp.read_text(encoding="utf-8"))

    # round 3：children 重过同一 gate
    all_children: list[dict] = []
    for i, h in need_split:
        sp = splits.get(_hid(i)) or {}
        for j, c in enumerate(sp.get("children") or [], 1):
            all_children.append({
                "handoff_id": f"{_hid(i)}.{j}",
                "evidence": c.get("evidence", ""),
                "reader_inference": c.get("reader_inference", ""),
            })
    child_verdicts: dict = {}
    if all_children:
        rresp = output_dir / "atomicity_regate_response.txt"
        if not rresp.exists():
            (output_dir / "atomicity_regate_prompt.txt").write_text(
                build_atomicity_prompt(all_children), encoding="utf-8")
            return "waiting", "atomicity_regate_response.txt"
        child_verdicts = parse_atomicity(
            rresp.read_text(encoding="utf-8"))

    # 确定性应用：ATOMIC 原样；拆分成功换 children；失败拦下记 telemetry
    final: list = []
    telemetry: list[dict] = []
    for i, h in enumerate(orig):
        hid = _hid(i)
        if not atomicity_eligible(h) or verdicts.get(hid) == "ATOMIC":
            final.append(h)
            continue
        if hid not in verdicts:
            telemetry.append({"handoff_id": hid,
                              "event": "atomicity_no_verdict"})
        children = validate_atomicity_split(
            splits.get(hid), child_verdicts, hid)
        if children is None:
            telemetry.append({"handoff_id": hid,
                              "event": "composite_rejected"})
            continue
        telemetry.append({"handoff_id": hid,
                          "event": "composite_split",
                          "children": len(children)})
        for c in children:
            final.append(InferenceHandoff(
                evidence=c["evidence"],
                reader_inference=c["reader_inference"],
                explicitness=h.explicitness,
                evidence_sufficiency=h.evidence_sufficiency,
                explicit_when=getattr(h, "explicit_when", None),
                payoff=getattr(h, "payoff", None),
            ))

    result_path.write_text(json.dumps({
        "verdicts": verdicts,
        "child_verdicts": child_verdicts,
        "telemetry": telemetry,
        "final_handoffs": [
            h.model_dump(mode="json") for h in final],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return "done", final
