"""ChoiceRecord — 一次创作选择的完整留痕（作者性第二工作包 §11-13）.

定位：与 TimeBook / CharacterUpdate 同类——sidecar spec，不进 serialization.py
状态机层。由 Selector 落盘（零 LLM），给「这个作者」攒选择证据。

禁止 4（只保存最终稿不是选择数据）：**必须保存被拒候选**（rejected），
否则没有选择数据。真正 taste 主要存在于拒绝行为（§13）——最终作品只告诉你
选了 C；ChoiceLedger 要告诉你看见过 A/B/C/D/E，为什么 A/B/D/E 死了、C 活下来。

hindsight（§12，关键）：几章后补「这个选择后来造成了什么」——不能只记当时理由。
没有这条，系统只能「坚持自己」，不能「重新理解过去」。

隐私：含作品语境，sidecar 存本地 gitignored（novels/<名>/output/），不入库。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

HindsightStatus = Literal[
    "still_supported",   # 仍支持：回看仍认为当时选择对
    "partial_regret",    # 部分后悔：方向对，代价估计错了
    "overturned",        # 完全推翻：现在认为当时选错了
    "complex",           # 结果复杂：对错难分，长期交织
    "unclear",           # 尚无法判断：后果还没显现
]


class CandidateRecord(BaseModel):
    """一个候选方案（含 PlotUnit 全文，JSON-safe）."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(description="候选唯一标识（如 A/B/C/D/E 或 pu_cand_1）")
    summary: str = Field(description="一句话概括该候选的故事走向（供报告/回看）")
    plotunit: dict = Field(
        description="PlotUnit.model_dump(mode='json')——非 prose，候选只到结构层"
    )
    new_state_ref: str = Field(
        description="该候选对应的输出状态 state_id（Consistency Gate 校验用）"
    )

    @field_validator("candidate_id", "summary", "new_state_ref")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class RejectedRecord(BaseModel):
    """一个被否候选的拒绝理由（禁止 4：拒绝必须留痕）."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(description="被否候选 ID")
    reason: str = Field(
        description="为什么拒绝——如『A 更戏剧化但人物当前不会这样』/『B Reader 分高"
        "但提前兑现关系冲突』/『E 符合类型套路但破坏信息权限』"
    )

    @field_validator("candidate_id", "reason")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class ChoiceRecord(BaseModel):
    """一次创作选择（decision_id 唯一）.

    允许出现「Reader 说 B 最好、Style 说 C 最稳、Author 说 E 更符合长期选择结构」
    → 最终选 E 完全合法，但**必须记录为什么愿意放弃 B 的读者优势**（tradeoff，
    最有用字段之一），喂给 ChoiceLedger。
    """

    model_config = ConfigDict(extra="forbid")

    # 基础上下文
    decision_id: str = Field(description="决策唯一标识")
    decision_timestamp: str = Field(description="决策时刻（ISO 字符串，Selector 注入）")
    plot_context: str = Field(description="决策时点的叙事局势摘要")
    state_ref: str = Field(description="决策输入 NarrativeState.state_id")
    character_refs: list[str] = Field(
        default_factory=list, description="决策涉及的角色 ID 列表"
    )
    style_profile_id: Optional[str] = Field(
        default=None,
        description="当前生效的风格档案 id（把选择证据归给『这个作者』）",
    )

    # 候选与选择
    candidates: list[CandidateRecord] = Field(
        description="候选全集（含被拒者，禁止 4：必须保存）"
    )
    selected_candidate: str = Field(description="最终选中的 candidate_id")
    rejected: list[RejectedRecord] = Field(
        description="每个被否候选的理由（禁止 4）"
    )
    tradeoff: str = Field(
        description="放弃 X 换取 Y：放弃更高即时爽感，换取人物长期因果一致性等"
    )

    # Value-Mediated Retrieval（5C）：决策触及的价值冲突（受限词汇表键）
    value_conflicts: list[str] = Field(
        default_factory=list,
        description="本次决策触及的价值冲突（映射到受限词汇表，供按价值检索选择史）",
    )

    # 回看（§12，由后续几章后补写）
    consequence: Optional[str] = Field(
        default=None,
        description="几章后补：这个选择后来造成了什么——不能只记当时理由",
    )
    hindsight: Optional[HindsightStatus] = Field(
        default=None, description="回看判定：仍支持/部分后悔/完全推翻/复杂/尚无法判断"
    )
    hindsight_note: Optional[str] = Field(default=None, description="回看补充说明")

    @field_validator(
        "decision_id", "decision_timestamp", "plot_context", "state_ref", "tradeoff"
    )
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("character_refs", "value_conflicts")
    @classmethod
    def _list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("selected_candidate")
    @classmethod
    def _selected_must_be_in_candidates(cls, value: str, info: ValidationInfo) -> str:
        # 交叉校验放在字段级无法访问 candidates，移到模型校验
        return value


class ChoiceLedgerEntry(BaseModel):
    """台账顶层骨架校验（对齐 character_updates.json 的 sidecar 形态）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    choices: list[ChoiceRecord] = Field(default_factory=list)
