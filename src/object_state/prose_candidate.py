"""A1 T5 — ProseCandidate（design §7 多版正文候选契约）.

每个存活 PlotUnit 生成 ``prose_variants_per_plot`` 版正文。正文文本是隐私红线
（绝不进入审计与 manifest），持久化只存 SHA-256、字数与候选归属；实际文本在
内存中参与比较，选中版本经 flow v3 原子提交才落盘 ``chapters/``。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProseCandidate(BaseModel):
    """一版候选正文的（无正文内容的）元数据契约."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(min_length=1, description="如 prose_plan_0001_v2")
    plotunit_id: str = Field(min_length=1, description="所属 PlotUnit 候选")
    prose_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="正文 SHA-256（隐私）")
    prose_chars: int = Field(gt=0, description="正文有效字符数（去空白）")
    status: Literal["candidate", "rejected", "accepted"] = "candidate"

    @model_validator(mode="after")
    def _plotunit_ref_matches_candidate(self) -> "ProseCandidate":
        prefix = f"prose_{self.plotunit_id}"
        if not self.candidate_id.startswith(prefix):
            raise ValueError("candidate_id must be prefixed with prose_<plotunit_id>")
        return self
