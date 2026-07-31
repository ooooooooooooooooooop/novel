"""Runtime argument validation for staged long-form workflows."""

from __future__ import annotations

import re


_CHAPTER_RANGE_PATTERN = re.compile(r"^([1-9]\d*)-([1-9]\d*)$")


def parse_chapter_range(value: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError("invalid --range: expected START-END")
    match = _CHAPTER_RANGE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("invalid --range: expected START-END with positive chapter numbers")
    start = int(match.group(1))
    end = int(match.group(2))
    if start > end:
        raise ValueError("invalid --range: START must be less than or equal to END")
    return start, end


def _validate_positive_int(option_name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid {option_name}: expected a positive integer")


def validate_long_runtime_args(
    *,
    chapter_range: str | None,
    batch_size: int,
    max_chapters: int,
) -> tuple[int, int] | None:
    parsed_range = parse_chapter_range(chapter_range) if chapter_range else None
    _validate_positive_int("--batch-size", batch_size)
    _validate_positive_int("--max-chapters", max_chapters)
    return parsed_range
