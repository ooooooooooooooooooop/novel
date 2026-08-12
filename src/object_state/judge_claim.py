"""A1 T5/T6 — ProseAnchor 与 JudgeClaim（带正文锚点的单轴评审判断）.

设计 §2：``JudgeClaim`` = 带正文锚点的单轴判断，不是无证据总分。设计 §8：
所有 JudgeClaim 必须含正文锚点；无锚点结论不能进入门禁。

G5 门：
- 无证据结论无法进入门禁 —— 锚点在模型层即强制（``anchors`` min_length=1），
  构造时无锚点的 claim 直接 ValidationError，代码路径不存在绕过构造的结论。
- 锚点必须真实 —— 运行层以「原文规范化子串」核验 excerpt 确实存在于被评审正文，
  评审器伪造引文（paraphrase 冒充原文）会被当作 schema/证据错误拒绝。

轴必须单轴（``axis`` 是一个字符串，不是多轴加权）；``verdict`` 三类
（satisfied / violated / inconclusive），``severity`` 两档（blocking 硬门禁 /
advisory 软质量）。硬门禁：severity=blocking 且 verdict=violated 的 claim
任一存在 → 候选淘汰，软分数不能抵消（requirement §5 规则 3/7）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProseAnchor(BaseModel):
    """正文引用锚点：定位一条 claim 所依据的确切正文片段."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    chapter_ref: str = Field(min_length=1, description="如 chapter_1")
    position: Literal["start", "middle", "end"]
    excerpt: str = Field(min_length=1, description="原文引文（须为被评审正文的子串）")
    char_start: int = Field(ge=0, description="在整章正文中的起始偏移")
    char_end: int = Field(gt=0, description="在整章正文中的结束偏移（开区间）")

    @model_validator(mode="after")
    def _excerpt_bounds_are_ordered(self) -> "ProseAnchor":
        if self.char_start >= self.char_end:
            raise ValueError("anchor char_start must be less than char_end")
        if not self.excerpt.strip():
            raise ValueError("anchor excerpt must be non-blank")
        return self


class JudgeClaim(BaseModel):
    """单轴、带正文锚点的评审判断."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    claim_id: str = Field(min_length=1)
    precommit_id: str = Field(min_length=1, description="该 claim 依据的 EvaluatorPrecommit")
    axis: str = Field(
        min_length=1,
        description="单轴：fact_conflict / contract_drift / character_fidelity / "
        "plotunit_expected_change / state_necessity / reader_engagement / "
        "friction / language_distinctiveness / constructive_ambiguity / ...",
    )
    verdict: Literal["satisfied", "violated", "inconclusive"]
    severity: Literal["blocking", "advisory"]
    # 模型层强制 ≥1 锚点：无锚点结论无法进入门禁（G5）。
    anchors: tuple[ProseAnchor, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1, description="判断依据（可引用锚点）")
    generator_source: Literal["code", "fact_judge", "character_judge", "reader_judge"]

    @model_validator(mode="after")
    def _blocking_requires_determinate_verdict(self) -> "JudgeClaim":
        if self.severity == "blocking" and self.verdict == "inconclusive":
            raise ValueError("blocking claims must be satisfied or violated")
        if not self.rationale.strip():
            raise ValueError("rationale must be non-blank")
        return self


def claim_is_hard_violation(claim: JudgeClaim) -> bool:
    """硬门禁判定：blocking + violated = 硬违例（候选淘汰，不能软抵消）."""
    return claim.severity == "blocking" and claim.verdict == "violated"


def soft_axis_score(claims: tuple[JudgeClaim, ...], axis: str) -> int:
    """软轴分数：satisfied 记 +1，violated 记 -1，inconclusive 记 0."""
    score = 0
    for claim in claims:
        if claim.axis != axis:
            continue
        if claim.verdict == "satisfied":
            score += 1
        elif claim.verdict == "violated":
            score -= 1
    return score
