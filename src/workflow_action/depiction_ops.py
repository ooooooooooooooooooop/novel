"""Depiction Ops — dim8b 白描意图定向核验.

与 blank_ops 同构但对象不同：本模块只对「Continue 已声明、PlotUnit
已冻结」的 DepictionIntent 做定向核验——review 只验证不补造
（authority：planning owns / continue 实例化 / prose 消费 / review 只验）。

核验问题不是「有没有相关动作」，而是「冻结的 ambient quality 是否真正
被可观察层承载」——弱载体/可替换痕迹不算 realized
（NEED GATE N03 标 BORDERLINE_REALIZATION 的教训）。

裁决真值表（终裁冻结，六用例）：
- owning beat 不在场（prose 合法转线出责任 beat）
    → none（OWNERSHIP_RELEASED，SCENE_OWNERSHIP_BOUNDARY 约束——
      「ambient 重要」≠「本 unit 负责演出」）
- 场景属于合法直接自陈（自白/汇报/检查等需要明说心理状态的情形）
    → none（LEGIT_EXPLICIT）
- 目标质感被抽象命名 + 无可观察载体
    → depiction_named_only（blocking）
- 未命名 + 无可观察载体
    → depiction_absent（blocking）
- 有可观察载体（不限于 planned_carriers——开放 realization space，
  换用其他有效载体同样算 realized）
    → none（ALTERNATE_CARRIER 合法）
- 既命名又有载体 → none（质感已实现；命名冗余归 RCC/解读空间族，
  不重复判 depiction failure）
"""

import json
import re

from src.object_state import PlotUnit, ReviewIssue
from src.workflow_action.review import narrative_spans_numbered


def depiction_candidates(plotunit: PlotUnit | None) -> list[dict]:
    """已声明的白描意图（全部进入核验——无 must_explain 类豁免字段）."""
    if plotunit is None or not getattr(plotunit, "depiction_intents", None):
        return []
    cands = []
    for idx, d in enumerate(plotunit.depiction_intents, 1):
        cands.append({
            "intent_id": f"d{idx}",
            "target_quality": d.target_quality,
            "beat_link": d.beat_link,
            "planned_carriers": list(d.planned_carriers or []),
            "placement": getattr(d, "placement", None),
            "rationale": getattr(d, "rationale", None),
        })
    return cands


def build_depiction_adjudication_prompt(
    prose_text: str, candidates: list[dict]
) -> str:
    """白描核验 prompt：只抽事实不判严重度.

    keep_dialogue=True：对白既可承载质感（语气/措辞/沉默）也可把
    质感命名说破——剥除引号内容会系统性失明。
    """
    spans = narrative_spans_numbered(prose_text, keep_dialogue=True)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- [{c['intent_id']}] 目标质感: {c['target_quality']}\n"
        f"  责任 beat: {c['beat_link']}"
        + (f"\n  计划载体(可替换): {'；'.join(c['planned_carriers'])}"
           if c.get("planned_carriers") else "")
        for c in candidates
    )
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号；"
        "另给出本章已声明的白描意图——作者计划让读者在现场【感受到】"
        "某种体验质感，且它应由可观察的动作/神态/语气/器物/空间/节奏"
        "承载，而不是由抽象词直接命名（如「他很烦躁」「气氛压抑」）。"
        "对每个意图抽取本章事实。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【已声明白描意图】\n" + cand_lines + "\n\n"
        "【抽取项】对每个意图输出：\n"
        "{\"intent_id\":\"dN\","
        "\"in_scope\":true|false——正文是否仍处该意图声明的责任 beat/"
        "场景范围内（owning beat 在正文中出现或正在演出；正文已合法转线"
        "到别的场景/别的事件线则 false）,"
        "\"legit_explicit\":true|false——当前场景是否属于需要人物直接"
        "自陈心理状态的合法情形（自白/汇报/诊断/检查等对质场合），"
        "\"quality_named\":true|false——目标质感是否被抽象词直接命名"
        "（旁白或人物直接把该情绪/质感说出来；「烦躁」「发酸」「畏惧」"
        "类命名；呈现可观察细节让读者自己感受不算）,"
        "\"named_excerpt\":\"命名该质感的正文原句（逐字摘录，≤60字）或null\","
        "\"carriers_present\":true|false——是否存在承载该目标质感的"
        "可观察载体（动作/神态/语气/器物/空间/节奏，不限于计划载体，"
        "任何有效可观察呈现都算；要求能让合理读者实际感受到该质感，"
        "稀薄到可替换的痕迹不算）,"
        "\"carrier_excerpts\":[\"承载质感的正文原句逐字摘录，≤60字/条\"]}\n\n"
        "注意：只输出 JSON：{\"candidates\":[..]}"
    )


def parse_depiction_adjudication(response: str) -> dict:
    """解析白描核验响应；失败返回空."""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_depiction_adjudication_runs(runs: list[dict]) -> dict:
    """多次核验按 intent_id 对齐取多数事实."""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    by_id: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("candidates") or []:
            iid = c.get("intent_id")
            if iid:
                by_id.setdefault(iid, []).append(c)
    merged = []
    for iid, cs in by_id.items():

        def _mj(getter):
            return sum(1 for c in cs if getter(c)) > len(cs) / 2

        merged.append({
            "intent_id": iid,
            "in_scope": _mj(lambda c: c.get("in_scope")),
            "legit_explicit": _mj(lambda c: c.get("legit_explicit")),
            "quality_named": _mj(lambda c: c.get("quality_named")),
            "named_excerpt": next(
                (c.get("named_excerpt") for c in cs
                 if c.get("named_excerpt")), None),
            "carriers_present": _mj(lambda c: c.get("carriers_present")),
            "carrier_excerpts": [
                x for c in cs for x in (c.get("carrier_excerpts") or [])
            ][:4],
            "votes": len(cs),
        })
    return {"candidates": merged}


def depiction_verdict(facts: dict, candidates: list[dict]) -> dict:
    """确定性裁决（dim8b 冻结真值表）."""
    verdicts: list[dict] = []
    policy = {c["intent_id"]: c for c in candidates}
    for c in facts.get("candidates") or []:
        iid = c.get("intent_id")
        spec = policy.get(iid)
        if spec is None:
            continue
        if not c.get("in_scope"):
            continue  # OWNERSHIP_RELEASED：合法转线，不误拦
        if c.get("legit_explicit"):
            continue  # LEGIT_EXPLICIT：需要自陈的场景不误拦
        named = bool(c.get("quality_named"))
        carried = bool(c.get("carriers_present"))
        if carried:
            continue  # realized（含 ALTERNATE_CARRIER）
        verdicts.append({
            "intent_id": iid,
            "verdict": ("depiction_named_only" if named
                        else "depiction_absent"),
            "severity": "blocking",
            "target_quality": spec["target_quality"],
            "beat_link": spec["beat_link"],
            "named_excerpt": c.get("named_excerpt"),
        })
    return {"verdicts": verdicts}


_DEPICTION_ADJUDICATED_TYPES = frozenset({
    "depiction_named_only",
    "depiction_absent",
})


def depiction_verdict_names(verdict_result: dict) -> list[str]:
    return [v["verdict"] for v in (verdict_result or {}).get("verdicts") or []]


def apply_depiction_adjudication(
    issues: list,
    verdict_result: dict,
    plotunit: PlotUnit | None = None,
) -> tuple[list, list[str]]:
    """把白描裁决应用回 issue 集合；返回 (issues, blocking_verdicts)."""
    issues = list(issues)
    verdicts = (verdict_result or {}).get("verdicts") or []
    if not verdicts:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _DEPICTION_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical", "warning"))]
        return issues, []
    blocking_names: list[str] = []
    for idx, v in enumerate(verdicts):
        vtype = v["verdict"]
        iid = v.get("intent_id") or ""
        blocking_names.append(vtype)
        desc = f"depiction adjudicator verdict={vtype} | 意图: {iid}"
        if vtype == "depiction_named_only":
            desc += (
                f"——声明的体验质感「{v.get('target_quality')}」"
                "被抽象词直接命名且无可观察载体承载，"
                "读者被告知而非感受到（白描失败：只剩命名）"
            )
            if v.get("named_excerpt"):
                desc += f"；命名句: 「{v['named_excerpt'][:60]}」"
        else:
            desc += (
                f"——声明的体验质感「{v.get('target_quality')}」"
                "在责任 beat 内既未命名也无任何可观察载体，"
                "读者无从感受（白描失败：质感缺席）"
            )
        desc += f"；责任 beat: {v.get('beat_link')}"
        issues.append(ReviewIssue(
            issue_id=f"depiction_adj_{idx + 1}",
            issue_type=vtype,
            severity="blocking",
            location=f"白描意图 {iid}"
                     + (f"（{plotunit.unit_id}）" if plotunit else ""),
            scope_of_impact="白描/体验质感呈现",
            violated_rule="已声明白描：质感须由可观察载体承载，"
                          "不得只剩抽象命名或整体缺席",
            description=desc,
            suggested_fix=(
                "GROUND_DEPICTION：把命名改写为可观察的动作/神态/语气/"
                "器物/空间呈现，让质感被看见而非被告知"
                if vtype == "depiction_named_only"
                else "GROUND_DEPICTION：在责任 beat 内补出承载该质感的"
                     "可观察细节（动作/神态/语气/器物/空间）；补不出则"
                     "不应声明此意图"
            ),
        ))
    return issues, blocking_names
