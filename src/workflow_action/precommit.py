"""A1 T5 — EvaluatorPrecommit 生成与确定性证伪（design §8；doc 48 §6 step 6）.

评审看正文前只读取可信状态、ReaderContract、PlotUnit 和承诺图，生成不可修改的
``EvaluatorPrecommit``；正文完成后用同一份预承诺执行证伪检查。

``falsify_prose_against_precommit`` 是**纯代码**的确定性证伪：把 PlotUnit 的
释放信息/后果/预期局势与正文逐项核对，产出带真实正文锚点的 JudgeClaim
（generator_source="code"）。硬违例（effective 单元缺失释放信息/后果）由
claim_is_hard_violation 判定为 blocking → 候选淘汰，软分数不能抵消
（requirement §5 规则 7：「每个提交状态变化都有正文证据」）。

锚点必须真实：excerpt 直接取自被评审正文的 [char_start, char_end) 区间，
不可能捏造（与 judge 路径同一核验口径）。
"""

from __future__ import annotations

from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.object_state.judge_claim import JudgeClaim, ProseAnchor
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.plan_search import compact_text

_ANCHOR_OPENING_CHARS = 160


def build_evaluator_precommit(
    *,
    precommit_id: str,
    plotunit: PlotUnit,
    input_state: NarrativeState,
    new_state: NarrativeState,
    trusted_state_hash: str,
) -> EvaluatorPrecommit:
    """只读正文前输入，生成不可修改的评审预承诺.

    input_state/new_state 均为结构对象（计划层），trusted_state_hash 为可信状态
    （facts ledger + 上一 NarrativeState）哈希——证明预承诺冻结于正文前的可信状态，
    正文完成后无法改写（模型无正文字段 + extra=forbid）。
    """
    return EvaluatorPrecommit(
        precommit_id=precommit_id,
        plotunit_id=plotunit.unit_id,
        input_state_id=input_state.state_id,
        output_state_id=new_state.state_id,
        expected_output_location=new_state.current_location or "",
        expected_output_situation=new_state.current_situation or "",
        expected_released_information=tuple(plotunit.released_information or []),
        expected_consequences=tuple(plotunit.consequences or []),
        effective=bool(plotunit.is_effective),
        trusted_state_hash=trusted_state_hash,
    )


def _find_item(prose: str, item: str) -> int:
    """在正文中定位一项计划内容；返回原始下标，找不到返回 -1."""
    if not item:
        return -1
    index = prose.find(item)
    if index >= 0:
        return index
    compact_prose = compact_text(prose)
    compact_item = compact_text(item)
    if compact_item and compact_item in compact_prose:
        return compact_prose.find(compact_item)
    return -1


def _opening_anchor(prose: str, chapter_ref: str) -> ProseAnchor:
    end = min(len(prose), _ANCHOR_OPENING_CHARS)
    return ProseAnchor(
        chapter_ref=chapter_ref,
        position="start",
        excerpt=prose[0:end],
        char_start=0,
        char_end=end,
    )


def _found_anchor(prose: str, chapter_ref: str, index: int, length: int) -> ProseAnchor:
    end = min(len(prose), index + length)
    if index >= end:
        return _opening_anchor(prose, chapter_ref)
    return ProseAnchor(
        chapter_ref=chapter_ref,
        position="middle",
        excerpt=prose[index:end],
        char_start=index,
        char_end=end,
    )


def falsify_prose_against_precommit(
    precommit: EvaluatorPrecommit, prose: str, chapter_ref: str
) -> list[JudgeClaim]:
    """纯代码证伪：PlotUnit 预期变化 ↔ 正文实际变化（design §8 check 1）.

    对每项释放信息/后果：正文包含 → satisfied advisory（正文证据）；正文缺失 →
    violated（effective 单元 blocking，非 effective advisory）。预期局势缺失 →
    advisory（局势短语易被意译，不作硬门禁）。全部 JudgeClaim 都带真实正文锚点。
    """
    claims: list[JudgeClaim] = []
    expected_items = list(precommit.expected_released_information) + list(
        precommit.expected_consequences
    )
    for index, item in enumerate(expected_items):
        found_at = _find_item(prose, item)
        is_consequence = index >= len(precommit.expected_released_information)
        if found_at >= 0:
            claims.append(
                JudgeClaim(
                    claim_id=f"code_expected_{index + 1:02d}",
                    precommit_id=precommit.precommit_id,
                    axis="plotunit_expected_change",
                    verdict="satisfied",
                    severity="advisory",
                    anchors=(
                        _found_anchor(prose, chapter_ref, found_at, len(item)),
                    ),
                    rationale=(
                        "正文已包含该 PlotUnit 预期信息/后果（正文证据落地）："
                        f"{item}"
                    ),
                    generator_source="code",
                )
            )
        else:
            severity = "blocking" if precommit.effective else "advisory"
            label = "后果" if is_consequence else "释放信息"
            claims.append(
                JudgeClaim(
                    claim_id=f"code_missing_{index + 1:02d}",
                    precommit_id=precommit.precommit_id,
                    axis="plotunit_expected_change",
                    verdict="violated",
                    severity=severity,
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale=(
                        f"正文未找到该 PlotUnit 预期{label}：『{item}』——"
                        "提交状态变化缺少对应正文证据"
                    ),
                    generator_source="code",
                )
            )
    if compact_text(precommit.expected_output_situation):
        if compact_text(precommit.expected_output_situation) in compact_text(prose):
            claims.append(
                JudgeClaim(
                    claim_id="code_situation_ok",
                    precommit_id=precommit.precommit_id,
                    axis="prose_actual_change",
                    verdict="satisfied",
                    severity="advisory",
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale="正文体现了预期输出局势。",
                    generator_source="code",
                )
            )
        else:
            claims.append(
                JudgeClaim(
                    claim_id="code_situation_missing",
                    precommit_id=precommit.precommit_id,
                    axis="prose_actual_change",
                    verdict="violated",
                    severity="advisory",
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale="正文未明显体现预期输出局势（advisory，局势可被意译）。",
                    generator_source="code",
                )
            )
    return claims
