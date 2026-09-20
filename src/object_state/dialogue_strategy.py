"""DialogueStrategy — 对白作为社会行动的隐藏规划对象（非事实、非逐句棋谱）.

描述一场对白的社会策略结构：谁想通过说话改变什么、为什么不能直说、
谁知道什么、关键策略位移点（beat）。与 DiagnosticChoice 同构：
生成于 Continue、编译为 writer-facing 执行契约作用于 Prose、
完整对象仅供 post-prose Review 对照判定。

Eligibility（不满足则不创建对象——普通寒暄/交代/确认不建模）：
- 至少一方有需通过对话推进的 private/social objective
- 存在不能简单直说的社会约束、信息约束或利益冲突
- 对方有真实 agency（可抵抗、误解、还价、反制）
- 对话结果可能改变信息/承诺/杠杆/关系位置/行动空间

Beat = 一次社会策略动作使对方回应空间/信息/承诺/地位/行动空间
发生变化；只发生策略位移才切 beat（1-4 个，非逐句建模）。
不写进 State V2 / CharacterModel：accepted prose 的变化仍由
现有事实状态通路落地。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

TacticalMove = Literal[
    "PROBE", "EVADE", "PRESS", "BARGAIN",
    "COMMIT", "REFUSE", "REDIRECT", "WITHHOLD",
]

TargetDelta = Literal[
    "INFORMATION", "COMMITMENT", "LEVERAGE",
    "FACE_OR_STATUS", "ACTION_SPACE",
]


class DialogueBeat(BaseModel):
    """一次策略位移（非一句话）."""

    model_config = ConfigDict(extra="forbid")

    actor: str = Field(description="行动方（角色名或简述）")
    tactical_move: TacticalMove = Field(
        description="作者侧策略分类（不写给读者看）"
    )
    target_delta: TargetDelta = Field(
        description="本轮想改变：信息/承诺/杠杆/地位/行动空间"
    )
    pressure_basis: str = Field(
        description="为什么这一步能产生压力（对方不能无视的理由）"
    )
    success_signal: str = Field(
        description="作者侧判定：对方什么反应算这一步奏效"
    )
    response_to: Optional[str] = Field(
        default=None,
        description="第 2 个 beat 起必填：本动作是对哪个前序局面的回应"
        "（不是机械问答，是被对方改变后的局面逼出的策略动作）",
    )

    @field_validator("actor", "pressure_basis", "success_signal")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v


class DialogueStrategy(BaseModel):
    """一场对白的社会策略结构（隐藏质量注解，≤1/场景）."""

    model_config = ConfigDict(extra="forbid")

    participants: list[str] = Field(min_length=2, description="对话方")
    interaction_objective: str = Field(
        description="这场对白真正想改变什么（各说各话的目标差可写多条；"
        "指关系/信息/承诺/行动层面的结果，非表层话题）"
    )
    social_constraint: str = Field(
        description="为什么不能直说（体面/立场/信息优势/把柄/风险）"
    )
    information_asymmetry: str = Field(
        description="谁知道什么、谁不知道什么、什么不能明说"
    )
    stakes: str = Field(description="策略失败当场损失什么")
    beats: list[DialogueBeat] = Field(
        min_length=1, max_length=4,
        description="稀疏策略位移点（1-4，只有策略位移才切 beat）",
    )

    @field_validator("participants")
    @classmethod
    def _participants_non_blank(cls, vs: list[str]) -> list[str]:
        if any(not v.strip() for v in vs):
            raise ValueError("participants must be non-empty")
        return vs

    @field_validator(
        "interaction_objective", "social_constraint",
        "information_asymmetry", "stakes",
    )
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v

    def to_prompt_context(self) -> str:
        """完整策略面——仅供 Continue 自检 / post-prose Review / trace."""
        lines = [
            "【对白社会策略】",
            f"参与者: {' / '.join(self.participants)}",
            f"交互目的: {self.interaction_objective}",
            f"社会约束: {self.social_constraint}",
            f"信息不对称: {self.information_asymmetry}",
            f"失败代价: {self.stakes}",
        ]
        for i, b in enumerate(self.beats, 1):
            line = (
                f"beat{i}: {b.actor} | {b.tactical_move}→{b.target_delta} | "
                f"压力依据: {b.pressure_basis} | 奏效信号: {b.success_signal}"
            )
            if b.response_to:
                line += f" | 回应: {b.response_to}"
            lines.append(line)
        return "\n".join(lines)

    def to_execution_context(self) -> str:
        """writer-facing 编译产物：只含行为约束，不含策略分析.

        防火墙：objective/asymmetry/move 标签/success_signal 永不进
        Prose prompt——否则模型会把策略分析文学化成正文说明。
        key_response_required 边界：策略中无合法 WITHHOLD 位时，
        关键问题不得以迟疑/停顿/不答拖延——必须当场得到实际回应。
        """
        lines = [
            "【对白执行契约】",
            "本场对话存在未明说的利益/信息冲突（策略细节对 writer 隐藏）：",
            "- 人物通过实际说法推进目的，而不是解释目的",
            "- 关键社会压力形成后，必须在本场得到实际回应",
            "- 回应可以是回答、拒绝、反问、转移、还价、行动或有后果的沉默",
            "- 沉默/克制不能替代本来必须发生的追问、拒绝或表态",
            "- 只有当沉默本身改变局面时，它才算有效回应",
            "- 至少一次交换应改变信息、承诺、杠杆或行动空间",
            "- 一项边界/条件/要求经双方实质确认后，后续交锋必须新增社会行动"
            "变化或转入行动——不得只换措辞重新确认同一已确立命题",
            "- 不得为了让读者明白而让人物把不能直说的事说破",
            "- 对白后不得用旁白翻译潜台词",
        ]
        if not any(b.tactical_move == "WITHHOLD" for b in self.beats):
            lines.append(
                "- 本场关键问题不得以张嘴又停、避而不答、反复确认同一限制"
                "等方式拖延——对方必须当场给出实际回应"
            )
        return "\n".join(lines)
