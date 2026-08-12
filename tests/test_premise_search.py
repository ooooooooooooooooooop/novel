"""T4 — needs_premise 自动前提搜索单元测试：模型契约 / prompt / 严格解析 / 义务匹配 /
帧投影 / 确定性验证.

与 test_autonomous_runner.py 的集成测试互补：此处直接构造 PremiseCandidate 与帧状态，
断言验证逻辑本身（不经过 runner / provider）。
"""

import json

import pytest
from pydantic import ValidationError

from src.object_state.foreshadowgraph import ForeshadowGraph
from src.object_state.premise_candidate import PremiseCandidate
from src.object_state.readercontract import ReaderContract
from src.object_state.workspec import WorkSpec
from src.workflow_action.continuation_viability import analyze_continuation_viability
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.premise_search import (
    build_premise_search_prompt,
    match_open_promise_threads,
    parse_premise_candidates,
    project_premise_frames,
    validate_premise_candidate,
)


def _candidate_payload(**overrides) -> dict:
    payload = {
        "candidate_id": "premise-001",
        "new_external_conflict": "外部势力逼近",
        "new_phase_goal": "追查神秘来信背后的人",
        "boundary_to_closed_arc": "不重开已闭合的情感闭环",
        "obligations_to_old_promises": ["rem_001"],
        "new_state_change": "主角获得关键线索",
        "reader_contract_legal": True,
        "reader_contract_reason": "延续契约悬念核心",
    }
    payload.update(overrides)
    return payload


def _open_foreshadows(entries: list[dict] | None = None) -> ForeshadowGraph:
    if entries is None:
        entries = [
            {
                "thread_id": "rem_001",
                "setup_point": "第一章",
                "content": "神秘来信",
                "visibility_level": "explicit",
                "expected_payoff": "回收",
                "current_status": "active",
            }
        ]
    return ForeshadowGraph(entries=entries)


def _workspec() -> WorkSpec:
    return WorkSpec(
        genre="悬疑",
        audience="青年",
        theme="真相",
        tone="克制",
        pacing="短弧推进",
    )


def _contract() -> ReaderContract:
    return ReaderContract(
        contract_id="contract-001",
        audience="青年读者",
        core_pleasures=["悬念推进", "人物可信"],
        follow_reason="主角坚持追查真相",
        core_tension="真相与代价",
        chapter_pacing="每章一个新线索",
        opening_minimum_promise="主角面临选择并付出代价",
    )


def _completed_frames() -> list:
    """结构完整但全部 completed → no_active_frame（needs_premise 前置条件）。"""
    unit = NarrativeFrameUnit()
    frames = unit.build_frame(
        workspec_context="作品类型: 悬疑\n主题: 真相\n",
        structure_template=[{"name": "rising_action", "purpose": "p", "position": "flexible"}],
    )
    for frame in frames:
        frame["status"] = "completed"
    return frames


# ---------------------------------------------------------------- 模型契约


class TestPremiseCandidateModel:
    def test_valid(self):
        cand = PremiseCandidate(**{
            "candidate_id": "premise-001",
            "new_external_conflict": "外部势力逼近",
            "new_phase_goal": "追查神秘来信背后的人",
            "boundary_to_closed_arc": "不重开已闭合的情感闭环",
            "obligations_to_old_promises": ["rem_001"],
            "new_state_change": "主角获得关键线索",
            "reader_contract_legal": True,
            "reader_contract_reason": "延续契约悬念核心",
        })
        assert cand.candidate_id == "premise-001"
        assert cand.obligations_to_old_promises == ("rem_001",)
        assert cand.reader_contract_legal is True

    def test_empty_obligations_rejected(self):
        with pytest.raises(ValidationError):
            PremiseCandidate(**{
                "candidate_id": "premise-001",
                "new_external_conflict": "外部势力逼近",
                "new_phase_goal": "追查神秘来信背后的人",
                "boundary_to_closed_arc": "不重开已闭合的情感闭环",
                "obligations_to_old_promises": [],
                "new_state_change": "主角获得关键线索",
                "reader_contract_legal": True,
                "reader_contract_reason": "延续契约悬念核心",
            })

    def test_blank_obligation_entry_rejected(self):
        with pytest.raises(ValidationError):
            PremiseCandidate(**{
                "candidate_id": "premise-001",
                "new_external_conflict": "外部势力逼近",
                "new_phase_goal": "追查神秘来信背后的人",
                "boundary_to_closed_arc": "不重开已闭合的情感闭环",
                "obligations_to_old_promises": ["  "],
                "new_state_change": "主角获得关键线索",
                "reader_contract_legal": True,
                "reader_contract_reason": "延续契约悬念核心",
            })

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            PremiseCandidate(**_candidate_payload(extra="不应出现"))


# ---------------------------------------------------------------- prompt 构建


class TestBuildPremiseSearchPrompt:
    def test_contains_obligations_count_and_frame(self):
        prompt = build_premise_search_prompt(
            state_context="【当前状态】\n调查中",
            workspec_context="作品约束文本",
            frame_context={"current_frame": {"frame_id": "scene_001"}},
            open_promises=[("rem_001", "神秘来信")],
            count=4,
        )
        assert "【当前状态】" in prompt
        assert "【未兑现承诺（活跃线索）】" in prompt
        assert "rem_001: 神秘来信" in prompt
        assert "【作品约束】" in prompt
        assert "作品约束文本" in prompt
        assert '"candidates"' in prompt
        assert "生成 4 个互不相同的候选" in prompt
        assert json.dumps(
            {"current_frame": {"frame_id": "scene_001"}}, ensure_ascii=False, indent=2
        ) in prompt

    def test_required_premise_and_contract_sections(self):
        prompt = build_premise_search_prompt(
            state_context="s",
            workspec_context="w",
            frame_context=None,
            open_promises=[("rem_001", "神秘来信")],
            contract_context="读者契约正文",
            required_premise="需新前提以推进承诺",
            count=2,
        )
        assert "【所需前提】" in prompt
        assert "需新前提以推进承诺" in prompt
        assert "【读者契约】" in prompt
        assert "读者契约正文" in prompt

    def test_absent_optional_sections(self):
        prompt = build_premise_search_prompt(
            state_context="s",
            workspec_context="w",
            frame_context=None,
            open_promises=[],
            count=1,
        )
        assert "【所需前提】" not in prompt
        assert "【读者契约】" not in prompt


# ---------------------------------------------------------------- 严格解析


class TestParsePremiseCandidates:
    def test_valid_single(self):
        response = json.dumps({"candidates": [_candidate_payload()]})
        parsed = parse_premise_candidates(response)
        assert len(parsed) == 1
        assert parsed[0].candidate_id == "premise-001"

    def test_valid_multiple(self):
        response = json.dumps({
            "candidates": [
                _candidate_payload(candidate_id="premise-001"),
                _candidate_payload(candidate_id="premise-002"),
            ]
        })
        assert len(parse_premise_candidates(response)) == 2

    def test_missing_field_rejected(self):
        bad = _candidate_payload()
        del bad["reader_contract_reason"]
        with pytest.raises(ValueError, match="missing field"):
            parse_premise_candidates(json.dumps({"candidates": [bad]}))

    def test_extra_field_rejected(self):
        with pytest.raises(ValueError, match="unexpected field"):
            parse_premise_candidates(json.dumps({
                "candidates": [_candidate_payload(bonus="x")]
            }))

    def test_duplicate_candidate_id_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            parse_premise_candidates(json.dumps({
                "candidates": [
                    _candidate_payload(candidate_id="premise-001"),
                    _candidate_payload(candidate_id="premise-001"),
                ]
            }))

    def test_empty_candidates_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_premise_candidates(json.dumps({"candidates": []}))

    def test_non_object_candidate_rejected(self):
        with pytest.raises(ValueError, match="must be an object"):
            parse_premise_candidates(json.dumps({"candidates": ["premise-001"]}))

    def test_non_list_candidates_rejected(self):
        with pytest.raises(ValueError, match="non-empty list"):
            parse_premise_candidates(json.dumps({"candidates": "premise-001"}))

    def test_blank_candidate_id_rejected(self):
        with pytest.raises(ValueError, match="blank"):
            parse_premise_candidates(json.dumps({
                "candidates": [_candidate_payload(candidate_id="   ")]
            }))


# ---------------------------------------------------------------- 义务匹配


class TestMatchOpenPromiseThreads:
    def _threads(self):
        return _open_foreshadows().entries

    def test_exact_thread_id(self):
        assert match_open_promise_threads(["rem_001"], self._threads()) == ["rem_001"]

    def test_content_mutual_substring(self):
        # 义务用承诺内容指向 → 内容互含即命中
        assert match_open_promise_threads(["神秘来信"], self._threads()) == ["rem_001"]

    def test_no_match(self):
        assert match_open_promise_threads(["虚造承诺"], self._threads()) == []


# ---------------------------------------------------------------- 帧投影


class TestProjectPremiseFrames:
    def test_creates_chain_and_deactivates_old(self):
        frames = _completed_frames()
        candidate = PremiseCandidate(**_candidate_payload())
        projected = project_premise_frames(
            candidate, frames, next_chapter_number=2, matched_thread_ids=["rem_001"]
        )
        by_id = {f["frame_id"]: f for f in projected}
        assert by_id["arc_002"]["level"] == "arc"
        assert by_id["arc_002"]["status"] == "active"
        assert by_id["arc_002"]["purpose"] == candidate.new_phase_goal
        assert by_id["arc_002"]["active_thread_ids"] == ["rem_001"]
        assert by_id["arc_002"]["parent_id"] == "book_001"
        assert by_id["chapter_002"]["title"] == "Chapter 2"
        assert by_id["chapter_002"]["parent_id"] == "arc_002"
        assert by_id["scene_002"]["formula_node"] == "rising_action"
        assert by_id["scene_002"]["parent_id"] == "chapter_002"

    def test_cursor_points_to_new_scene_and_validate_passes(self):
        frames = _completed_frames()
        candidate = PremiseCandidate(**_candidate_payload())
        projected = project_premise_frames(
            candidate, frames, next_chapter_number=2, matched_thread_ids=["rem_001"]
        )
        unit = NarrativeFrameUnit()
        blocking = [i for i in unit.validate_frame_state(projected) if i["severity"] == "blocking"]
        assert blocking == []
        cursor = unit.get_cursor(projected)
        assert cursor is not None
        assert cursor["current_frame_id"] == "scene_002"

    def test_original_frames_not_mutated(self):
        frames = _completed_frames()
        snapshot = json.dumps(frames, ensure_ascii=False, sort_keys=True)
        project_premise_frames(
            PremiseCandidate(**_candidate_payload()),
            frames,
            next_chapter_number=2,
            matched_thread_ids=["rem_001"],
        )
        assert json.dumps(frames, ensure_ascii=False, sort_keys=True) == snapshot

    def test_projection_returns_continue_viability(self):
        # 投影新帧后 viability 必须回到 continue（新 scene 非终止节点 + 承诺待推进）
        frames = _completed_frames()
        candidate = PremiseCandidate(**_candidate_payload())
        projected = project_premise_frames(
            candidate, frames, next_chapter_number=2, matched_thread_ids=["rem_001"]
        )
        unit = NarrativeFrameUnit()
        context = unit.build_continue_context(projected, unit.get_cursor(projected))
        verdict = analyze_continuation_viability(
            narrative_state=None,
            foreshadows=_open_foreshadows(),
            frame_context=context,
            workspec=_workspec(),
        )
        assert verdict.verdict == "continue"


# ---------------------------------------------------------------- 确定性验证


class TestValidatePremiseCandidate:
    def test_valid_candidate_passes(self):
        ok, reason = validate_premise_candidate(
            PremiseCandidate(**_candidate_payload()),
            foreshadows=_open_foreshadows(),
            frame_context=None,
            workspec=_workspec(),
            contract=_contract(),
            frames=_completed_frames(),
            next_chapter_number=2,
        )
        assert ok, reason

    def test_bad_obligation_rejected(self):
        ok, reason = validate_premise_candidate(
            PremiseCandidate(**_candidate_payload(obligations_to_old_promises=["虚造承诺"])),
            foreshadows=_open_foreshadows(),
            frame_context=None,
            workspec=_workspec(),
            contract=_contract(),
            frames=_completed_frames(),
            next_chapter_number=2,
        )
        assert not ok
        assert "未命中" in reason

    def test_no_open_promises_rejected(self):
        ok, reason = validate_premise_candidate(
            PremiseCandidate(**_candidate_payload()),
            foreshadows=_open_foreshadows(entries=[]),
            frame_context=None,
            workspec=_workspec(),
            contract=_contract(),
            frames=_completed_frames(),
            next_chapter_number=2,
        )
        assert not ok
        assert "stop" in reason

    def test_reader_contract_illegal_rejected(self):
        ok, reason = validate_premise_candidate(
            PremiseCandidate(**_candidate_payload(reader_contract_legal=False)),
            foreshadows=_open_foreshadows(),
            frame_context=None,
            workspec=_workspec(),
            contract=_contract(),
            frames=_completed_frames(),
            next_chapter_number=2,
        )
        assert not ok
        assert "读者契约" in reason

    def test_blank_content_impossible_at_model_layer(self):
        # PremiseCandidate frozen + min_length=1：空白冲突/目标在模型层即被拒，
        # validate_premise_candidate 中的空内容检查为防御性（经 parse 的候选不可能空白）。
        with pytest.raises(ValidationError):
            PremiseCandidate(**{
                **_candidate_payload(),
                "new_external_conflict": "  ",
                "new_phase_goal": "",
            })

    def test_conflict_equals_goal_rejected(self):
        ok, reason = validate_premise_candidate(
            PremiseCandidate(**{
                **_candidate_payload(),
                "new_external_conflict": "追查神秘来信背后的人",
                "new_phase_goal": "追查神秘来信背后的人",
            }),
            foreshadows=_open_foreshadows(),
            frame_context=None,
            workspec=_workspec(),
            contract=_contract(),
            frames=_completed_frames(),
            next_chapter_number=2,
        )
        assert not ok
        assert "重复" in reason
