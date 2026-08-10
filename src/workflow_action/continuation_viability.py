"""ContinuationViabilityUnit — 续写可行性判断（Q1 R1，纯代码先判 + 操作者确认）.

回答「生成 PlotUnit 之前，是否还有有效的下一步」：
- `continue`：存在活跃叙事帧，可产生新的状态变化；
- `needs_premise`：当前结构已完成但仍有未兑现承诺（或可重启但需新冲突/新阶段目标）；
- `stop`：故事已完成主要情感闭环，继续写是重新解释已结束的故事——正确续写是停止。

确定性判定（零 LLM）基于可追溯信号：no_active_frame / 活跃承诺数 / 终止型节点 /
读者契约结束条件。信号冲突时 `deterministic=False`，走操作者/LLM 确认的 staged slot。

零成本契约：无数据可判时（fresh 工作区）默认 continue，不改变现有流程字节。
"""

import json

from src.object_state.continuation_viability import (
    TERMINAL_FORMULA_NODES,
    ViabilityVerdict,
    ContinuationViabilityDecision,
    ContinuationViabilitySignal,
)
from src.object_state.readercontract import ReaderContract


def _signal(signal_id: str, direction: str, strength: str, evidence: str) -> ContinuationViabilitySignal:
    return ContinuationViabilitySignal(
        signal_id=signal_id,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,  # type: ignore[arg-type]
        evidence=evidence,
    )


def _match_ending_conditions(contract: ReaderContract, current_situation: str) -> list[str]:
    """契约结束条件 ↔ 当前情形的子串匹配（确定性代理）.

    结束条件是面向操作者写的自然语言；这里做保守子串命中：条件串出现在
    current_situation 中即视为触发。命中越多越强。测试样本可显式构造。
    """
    if not contract.ending_conditions:
        return []
    return [cond for cond in contract.ending_conditions if cond and cond in current_situation]


def analyze_continuation_viability(
    *,
    narrative_state,
    foreshadows=None,
    frame_context: dict | None = None,
    workspec=None,
    contract: ReaderContract | None = None,
    recent_chapter_count: int = 0,
) -> ContinuationViabilityDecision:
    """纯代码确定性判定：continue / needs_premise / stop（或 ambiguous → deterministic=False）.

    Args:
        narrative_state: 当前 NarrativeState（可为 None，仅用于结束条件匹配）。
        foreshadows: ForeshadowGraph 或 None。
        frame_context: build_continue_context 的返回（含 no_active_frame/current_frame）。
        workspec: WorkSpec 或 None（compose 有，extend 的 workspec 为重建产物）。
        contract: ReaderContract 或 None（无契约 → 结束条件信号不参与）。
        recent_chapter_count: 已提交章数（用于 fresh 判定）。
    """
    signals: list[ContinuationViabilitySignal] = []
    no_active_frame = bool(frame_context and frame_context.get("no_active_frame"))
    current_frame = (frame_context or {}).get("current_frame") or {}
    formula_node = (current_frame or {}).get("formula_node") or ""
    terminal_node = formula_node in TERMINAL_FORMULA_NODES
    active_threads = foreshadows.get_active() if foreshadows is not None else []
    open_promises = len(active_threads)
    current_situation = getattr(narrative_state, "current_situation", "") or ""

    if no_active_frame:
        signals.append(
            _signal("no_active_frame", "stop", "strong",
                    "无活跃叙事帧——结构已完成，最后场景无 successor")
        )
    if open_promises:
        signals.append(
            _signal("open_threads", "continue", "strong" if open_promises >= 2 else "weak",
                    f"{open_promises} 条活跃承诺未兑现")
        )
    if terminal_node and not no_active_frame:
        signals.append(
            _signal("terminal_node", "stop", "weak",
                    f"当前节点 {formula_node} 为终止型节点")
        )

    ending_matched: list[str] = []
    if contract is not None:
        ending_matched = _match_ending_conditions(contract, current_situation)
        if ending_matched:
            signals.append(
                _signal("ending_conditions", "stop", "weak",
                        "契约结束条件触发: " + "；".join(ending_matched))
            )

    reasons: list[str] = []
    required_premise: str | None = None
    deterministic = True

    if no_active_frame:
        if open_promises:
            verdict: ViabilityVerdict = "needs_premise"
            reasons = [
                f"无活跃叙事帧，但仍有 {open_promises} 条活跃承诺未兑现",
                "需要操作者提供新前提/新结构，才能继续推进这些承诺",
            ]
            required_premise = (
                f"需新前提以推进 {open_promises} 条未兑现承诺："
                + "；".join(t.content for t in active_threads[:3])
            )
        else:
            verdict = "stop"
            reasons = [
                "无活跃叙事帧，故事结构已完成",
                "无未兑现承诺；继续写将重新解释已经结束的故事",
                "正确续写是停止（或操作者显式批准新前提重启）",
            ]
    elif ending_matched and not open_promises:
        verdict = "stop"
        reasons = [
            "读者契约结束条件已触发：" + "；".join(ending_matched),
            "无活跃承诺——故事已到契约定义的结尾",
        ]
    elif ending_matched and open_promises:
        # 契约要求结束但仍有未兑现承诺 → 信号冲突，须操作者/LLM 确认
        verdict = "needs_premise"
        deterministic = False
        reasons = [
            "读者契约结束条件已触发，但仍有 " + str(open_promises) + " 条承诺未兑现",
            "继续推进承诺会延伸故事长度；直接结束会留下悬空承诺——需操作者决策",
        ]
        required_premise = (
            f"二选一：① 批准新前提继续推进承诺；② 确认结束并把 {open_promises} 条承诺转为有意留白。"
        )
    else:
        verdict = "continue"
        reasons = ["存在活跃叙事帧，下一章可产生新的状态变化"]
        if open_promises:
            reasons.append(f"{open_promises} 条活跃承诺待推进")
        if terminal_node:
            reasons.append(f"当前处于终止型节点 {formula_node}——本章即为收束章")

    return ContinuationViabilityDecision(
        verdict=verdict,
        deterministic=deterministic,
        reasons=reasons,
        signals=signals,
        required_premise=required_premise,
    )


def viability_continue_note(decision) -> str:
    """把确定性 continue 中生成器需要明确知道的方向压成一行注记（零成本：空则不入）."""
    for reason in decision.reasons:
        if "终止型节点" in reason:
            return (
                "可行性确认：当前处于终止型节点——本章应承担收束功能，"
                "为故事给出可信的新平衡，而非开启新支线。"
            )
    return ""


class ContinuationViabilityUnit:
    """Staged 判定单元：确定性分析为 continue/stop 时直接放行/阻断；
    冲突（deterministic=False）时写 prompt 交操作者/LLM 确认。"""

    def build_prompt(
        self,
        analysis: ContinuationViabilityDecision,
        *,
        workspec_context: str = "",
        excerpt_context: str = "",
        contract_context: str = "",
    ) -> str:
        contract_section = f"\n【读者契约】\n{contract_context}" if contract_context else ""
        return f"""你正在维护一部连载小说。根据以下确定性信号，决定是否继续生成下一章。

【预判定（纯代码信号）】
{analysis.to_prompt_context()}

{contract_section}

【作品约束】
{workspec_context}

【续写要求】
1. 若故事已完成主要情感闭环且无未兑现承诺 → verdict 必须为 "stop"；
2. 若结构已结束但仍有未兑现承诺，或需新冲突/新阶段目标才能继续 → verdict 必须为 "needs_premise"，并给出 required_premise；
3. 若存在有效下一步 → verdict 为 "continue"。
4. 不能仅凭「还可以继续写」选择 continue；continue 必须伴随具体的新状态变化理由。

【输出格式】
严格输出 JSON（只输出 JSON，不要 markdown）：
{{
  "verdict": "continue | needs_premise | stop",
  "reasons": ["判定理由1", "判定理由2"],
  "required_premise": "仅 needs_premise 时填写所需新前提；否则为 null"
}}
"""

    def parse_response(self, response: str) -> ContinuationViabilityDecision:
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("ContinuationViability response must be a JSON object")
        required = ("verdict", "reasons")
        missing = [field for field in required if field not in data]
        if missing:
            raise ValueError(
                "ContinuationViability response missing field(s): " + ", ".join(missing)
            )
        extra = sorted(set(data) - set(required) - {"required_premise"})
        if extra:
            raise ValueError(
                "ContinuationViability response has unexpected field(s): " + ", ".join(extra)
            )
        verdict = data["verdict"]
        if verdict not in ("continue", "needs_premise", "stop"):
            raise ValueError(f"invalid ContinuationViability verdict: {verdict}")
        reasons = data["reasons"]
        if not isinstance(reasons, list):
            raise ValueError("ContinuationViability reasons must be a list")
        premise = data.get("required_premise")
        if premise is not None and not isinstance(premise, str):
            raise ValueError("ContinuationViability required_premise must be a string or null")
        return ContinuationViabilityDecision(
            verdict=verdict,
            deterministic=True,
            reasons=[str(r) for r in reasons],
            required_premise=premise or None,
        )
