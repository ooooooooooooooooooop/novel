"""DiagnosticChoice — 诊断性选择机会（条件性规划对象，非事实）.

描述写作机会：如果人物在这个压力下选 A 会暴露什么，选 B 又会暴露什么。
与 reader_handoffs 同构：生成于 Continue、作用于 Prose、由 Review 复核。
Revealed preference 是读者从最终行为得到的推断，不得写成 CharacterModel fact。

资格规则（anti-fake-choice）：仅当
- 至少 2 个当下真实可行选项，且
- 选项成本结构有有意义差异，且
- 人物本人拥有决定权
才创建；否则无对象（不为每场景硬塞选择）。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChoiceAlternative(BaseModel):
    """一个真实可行的选项."""

    model_config = ConfigDict(extra="forbid")

    option: str = Field(description="选项内容（当下真正可行的行动）")
    viability_basis: str = Field(
        description="为什么此选项在人物当前知识/资源/规则下真实可行"
    )
    cost: str = Field(
        description="选它失去什么（时间/风险/身份/关系/尊严/机会/信息/道德负担/未来行动空间）"
    )

    @field_validator("option", "viability_basis", "cost")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v


class ConditionalRevelation(BaseModel):
    """条件性偏好显形——不是人物事实."""

    model_config = ConfigDict(extra="forbid")

    if_option: str = Field(description="若选哪个选项（对应 alternatives.option 或简述）")
    preference_signal: str = Field(
        description="若选该项，会更支持读者对人物偏好的哪种推断"
        "（条件性信号，如『关系优先于短期收益』；禁止写成人物事实）"
    )

    @field_validator("if_option", "preference_signal")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v


class DiagnosticChoice(BaseModel):
    """诊断性选择机会（可选，≤1/场景）."""

    model_config = ConfigDict(extra="forbid")

    pressure: str = Field(
        description="当前什么压力迫使人物不能什么都要（无成本兼得则无暴露）"
    )
    alternatives: list[ChoiceAlternative] = Field(
        min_length=2,
        description="至少两个真实可行选项（含各自 viability_basis 与 cost）",
    )
    agency_basis: str = Field(
        description="为什么决定权属于人物本人（非被上级/巧合/他人替代）"
    )
    conditional_revelations: list[ConditionalRevelation] = Field(
        min_length=2,
        description="各选项对应的条件性偏好信号（仅推断，非事实）",
    )

    @field_validator("pressure", "agency_basis")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v

    def to_prompt_context(self) -> str:
        """完整分析面——仅供 Continue 自检 / post-prose Review / trace."""
        lines = ["【诊断性选择机会】", f"压力: {self.pressure}"]
        for i, a in enumerate(self.alternatives, 1):
            lines.append(
                f"选项{i}: {a.option}（可行依据: {a.viability_basis}；代价: {a.cost}）"
            )
        lines.append(f"决定权: {self.agency_basis}")
        for r in self.conditional_revelations:
            lines.append(f"若选「{r.if_option}」→ 支持推断: {r.preference_signal}")
        return "\n".join(lines)

    def to_execution_context(self) -> str:
        """writer-facing 编译产物：只含行为约束，不含任何分析内容.

        防火墙（Analysis-to-Prose Leakage）：alternatives/cost/revelation
        的文字永不进 Prose prompt——模型只能看到"该怎么执行"的布尔约束。
        """
        return "\n".join([
            "【选择执行契约】",
            "本场存在一个已规划的真实取舍（细节对 writer 隐藏）：",
            "- enact_choice: 选择必须在本场经行动/对白/不行动/资源分配落地",
            "- pressure_must_be_visible: 让压力在场景中可见",
            "- cost_must_be_felt: 选择发生前或当下，读者须能感知至少一个真实代价",
            "- option_inventory_forbidden: 不得逐项盘点备选方案",
            "- comparative_deliberation_forbidden: 不得逐项权衡利弊（含内心独白）",
            "- trait_gloss_forbidden: 选择落地后不得用旁白解释人物性格答案",
        ])
