"""测试长文运行时参数校验（boundary_control.runtime_args）."""

import pytest

from src.boundary_control.runtime_args import (
    parse_chapter_range,
    validate_long_runtime_args,
)


def test_parse_chapter_range_valid():
    assert parse_chapter_range("1-50") == (1, 50)
    assert parse_chapter_range("3-3") == (3, 3)


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "0-5",
        "5-",
        "-5",
        "1-0",
        "1,2",
        "1--2",
        "一-五",
    ],
)
def test_parse_chapter_range_invalid_format(value):
    with pytest.raises(ValueError, match="invalid --range"):
        parse_chapter_range(value)


def test_parse_chapter_range_start_greater_than_end():
    with pytest.raises(ValueError, match="START must be less than or equal to END"):
        parse_chapter_range("10-2")


def test_parse_chapter_range_rejects_non_string():
    with pytest.raises(ValueError, match="invalid --range"):
        parse_chapter_range(12)


def test_validate_long_runtime_args_valid_returns_parsed_range():
    parsed = validate_long_runtime_args(
        chapter_range="2-8",
        batch_size=3,
        max_chapters=50,
    )
    assert parsed == (2, 8)


def test_validate_long_runtime_args_without_range_returns_none():
    parsed = validate_long_runtime_args(
        chapter_range=None,
        batch_size=3,
        max_chapters=50,
    )
    assert parsed is None


@pytest.mark.parametrize(
    "batch_size",
    [0, -1, True, "5", 1.5],
)
def test_validate_long_runtime_args_rejects_invalid_batch_size(batch_size):
    with pytest.raises(ValueError, match="--batch-size"):
        validate_long_runtime_args(
            chapter_range=None,
            batch_size=batch_size,
            max_chapters=50,
        )


@pytest.mark.parametrize(
    "max_chapters",
    [0, -1, True, "50", 50.0],
)
def test_validate_long_runtime_args_rejects_invalid_max_chapters(max_chapters):
    with pytest.raises(ValueError, match="--max-chapters"):
        validate_long_runtime_args(
            chapter_range=None,
            batch_size=3,
            max_chapters=max_chapters,
        )


def test_validate_long_runtime_args_propagates_range_validation():
    with pytest.raises(ValueError, match="invalid --range"):
        validate_long_runtime_args(
            chapter_range="bad",
            batch_size=3,
            max_chapters=50,
        )
