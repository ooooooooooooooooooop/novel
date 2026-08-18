"""Evidence-backed neutral templates.

This module models reusable choice evidence, not a persona, identity, or final judge.
It solves the narrow problem of preserving auditable choice principles without
replacing AuthorKernel or AuthorModelV3.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceRef(BaseModel):
    """A neutral, auditable reference to one recorded decision."""
    model_config = ConfigDict(extra="forbid")
    decision_id: str
    source_id: str

    @field_validator("decision_id", "source_id")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip() or any(token in value.lower() for token in ("persona", "author identity")):
            raise ValueError("evidence references must be neutral and non-blank")
        return value.strip()


class TemplatePrinciple(BaseModel):
    """An inferred choice pattern; it is never an identity assertion."""
    model_config = ConfigDict(extra="forbid")
    category: Literal["value_conflict", "tradeoff", "selection", "hindsight"]
    key: str
    description: str
    supporting_choices: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("key", "description")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("principle text must be non-blank")
        return value.strip()

    @model_validator(mode="after")
    def requires_evidence(self) -> "TemplatePrinciple":
        if not self.supporting_choices:
            raise ValueError("a principle requires supporting choices")
        return self


class TemplateRuntime(BaseModel):
    """Runtime provenance, deliberately separate from facts and inferences."""
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["choice_ledger"] = "choice_ledger"
    algorithm: str = "deterministic-v1"
    status: Literal["candidate", "shadow", "provisional"] = "candidate"


class AuthorTemplate(BaseModel):
    """A neutral, evidence-backed prior for shadow use, not a person model or gate."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, ge=1)
    template_id: str
    hard_facts: list[str] = Field(default_factory=list)
    principles: list[TemplatePrinciple] = Field(default_factory=list)
    inference_notes: list[str] = Field(default_factory=list)
    style_references: list[str] = Field(default_factory=list)
    kernel_reference: str | None = None
    measurement_evidence: list[EvidenceRef] = Field(default_factory=list)
    runtime: TemplateRuntime = Field(default_factory=TemplateRuntime)

    @field_validator("template_id")
    @classmethod
    def safe_id(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in value):
            raise ValueError("template_id must be a neutral safe identifier")
        return value
