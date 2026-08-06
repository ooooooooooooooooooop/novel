"""F5 续写意象/原文长段去重测试（B 档）.

覆盖：
- find_overlapping_spans：完整重叠 / 内嵌长段命中 / 亚阈值不报 / 相邻合并 /
  左侧扩展 / 空输入
- build_prompt 零成本契约：reuse_source 缺省时 prompt 字节不变，不含去重约束
- reuse_source 注入：带原文时含 ≥30 字符禁止逐字复刻约束
"""

from src.object_state import NarrativeState, PlotUnit
from src.workflow_action.prose import (
    REUSE_MIN_CHARS,
    build_prompt,
    find_overlapping_spans,
)

# 一段可复用的原文（> REUSE_MIN_CHARS）
_SOURCE_SNIPPET = (
    "雨点顺着屋檐落成一条线，院子里的青砖被洇成深色。"
    "他站在廊下，袖口还沾着墨水，低头看着手里那封信。"
)


def _mk_plotunit(unit_id: str = "pu_f5") -> PlotUnit:
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


# ---------- find_overlapping_spans ----------

def test_overlap_identical_drafts_flagged_once():
    spans = find_overlapping_spans(_SOURCE_SNIPPET, _SOURCE_SNIPPET)
    assert len(spans) == 1
    assert spans[0]["length"] == len(_SOURCE_SNIPPET)
    assert spans[0]["start"] == 0


def test_overlap_embedded_long_snippet_detected():
    draft = "新的续写开头。" + _SOURCE_SNIPPET + "然后是新的结尾。"
    spans = find_overlapping_spans(draft, _SOURCE_SNIPPET)
    assert spans, "内嵌的完整原文片段应被检出"
    assert spans[0]["length"] >= REUSE_MIN_CHARS
    assert spans[0]["start"] == len("新的续写开头。")


def test_overlap_below_threshold_not_flagged():
    short = "雨水顺着屋檐"  # < REUSE_MIN_CHARS
    draft = "全新内容" + short + "更多全新内容"
    assert find_overlapping_spans(draft, short) == []


def test_overlap_merges_adjacent_seed_spans():
    """两个相邻种子命中同一原文长段时合并为单一 span。"""
    draft = "前缀" + _SOURCE_SNIPPET + "后缀"
    spans = find_overlapping_spans(draft, _SOURCE_SNIPPET)
    assert len(spans) == 1
    assert spans[0]["length"] == len(_SOURCE_SNIPPET)


def test_overlap_extends_left_of_seed():
    """种子命中后向左扩展：重叠从更早位置开始。"""
    source = "引子" + _SOURCE_SNIPPET
    # 从 source 中部取一段（覆盖种子及其左侧原文字符），draft 嵌入它
    seg_start = 4
    seg = source[seg_start:seg_start + REUSE_MIN_CHARS + 12]
    assert len(seg) > REUSE_MIN_CHARS
    draft = "无关开头" + seg + "无关结尾"
    spans = find_overlapping_spans(draft, source)
    assert spans and spans[0]["length"] >= REUSE_MIN_CHARS
    # 左扩展应覆盖到 seg 起点（早于种子起点），且只并进真实共有的源文字符
    assert spans[0]["start"] == len("无关开头")
    assert spans[0]["length"] == len(seg)


def test_overlap_empty_inputs():
    assert find_overlapping_spans("", _SOURCE_SNIPPET) == []
    assert find_overlapping_spans(_SOURCE_SNIPPET, "") == []
    assert find_overlapping_spans("短", _SOURCE_SNIPPET) == []


def test_overlap_distinct_texts_no_match():
    assert find_overlapping_spans("全新的一章内容。", _SOURCE_SNIPPET) == []


# ---------- build_prompt 零成本 + reuse_source 注入 ----------

def test_build_prompt_reuse_source_default_zero_cost():
    prompt = build_prompt(_mk_plotunit(), _mk_state())
    assert prompt == build_prompt(
        _mk_plotunit(), _mk_state(), reuse_source=""
    )
    assert "禁止逐字复刻原文" not in prompt


def test_build_prompt_reuse_source_injects_constraint():
    prompt = build_prompt(
        _mk_plotunit(), _mk_state(), reuse_source=_SOURCE_SNIPPET
    )
    assert "禁止逐字复刻原文" in prompt
    assert f"≥{REUSE_MIN_CHARS} 字符" in prompt
    # 位于目标篇幅约束之后（第 6 条）
    assert "6. 参考原文语感与意象" in prompt


def test_build_prompt_all_f4_f5_defaults_zero_cost():
    """F4+F5 参数全部缺省时与最小调用字节一致。"""
    minimal = build_prompt(_mk_plotunit(), _mk_state())
    explicit = build_prompt(
        _mk_plotunit(),
        _mk_state(),
        target_chapter_chars=None,
        reuse_source="",
    )
    assert minimal == explicit
    assert "目标篇幅" not in explicit
    assert "禁止逐字复刻原文" not in explicit
