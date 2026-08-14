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
    falsify_blocking,
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


def _state(state_id="ns_002", **overrides) -> NarrativeState:
    fields = {
        "current_time": "稍后",
        "current_location": "城南茶楼",
        "current_situation": "追查真相",
        "active_characters": ["c001"],
    }
    fields.update(overrides)
    return NarrativeState(state_id=state_id, **fields)


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


# ---------------------------------------------------------------- 意译容忍（G8 根因）


class TestFalsifyParaphraseTolerance:
    """长句条目在自然意译下的确定性证伪（G8：plan 句子级条目 vs prose 必然意译）."""

    def test_long_item_paraphrase_tolerated(self):
        # 长句条目，正文意译但保留词结构 → satisfied，且不构成候选级阻断。
        precommit = _precommit(
            plotunit=_plotunit(
                released=("举报信点名土地评估价低于同区基准价约两成",), consequences=()
            )
        )
        prose = ("举报信里写得明白：开发区那块地评估价压得偏低，"
                 "比同区域近三年成交均价低了差不多两成。")
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert any(c.verdict == "satisfied" for c in claims)
        assert falsify_blocking(claims) is False

    def test_situation_paraphrase_satisfied(self):
        # 预期局势是长句，正文意译但保留词结构 → satisfied（advisory）。
        situation = "沈砚已读取举报信核心内容并留存手抄副本，举报信已进入积压件"
        precommit = _precommit(
            plotunit=_plotunit(),
            new_state=_state(current_situation=situation),
        )
        prose = ("沈砚把那两页信纸的内容抄进了工作笔记，留了个副本。"
                 "举报信原封进了积压件夹子。")
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        situation_claim = [c for c in claims if c.axis == "prose_actual_change"]
        assert situation_claim and situation_claim[0].verdict == "satisfied"

    def test_soft_rendering_single_item_blocks(self):
        # 词结构完全未落地（软渲染）→ violated；单条目计划缺失即阻断。
        precommit = _precommit(
            plotunit=_plotunit(
                released=("双方关系出现微妙裂痕：顾承风完成了劝说动作，但沈砚并未承诺收手",),
                consequences=(),
            )
        )
        prose = ("顾承风坐了一个钟头，话里话外劝他把那封信归档了事。沈砚只是喝茶，"
                 "一个字也没应。末了顾承风起身告辞。")
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert any(c.verdict == "violated" for c in claims)
        assert falsify_blocking(claims) is True

    def test_absent_long_item_blocks(self):
        precommit = _precommit(
            plotunit=_plotunit(
                released=("省纪委下发了对开发区地块的巡视进驻通知",), consequences=()
            )
        )
        prose = "沈砚喝完茶，把工作笔记合上，继续整理手头的文件。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert any(c.verdict == "violated" for c in claims)
        assert falsify_blocking(claims) is True


class TestFalsifyBlockingAggregation:
    """候选级聚合：缺失项 ≥ 已落地项才硬阻断；少数缺失交 LLM 评审维."""

    def _precommit_items(self, items, effective=True):
        return _precommit(
            plotunit=_plotunit(released=items, consequences=(), is_effective=effective)
        )

    def test_majority_missing_blocks(self):
        # 2 落地 2 缺失 → 缺失 ≥ 落地 → 阻断。
        precommit = self._precommit_items(
            ["举报信点名评估价偏低", "沈砚将举报信登记备查",
             "顾承风以路过为由前来施压", "沈砚留存了手抄副本"]
        )
        prose = "沈砚展开那封举报信，记下评估价偏低，将举报信登记备查。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert falsify_blocking(claims) is True

    def test_minority_missing_not_blocking(self):
        # 3 落地 1 缺失 → 缺失 < 落地 → 不阻断；缺失项仍为 blocking 严重级 claim。
        precommit = self._precommit_items(
            ["举报信点名评估价偏低", "沈砚将举报信登记备查", "沈砚留存了手抄副本",
             "顾承风以路过为由前来施压"]
        )
        prose = ("沈砚展开那封举报信，记下评估价偏低，将举报信登记备查，还留了手抄副本。")
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert falsify_blocking(claims) is False
        missing = [c for c in claims if c.verdict == "violated"]
        assert any(claim_is_hard_violation(c) for c in missing)

    def test_non_effective_never_blocks(self):
        # 非 effective 计划缺失全 advisory → 永不硬阻断。
        precommit = self._precommit_items(
            ["省纪委下发了巡视进驻通知"], effective=False
        )
        prose = "沈砚喝完茶。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert falsify_blocking(claims) is False
