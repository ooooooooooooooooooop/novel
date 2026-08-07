"""Tests for timeline_context / excerpt_context injection into Continue prompt.

镜像 test_retrieval_injection / test_style_injection 的"空串静默降级 + 字节不变"范式：
两个新注入段在缺省（空串）时不得产生任何注入字节。
"""

from src.object_state import (
    FactEntry,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
)
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.excerpt import append_generated_chapters, load_recent_excerpts


def _state() -> NarrativeState:
    return NarrativeState(
        state_id="s1",
        current_time="夜",
        current_location="藏经阁",
        active_characters=["gl"],
        current_situation="发现古书",
        active_conflicts=["时间压力"],
    )


def _base_prompt(
    timeline_context: str = "",
    excerpt_context: str = "",
    retrieval_context: str = "",
) -> str:
    cont = ContinueUnit()
    return cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        platform=None,
        genre=None,
        retrieval_context=retrieval_context,
        timeline_context=timeline_context,
        excerpt_context=excerpt_context,
    )


# --- timeline 注入 ---


def test_no_timeline_no_section():
    prompt = _base_prompt()
    assert "【已发生事件时间线】" not in prompt


def test_timeline_adds_section():
    prompt = _base_prompt(timeline_context="1. 主角重生")
    assert "【已发生事件时间线】" in prompt
    assert "1. 主角重生" in prompt


def test_timeline_section_after_style_before_state():
    prompt = _base_prompt(timeline_context="1. 事件")
    constraints_pos = prompt.find("【作品约束】")
    timeline_pos = prompt.find("【已发生事件时间线】")
    state_pos = prompt.find("【当前叙事状态】")
    assert constraints_pos < timeline_pos < state_pos


def test_timeline_default_unchanged_prompt():
    """默认 timeline_context='' 时 prompt 与无此参数时字节一致（防回归）."""
    cont = ContinueUnit()
    with_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        timeline_context="",
    )
    without_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
    )
    assert with_param == without_param


def test_facts_timeline_renders_event_only():
    """FactLedger.to_timeline_context 只取 confirmed 事件类事实，空账本返回空串."""
    ledger = FactLedger(entries=[])
    assert ledger.to_timeline_context() == ""

    ledger = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="主角重生",
                fact_type="event",
                confirmed=True,
                timestamp="1994年",
            ),
            FactEntry(
                fact_id="f2",
                statement="主角未确认推断",
                fact_type="event",
                confirmed=False,
            ),
            FactEntry(
                fact_id="f3",
                statement="令牌归主角",
                fact_type="object",
                confirmed=True,
            ),
        ]
    )
    tl = ledger.to_timeline_context()
    assert "【已发生事件时间线】" in tl
    assert "主角重生" in tl
    assert "未确认推断" not in tl
    assert "令牌归主角" not in tl  # object 类型不进时间线


def test_timeline_include_header_false_removes_header():
    """双层段头回归：include_header=False 去掉内层【已发生事件时间线】头."""
    ledger = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="主角重生",
                fact_type="event",
                confirmed=True,
                timestamp="1994年",
            ),
        ]
    )
    tl = ledger.to_timeline_context(include_header=False)
    assert "【已发生事件时间线】" not in tl
    assert "主角重生" in tl
    # 默认 include_header=True 保留头
    assert "【已发生事件时间线】" in ledger.to_timeline_context()


# --- excerpt 注入 ---


def test_no_excerpt_no_section():
    prompt = _base_prompt()
    assert "【原文锚点与文风样例】" not in prompt


def test_excerpt_adds_section():
    prompt = _base_prompt(excerpt_context="【第3章 测试】\n原文逐字……")
    assert "【原文锚点与文风样例】" in prompt
    assert "原文逐字" in prompt


def test_excerpt_default_unchanged_prompt():
    """默认 excerpt_context='' 时 prompt 与无此参数时字节一致（防回归）."""
    cont = ContinueUnit()
    with_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
        excerpt_context="",
    )
    without_param = cont.build_prompt(
        state=_state(),
        characters=[],
        facts=FactLedger(entries=[]),
        foreshadows=ForeshadowGraph(entries=[]),
        workspec_context="作品类型: 仙侠",
    )
    assert with_param == without_param


def test_load_recent_excerpts_empty_source():
    assert load_recent_excerpts("") == ""
    assert load_recent_excerpts("   ") == ""


def test_load_recent_excerpts_takes_tail_chapters():
    text = (
        "第1章 开头\n第一章正文内容。\n\n"
        "第2章 中间\n第二章正文内容。\n\n"
        "第3章 结尾\n第三章正文内容。"
    )
    out = load_recent_excerpts(text, tail_chapters=2)
    assert "第3章 结尾" in out
    assert "第2章 中间" in out
    assert "第1章 开头" not in out  # 只取最近 2 章
    assert "原文逐字" in out or "逐字摘录" in out


def test_load_recent_excerpts_preserves_layout():
    """保留原始断句/段落（不压扁原文结构）."""
    text = "第1章 一\n第一行。\n第二行。\n\n第2章 二\n接续段。"
    out = load_recent_excerpts(text, tail_chapters=1)
    assert "接续段。" in out  # 最近一章正文在场
    assert "\n" in out  # 段落结构未压扁


# --- append_generated_chapters：续写多章后锚点应落在最后生成章 ---


def test_append_generated_chapters_no_chapters_dir(tmp_path):
    """无 chapters 目录时原样返回 source_text."""
    src = "第1章 一\n原书正文。"
    assert append_generated_chapters(src, tmp_path / "none") == src


def test_append_generated_chapters_appends_generated_tail(tmp_path):
    """源文本只有首章，chapters/ 已有续写章时，追加后 recent excerpt 应含续写章."""
    src = "第一章 一\n原书首章正文内容。"
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_1.txt").write_text(src, encoding="utf-8")  # 与 input 同章
    (chapters / "chapter_2.txt").write_text(
        "第二章 二\n续写第二章正文。", encoding="utf-8"
    )
    (chapters / "chapter_3.txt").write_text(
        "第三章 三\n续写第三章正文。", encoding="utf-8"
    )

    combined = append_generated_chapters(src, chapters)

    out = load_recent_excerpts(combined, tail_chapters=2)
    assert "续写第三章正文" in out   # 最近章来自已续写内容
    assert "续写第二章正文" in out
    # 首章不重复追加（chapter_1 内容已在 source_text 中）
    assert combined.count("原书首章正文内容。") == 1


def test_append_generated_chapters_recent_excerpt_not_stuck_on_input(tmp_path):
    """回归防线：只喂 input（首章）时 recent excerpt 只有首章——这正是 bug 形态."""
    src = "第一章 一\n原书首章正文内容。"
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_1.txt").write_text(src, encoding="utf-8")
    (chapters / "chapter_2.txt").write_text(
        "第二章 二\n续写第二章正文。", encoding="utf-8"
    )
    (chapters / "chapter_3.txt").write_text(
        "第三章 三\n续写第三章正文。", encoding="utf-8"
    )

    # bug 形态：只用 src → 锚点锁死首章
    stale = load_recent_excerpts(src, tail_chapters=2)
    assert "原书首章正文内容" in stale
    assert "续写第三章正文" not in stale

    # 修复形态：combined → 锚点含最后生成章
    fixed = load_recent_excerpts(
        append_generated_chapters(src, chapters), tail_chapters=2
    )
    assert "续写第三章正文" in fixed


def test_append_generated_chapters_prev_tail_lands_on_last_generated(tmp_path):
    """prev_chapter_tail(combined) 取到的是最后生成章结尾，而非首章结尾."""
    from src.workflow_action.prose import prev_chapter_tail

    src = "第一章 一\n原书首章正文内容。这是首章结尾。"
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "chapter_1.txt").write_text(src, encoding="utf-8")
    (chapters / "chapter_2.txt").write_text(
        "第二章 二\n续写第二章正文。这是第二章结尾。", encoding="utf-8"
    )

    combined = append_generated_chapters(src, chapters)
    tail = prev_chapter_tail(combined, max_chars=20)
    assert "第二章结尾" in tail
    assert "首章结尾" not in tail
