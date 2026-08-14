"""SingleCandidateReview — 单候选评审（G7 内容无关评审协议的数据模型）.

旧 A/B 偏好评审把两个候选并排展示，评审模型可以按「候选甲」槽位作答而不是按内容
（deepseek-v4-flash temp0 实测把偏好名到「甲」槽位 → position consistency 0.5）。
G7 修复的第一步是**单候选评审**：每次只评审一个文本，产出内容摘要 + 带原文锚点的
单轴判断。两个候选的评审结果由程序做确定性比较（硬轴消除 + 软轴帕累托），只有
确定性比较无法分出高下时才做证据锚定仲裁（见 workflow_action.preference_review）。

锚点纪律与 JudgeClaim 相同：excerpt 必须逐字来自被评审文本（compact 后子串校验），
捏造/越界即整批拒绝。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreferenceAnchor(BaseModel):
    """文本锚点：excerpt 必须逐字来自被评审文本；char 偏移由程序定位后回填."""

    excerpt: str = Field(min_length=1)
    char_start: int = -1
    char_end: int = -1


class PreferenceReviewClaim(BaseModel):
    """单轴判断：verdict ∈ satisfied/violated/inconclusive；severity ∈ blocking/advisory."""

    claim_id: str = Field(min_length=1)
    axis: str = Field(min_length=1)
    verdict: str = Field(pattern=r"^(satisfied|violated|inconclusive)$")
    severity: str = Field(default="advisory", pattern=r"^(blocking|advisory)$")
    anchors: list[PreferenceAnchor] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class SingleCandidateReview(BaseModel):
    """一份单候选评审：内容摘要 + 锚定判断 + 置信度 + 弃权声明."""

    review_id: str = Field(min_length=1)
    content_digest: str = Field(min_length=1)
    claims: list[PreferenceReviewClaim] = Field(default_factory=list)
    experience_rating: int | None = Field(default=None, ge=1, le=5)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    abstain: bool = False
    abstain_reason: str = ""

    def hard_violation_count(self) -> int:
        """blocking+violated 硬违例数（硬轴消除的第一排序键）."""
        return sum(
            1
            for claim in self.claims
            if claim.verdict == "violated" and claim.severity == "blocking"
        )

    def axis_scores(self) -> dict[str, int]:
        """按轴累计 satisfied=+1 / violated=-1 / inconclusive=0（软轴帕累托用）."""
        scores: dict[str, int] = {}
        for claim in self.claims:
            delta = (
                1
                if claim.verdict == "satisfied"
                else -1
                if claim.verdict == "violated"
                else 0
            )
            scores[claim.axis] = scores.get(claim.axis, 0) + delta
        return scores
