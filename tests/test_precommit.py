"""T5 — EvaluatorPrecommit 生成与确定性证伪单元测试（design §8；doc 48 §6 step 6）.

覆盖：
- 预承诺不可变性（G5）：正文前冻结，同一预承诺对两份不同正文产生相同对象，
  无正文字段（extra=forbid 使塞正文派生信息直接失败）。
- 纯代码证伪：释放信息/后果在正文 → satisfied（真实锚点）；缺失 →
  violated（effective=blocking，非 effective=advisory）；局势缺失 → advisory。
- 锚点真实性：excerpt 必须与正文区间逐字全等（无法捏造）。
"""

import pytest
from pydantic import ValidationError

from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.object_state.judge_claim import claim_is_hard_violation
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.precommit import (
    build_evaluator_precommit,
    falsify_prose_against_precommit,
)

_TRUSTED_HASH = "a" * 64


def _plotunit(*, released=("信的内容",), consequences=("独自赴约",),
              is_effective=True) -> PlotUnit:
    return PlotUnit(
        unit_id="pu_001",
        level="scene",
        goal="推进",
        participants=["c001"],
        conflict="候选冲突",
        input_state_ref="ns_001",
        output_state_ref="ns_002",
        released_information=list(released),
        consequences=list(consequences),
        is_effective=is_effective,
    )


def _state(state_id="ns_002") -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="稍后",
        current_location="城南茶楼",
        current_situation="追查真相",
        active_characters=["c001"],
    )


def _input_state() -> NarrativeState:
    return NarrativeState(
        state_id="ns_001",
        current_time="夜晚",
        current_location="案发现场",
        current_situation="调查开始",
        active_characters=["c001"],
    )


def _precommit(*, plotunit=None, input_state=None, new_state=None) -> EvaluatorPrecommit:
    return build_evaluator_precommit(
        precommit_id="precommit_plan_0001",
        plotunit=plotunit or _plotunit(),
        input_state=input_state or _input_state(),
        new_state=new_state or _state(),
        trusted_state_hash=_TRUSTED_HASH,
    )


# ---------------------------------------------------------------- 不可变性（G5）


class TestEvaluatorPrecommitImmutability:
    def test_same_precommit_for_different_prose(self):
        precommit = _precommit()
        # 同一预承诺对两份不同正文的对象完全相等（冻结于正文前）。
        assert precommit == _precommit()

    def test_no_prose_field_structurally(self):
        assert "prose" not in precommit_field_names(_precommit())

    def test_extra_prose_field_rejected(self):
        with pytest.raises(ValidationError):
            EvaluatorPrecommit.model_validate(
                {
                    "precommit_id": "precommit_plan_0001",
                    "plotunit_id": "pu_001",
                    "input_state_id": "ns_001",
                    "output_state_id": "ns_002",
                    "expected_output_location": "城南茶楼",
                    "expected_output_situation": "追查真相",
                    "expected_released_information": ["信的内容"],
                    "expected_consequences": ["独自赴约"],
                    "effective": True,
                    "trusted_state_hash": _TRUSTED_HASH,
                    "prose": "试图把正文塞进预承诺",
                }
            )

    def test_empty_released_information_rejected(self):
        with pytest.raises(ValidationError):
            EvaluatorPrecommit.model_validate(
                {
                    "precommit_id": "p1",
                    "plotunit_id": "pu_001",
                    "input_state_id": "ns_001",
                    "output_state_id": "ns_002",
                    "expected_output_location": "城南茶楼",
                    "expected_output_situation": "追查真相",
                    "expected_released_information": [" "],
                    "expected_consequences": ["独自赴约"],
                    "effective": True,
                    "trusted_state_hash": _TRUSTED_HASH,
                }
            )


def precommit_field_names(precommit: EvaluatorPrecommit) -> list[str]:
    return list(precommit.model_dump().keys())


# ---------------------------------------------------------------- 确定性证伪


class TestFalsifyProseAgainstPrecommit:
    def test_present_information_satisfied_with_real_anchor(self):
        prose = "他展开信，信的内容清清楚楚，他决定独自赴约。"
        claims = falsify_prose_against_precommit(
            _precommit(), prose, chapter_ref="chapter_1"
        )
        satisfied = [c for c in claims if c.verdict == "satisfied"]
        assert len(satisfied) == 2  # 释放信息 + 后果
        for claim in satisfied:
            assert claim.generator_source == "code"
            # 锚点真实性：excerpt 必须逐字取自正文该区间。
            anchor = claim.anchors[0]
            assert prose[anchor.char_start:anchor.char_end] == anchor.excerpt

    def test_missing_information_blocking_for_effective(self):
        prose = "他展开信，却只字未提那件事。"
        precommit = _precommit()
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        missing = [
            c for c in claims
            if c.verdict == "violated" and c.axis == "plotunit_expected_change"
        ]
        assert missing, "effective 单元缺失释放信息必须是 violated"
        assert all(claim_is_hard_violation(c) for c in missing)
        assert all(c.axis == "plotunit_expected_change" for c in missing)

    def test_missing_information_advisory_for_non_effective(self):
        precommit = _precommit(plotunit=_plotunit(is_effective=False))
        prose = "他走进茶楼。"
        missing = [
            c for c in falsify_prose_against_precommit(precommit, prose, "chapter_1")
            if c.verdict == "violated"
        ]
        assert missing
        assert not any(claim_is_hard_violation(c) for c in missing)

    def test_situation_present_satisfied_advisory(self):
        prose = "他走进城南茶楼，追查真相的气氛压在每个人脸上。"
        claims = falsify_prose_against_precommit(_precommit(), prose, "chapter_1")
        situation = [c for c in claims if c.axis == "prose_actual_change"]
        assert situation
        assert situation[0].verdict == "satisfied"
        assert situation[0].severity == "advisory"

    def test_situation_missing_advisory_not_blocking(self):
        prose = "他走进茶楼。"
        claims = falsify_prose_against_precommit(_precommit(), prose, "chapter_1")
        situation = [c for c in claims if c.axis == "prose_actual_change"]
        assert situation
        assert situation[0].verdict == "violated"
        assert situation[0].severity == "advisory"  # 局势可被意译，不作硬门禁

    def test_all_claims_carry_real_anchors(self):
        prose = "他展开信，信的内容清清楚楚，他决定独自赴约。"
        claims = falsify_prose_against_precommit(_precommit(), prose, "chapter_1")
        for claim in claims:
            anchor = claim.anchors[0]
            assert prose[anchor.char_start:anchor.char_end] == anchor.excerpt

    def test_precommit_id_binding(self):
        claims = falsify_prose_against_precommit(
            _precommit(), "信的内容", "chapter_1"
        )
        assert all(c.precommit_id == "precommit_plan_0001" for c in claims)
