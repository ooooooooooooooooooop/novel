"""ProseUnit 章节正文落盘测试（A 档）.

覆盖：
- next_chapter_number：空目录→1、chapter_1197→1198、忽略非数字文件
- chapter_path 无前导零命名
- build_prompt：硬性约束 + 可选上下文注入 / 不注入
- parse_response：非空 / 下限校验 / strip
- prev_chapter_tail：尾取与空串
- staged slot：prose_prompt.txt 派生 slot id = "prose"
- CLI 透传：extend / compose 的 --no-prose 进入子进程命令
"""

from pathlib import Path

import pytest

from src.boundary_control.runtime_identity import staged_slot_id
from src.novel_cli import main as cli_main
from src.object_state import NarrativeState, PlotUnit
from src.workflow_action.prose import (
    MIN_PROSE_CHARS,
    build_prompt,
    chapter_path,
    is_duplicate_of_last,
    next_chapter_number,
    parse_response,
    prev_chapter_tail,
)


def _mk_plotunit(unit_id: str = "pu_s1") -> PlotUnit:
    return PlotUnit(
        unit_id=unit_id,
        level="scene",
        goal="追查线索",
        conflict="线人失踪",
        input_state_ref="s0",
        output_state_ref="s1",
        released_information=["线人曾收到一封信"],
        consequences=["线索中断"],
    )


def _mk_state(state_id: str = "s1") -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_situation="线索中断",
        current_time="第3天",
        current_location="客栈",
    )


# ---------- next_chapter_number / chapter_path ----------

def test_next_chapter_number_empty_dir_is_one(tmp_path):
    assert next_chapter_number(tmp_path) == 1


def test_next_chapter_number_max_plus_one(tmp_path):
    (tmp_path / "chapter_3.txt").write_text("a", encoding="utf-8")
    (tmp_path / "chapter_1197.txt").write_text("b", encoding="utf-8")
    assert next_chapter_number(tmp_path) == 1198


def test_next_chapter_number_ignores_non_numeric(tmp_path):
    (tmp_path / "chapter_1197.txt").write_text("a", encoding="utf-8")
    (tmp_path / "chapter_prologue.txt").write_text("b", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("c", encoding="utf-8")
    assert next_chapter_number(tmp_path) == 1198


def test_chapter_path_no_leading_zero(tmp_path):
    assert chapter_path(tmp_path, 1198).name == "chapter_1198.txt"
    assert chapter_path(tmp_path, 1).name == "chapter_1.txt"


# ---------- build_prompt ----------

def test_build_prompt_renders_plotunit_and_constraints():
    prompt = build_prompt(_mk_plotunit(), _mk_state())
    assert "【PlotUnit】" in prompt
    assert "追查线索" in prompt and "线人失踪" in prompt
    assert "【输出格式】直接输出章节正文（纯文本，不要 JSON、不要前后缀说明）。" in prompt
    assert "不得引入 PlotUnit 之外的新事实、新角色、新设定。" in prompt


def test_build_prompt_optional_contexts_injected_only_when_present():
    full = build_prompt(
        _mk_plotunit(),
        _mk_state(),
        workspec_context="仙侠",
        style_context="克制",
        excerpt_context="摘录",
        timeline_context="第三章~第五章",
        time_context="秋季",
        prev_chapter_end="前章结尾片段",
    )
    for marker in ("【作品约束】", "【写作风格】", "【上下文摘录】", "【时间线】",
                   "【时间上下文】", "【前章结尾】"):
        assert marker in full, marker

    bare = build_prompt(_mk_plotunit(), _mk_state())
    for marker in ("【作品约束】", "【写作风格】", "【上下文摘录】", "【时间线】",
                   "【时间上下文】", "【前章结尾】"):
        assert marker not in bare, marker


# ---------- parse_response ----------

def test_parse_response_strips_and_accepts_long():
    body = "字" * (MIN_PROSE_CHARS + 5)
    assert parse_response("  \n" + body + "\n  ") == body


def test_parse_response_rejects_short():
    with pytest.raises(ValueError, match="too short"):
        parse_response("太短的正文")


def test_parse_response_rejects_empty():
    with pytest.raises(ValueError, match="empty"):
        parse_response("   \n  ")


# ---------- prev_chapter_tail ----------

def test_prev_chapter_tail_takes_tail():
    text = "甲" * 1000
    assert prev_chapter_tail(text) == "甲" * 600


def test_prev_chapter_tail_empty():
    assert prev_chapter_tail("") == ""


# ---------- staged slot 兼容 ----------

def test_prose_prompt_slot_id_is_prose(tmp_path):
    assert staged_slot_id(Path("prose_prompt.txt")) == "prose"


# ---------- CLI --no-prose 透传 ----------

def test_extend_cli_passes_no_prose(tmp_path, monkeypatch):
    import src.novel_cli as cli

    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("这是续写原文。" * 30, encoding="utf-8")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    captured: dict = {}

    def fake_run_child(command):
        captured["command"] = list(command)
        return 0

    monkeypatch.setattr(cli, "_run_child", fake_run_child)
    ret = cli_main(
        ["extend", "示例小说乙", "--input", str(source), "--no-prose"]
    )
    assert ret == 0
    assert "--no-prose" in captured["command"]


def test_extend_cli_default_no_no_prose(tmp_path, monkeypatch):
    import src.novel_cli as cli

    novels_root = tmp_path / "novels"
    source = tmp_path / "source.txt"
    source.write_text("这是续写原文。" * 30, encoding="utf-8")
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    captured: dict = {}

    def fake_run_child(command):
        captured["command"] = list(command)
        return 0

    monkeypatch.setattr(cli, "_run_child", fake_run_child)
    ret = cli_main(["extend", "示例小说乙", "--input", str(source)])
    assert ret == 0
    assert "--no-prose" not in captured["command"]


def test_compose_cli_passes_no_prose(tmp_path, monkeypatch):
    import src.novel_cli as cli

    novels_root = tmp_path / "novels"
    monkeypatch.setenv("NOVELS_ROOT", str(novels_root))
    captured: dict = {}

    def fake_run_child(command):
        captured["command"] = list(command)
        return 0

    monkeypatch.setattr(cli, "_run_child", fake_run_child)
    ret = cli_main(["compose", "示例小说丁", "--no-prose"])
    assert ret == 0
    assert "--no-prose" in captured["command"]


# --- is_duplicate_of_last：防重复章闸门 ---


def test_duplicate_of_last_identical(tmp_path):
    """新正文与最后一章完全相同 → 判定重复."""
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    text = "第一章 一\n开头句。中间一段叙述。结尾收束。"
    (chapters / "chapter_1.txt").write_text(text, encoding="utf-8")
    # 同文本再写一章 → 应被判定为重复
    assert is_duplicate_of_last(text, chapters) is True


def test_duplicate_of_last_distinct(tmp_path):
    """新正文与最后一章完全不同 → 不判定重复."""
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_1.txt").write_text(
        "第一章 一\n首章正文。第一个情节。", encoding="utf-8"
    )
    new = "第二章 二\n完全不同的续写。新的场景。新的对话。"
    assert is_duplicate_of_last(new, chapters) is False


def test_duplicate_of_last_no_last_chapter(tmp_path):
    """目录为空 → 不判定重复（首章正常写盘）."""
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    assert is_duplicate_of_last("第一章 一\n首章正文。", chapters) is False


def test_duplicate_of_last_short_sentences_ignored(tmp_path):
    """<8 字短句不计入重叠（避免『他走了。』这类通用短句误判）."""
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    prev = "第一章 一\n他走了。天亮了。雨下了。长句承载的内容各不相同。"
    (chapters / "chapter_1.txt").write_text(prev, encoding="utf-8")
    new = "第二章 二\n他走了。天亮了。雨下了。完全不同的长句推进新情节。"
    assert is_duplicate_of_last(new, chapters) is False
