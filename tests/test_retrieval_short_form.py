"""Tests for the --retrieval switch in compose/extend short-form CLI and novel_cli passthrough."""

import subprocess
import sys
from pathlib import Path

from src.boundary_control.runtime_state import require_continue_runtime_state
from src.compose_short_form import initialize_from_workspec
from src.domain_layer.rules import get_structure_template
from src.object_state import (
    FactEntry,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    WorkSpec,
)
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.retrieval import load_retrieval_context

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SAMPLE_TEXT = """第一章 缘起

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
他这双手在藏书阁待了六年。今天那扇门是开着的。
他推开了门，看见那本书躺在地窖最深处。
"""


def _run_script(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, f"src/{script}", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _compose_continue_chain() -> tuple:
    """构造 compose 默认 WorkSpec 的 Continue 调用链所需对象."""
    workspec = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )
    objects = initialize_from_workspec(workspec)
    ws, _wm, narrative_state, characters, facts, foreshadows = (
        require_continue_runtime_state(objects)
    )
    frame_unit = NarrativeFrameUnit()
    frames = frame_unit.build_frame(
        workspec_context=ws.to_prompt_context(),
        structure_template=get_structure_template("eight_node"),
    )
    frame_context = frame_unit.build_continue_context(frames, frame_unit.get_cursor(frames))
    return ws, narrative_state, characters, facts, foreshadows, frame_context


def test_compose_argparse_parses_retrieval():
    result = _run_script("compose_short_form.py", "--help")
    assert result.returncode == 0
    assert "--retrieval" in result.stdout


def test_extend_argparse_parses_retrieval():
    result = _run_script("extend_short_form.py", "--help")
    assert result.returncode == 0
    assert "--retrieval" in result.stdout


def test_compose_off_has_no_retrieval_section():
    ws, narrative_state, characters, facts, foreshadows, frame_context = (
        _compose_continue_chain()
    )
    prompt = ContinueUnit().build_prompt(
        state=narrative_state,
        characters=characters,
        facts=facts,
        foreshadows=foreshadows,
        workspec_context=ws.to_prompt_context(),
        frame_context=frame_context,
        structure_template="eight_node",
        platform=ws.platform,
        genre=ws.genre,
    )
    assert "【相关事实检索】" not in prompt


def test_compose_on_empty_corpus_byte_identical_to_off(tmp_path):
    """默认 on 但语料为空 → 与 off 字节相同（降级锁死）."""
    ws, narrative_state, characters, facts, foreshadows, frame_context = (
        _compose_continue_chain()
    )
    cont = ContinueUnit()
    base = cont.build_prompt(
        state=narrative_state,
        characters=characters,
        facts=facts,
        foreshadows=foreshadows,
        workspec_context=ws.to_prompt_context(),
        frame_context=frame_context,
        structure_template="eight_node",
        platform=ws.platform,
        genre=ws.genre,
    )
    retrieval = load_retrieval_context(
        tmp_path, state=narrative_state, facts=facts, foreshadows=foreshadows
    )
    with_retrieval = cont.build_prompt(
        state=narrative_state,
        characters=characters,
        facts=facts,
        foreshadows=foreshadows,
        workspec_context=ws.to_prompt_context(),
        frame_context=frame_context,
        structure_template="eight_node",
        platform=ws.platform,
        genre=ws.genre,
        retrieval_context=retrieval,
    )
    assert retrieval == ""
    assert with_retrieval == base


def test_extend_on_nonempty_corpus_injects_block(tmp_path):
    """默认 on 且语料非空 → prompt 含检索块."""
    state = NarrativeState(
        state_id="ns_test",
        current_time="夜",
        current_location="藏经阁",
        current_situation="发现古书藏于密室",
    )
    facts = FactLedger(
        entries=[
            FactEntry(
                fact_id="f_001",
                statement="古书藏于藏经阁密室",
                fact_type="relation",
                confirmed=True,
            )
        ]
    )
    retrieval = load_retrieval_context(
        tmp_path,
        state=state,
        facts=facts,
        foreshadows=ForeshadowGraph(entries=[]),
    )
    assert "【相关事实检索】" in retrieval
    prompt = ContinueUnit().build_prompt(
        state=state,
        characters=[],
        facts=facts,
        foreshadows=ForeshadowGraph(entries=[]),
        retrieval_context=retrieval,
    )
    assert "【相关事实检索】" in prompt
    assert "古书藏于藏经阁密室" in prompt


def test_retrieval_invalid_choice_errors():
    result = _run_script("compose_short_form.py", "--retrieval", "bogus")
    assert result.returncode == 2


def test_novel_cli_compose_help_shows_retrieval():
    result = subprocess.run(
        [sys.executable, "src/novel_cli.py", "compose", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--retrieval" in result.stdout


def test_novel_cli_extend_help_shows_retrieval():
    result = subprocess.run(
        [sys.executable, "src/novel_cli.py", "extend", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--retrieval" in result.stdout
