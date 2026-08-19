"""Privacy-safe reusable Author model extracted from corpus evidence."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SAFE_TOKENS = ("author", "book", "novel", "path", "prose", "content")
_SAFE_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


class ChapterEvidence(BaseModel):
    """A chapter-numbered aggregate anchor, never a prose excerpt."""

    model_config = ConfigDict(extra="forbid")
    chapter_index: int = Field(ge=1)
    metric: str
    value: str

    @field_validator("metric", "value")
    @classmethod
    def neutral_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(token in value.lower() for token in _SAFE_TOKENS):
            raise ValueError("evidence must be neutral and non-prose")
        return value


class SelectionPattern(BaseModel):
    """An inferred selection pattern with explicit confidence and anchors."""

    model_config = ConfigDict(extra="forbid")
    pattern_id: str
    statement: str
    confidence: float = Field(ge=0, le=1)
    chapter_evidence: list[ChapterEvidence] = Field(min_length=1)

    @field_validator("pattern_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch not in _SAFE_ID_CHARS for ch in value):
            raise ValueError("pattern_id must be neutral safe ID")
        return value

    @field_validator("statement")
    @classmethod
    def neutral_statement(cls, value: str) -> str:
        value = value.strip()
        if not value or any(token in value.lower() for token in _SAFE_TOKENS):
            raise ValueError("selection pattern must be neutral")
        return value


class AuthorRuntime(BaseModel):
    """Runtime provenance kept separate from facts and inferences."""

    model_config = ConfigDict(extra="forbid")
    algorithm: str = "deterministic-metadata-v1"
    status: Literal["waiting", "materialized"] = "materialized"
    prompt_hash: str | None = None
    response_hash: str | None = None


class Author(BaseModel):
    """One extracted real-author instance; identity and persona are absent."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, ge=1)
    author_id: str
    method_layer_stats: dict[str, float] = Field(default_factory=dict)
    selection_patterns: list[SelectionPattern] = Field(min_length=1)
    corpus_size: dict[str, int]
    source_digest: str
    extraction_generation: Literal["deterministic-metadata-v1", "deep-v2"] = "deterministic-metadata-v1"
    author_template_ref: str | None = None
    style_profile_ref: str | None = None
    runtime: AuthorRuntime = Field(default_factory=AuthorRuntime)

    @field_validator("author_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch not in _SAFE_ID_CHARS for ch in value):
            raise ValueError("author_id must be neutral safe ID")
        return value

    @field_validator("corpus_size")
    @classmethod
    def valid_size(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not isinstance(key, str) or not key or value < 0 for key, value in value.items()):
            raise ValueError("corpus_size must contain non-negative counts")
        return value
