"""CharacterModel — 角色模型定义."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class CharacterModel(BaseModel):
    """角色决策模型.

    定义"这个人为什么会这样做".
    不是只有外貌和性格标签的人设卡.
    字段本体只保留压缩的长期结论, 支撑证据留在 PlotUnit / NarrativeState / handoff / review context.
    """

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(description="角色唯一标识")
    name: str = Field(description="角色名")
    identity: str = Field(description="身份定位, 如'被逐出宗门的少女'")

    # 驱动力
    outer_goal: str = Field(description="外在目标, 角色明确追求什么")
    inner_need: str = Field(description="内在需求, 角色真正需要什么")
    fear: str = Field(description="恐惧, 角色最怕发生什么")
    flaw: str = Field(description="缺陷, 限制角色决策的弱点")
    strength: str = Field(description="优势, 角色能依赖的能力")

    # 隐藏层
    secret: Optional[str] = Field(default=None, description="秘密, 未公开的核心信息")
    stance: str = Field(description="当前立场, 如中立/敌对/合作")

    # 成长
    arc_stage: Optional[str] = Field(
        default=None, description="弧线阶段, 如否认→挣扎→接受"
    )
    self_image: Optional[str] = Field(
        default=None, description="自我认知, 如'我必须独自承担'"
    )

    # 认知状态(硬事实 vs 错误信念分离, Track 3)
    knowledge_state: list[str] = Field(
        default_factory=list,
        description="已确认的已知信息(硬事实)",
    )
    misinformation: list[str] = Field(
        default_factory=list,
        description="角色持有的错误信念(不是推导字段, 是已稳定的角色属性)",
    )

    # 关系(只存结论, 不存依据)
    relations: dict[str, str] = Field(
        default_factory=dict,
        description="与其他角色的关系结论. key=角色ID, value=关系描述",
    )

    # ---- v4: 动态角色建模（方向文档第五节：从固定标签到经历/压力/变化） ----
    # 全部 Optional/default，向后兼容（旧 state 无这些字段可反序列化）。
    current_pressure: list[str] = Field(
        default_factory=list,
        description="当前压力——此刻正推动/逼迫角色行动的力量（时限/威胁/利益冲突），"
        "解释『为什么此刻这样决定』（压力随时间变化，非固定标签）",
    )
    change_trajectory: list[str] = Field(
        default_factory=list,
        description="变化过程——经历积累产生的成长/异化轨迹（如『从独行到愿意托付』），"
        "用于识别『合理变化』vs『缺少铺垫的突然转变』",
    )
    relation_behaviors: dict[str, str] = Field(
        default_factory=dict,
        description="关系→行为差异. key=角色ID, value=『面对此人时行为如何不同』"
        "（同一角色对不同人表现不同：对盟友坦诚/对上级戒备/对仇敌逞强），"
        "解决固定标签导致的『对谁都一个样』僵化",
    )

    @field_validator(
        "character_id",
        "name",
        "identity",
        "outer_goal",
        "inner_need",
        "fear",
        "flaw",
        "strength",
        "stance",
    )
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("knowledge_state", "misinformation", "current_pressure", "change_trajectory")
    @classmethod
    def _knowledge_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("relations", "relation_behaviors")
    @classmethod
    def _relation_entries_must_be_non_blank(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not value.strip() for key, value in values.items()):
            raise ValueError("relations entries must be non-empty")
        return values

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        lines = [
            f"【角色: {self.name}】",
            f"角色ID: {self.character_id}",
            f"身份: {self.identity}",
            f"外在目标: {self.outer_goal}",
            f"内在需求: {self.inner_need}",
            f"恐惧: {self.fear}",
            f"缺陷: {self.flaw}",
            f"优势: {self.strength}",
            f"立场: {self.stance}",
        ]
        if self.secret:
            lines.append(f"秘密: {self.secret}")
        if self.arc_stage:
            lines.append(f"成长阶段: {self.arc_stage}")
        if self.self_image:
            lines.append(f"自我认知: {self.self_image}")
        if self.knowledge_state:
            lines.append(f"已知信息: {'; '.join(self.knowledge_state)}")
        if self.misinformation:
            lines.append(f"错误信念: {'; '.join(self.misinformation)}")
        if self.relations:
            rels = [f"{k}: {v}" for k, v in self.relations.items()]
            lines.append(f"关系: {'; '.join(rels)}")
        # v4: 动态角色建模（空字段不渲染 → 与旧版逐字节一致）
        if self.current_pressure:
            lines.append(f"当前压力: {'; '.join(self.current_pressure)}")
        if self.change_trajectory:
            lines.append(f"变化轨迹: {'; '.join(self.change_trajectory)}")
        if self.relation_behaviors:
            rel_behav = [
                f"{k}: {v}" for k, v in self.relation_behaviors.items()
            ]
            lines.append(f"关系行为差异: {'; '.join(rel_behav)}")
        return "\n".join(lines)

    def reconcile_knowledge(
        self,
        learn: list[str] | None = None,
        drop_unknown: list[str] | None = None,
    ) -> list[str]:
        """按 Review 声明更新已知信息（knowledge_state）.

        - learn: 本章角色新得知的信息，追加（去重）。
        - drop_unknown: 被确证的『不知道X』断言，从 knowledge_state 移除。

        用途：正文/情节已把某信息揭示给角色后，把知识域与叙事同步，
        避免信息凭证检测对已过期的『不知道X』反复误报。返回变化条目。
        """
        learn = learn or []
        drop_unknown = drop_unknown or []
        changed: list[str] = []
        for item in learn:
            item = str(item).strip()
            if item and item not in self.knowledge_state:
                self.knowledge_state.append(item)
                changed.append(f"+{item}")
        for claim in drop_unknown:
            claim = str(claim).strip()
            if claim in self.knowledge_state:
                self.knowledge_state = [
                    k for k in self.knowledge_state if k != claim
                ]
                changed.append(f"-{claim}")
        return changed

    def resolve_pressures(self, items: list[str]) -> list[str]:
        """把已解决/不再当前的当前压力从 current_pressure 移除.

        只追加不清理会让已兑现的压力（如『处决文书今日到期』在获赦后仍残留）
        一直注入后续 prompt，误导生成把旧冲突当现状。返回被移除的条目。
        """
        removed: list[str] = []
        keep: list[str] = []
        for item in self.current_pressure:
            if item.strip() in [i.strip() for i in (items or [])]:
                removed.append(item)
            else:
                keep.append(item)
        self.current_pressure = keep
        return removed
