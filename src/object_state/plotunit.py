"""PlotUnit — 情节单元定义."""

from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

from src.object_state.depiction_intent import DepictionIntent
from src.object_state.detail_contract import DetailContract
from src.object_state.expectation_intent import ExpectationUpdateIntent
from src.object_state.diagnostic_choice import DiagnosticChoice
from src.object_state.dialogue_strategy import DialogueStrategy
from src.object_state.inference_handoff import InferenceHandoff
from src.object_state.scene_experience import SceneExperience
from src.object_state.statemodel import ClosureKind


class ThreadTransition(BaseModel):
    """线程生命周期信号（State V2 consequence writeback 契约）.

    只能由 accepted prose 对应的 PlotUnit 发出；evidence_anchor 必须可定位到
    最终接受的正文。selector/plan 说"将承诺/将履行"不得触发创建或关闭：
    OPEN 与 CLOSE 对称——没发生的承诺不记，发生了的承诺才记。

    OPEN：正文明确形成了新的义务/后果压力（承诺、站队、暴露、资源消耗），
    由系统生成 thread_id；CLOSE：既有线程被履行/违背/解除/取代。
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["OPEN", "CLOSE"] = Field(default="CLOSE")
    thread_id: str = Field(
        default="", description="CLOSE 必填：既有线程 ID；OPEN 留空（系统生成）"
    )
    thread_label: str = Field(
        default="", description="OPEN 必填：新线程标签（义务/压力内容）"
    )
    thread_type: str = Field(
        default="情节线", description="OPEN：线程类型（如 承诺线/关系线/信息线）"
    )
    closure_kind: Optional[ClosureKind] = Field(
        default=None, description="CLOSE 必填：FULFILLED/VIOLATED/DISCHARGED/SUPERSEDED"
    )
    evidence_anchor: str = Field(
        description="accepted prose 中的可定位锚点或章节引用（非空）"
    )

    @field_validator("evidence_anchor")
    @classmethod
    def _anchor_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @model_validator(mode="after")
    def _fields_match_action(self) -> "ThreadTransition":
        if self.action == "OPEN" and not self.thread_label.strip():
            raise ValueError("OPEN transition requires non-empty thread_label")
        if self.action == "CLOSE" and (not self.thread_id.strip()
                                     or self.closure_kind is None):
            raise ValueError("CLOSE transition requires thread_id and closure_kind")
        return self


class PlotUnit(BaseModel):
    """最小有效叙事推进单元.

    定义"这次推进改变了什么".
    不是单纯的事件记录或文本段落.
    必须导致至少一个关键状态字段发生有意义变化.
    """

    model_config = ConfigDict(extra="forbid")

    unit_id: str = Field(description="单元唯一标识")
    level: Literal["book", "arc", "chapter", "scene"] = Field(
        description="层级: book / arc / chapter / scene"
    )
    goal: str = Field(description="本单元目标")

    # 参与者与冲突
    participants: list[str] = Field(
        default_factory=list, description="参与角色ID列表"
    )
    conflict: str = Field(description="核心冲突")

    # 状态引用(轻量引用, 不嵌套完整对象)
    input_state_ref: str = Field(description="输入状态 NarrativeState.state_id")
    output_state_ref: str = Field(description="输出状态 NarrativeState.state_id")

    # 推进内容
    released_information: list[str] = Field(
        default_factory=list, description="本单元释放给读者的新信息"
    )
    emotional_shift: Optional[str] = Field(
        default=None, description="情绪变化, 如从压抑到爆发"
    )
    hook: Optional[str] = Field(default=None, description="钩子, 如悬念铺垫")
    hook_type: Optional[str] = Field(
        default=None,
        description="钩子类型（显式枚举：HOOK_TAXONOMY[level] 的 type，如 scene 层 "
        "revelation / transition / scene_hook，chapter 层 cliffhanger / reveal / "
        "emotional_peak / promise / in_media_res / mystery_setup / emotional_anchor）。"
        "None=自由文本钩子（默认），不做严格层级校验",
    )
    formula_node: Optional[str] = Field(
        default=None, description="关联的结构模板节点名，如 opener_hook / climax"
    )

    # 后果
    consequences: list[str] = Field(
        default_factory=list, description="本单元导致的后果清单"
    )

    # 状态变化摘要（弱推进检查依据）
    state_change_summary: Optional[str] = Field(
        default=None,
        description="状态变化摘要：本单元改变了什么（目标/信息/关系/风险/冲突），"
        "weak_progression 判定依据",
    )
    removable_without_loss: Optional[bool] = Field(
        default=None,
        description="删除本单元后主线是否几乎不受损（冗余度判定依据）",
    )

    # ---- v4: 场景体验中间层（方向文档第四节）----
    # 把结构翻译成读者体验的五维（看见/阻碍/选择/结果/认知变化），
    # 作为正文展开的先验，避免「解释充分但缺乏现场感」。Optional：空不渲染，
    # 与旧版逐字节一致（零回归契约）。
    scene_experience: Optional[SceneExperience] = Field(
        default=None,
        description="场景体验中间层：主角看见/阻碍/选择依据/结果/认知变化。"
        "Continue 生成 PlotUnit 时可选产出，Prose 展开时注入正文",
    )

    # ---- RCC V1: 认知交接点（读者认知劳动分配的规划层）----
    # 每个场景最多 1–3 个高价值交接点：证据→读者自推→何时才允许显式。
    # Optional：空不渲染，与旧版逐字节一致（零回归契约）。
    reader_handoffs: Optional[list[InferenceHandoff]] = Field(
        default=None,
        description="认知交接点：本场景把哪些推断工作交还给读者（≤3 个，"
        "只标关键 beat）。Continue 可选产出，Prose 展开时注入为停止条件",
    )

    # ---- CCR V1: 诊断性选择机会（人物通过选择显形的规划层）----
    # 条件性规划对象：压力→≥2真实备选（各带代价）→人物决定权→各选项的
    # 条件性偏好信号。最多 1 个/场景；不满足 anti-fake 资格则省略。
    # Optional：空不渲染，与旧版逐字节一致（零回归契约）。
    diagnostic_choice: Optional[DiagnosticChoice] = Field(
        default=None,
        description="诊断性选择机会：本场景值得 dramatize 的取舍点（≤1 个）。"
        "Continue 可选产出，Prose 展开时注入；revealed preference 仅作"
        "条件性信号，不得写成人物事实",
    )

    # ---- Dialogue V1: 对白社会策略（对话作为社会行动的规划层）----
    # 隐藏质量注解：interaction objective / social constraint /
    # information asymmetry / 稀疏策略 beats（1-4）。Prose 只见编译后
    # 执行契约；完整对象供 post-prose Review。≤1 个/场景，普通寒暄不建。
    dialogue_strategy: Optional[DialogueStrategy] = Field(
        default=None,
        description="对白社会策略：本场值得建模的社会博弈（≤1 个）。"
        "Continue 可选产出；writer 只见执行契约，完整对象供 Review 对照",
    )

    # ---- DFD V1: 细节功能契约（环境细节承重功能的规划层）----
    # 隐藏质量注解：当前读者任务 + 计划承重细节（功能+读者效应+共享簇）
    # + 细节预算。Prose 只见编译后执行契约；完整对象供 post-prose
    # Review 对照。≤1 个/场景，无环境着墨需求的场景不建。
    detail_contract: Optional[DetailContract] = Field(
        default=None,
        description="细节功能契约：本场景值得建模的环境细节功能分配（≤1 个）。"
        "Continue 可选产出；writer 只见执行契约，完整对象供 Review 对照",
    )

    # ---- dim7: 读者预期更新意图（信息缺口/预测管理的规划层）----
    # 隐藏质量注解：对读者预期的计划操作（OPEN/NARROW/STRENGTHEN/
    # WEAKEN/FLIP/RESOLVE + answer_due_now）。Prose 只见编译后行为契约；
    # intended_prediction 永不进 writer-facing 文本。≤2 个/单元，
    # 只动关键信息缺口；计划≠事实，post-prose grounding 才更新台账。
    # Optional：空不渲染，与旧版逐字节一致（零回归契约）。
    expectation_intents: Optional[list[ExpectationUpdateIntent]] = Field(
        default=None,
        description="读者预期更新意图：本场景对读者预期做什么操作（≤2 个）。"
        "Continue 可选产出；writer 只见执行契约，完整对象供 Review/grounding 对照",
    )

    # ---- dim8b: 白描意图（experiential quality 的规划层）----
    # 隐藏质量注解：本单元应让读者感受到的 ambient 质感（烦躁/戒备/疏离/
    # 关系温度），且由可观察载体呈现而非抽象命名。beat_link=责任绑定
    # （谁/哪个 beat 承载）；planned_carriers=开放 realization space。
    # 稀疏资格：重要+命名损失体验+有载体空间。≤2 个/单元。
    # Optional：空不渲染，与旧版逐字节一致（零回归契约）。
    depiction_intents: Optional[list[DepictionIntent]] = Field(
        default=None,
        description="白描意图：本单元要承载的体验质感（≤2 个，稀疏资格）。"
        "Continue 可选产出；writer 只见执行契约，完整对象供 post-prose 核验",
    )

    # 线程生命周期信号不在 PlotUnit：pre-prose 规划器无法逐字引用未来正文，
    # factual OPEN/CLOSE 由 post-prose Review 阶段声明（review.extract_transitions）。

    # 有效性标记(运行时判断)
    is_effective: StrictBool = Field(
        default=False,
        description="是否导致有意义状态变化. 运行时由 Review 确认后标记.",
    )

    @field_validator(
        "unit_id", "goal", "conflict", "input_state_ref", "output_state_ref"
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("participants")
    @classmethod
    def _participant_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("released_information", "consequences")
    @classmethod
    def _progression_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    def to_prompt_context(self, writer_facing: bool = False) -> str:
        """生成给 LLM 的上下文描述.

        writer_facing=True（Prose/Rewrite 用）：diagnostic_choice 只渲染
        编译后的执行契约（分析防火墙）；False 时渲染完整对象（Review/trace）。
        """
        lines = [
            f"【PlotUnit: {self.unit_id} | {self.level}】",
            f"目标: {self.goal}",
            f"冲突: {self.conflict}",
            f"参与者: {', '.join(self.participants)}",
        ]
        if self.released_information:
            lines.append(f"释放信息: {'; '.join(self.released_information)}")
        if self.emotional_shift:
            lines.append(f"情绪变化: {self.emotional_shift}")
        if self.hook:
            lines.append(f"钩子: {self.hook}")
        if self.hook_type:
            lines.append(f"钩子类型: {self.hook_type}")
        if self.formula_node:
            lines.append(f"结构节点: {self.formula_node}")
        if self.consequences:
            lines.append(f"后果: {'; '.join(self.consequences)}")
        if self.state_change_summary:
            lines.append(f"状态变化: {self.state_change_summary}")
        if self.removable_without_loss is not None:
            lines.append(f"可删无损: {'是' if self.removable_without_loss else '否'}")
        if self.scene_experience:
            lines.append(self.scene_experience.to_prompt_context(self.unit_id))
        if self.reader_handoffs:
            lines.append("【认知交接点】")
            for handoff in self.reader_handoffs:
                lines.append(handoff.to_prompt_context())
        if self.diagnostic_choice:
            lines.append(
                self.diagnostic_choice.to_execution_context()
                if writer_facing
                else self.diagnostic_choice.to_prompt_context()
            )
        if self.dialogue_strategy:
            lines.append(
                self.dialogue_strategy.to_execution_context()
                if writer_facing
                else self.dialogue_strategy.to_prompt_context()
            )
        if self.detail_contract:
            lines.append(
                self.detail_contract.to_execution_context()
                if writer_facing
                else self.detail_contract.to_prompt_context()
            )
        if self.expectation_intents:
            if writer_facing:
                lines.append("【读者预期执行契约】")
                lines.extend(
                    intent.to_execution_context()
                    for intent in self.expectation_intents
                )
            else:
                lines.append("【读者预期更新意图】")
                lines.extend(
                    intent.to_prompt_context()
                    for intent in self.expectation_intents
                )
        if self.depiction_intents:
            lines.append(
                "【白描执行契约】" if writer_facing else "【白描意图】")
            for intent in self.depiction_intents:
                lines.append(
                    intent.to_execution_context()
                    if writer_facing else intent.to_prompt_context())
        lines.append(f"有效推进: {'是' if self.is_effective else '待确认'}")
        return "\n".join(lines)
