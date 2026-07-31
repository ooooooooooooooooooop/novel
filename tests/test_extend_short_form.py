"""测试 extend_short_form slice."""

import importlib
import json

import pytest

from src.llm_interface import FileExchangeInterface, LLMInterface
from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)

ContinueUnit = importlib.import_module("src.workflow_action.continuation").ContinueUnit


class MockLLM(LLMInterface):
    """Mock LLM 接口，用于无人工介入测试."""

    def __init__(self, response: str):
        self._response = response

    def name(self) -> str:
        return "MockLLM"

    def call(self, prompt: str) -> str:
        return self._response


def test_continue_unit_prompt_builds():
    """验证 ContinueUnit 能生成 prompt 不抛异常."""
    cont = ContinueUnit()

    state = NarrativeState(
        state_id="ns_test",
        current_time="测试时间",
        current_location="测试地点",
        current_situation="测试局势",
    )
    char = CharacterModel(
        character_id="c001",
        name="测试角色",
        identity="测试身份",
        outer_goal="目标",
        inner_need="需求",
        fear="恐惧",
        flaw="缺陷",
        strength="优势",
        stance="中立",
    )
    facts = FactLedger()
    foreshadows = ForeshadowGraph()

    # 直接测试 prompt 生成（不调用 LLM）
    prompt = cont.build_prompt(state, [char], facts, foreshadows, "")
    assert "叙事续写专家" in prompt
    assert "ns_test" in prompt
    assert "c001" in prompt


def test_continue_unit_parses_response():
    """验证 ContinueUnit 能解析 Mock LLM 响应."""
    mock_response = json.dumps(
        {
            "plotunit": {
                "unit_id": "pu_test_001",
                "level": "scene",
                "goal": "测试目标",
                "participants": ["c001"],
                "conflict": "测试冲突",
                "input_state_ref": "ns_test",
                "output_state_ref": "ns_test_2",
                "released_information": ["新信息"],
                "consequences": ["后果"],
            },
            "new_state": {
                "state_id": "ns_test_2",
                "current_time": "新时间",
                "current_location": "新地点",
                "current_situation": "新局势",
                "active_characters": ["c001"],
            },
            "new_facts": [
                {
                    "fact_id": "f_test",
                    "statement": "测试事实",
                    "fact_type": "event",
                    "involved_entities": [],
                    "confirmed": True,
                }
            ],
            "confidence_gaps": ["不确定"],
        }
    )

    cont = ContinueUnit()

    plotunit, new_state, new_facts, gaps = cont.parse_response(mock_response)

    assert plotunit.unit_id == "pu_test_001"
    assert plotunit.goal == "测试目标"
    assert new_state.state_id == "ns_test_2"
    assert len(new_facts) == 1
    assert new_facts[0]["fact_id"] == "f_test"
    assert gaps == ["不确定"]


def test_extend_entry_imports():
    """验证 extend_short_form 入口可导入."""
    mod = importlib.import_module("src.extend_short_form")
    assert hasattr(mod, "main")


def test_mock_llm_interface():
    """验证 MockLLM 自身工作正常."""
    llm = MockLLM('{"test": true}')
    assert llm.call("anything") == '{"test": true}'
    assert llm.name() == "MockLLM"


def test_file_exchange_refuses_to_delete_existing_response(tmp_path):
    prompt_path = tmp_path / "continue_prompt.txt"
    response_path = tmp_path / "continue_response.txt"
    response_path.write_text("old response", encoding="utf-8")
    llm = FileExchangeInterface(prompt_path, response_path, timeout=0)

    with pytest.raises(ValueError, match="response file already exists"):
        llm.call("new prompt")

    assert response_path.read_text(encoding="utf-8") == "old response"
    assert not prompt_path.exists()


def test_continue_with_structure_template_and_frame():
    """完整状态续写：structure_template 和 frame_context 同时注入 prompt."""
    cont = ContinueUnit()
    state = NarrativeState(
        state_id="ns_test",
        current_time="测试时间",
        current_location="测试地点",
        current_situation="测试局势",
    )
    char = CharacterModel(
        character_id="c001",
        name="测试角色",
        identity="测试身份",
        outer_goal="目标",
        inner_need="需求",
        fear="恐惧",
        flaw="缺陷",
        strength="优势",
        stance="中立",
    )
    facts = FactLedger()
    foreshadows = ForeshadowGraph()

    frame_context = {
        "cursor": {"current_frame_id": "sc_001", "current_level": "scene"},
        "current_frame": {
            "frame_id": "sc_001",
            "level": "scene",
            "title": "开场",
            "purpose": "建立悬念",
            "position": "start",
            "status": "active",
        },
        "parent_chain": [
            {
                "frame_id": "book_001",
                "level": "book",
                "title": "Book",
                "purpose": "p",
                "position": "full",
                "status": "active",
            },
            {
                "frame_id": "arc_001",
                "level": "arc",
                "title": "Arc1",
                "purpose": "p",
                "position": "full",
                "status": "active",
            },
        ],
        "sibling_context": [],
        "active_threads": ["thread_book"],
    }

    prompt = cont.build_prompt(
        state,
        [char],
        facts,
        foreshadows,
        workspec_context="genre: 仙侠",
        frame_context=frame_context,
        structure_template="eight_node",
    )
    assert "结构模板: eight_node" in prompt
    assert "opener_hook" in prompt
    assert "thread_book" in prompt


def test_continue_prompt_includes_emotion_guidance():
    from src.domain_layer.rules import get_structure_template
    from src.workflow_action.frame import NarrativeFrameUnit

    state = NarrativeState(
        state_id="ns_test",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    unit = ContinueUnit()
    frame_unit = NarrativeFrameUnit()
    frames = frame_unit.build_frame("mock workspec", get_structure_template("eight_node"))
    cursor = frame_unit.get_cursor(frames)
    frame_context = frame_unit.build_continue_context(frames, cursor)

    prompt = unit.build_prompt(
        state=state,
        characters=[],
        facts=FactLedger(),
        foreshadows=ForeshadowGraph(),
        frame_context=frame_context,
    )

    assert "当前结构节点: opener_hook" in prompt
    assert "推荐情绪: 困惑 / 压抑 / 好奇" in prompt
    assert "请让 emotional_shift 体现以上某种情绪变化。" in prompt


def test_continue_with_gaps_preserves_uncertainty():
    """断点续写：confidence_gaps 被正确保留，不阻断推进."""
    mock_response = json.dumps(
        {
            "plotunit": {
                "unit_id": "pu_gap_001",
                "level": "scene",
                "goal": "推进剧情",
                "participants": ["c001"],
                "conflict": "信息不足",
                "input_state_ref": "ns_test",
                "output_state_ref": "ns_test_2",
            },
            "new_state": {
                "state_id": "ns_test_2",
                "current_time": "新时间",
                "current_location": "新地点",
                "current_situation": "新局势",
                "active_characters": ["c001"],
            },
            "new_facts": [],
            "confidence_gaps": ["角色背景未交代", "势力关系模糊"],
        }
    )

    cont = ContinueUnit()
    plotunit, new_state, new_facts, gaps = cont.parse_response(mock_response)

    assert plotunit.unit_id == "pu_gap_001"
    assert len(gaps) == 2
    assert "角色背景未交代" in gaps
    assert "势力关系模糊" in gaps


def test_review_extend_route_decision():
    """Review 对 extend 场景的 route 判断：pass 或 rewrite."""
    from src.object_state import PlotUnit, WorkSpec
    from src.workflow_action.review import ReviewUnit

    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
        structure_template="eight_node",
    )
    plotunit = PlotUnit(
        unit_id="pu_001",
        level="scene",
        goal="测试目标",
        conflict="测试冲突",
        input_state_ref="ns_001",
        output_state_ref="ns_002",
    )
    state = NarrativeState(
        state_id="ns_001",
        current_time="测试时间",
        current_location="测试地点",
        current_situation="测试局势",
    )

    review = ReviewUnit()

    # 验证 build_prompt 对 extend 场景不抛异常（_domain_rules 会执行）
    prompt = review.build_prompt([workspec, plotunit, state], context="extend")
    assert "extend" in prompt

    # 验证 parse_response 对 rewrite 路由
    mock_response = json.dumps(
        {
            "issues": [
                {
                    "issue_id": "iss_001",
                    "issue_type": "fact_conflict",
                    "severity": "blocking",
                    "location": "FactLedger",
                    "scope_of_impact": "后续",
                    "violated_rule": "事实一致性",
                    "description": "事实矛盾",
                }
            ],
            "reminders": [],
            "route": "rewrite",
        }
    )
    issues, reminders, route = review.parse_response(mock_response)
    assert route == "rewrite"
    assert len(issues) == 1
    assert issues[0].is_blocking()


def test_review_detects_emotion_mismatch():
    from src.object_state import PlotUnit
    from src.workflow_action.review import ReviewUnit

    pu = PlotUnit(
        unit_id="pu_test",
        level="scene",
        goal="测试",
        conflict="测试",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
        emotional_shift="从信任到安稳",
        formula_node="climax",
    )
    review = ReviewUnit()
    issues = review._domain_rules([pu])
    mismatch_issues = [
        issue for issue in issues if issue.issue_id == "iss_emotion_match_pu_test"
    ]

    assert len(mismatch_issues) == 1
    assert mismatch_issues[0].issue_type == "weak_progression"


def test_continue_prompt_includes_platform_guidance():
    from src.domain_layer.rules import get_structure_template
    from src.object_state import WorkSpec
    from src.workflow_action.continuation import ContinueUnit
    from src.workflow_action.frame import NarrativeFrameUnit

    state = NarrativeState(
        state_id="ns_test",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
        platform="web_novel_daily",
    )
    unit = ContinueUnit()
    frame_unit = NarrativeFrameUnit()
    frames = frame_unit.build_frame("mock workspec", get_structure_template("eight_node"))
    cursor = frame_unit.get_cursor(frames)
    frame_context = frame_unit.build_continue_context(frames, cursor)

    prompt = unit.build_prompt(
        state=state,
        characters=[],
        facts=FactLedger(),
        foreshadows=ForeshadowGraph(),
        workspec_context=workspec.to_prompt_context(),
        frame_context=frame_context,
        platform="web_novel_daily",
    )

    assert "平台约束: web_novel_daily" in prompt
    assert "chapter_end mandatory" in prompt
    assert "读者耐心较低" in prompt


def test_continue_prompt_includes_genre_guidance():
    from src.object_state import WorkSpec
    from src.workflow_action.continuation import ContinueUnit

    state = NarrativeState(
        state_id="ns_test",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )
    unit = ContinueUnit()

    prompt = unit.build_prompt(
        state=state,
        characters=[],
        facts=FactLedger(),
        foreshadows=ForeshadowGraph(),
        workspec_context=workspec.to_prompt_context(),
        genre="仙侠",
    )

    assert "仙侠 类型约束" in prompt
    assert "修为突破必须有代价" in prompt


def test_continue_prompt_critical_node_recommends_high_hook():
    from src.domain_layer.rules import get_structure_template
    from src.object_state import WorkSpec
    from src.workflow_action.continuation import ContinueUnit
    from src.workflow_action.frame import NarrativeFrameUnit

    state = NarrativeState(
        state_id="ns_test",
        current_time="测试",
        current_location="测试",
        current_situation="测试",
    )
    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )
    unit = ContinueUnit()
    frame_unit = NarrativeFrameUnit()
    frames = frame_unit.build_frame("mock workspec", get_structure_template("eight_node"))
    cursor = frame_unit.set_cursor(frames, "scene_007")
    frame_context = frame_unit.build_continue_context(frames, cursor)

    prompt = unit.build_prompt(
        state=state,
        characters=[],
        facts=FactLedger(),
        foreshadows=ForeshadowGraph(),
        workspec_context=workspec.to_prompt_context(),
        frame_context=frame_context,
        genre="仙侠",
    )

    assert "关键节点钩子要求" in prompt
    assert "high-effectiveness" in prompt


def test_extend_argparse_parses_chapter_wise():
    """验证 extend 脚本能正确解析 --chapter-wise 参数."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "src/extend_short_form.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    assert "--chapter-wise" in result.stdout


def test_extend_argparse_parses_resume():
    """验证 extend 脚本能正确解析 --resume 参数."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "src/extend_short_form.py", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    assert "--resume" in result.stdout
