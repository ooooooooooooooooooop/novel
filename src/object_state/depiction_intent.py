"""DepictionIntent — ambient 白描意图（dim8b 规划层对象）.

对应 NEED GATE 终裁：「希望读者感受到某种体验质感（烦躁/犹豫/戒备/
疏离/关系温度变化……）——它不是待推断命题（归 dim8a reader_handoffs），
也不是环境细节对象（归 DFD detail_contract），而是 experiential quality。
当它没有结构对象声明时，writer 不知道要写、review 不知道要查，
遗漏静默通过。

与 InferenceHandoff 同类：是规格（spec）不是叙事状态，不进状态机。
用法：作为 PlotUnit 的可选字段 depiction_intents（空=不渲染，
与旧版逐字节一致）。Continue 可选产出；post-prose 定向核验只验不补造。

稀疏资格（终裁冻结）：重要 + 命名会损失体验 + 有可观察载体空间。
普通自陈/信息交代/推断命题不进。

V0.1 硬语义约束（NEED GATE 暴露的两边界）：
- beat_link 是硬字段：谁负责/在哪个 beat 承载——解决「该 ambient
  重要」≠「本 unit 负责演出」的 ownership 问题；prose 合法转线出
  owning beat → OWNERSHIP_RELEASED 不误拦。
- planned_carriers 是开放 realization space 非 checklist——核验
  的是「target 是否被可观察地实现」，不是「逐项照抄计划载体」；
  换用其他有效载体同样算 realized（ALTERNATE_CARRIER）。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class DepictionIntent(BaseModel):
    """单个白描意图：本单元应让读者【感受】到某体验质感，
    且它应由可观察载体呈现而非抽象命名。"""

    model_config = ConfigDict(extra="forbid")

    target_quality: str = Field(
        description="目标体验质感——希望读者感受到什么（experiential "
        "quality：戒备中的敬畏/平静下的隐忧/亲昵下的酸涩/恭敬下的畏惧算计…）。"
        "必须是感受不是推断命题：「她其实知道他撒谎」这类待推断判断归 "
        "reader_handoffs，不进本对象",
    )
    beat_link: str = Field(
        description="责任绑定（硬语义）：这个质感由哪个 beat/谁负责承载——"
        "如『阿尔杰向乔戈里汇报的回合』『许思张恪沙发上亲昵段』。"
        "回答：谁负责？在哪个 beat 负责？",
    )
    planned_carriers: list[str] = Field(
        default_factory=list,
        description="计划可观察载体（开放 realization space，非 checklist）——"
        "可行的动作/神态/语气/器物/空间/节奏候选；prose 可换用其他有效载体，"
        "核验只问目标质感是否被可观察地实现",
    )
    placement: Optional[str] = Field(
        default=None,
        description="单元内位置——该质感应落在哪一段（可空）",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="为何此刻需要这个质感——beat 理由/读者体验依据（可空）",
    )

    @field_validator("target_quality", "beat_link")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    def to_prompt_context(self) -> str:
        """生成给核验/修订层的上下文描述."""
        lines = [
            f"- 目标质感: {self.target_quality}",
            f"  责任 beat: {self.beat_link}",
        ]
        if self.planned_carriers:
            lines.append(
                "  计划载体(可替换): " + "；".join(self.planned_carriers))
        if self.placement:
            lines.append(f"  位置: {self.placement}")
        if self.rationale:
            lines.append(f"  理由: {self.rationale}")
        return "\n".join(lines)

    def to_execution_context(self) -> str:
        """writer-facing 执行契约：告诉 writer 这个 beat 要承载什么质感."""
        lines = [
            f"- 体验质感: {self.target_quality}——须由可观察的"
            "动作/神态/语气/器物/空间/节奏呈现，不得抽象命名",
            f"  责任 beat: {self.beat_link}",
        ]
        if self.planned_carriers:
            lines.append(
                "  候选载体(可替换): " + "；".join(self.planned_carriers))
        if self.placement:
            lines.append(f"  位置: {self.placement}")
        return "\n".join(lines)
