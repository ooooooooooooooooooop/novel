"""T5/T6 — 评审委员会单轴 JudgeClaim 与锚点核验单元测试（design §7-8）.

覆盖：
- 模型契约：ProseAnchor 边界有序、JudgeClaim 必带锚点（G5 无证据结论不能
  进门禁）、blocking 不允许 inconclusive。
- 锚点真实性核验（两道核验之二）：excerpt 与正文区间 compact 全等，
  伪造引文/越界偏移 → ValueError（schema/证据错误 → execution_failed）。
- 上下文隔离（T5.6）：评审 prompt 只含该候选预承诺 + 正文 + 契约，不含
  生成 prompt、其他候选正文。
- generator_source 由运行层注入（评审无法自报身份）。
"""

import pytest
from pydantic import ValidationError

from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.object_state.judge_claim import (
    JudgeClaim,
    ProseAnchor,
    claim_is_hard_violation,
    soft_axis_score,
)
from src.workflow_action.judge_council import (
    HARD_AXES,
    SOFT_AXES,
    build_judge_claim_prompt,
    parse_judge_claims,
)

_PROSE = "他推开那扇虚掩的门，屋里的油灯被风带了一下，火苗斜斜地伏下去又立起来。"


def _anchor(char_start=0, char_end=10, **overrides) -> ProseAnchor:
    payload = {
        "chapter_ref": "chapter_1",
        "position": "start",
        "excerpt": _PROSE[char_start:char_end],
        "char_start": char_start,
        "char_end": char_end,
    }
    payload.update(overrides)
    return ProseAnchor(**payload)


def _precommit() -> EvaluatorPrecommit:
    return EvaluatorPrecommit(
        precommit_id="precommit_plan_0001",
        plotunit_id="pu_001",
        input_state_id="ns_001",
        output_state_id="ns_002",
        expected_output_location="城南茶楼",
        expected_output_situation="追查真相",
        expected_released_information=("信的内容",),
        expected_consequences=("独自赴约",),
        effective=True,
        trusted_state_hash="a" * 64,
    )


def _claim(**overrides) -> JudgeClaim:
    payload = {
        "claim_id": "cl_001",
        "precommit_id": "precommit_plan_0001",
        "axis": "progression",
        "verdict": "satisfied",
        "severity": "advisory",
        "anchors": (_anchor(),),
        "rationale": "正文推进了状态。",
        "generator_source": "reader_judge",
    }
    payload.update(overrides)
    return JudgeClaim(**payload)


# ---------------------------------------------------------------- 模型契约


class TestProseAnchor:
    def test_valid(self):
        anchor = _anchor()
        assert anchor.excerpt == _PROSE[0:10]
        assert anchor.position == "start"

    def test_char_start_equals_char_end_rejected(self):
        with pytest.raises(ValidationError):
            _anchor(char_start=5, char_end=5)

    def test_negative_start_rejected(self):
        with pytest.raises(ValidationError):
            _anchor(char_start=-1, char_end=5)

    def test_blank_excerpt_rejected(self):
        with pytest.raises(ValidationError):
            _anchor(excerpt="   ")


class TestJudgeClaim:
    def test_valid(self):
        claim = _claim()
        assert claim.generator_source == "reader_judge"
        assert claim.anchors[0].chapter_ref == "chapter_1"

    def test_anchors_required_not_empty(self):
        with pytest.raises(ValidationError):
            _claim(anchors=())

    def test_blocking_cannot_be_inconclusive(self):
        with pytest.raises(ValidationError, match="blocking"):
            _claim(verdict="inconclusive", severity="blocking")

    def test_advisory_inconclusive_allowed(self):
        claim = _claim(verdict="inconclusive", severity="advisory")
        assert claim.verdict == "inconclusive"

    def test_unknown_generator_source_rejected(self):
        with pytest.raises(ValidationError):
            _claim(generator_source="llm")


class TestClaimIsHardViolation:
    def test_blocking_violated_is_hard(self):
        assert claim_is_hard_violation(
            _claim(verdict="violated", severity="blocking")
        )

    def test_blocking_satisfied_not_hard(self):
        assert not claim_is_hard_violation(
            _claim(verdict="satisfied", severity="blocking")
        )

    def test_advisory_violated_not_hard(self):
        assert not claim_is_hard_violation(
            _claim(verdict="violated", severity="advisory")
        )

    def test_inconclusive_blocking_impossible_by_contract(self):
        # 模型禁止 blocking+inconclusive，故 hard 只可能来自 blocking+violated。
        assert not claim_is_hard_violation(
            _claim(verdict="inconclusive", severity="advisory")
        )


class TestSoftAxisScore:
    def test_satisfied_plus_one(self):
        assert soft_axis_score((_claim(verdict="satisfied"),), "progression") == 1

    def test_violated_minus_one(self):
        assert soft_axis_score((_claim(verdict="violated"),), "progression") == -1

    def test_inconclusive_zero(self):
        assert soft_axis_score(
            (_claim(verdict="inconclusive"),), "progression"
        ) == 0

    def test_filtered_by_axis(self):
        claims = (
            _claim(verdict="satisfied", axis="progression"),
            _claim(verdict="violated", axis="friction"),
        )
        assert soft_axis_score(claims, "progression") == 1
        assert soft_axis_score(claims, "friction") == -1
        assert soft_axis_score(claims, "language_distinctiveness") == 0

    def test_hard_axes_not_in_soft_axis_score(self):
        # 硬轴违例不进软分数（软分数不能抵消硬违例）。
        claim = _claim(verdict="violated", axis="fact_conflict")
        for soft_axis in SOFT_AXES:
            assert soft_axis_score((claim,), soft_axis) == 0


# ---------------------------------------------------------------- 评审 prompt 隔离


class TestBuildJudgeClaimPrompt:
    def test_includes_precommit_expected_values_and_prose(self):
        prompt = build_judge_claim_prompt(
            _precommit(), _PROSE, role="reader_judge"
        )
        assert "precommit_plan_0001" in prompt
        assert "信的内容" in prompt
        assert "独自赴约" in prompt
        assert _PROSE in prompt

    def test_judge_does_not_see_generation_prompt_or_other_candidates(self):
        # 上下文隔离：评审 prompt 不含生成 prompt 标记、不含其他候选正文。
        prompt = build_judge_claim_prompt(_precommit(), _PROSE, role="reader_judge")
        assert "【续写要求】" not in prompt
        assert "【多候选要求】" not in prompt
        other_prose = "另一个候选的正文，与评审正文完全不同。"
        assert other_prose not in prompt

    def test_soft_and_hard_axes_defined(self):
        assert "progression" in SOFT_AXES
        assert "fact_conflict" in HARD_AXES
        assert set(SOFT_AXES).isdisjoint(HARD_AXES)

    def test_contract_context_injected_when_provided(self):
        prompt = build_judge_claim_prompt(
            _precommit(), _PROSE, reader_contract_context="读者等的是真相浮出水面"
        )
        assert "读者等的是真相浮出水面" in prompt


# ---------------------------------------------------------------- 严格解析 + 锚点核验


def _claim_json(**claim_overrides) -> dict:
    claim = {
        "claim_id": "cl_001",
        "precommit_id": "precommit_plan_0001",
        "axis": "progression",
        "verdict": "satisfied",
        "severity": "advisory",
        "anchors": [
            {"position": "start", "excerpt": _PROSE[0:12], "char_start": 0, "char_end": 12}
        ],
        "rationale": "正文推进了状态。",
    }
    claim.update(claim_overrides)
    return claim


def _parse(prose=_PROSE, claims=None, **kwargs):
    payload = json_dumps({"claims": claims if claims is not None else [_claim_json()]})
    return parse_judge_claims(payload, prose=prose, chapter_ref="chapter_1",
                              role="reader_judge", precommit=_precommit(), **kwargs)


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


class TestParseJudgeClaims:
    def test_valid_parses_with_injected_context(self):
        claims = _parse()
        assert len(claims) == 1
        claim = claims[0]
        assert claim.generator_source == "reader_judge"  # 运行层注入，评审无法自报
        assert claim.anchors[0].chapter_ref == "chapter_1"
        assert claim.precommit_id == "precommit_plan_0001"

    def test_empty_claims_allowed(self):
        assert _parse(claims=[]) == []

    def test_non_object_top_level_rejected(self):
        with pytest.raises(ValueError, match="only 'claims'"):
            parse_judge_claims(json_dumps({"claims": [], "extra": 1}),
                               prose=_PROSE, chapter_ref="chapter_1",
                               role="reader_judge", precommit=_precommit())

    def test_extra_claim_field_rejected(self):
        with pytest.raises(ValueError, match="extra field"):
            _parse(claims=[_claim_json(generator_source="reader_judge")])

    def test_missing_claim_field_rejected(self):
        with pytest.raises(ValueError, match="missing field"):
            claim = _claim_json()
            del claim["rationale"]
            _parse(claims=[claim])

    def test_wrong_precommit_rejected(self):
        with pytest.raises(ValueError, match="wrong precommit"):
            _parse(claims=[_claim_json(precommit_id="precommit_plan_9999")])

    def test_empty_anchors_rejected(self):
        with pytest.raises(ValueError, match="non-empty list"):
            _parse(claims=[_claim_json(anchors=[])])

    def test_out_of_bounds_anchor_rejected(self):
        with pytest.raises(ValueError, match="invalid char bounds"):
            _parse(claims=[_claim_json(anchors=[{
                "position": "start",
                "excerpt": "越界",
                "char_start": 0,
                "char_end": len(_PROSE) + 5,
            }])])

    def test_anchor_order_reversed_rejected(self):
        with pytest.raises(ValueError, match="invalid char bounds"):
            _parse(claims=[_claim_json(anchors=[{
                "position": "start",
                "excerpt": "倒序",
                "char_start": 12,
                "char_end": 5,
            }])])

    def test_fabricated_anchor_rejected(self):
        # 评审伪造引文（paraphrase 冒充原文）→ 整批拒绝。
        with pytest.raises(ValueError, match="fabricated anchor"):
            _parse(claims=[_claim_json(anchors=[{
                "position": "start",
                "excerpt": "这是完全不同的措辞，不是正文原文",
                "char_start": 0,
                "char_end": 12,
            }])])

    def test_anchor_with_extra_field_rejected(self):
        with pytest.raises(ValueError, match="must have exactly"):
            _parse(claims=[_claim_json(anchors=[{
                "position": "start",
                "excerpt": _PROSE[0:5],
                "char_start": 0,
                "char_end": 5,
                "chapter_ref": "chapter_1",  # 评审不许自报章节
            }])])

    def test_blank_rationale_rejected(self):
        with pytest.raises(ValueError):
            _parse(claims=[_claim_json(rationale="   ")])
