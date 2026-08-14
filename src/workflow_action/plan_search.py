"""A1 T5 — 多 PlotUnit 候选搜索（design §7；doc 48 §6 step 6）.

T5.1/T5.2：PlotUnit 候选必须具有不同的输出状态变化；语义聚类后重复候选淘汰。
T5.3：每个存活 PlotUnit 生成固定数量正文（正文变体见 runner / prose 变体提示）。

一次 provider 调用返回 ``policy.search.plot_candidates`` 个候选（严格解析，
不吞缺字段/多余字段/重复 id/空列表）；``dedup_plan_candidates`` 以输出状态变化
签名做语义去重（首现优先、封顶）；``verify_plan_diversity`` 是 G5「候选数量与
差异约束可验证」的确定性验证器（运行层把验证结果落盘为证据）。

输出状态变化签名 = 候选的 new_state（地点/局势/参与者）+ released_information
+ consequences 的规范化压缩串。两个候选在所有这些维度上规范化相同 → 视为重复
计划（同一输出状态变化），后者淘汰。
"""

from __future__ import annotations

import json
import re
import unicodedata

from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.json_repair import parse_json

# 规范化：NFKC + 去空白与标点（与语义接缝共用同一套「不改变事件身份」的纪律）。
_COMPACT_RE = re.compile(r"[\s，。！？；：、,.!?;:“”‘’—…・\-—…~·（()）【】《》「」『』]+")


def compact_text(text: str) -> str:
    """NFKC + 去空白/标点的规范化压缩（用于签名与差分子串比较）."""
    return _COMPACT_RE.sub("", unicodedata.normalize("NFKC", str(text or "")))


def build_plot_batch_prompt(base_continue_prompt: str, count: int) -> str:
    """把单 PlotUnit 续写 prompt 包装成多候选批次输出规格.

    ``base_continue_prompt`` 是 ContinueUnit 已构建的正文前上下文（含【续写要求】
    与单候选【输出格式】）。这里只追加批次要求，不重复注入上下文，保持正文前
    上下文字节与单候选路径一致（生成器看不到任何隐藏夹具/holdout）。
    """
    if count < 1:
        raise ValueError("plot candidate count must be at least 1")
    return base_continue_prompt + f"""

【多候选要求】
本次请输出 **{count} 个互不相同** 的 PlotUnit 候选，而不是单个。

输出格式（严格 JSON，外层只有 candidates 一个键）：
{{
  "candidates": [
    {{
      "plotunit": {{ "unit_id": "pu_xxx", ... }},
      "new_state": {{ "state_id": "ns_xxx", ... }},
      "new_facts": [],
      "confidence_gaps": []
    }},
    ...
  ]
}}

每个候选内部的 plotunit / new_state / new_facts / confidence_gaps 字段
与上文【输出格式】完全相同，共 {count} 个元素。

约束：
1. 必须输出恰好 {count} 个候选；每个都必须满足上文【续写要求】，不得以牺牲质量换取数量。
2. **每个候选必须导致不同的输出状态变化**——new_state 的地点/局势/参与者、
   released_information 与 consequences 不得彼此雷同（语义重复候选会被淘汰）。
3. 候选之间可以有不同倾向（有的保守推进、有的制造转折），但都必须忠实于当前
   可信状态、角色与承诺，不得引入与已发生事件矛盾的新设定。
4. released_information 与 consequences 每项必须是**简洁、可辨识的要点**：一条一个
   关键事实，含具体名词/数字/人物/动作（如「举报信点名评估价低于基准两成」），
   以短语或短句为宜，**不要写成多分句的完整叙述段**。正文层将以这些要点的词结构
   为证据校验其落地——冗长整句在正文中必然被意译，无法通过确定性证伪。
"""


def parse_plot_batch_response(
    response: str, count: int
) -> list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]]:
    """严格解析多 PlotUnit 候选响应.

    Returns:
        按生成顺序的 ``[(PlotUnit, NarrativeState, new_facts, confidence_gaps), ...]``。
        任何形状违例（非对象/缺字段/多余字段/空列表/超 count/字段类型错）→ ValueError
        （由 runner 记为 schema/证据错误 → execution_failed，不重试、不吞异常）。
    """
    if count < 1:
        raise ValueError("plot candidate count must be at least 1")
    data = parse_json(response)
    if not isinstance(data, dict) or set(data) != {"candidates"}:
        raise ValueError("plot batch response must be a JSON object with only 'candidates'")
    candidates = data["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("plot batch 'candidates' must be a list")
    if not 1 <= len(candidates) <= count:
        raise ValueError(
            f"plot batch must contain between 1 and {count} candidates, got {len(candidates)}"
        )
    parsed: list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            raise ValueError(f"candidate {index} must be a JSON object")
        required = {"plotunit", "new_state", "new_facts", "confidence_gaps"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required)
        if missing or extra:
            raise ValueError(
                f"candidate {index} missing field(s) {missing} and/or extra field(s) {extra}"
            )
        if not isinstance(item["new_facts"], list):
            raise ValueError(f"candidate {index} new_facts must be a list")
        gaps = item["confidence_gaps"]
        if not isinstance(gaps, list) or not all(
            isinstance(gap, str) and gap.strip() for gap in gaps
        ):
            raise ValueError(
                f"candidate {index} confidence_gaps must be a list of non-empty strings"
            )
        plotunit = PlotUnit(**item["plotunit"])
        new_state = NarrativeState(**item["new_state"])
        parsed.append((plotunit, new_state, item["new_facts"], gaps))
    return parsed


def plan_candidate_signature(
    plan: tuple[PlotUnit, NarrativeState, list[dict], list[str]],
) -> str:
    """候选的输出状态变化签名（去重/差异约束的依据）."""
    plotunit, new_state, _new_facts, _gaps = plan
    parts = [
        new_state.current_time or "",
        new_state.current_location or "",
        new_state.current_situation or "",
        " ".join(sorted(new_state.active_characters or [])),
        " ".join(plotunit.released_information or []),
        " ".join(plotunit.consequences or []),
        plotunit.conflict or "",
    ]
    return "|".join(compact_text(part) for part in parts)


def dedup_plan_candidates(
    plans: list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]],
    max_candidates: int,
) -> list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]]:
    """语义去重：输出状态变化签名相同的候选只保留首个，并封顶 max_candidates."""
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    kept: list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]] = []
    seen: set[str] = set()
    for plan in plans:
        signature = plan_candidate_signature(plan)
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(plan)
        if len(kept) >= max_candidates:
            break
    return kept


def verify_plan_diversity(
    plans: list[tuple[PlotUnit, NarrativeState, list[dict], list[str]]],
    max_candidates: int,
) -> tuple[bool, str]:
    """G5 确定性验证器：候选数量与差异约束是否成立.

    Returns:
        ``(ok, reason)``——ok 表示非空、数量 ≤ max_candidates、且候选输出状态
        变化两两不同（无重复签名）。
    """
    if not plans:
        return False, "no plot candidate remains after parse/dedup"
    if len(plans) > max_candidates:
        return False, f"{len(plans)} candidates exceed max {max_candidates}"
    signatures = [plan_candidate_signature(plan) for plan in plans]
    if len(set(signatures)) != len(signatures):
        return False, "duplicate output state change among surviving candidates"
    return True, f"{len(plans)} distinct candidate(s) within max {max_candidates}"


def state_necessity_violation(
    plotunit: PlotUnit,
    input_state: NarrativeState,
    new_state: NarrativeState,
) -> tuple[str, str] | None:
    """design §8 check 4 的计划层代理：删除该场景后状态是否仍相同.

    仅对 is_effective 的 PlotUnit 强制：若输出状态在地点/局势/参与者/时间上与输入
    状态规范化全等，说明该场景没有造成任何状态变化，正文证据无从谈起 → 返回
    (axis, reason) 硬违例；非 effective（过渡/铺垫单元）不强制。此检查在正文前
    运行（plan 闸），不产生 JudgeClaim（JudgeClaim 必须带正文锚点）。
    """
    if not plotunit.is_effective:
        return None
    unchanged = (
        compact_text(new_state.current_location or "")
        == compact_text(input_state.current_location or "")
        and compact_text(new_state.current_situation or "")
        == compact_text(input_state.current_situation or "")
        and sorted(new_state.active_characters or [])
        == sorted(input_state.active_characters or [])
        and compact_text(new_state.current_time or "")
        == compact_text(input_state.current_time or "")
    )
    if unchanged:
        return (
            "state_necessity",
            "effective PlotUnit 输出状态与输入状态在地点/局势/参与者/时间上完全相同——"
            "删除该场景后状态不变，不存在可写的正文证据",
        )
    return None
