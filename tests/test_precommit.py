"""T5 — EvaluatorPrecommit 生成与确定性证伪单元测试（design §8；doc 48 §6 step 6）.

覆盖：
- 预承诺不可变性（G5）：正文前冻结，同一预承诺对两份不同正文产生相同对象，
  无正文字段（extra=forbid 使塞正文派生信息直接失败）。
- 词语检索不冒充语义判断；逐项事实评审覆盖作为选稿前置条件。
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
    evidence_obligations,
    unresolved_evidence,
    _find_item,
    validate_commit_evidence,
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
        # 即便逐字命中，也不能把提及认作已发生；不依赖关键词的特殊名单。
        item = "材料已经送到负责人案头"
        precommit = _precommit(plotunit=_plotunit(released=(item,), consequences=()))
        cases = [
            "材料已经送到负责人案头。负责人签收了。",
            "他打算把材料送到负责人案头，等办妥后再联系。",
            "材料没有送到负责人案头，仍锁在柜子里。",
            "如果材料已经送到负责人案头，事情就好办了。",
            "他误以为材料已经送到负责人案头，其实尚未寄出。",
            "材料并非没有送到负责人案头，他已经签收。",
            "他说材料已经送到负责人案头，接收者却否认收到。",
            "材料上午未寄出，下午已经送到负责人案头。",
            "甲的材料已经送到负责人案头，乙的仍未寄出。",
            "材料已经送到负责人案头，他打算明天再送另一份。",
        ]
        for prose in cases:
            claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
            assert all(c.verdict == "inconclusive" for c in claims)
            assert all(c.severity == "advisory" for c in claims)
            assert unresolved_evidence(precommit, claims)  # 无事实评审不能过关。
            for c in claims:
                for a in c.anchors:
                    assert prose[a.char_start:a.char_end] == a.excerpt

    def test_missing_information_blocking_for_effective(self):
        precommit = _precommit()
        claims = falsify_prose_against_precommit(precommit, "他只字未提。", "chapter_1")
        assert not any(claim_is_hard_violation(c) for c in claims)
        assert set(unresolved_evidence(precommit, claims)) == set(evidence_obligations(precommit))

    def test_missing_information_advisory_for_non_effective(self):
        precommit = _precommit(plotunit=_plotunit(is_effective=False))
        claims = falsify_prose_against_precommit(precommit, "他走进茶楼。", "chapter_1")
        assert all(c.verdict == "inconclusive" for c in claims)
        assert unresolved_evidence(precommit, claims)  # 非 effective 也不自动确认世界事实。

    def test_situation_present_satisfied_advisory(self):
        precommit = _precommit()
        assert evidence_obligations(precommit) == {
            "evidence_location": "城南茶楼", "evidence_situation": "追查真相",
            "evidence_released_001": "信的内容", "evidence_consequence_001": "独自赴约",
            "evidence_state_current_time": '{"after": "稍后", "before": "夜晚", "field": "current_time"}',
        }
        assert evidence_obligations(precommit) == evidence_obligations(_precommit())
        claims = falsify_prose_against_precommit(precommit, "他追查真相。", "chapter_1")
        assert all(c.verdict == "inconclusive" for c in claims)

    def test_situation_missing_advisory_not_blocking(self):
        claims = falsify_prose_against_precommit(_precommit(), "他走进茶楼。", "chapter_1")
        assert all(c.severity == "advisory" for c in claims)
        assert not falsify_blocking(claims)
        with pytest.raises(ValueError, match="empty prose"):
            falsify_prose_against_precommit(_precommit(), "  ", "chapter_1")

    def test_all_claims_carry_real_anchors(self):
        prose = "开场。\n\n他看完信的 内容，\n决定独自赴约。"
        claims = falsify_prose_against_precommit(_precommit(), prose, "chapter_1")
        assert _find_item(prose, "信的内容") == prose.index("信的")
        assert _find_item(prose, "独自赴约") == prose.index("独自赴约")
        for claim in claims:
            anchor = claim.anchors[0]
            assert prose[anchor.char_start:anchor.char_end] == anchor.excerpt

    def test_precommit_id_binding(self):
        precommit = _precommit()
        hint = falsify_prose_against_precommit(precommit, "信的内容", "chapter_1")[0]
        # 人工构造已校验的评审对象，仅测试覆盖门禁，绝不是语义准确率证据。
        claims = [hint.model_copy(update={"claim_id": key, "axis": "fact_conflict",
                  "generator_source": "fact_judge", "verdict": "satisfied"})
                  for key in evidence_obligations(precommit)]
        assert unresolved_evidence(precommit, claims) == {}
        assert unresolved_evidence(precommit, claims[:-1]) == {claims[-1].claim_id: "missing"}
        assert unresolved_evidence(precommit, claims + [claims[0]]) == {claims[0].claim_id: "duplicate"}
        for field, value, reason in [
            ("precommit_id", "another_plan", "wrong_binding"),
            ("generator_source", "reader_judge", "wrong_binding"),
            ("axis", "progression", "wrong_binding"),
            ("verdict", "inconclusive", "inconclusive"),
            ("verdict", "violated", "violated"),
        ]:
            changed = [claims[0].model_copy(update={field: value}), *claims[1:]]
            assert unresolved_evidence(precommit, changed) == {claims[0].claim_id: reason}
        # A full candidate freeze covers new facts and every semantic state change.
        import hashlib
        import json
        previous = _input_state()
        previous.hidden_information = ["柜子里存着副本"]
        proposed = previous.model_copy(deep=True, update={"state_id": "ns_002"})
        proposed.private_information_map = {"柜子里存着副本": ["c001"]}
        facts = [{"fact_id": "f_new", "statement": "钥匙已交还", "fact_type": "event", "confirmed": True}]
        plan = _plotunit(released=(), consequences=())
        bound = build_evaluator_precommit(precommit_id="bound", plotunit=plan,
            input_state=previous, new_state=proposed, new_facts=facts, trusted_state_hash=_TRUSTED_HASH)
        obligations = evidence_obligations(bound)
        assert set(obligations) == {"evidence_state_private_information_map", "evidence_fact_001"}
        assert "evidence_state_hidden_information" not in obligations  # unchanged: no repeated exposition
        assert "evidence_location" not in obligations
        assert "evidence_situation" not in obligations
        body = "他交还了钥匙，获悉了副本所在。"
        hint = falsify_prose_against_precommit(bound, body, "chapter_1")[0]
        reviewed = [hint.model_copy(update={"claim_id": key, "axis": "fact_conflict",
                    "generator_source": "fact_judge", "verdict": "satisfied"}) for key in obligations]
        args = dict(plotunit=plan, new_state=proposed, new_facts=facts, prose=body,
                    reviewed_prose_sha256=hashlib.sha256(body.encode()).hexdigest(), claims=reviewed)
        validate_commit_evidence(bound, **args)
        for field, value in [("new_facts", []), ("prose", body + "后来。"),
                             ("new_state", proposed.model_copy(update={"current_goals": ["新目标"]})),
                             ("plotunit", plan.model_copy(update={"goal": "替换的计划"})), ("claims", [])]:
            with pytest.raises(ValueError):
                validate_commit_evidence(bound, **{**args, field: value})
        with pytest.raises(ValidationError, match="payload hash"):
            EvaluatorPrecommit.model_validate({**bound.model_dump(), "candidate_payload_json": "{}"})
        with pytest.raises(ValidationError, match="declared expectations"):
            EvaluatorPrecommit.model_validate({**bound.model_dump(), "expected_output_location": "另一地点"})
        legacy = EvaluatorPrecommit.model_validate({**bound.model_dump(), "input_state_json": "",
            "candidate_payload_json": "", "candidate_payload_sha256": ""})
        with pytest.raises(ValueError, match="legacy precommit"):
            validate_commit_evidence(legacy, **args)
        # Mutating the original objects cannot alter the frozen snapshot.
        frozen = bound.candidate_payload_json
        facts[0]["statement"] = "篡改的事实"
        proposed.private_information_map["柜子里存着副本"].append("c002")
        assert bound.candidate_payload_json == frozen
        assert json.loads(frozen)["new_facts"][0]["statement"] == "钥匙已交还"


class TestFalsifyParaphraseTolerance:
    def test_long_item_paraphrase_tolerated(self):
        precommit = _precommit(plotunit=_plotunit(
            released=("举报信点名土地评估价低于同区基准价约两成",), consequences=()))
        prose = "举报信里写得明白：开发区那块地评估价压得偏低，比同区域近三年成交均价低了差不多两成。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert all(c.verdict == "inconclusive" for c in claims)
        assert not falsify_blocking(claims)

    def test_situation_paraphrase_satisfied(self):
        precommit = _precommit(new_state=_state(current_situation="调查者已经抄录信件并留存副本"))
        prose = "他把信上的内容抄进工作笔记，留了个副本。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert all(c.verdict == "inconclusive" for c in claims)
        assert unresolved_evidence(precommit, claims)

    def test_soft_rendering_single_item_blocks(self):
        # 间接表达不能凭词语缺失判错；完整语义核对仍是选稿前置条件。
        precommit = _precommit(plotunit=_plotunit(released=("来客劝说，但主人没有答应",), consequences=()))
        prose = "来客话里话外劝他把信归档。主人只是喝茶，一个字也没应。"
        claims = falsify_prose_against_precommit(precommit, prose, "chapter_1")
        assert not falsify_blocking(claims)
        assert unresolved_evidence(precommit, claims)

    def test_absent_long_item_blocks(self):
        precommit = _precommit(plotunit=_plotunit(released=("巡视组下发了进驻通知",), consequences=()))
        claims = falsify_prose_against_precommit(precommit, "他喝完茶，合上笔记。", "chapter_1")
        assert not falsify_blocking(claims)
        assert unresolved_evidence(precommit, claims)


class TestFalsifyBlockingAggregation:
    """保留既有显式硬违例聚合；词语检索不再伪造这类断言。"""
    def _claim(self, verdict, severity="advisory"):
        hint = falsify_prose_against_precommit(_precommit(), "正文", "chapter_1")[-1]
        return hint.model_copy(update={"axis": "plotunit_expected_change",
                                      "verdict": verdict, "severity": severity})

    def test_majority_missing_blocks(self):
        assert falsify_blocking([self._claim("violated", "blocking"), self._claim("satisfied")])

    def test_minority_missing_not_blocking(self):
        assert not falsify_blocking([self._claim("violated", "blocking"),
                                     self._claim("satisfied"), self._claim("satisfied")])

    def test_non_effective_never_blocks(self):
        assert not falsify_blocking([self._claim("violated"), self._claim("inconclusive")])
