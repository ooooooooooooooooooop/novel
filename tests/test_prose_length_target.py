"""F4 续写篇幅对齐硬约束测试（B 档）.

覆盖：
- average_chapter_chars：章均去空白字符数、空输入→0、忽略空白
- 零成本契约：target_chapter_chars 缺省 None 时 prompt 字节与旧版一致
  （不含目标篇幅行）
- target 注入：build_prompt 带目标时含目标行与 ±35% 带
- parse_response 篇幅告警：低于目标下界打印 WARNING 不抛错、达标不告警
"""

import pytest

from src.object_state import NarrativeState, PlotUnit
from src.workflow_action.prose import (
    CHAPTER_LEN_TOLERANCE,
    MIN_PROSE_CHARS,
    average_chapter_chars,
    build_prompt,
    parse_response,
)


class _Chunk:
    """split_by_chapters 产物的最小替身（.text / .chapter_index）。"""

    def __init__(self, text: str, chapter_index: int = 1):
        self.text = text
        self.chapter_index = chapter_index


def _mk_plotunit(unit_id: str = "pu_f4") -> PlotUnit:
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


# ---------- average_chapter_chars ----------

def test_average_chapter_chars_mean_of_compact_counts():
    chunks = [
        _Chunk("一 二 三", 1),   # 去空白 3
        _Chunk("甲\n乙\n丙丁", 2),  # 去空白 4
        _Chunk("", 3),          # 空章不计
    ]
    assert average_chapter_chars(chunks) == round((3 + 4) / 2)


def test_average_chapter_chars_no_text_returns_zero():
    assert average_chapter_chars([]) == 0
    assert average_chapter_chars([_Chunk("", 1), _Chunk("", 2)]) == 0


# ---------- build_prompt 零成本契约 + target 注入 ----------

def test_build_prompt_default_is_zero_cost_identical():
    """target 缺省 None 时，与显式 None 字节一致，且不含目标篇幅行。"""
    prompt = build_prompt(_mk_plotunit(), _mk_state())
    assert prompt == build_prompt(
        _mk_plotunit(), _mk_state(), target_chapter_chars=None
    )
    assert "目标篇幅" not in prompt
    assert "不得明显偏短" in prompt  # 原第 4 条约束仍在


def test_build_prompt_target_injects_length_constraint():
    prompt = build_prompt(
        _mk_plotunit(), _mk_state(), target_chapter_chars=6500
    )
    assert "目标篇幅约 6500 字符（去空白）" in prompt
    assert f"±{int(CHAPTER_LEN_TOLERANCE * 100)}%" in prompt  # ±35%
    # 新约束排在原有 4 条硬性约束之后
    assert prompt.index("5. 本章目标篇幅") > prompt.index("4. 篇幅与上下文风格匹配")


# ---------- parse_response 篇幅告警（warn-only，不阻断） ----------

def test_parse_response_warns_when_below_target_band(capsys):
    body = "字" * 2200  # < 6500 × 0.65 = 4225
    assert parse_response(body, target_chars=6500) == body
    out = capsys.readouterr().out
    assert "WARNING prose short" in out
    assert "6500" in out


def test_parse_response_no_warning_when_target_met(capsys):
    body = "字" * 4500  # ≥ 6500 × 0.65
    assert parse_response(body, target_chars=6500) == body
    assert capsys.readouterr().out == ""


def test_parse_response_no_warning_without_target(capsys):
    body = "字" * (MIN_PROSE_CHARS + 5)
    assert parse_response(body) == body
    assert capsys.readouterr().out == ""


def test_parse_response_target_never_overrides_minimum(capsys):
    """低于 MIN_PROSE_CHARS 仍抛错，篇幅告警不吞下限校验。"""
    with pytest.raises(ValueError, match="too short"):
        parse_response("短", target_chars=6500)
