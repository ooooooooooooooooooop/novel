"""ForeshadowGraph — 伏笔图定义."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class ForeshadowEntry(BaseModel):
    """单条伏笔/承诺/误导."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(description="线索唯一标识")
    setup_point: str = Field(description="埋设点, 如'第3章末尾神秘人影'")
    content: str = Field(description="内容, 如'主角身世之谜'")
    visibility_level: Literal["explicit", "implicit"] = Field(
        description="显性(读者明显感知)或隐性(细节暗示)"
    )
    expected_payoff: str = Field(description="预期回收方式")
    current_status: Literal[
        "active", "resolved", "abandoned", "transformed", "open", "delayed", "false_path"
    ] = Field(
        default="active",
        description="当前状态。open/delayed/false_path 为管理态：open=已建立未启动推进，"
        "delayed=推迟回收（须带代价），false_path=误导性假线索",
    )
    expiry_risk: Optional[str] = Field(
        default=None, description="过期风险, 如'若5章内未回收则失效'"
    )
    expires_at: Optional[str] = Field(
        default=None,
        description="先知时效/回收期限点(YYYY-MM 或 YYYY-MM-DD)；仍 active 且"
        "当前叙事时间 >= 该点则判定逾期。None=不参与先知时效检测。",
    )

    # 推进轨迹（回收质量审查依据）
    advancement_nodes: list[str] = Field(
        default_factory=list, description="推进节点(PlotUnit/章号), 伏笔被推进的位置"
    )
    narrowing_events: list[str] = Field(
        default_factory=list, description="收窄事件, 缩小承诺可能性范围的事件"
    )
    payoff_nodes: list[str] = Field(
        default_factory=list, description="回收节点(PlotUnit/章号), 揭晓/确认/反转的位置"
    )
    urgency_to_payoff: Optional[str] = Field(
        default=None, description="紧迫性描述, 如'临近真相的时机'"
    )
    overdue_risk: Optional[str] = Field(
        default=None, description="逾期风险描述, 如'主线承诺长时间无推进'"
    )
    scope_level: Optional[Literal["plot", "arc", "book"]] = Field(
        default=None, description="承诺范围层级: plot/arc/book"
    )

    # 轻量引用
    linked_characters: list[str] = Field(
        default_factory=list, description="关联角色ID"
    )
    linked_facts: list[str] = Field(
        default_factory=list, description="关联 FactLedger.fact_id"
    )
    linked_plotunits: list[str] = Field(
        default_factory=list, description="关联 PlotUnit.unit_id"
    )

    @field_validator("thread_id", "setup_point", "content", "expected_payoff")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("expires_at")
    @classmethod
    def _opt_expiry_must_be_non_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("expires_at must be non-empty when provided")
        return value

    @field_validator("linked_characters", "linked_facts", "linked_plotunits")
    @classmethod
    def _linked_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("advancement_nodes", "narrowing_events", "payoff_nodes")
    @classmethod
    def _trajectory_refs_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values

    @field_validator("urgency_to_payoff", "overdue_risk")
    @classmethod
    def _optional_risk_text_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value


class ForeshadowGraph(BaseModel):
    """伏笔与承诺追踪图.

    记录"系统答应过读者什么".
    不是松散备注列表.
    """

    model_config = ConfigDict(extra="forbid")

    entries: list[ForeshadowEntry] = Field(
        default_factory=list, description="伏笔条目列表"
    )

    def get_active(self) -> list[ForeshadowEntry]:
        """获取未回收的活跃承诺."""
        return [e for e in self.entries if e.current_status == "active"]

    def get_expired_risk(self) -> list[ForeshadowEntry]:
        """获取有过期风险的条目."""
        return [e for e in self.entries if e.expiry_risk is not None]

    def resolve(self, thread_id: str) -> bool:
        """标记为已回收."""
        for e in self.entries:
            if e.thread_id == thread_id:
                e.current_status = "resolved"
                return True
        return False

    def set_status(self, thread_id: str, status: str) -> bool:
        """按 Review 声明把伏笔线程置为指定状态（active/resolved/…）.

        用于「正文已兑现但线程仍标 active」的状态 reconcile——被 LLM 审查
        判定已回收的承诺在此落为 resolved，后续 Review 不再误报 promise_loss。
        未知线程 id 或非法状态返回 False（不抛错，静默跳过）。
        """
        allowed = {
            "active", "resolved", "abandoned", "transformed",
            "open", "delayed", "false_path",
        }
        if status not in allowed:
            return False
        for e in self.entries:
            if e.thread_id == thread_id:
                e.current_status = status
                return True
        return False

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述."""
        active = self.get_active()
        if not active:
            return "【伏笔图】无活跃承诺"
        lines = ["【活跃承诺/伏笔】"]
        for e in active:
            vis = "显性" if e.visibility_level == "explicit" else "隐性"
            lines.append(f"- [{vis}] {e.content} (埋设: {e.setup_point})")
            if e.expiry_risk:
                lines.append(f"  风险: {e.expiry_risk}")
            if e.advancement_nodes:
                lines.append(f"  已推进: {', '.join(e.advancement_nodes)}")
            if e.urgency_to_payoff:
                lines.append(f"  紧迫性: {e.urgency_to_payoff}")
            if e.overdue_risk:
                lines.append(f"  逾期风险: {e.overdue_risk}")
            if e.scope_level:
                lines.append(f"  范围层级: {e.scope_level}")
        return "\n".join(lines)
