"""DetailContract — 环境细节的功能契约（隐藏规划对象）.

描述本场景计划承重细节各自承担的当前功能：定位/行动约束/感官/关系/
氛围（一处多能优先），以及这些细节服务的当前读者任务。与
DialogueStrategy 同构：生成于 Continue、编译为 writer-facing 执行契约
作用于 Prose、完整对象仅供 post-prose Review 对照判定。

Eligibility（不满足则不创建对象——纯对白场/纯动作过场不建模）：
- 本场景存在值得着墨的环境/空间/物品（新地点、行动舞台、关系场域、
  情绪载具）
- 细节差异会实质影响读者定位、行动理解或氛围积累
- 普通过渡场景（走廊、上车下车）不建模

Function 判据（realized_current_effect）：标签不许自证——「用了颜色」
不等于完成感官功能，「写了阴暗形容词」不等于完成氛围功能。每处计划
细节必须写明它在当前句段要产生的读者效应。

shared_cluster：多个细节可共用一个 collective function（如战斗前
空间枚举共享 ORIENTATION+ACTION_CONSTRAINT）。范围有限、功能必须在
当前行动/后文可兑现——不允许「这是氛围」式声明自证。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

DetailFunction = Literal[
    "ORIENTATION",        # 定位：帮读者建立空间/位置/时间坐标
    "ACTION_CONSTRAINT",  # 行动约束：限制或使能行动（掩体/距离/工具/出口）
    "SENSORY",            # 感官锚点：使场景真实可感的具体感官
    "RELATIONAL",         # 关系标记：细节承载人物关系/地位/历史
    "ATMOSPHERE",         # 氛围：情绪/张力调制的环境投射
]


class PlannedDetail(BaseModel):
    """一处计划承重细节（计划中声明，非正文原文）."""

    model_config = ConfigDict(extra="forbid")

    detail: str = Field(description="计划写的细节内容（一句话描述）")
    functions: list[DetailFunction] = Field(
        min_length=1, max_length=2,
        description="本细节承担的功能（1-2 个，一处多能优先）",
    )
    realized_effect: str = Field(
        description="本细节在当前句段要产生的具体读者效应"
        "（读了它读者获得什么定位/判断/感受——不得是功能标签复述）",
    )
    carrier: str = Field(
        description="承载/吸收方式：本细节通过什么进入当前句段——挂在谁的"
        "动作/感知/判断/空间阻碍/关系变化上，改变了什么状态"
        "（如「登记本通过要求入内者停下登记来改变进入动作」）。"
        "不允许「物件被声明存在」式完成任务——细节必须改变句段中的某个状态",
    )
    shared_cluster: Optional[str] = Field(
        default=None,
        description="共享功能簇 id：同簇细节共同兑现一个 collective "
        "function（如空间建立镜头共享定位+行动约束）",
    )

    @field_validator("detail", "realized_effect", "carrier")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v


class DetailContract(BaseModel):
    """场景细节功能契约（隐藏质量注解，≤1/场景）."""

    model_config = ConfigDict(extra="forbid")

    reader_task: str = Field(
        description="本场景当前读者任务：读者此刻需要建立/追踪/感受什么"
        "（定位新空间/追踪行动可行性/积累张力/识别关系站位…）",
    )
    load_bearing_details: list[PlannedDetail] = Field(
        min_length=1, max_length=6,
        description="计划承重细节（1-6）：每处必须声明功能与读者效应",
    )
    detail_budget: Optional[int] = Field(
        default=None,
        description="局部细节预算：本场景环境/细节描写的大致上限"
        "（防过载稀释当前读者任务；None=不设限）",
    )

    @field_validator("reader_task")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must be non-empty")
        return v

    def to_prompt_context(self) -> str:
        """完整契约面——仅供 Continue 自检 / post-prose Review / trace."""
        lines = [
            "【细节功能契约】",
            f"当前读者任务: {self.reader_task}",
        ]
        if self.detail_budget is not None:
            lines.append(f"细节预算: ~{self.detail_budget} 处")
        for i, d in enumerate(self.load_bearing_details, 1):
            line = (
                f"detail{i}: {d.detail} | 功能: {'+'.join(d.functions)} | "
                f"读者效应: {d.realized_effect} | 承载: {d.carrier}"
            )
            if d.shared_cluster:
                line += f" | 簇: {d.shared_cluster}"
            lines.append(line)
        return "\n".join(lines)

    def to_execution_context(self) -> str:
        """writer-facing 编译产物：只含行为约束，不含功能分析.

        防火墙：function 标签/realized_effect 分析永不进 Prose——否则
        模型会把功能论证文学化成正文说明。writer 只见「细节须承重」的
        行为契约与计划细节内容。
        """
        lines = [
            "【细节执行契约】",
            "本场环境/细节描写须承担当前任务：",
            "- 每处环境细节必须让读者获得定位、行动判断、感官在场、"
            "关系信号或氛围积累中的至少一项真实效应",
            "- 不得连续枚举互不承重的物体（装修清单）：删掉后读者什么"
            "都没失去的描述必须删",
            "- 一处细节可同时承担多项功能，优先选择能承重而非仅好看的",
            "- 氛围须由具体细节投射产生，不得用形容词声明氛围",
            "- 细节不得只以「物件被声明存在」的方式落地：它必须附着在某个"
            "动作/感知/判断/空间阻碍/关系变化上，改变当前句段的某个状态",
            "- 已建立的细节不得仅为证明其持续存在而再现；再现必须新增"
            "状态、作用或意义，否则默认让它退休",
            "- 计划承重细节：",
        ]
        for d in self.load_bearing_details:
            lines.append(f"  · {d.detail}")
        if self.detail_budget is not None:
            lines.append(
                f"- 本场环境细节总量约 ≤{self.detail_budget} 处——"
                "超出部分若不能承重即为稀释"
            )
        return "\n".join(lines)
