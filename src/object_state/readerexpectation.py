"""ReaderExpectation — 读者预期管理视图（核心2：读者体验）.

与 ForeshadowGraph（核心1：作者埋的伏笔）的区别（方向文档第六节）：
- ForeshadowGraph 回答「作者埋过什么」——追踪承诺的建立/推进/回收
- ReaderExpectation 回答「读者正在等什么答案」——把伏笔翻译成读者视角的问题，
  带等待时长与吸引力判断

本模块是从 ForeshadowGraph 派生的「读者视角」视图，不是独立状态：
不进入 NarrativeState/Frame/FactLedger 状态机，由审查/编排时动态生成。

核心价值：
1. 读者当前最想知道什么（按等待时长 + 重要性排序）
2. 哪个悬念已拖延过久（window 逾期 → 读者耐心流失风险）
3. 某条主线是否已失去吸引力（长期无推进）
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# 读者预期窗口（PlotUnit 计数）：active 伏笔超过此窗口无推进则判定拖延。
DEFAULT_WINDOW_PLOTUNITS = 3
# 读者预期逾期阈值：拖延超过此窗口数升级为「失去吸引力」风险。
OVERDUE_ESCALATION_MULTIPLIER = 2


class ReaderExpectation(BaseModel):
    """一条读者预期：读者正在等什么答案."""

    model_config = ConfigDict(extra="forbid")

    expectation_id: str = Field(description="预期标识（对齐 Foreshadow thread_id）")
    reader_question: str = Field(
        description="读者视角的问题——把伏笔内容翻译成『读者想知道什么』"
    )
    source_thread_id: str = Field(description="来源 Foreshadow thread_id")
    importance: Literal["high", "medium", "low"] = Field(
        description="对读者追读的重要性（高=读者最想知道）"
    )
    opened_at: str = Field(description="预期建立点（对齐 setup_point）")
    last_advanced_at: Optional[str] = Field(
        default=None, description="最近一次推进点（空=从未推进）"
    )
    advancement_count: int = Field(
        default=0, ge=0, description="已推进次数（PlotUnit 级）"
    )
    window_plotunits: int = Field(
        default=DEFAULT_WINDOW_PLOTUNITS, ge=1, description="预期窗口（PlotUnit 数）"
    )
    status: Literal["waiting", "advanced", "overdue", "stale"] = Field(
        default="waiting",
        description="waiting=在窗口内等待; advanced=已推进; "
        "overdue=超过窗口无推进（拖延）; stale=远超窗口（失去吸引力风险）",
    )

    @field_validator(
        "expectation_id", "reader_question", "source_thread_id", "opened_at"
    )
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class ReaderExpectationLedger(BaseModel):
    """读者预期台账（从 ForeshadowGraph 派生的读者视角视图）."""

    model_config = ConfigDict(extra="forbid")

    expectations: list[ReaderExpectation] = Field(
        default_factory=list, description="读者预期列表"
    )
    generated_from: str = Field(
        default="", description="来源（如 ForeshadowGraph）"
    )

    def get_by_status(self, status: str) -> list[ReaderExpectation]:
        """按状态过滤."""
        return [e for e in self.expectations if e.status == status]

    def top_questions(self, limit: int = 5) -> list[ReaderExpectation]:
        """读者当前最想知道什么（按 importance + 逾期状态排序）. 高优先在前."""
        order = {"high": 0, "medium": 1, "low": 2}
        status_order = {"overdue": 0, "stale": 1, "waiting": 2, "advanced": 3}
        return sorted(
            self.expectations,
            key=lambda e: (status_order[e.status], order[e.importance]),
        )[:limit]

    def overdue_expectations(self) -> list[ReaderExpectation]:
        """已拖延的预期（超过窗口无推进）."""
        return [
            e
            for e in self.expectations
            if e.status in ("overdue", "stale")
        ]

    def to_prompt_context(self) -> str:
        """生成给 LLM 的上下文描述（读者视角的等待清单）."""
        if not self.expectations:
            return "【读者预期】无活跃期待"
        lines = ["【读者预期（读者正在等什么）】"]
        for e in self.top_questions(limit=8):
            status_tag = {
                "waiting": "等待中",
                "advanced": "已推进",
                "overdue": "拖延",
                "stale": "失去吸引力风险",
            }[e.status]
            lines.append(
                f"- [{e.importance}/{status_tag}] {e.reader_question}"
                f"（建立于 {e.opened_at}"
                + (f"，推进 {e.advancement_count} 次" if e.advancement_count else "，未推进")
                + "）"
            )
        if self.overdue_expectations():
            lines.append(
                "注意: 以下预期已拖延过久，读者耐心可能流失: "
                + "; ".join(e.reader_question for e in self.overdue_expectations())
            )
        return "\n".join(lines)


# --- 派生逻辑：ForeshadowGraph → ReaderExpectationLedger ---


def _foreshadow_importance(entry) -> str:
    """按伏笔范围/可见性估算读者重要性."""
    if entry.scope_level == "book":
        return "high"
    if entry.scope_level == "arc":
        return "medium"
    return "high" if entry.visibility_level == "explicit" else "low"


def derive_reader_expectations(
    foreshadow_graph,
    current_plotunit_count: int = 0,
    window_plotunits: int = DEFAULT_WINDOW_PLOTUNITS,
) -> ReaderExpectationLedger:
    """从 ForeshadowGraph 派生读者预期台账.

    Args:
        foreshadow_graph: ForeshadowGraph 对象
        current_plotunit_count: 当前已推进的 PlotUnit 总数（用于判断等待时长）
        window_plotunits: 读者预期窗口（超过则判定拖延）

    状态判定规则：
    - 从未推进且 current_plotunit_count <= window → waiting
    - 推进过但距上次推进超窗口 → overdue（拖延）
    - 从未推进且 current_plotunit_count > window * OVERDUE_ESCALATION_MULTIPLIER
      → stale（失去吸引力风险）
    """
    ledger = ReaderExpectationLedger(generated_from="ForeshadowGraph")
    active = foreshadow_graph.get_active()
    for entry in active:
        adv_count = len(entry.advancement_nodes)
        last_adv = entry.advancement_nodes[-1] if entry.advancement_nodes else None
        status: Literal["waiting", "advanced", "overdue", "stale"] = "waiting"
        if adv_count > 0 and last_adv is not None:
            # 已推进：推进节点按 PlotUnit 计，若已推进但不知道距当前多远，
            # 保守判定为 advanced（不误报拖延，除非 overdue_risk 显式标记）
            status = "advanced"
        elif current_plotunit_count > window_plotunits * OVERDUE_ESCALATION_MULTIPLIER:
            status = "stale"
        elif current_plotunit_count > window_plotunits:
            status = "overdue"

        # 显式 overdue_risk 覆盖（作者/系统已标记逾期风险）
        if entry.overdue_risk:
            status = "stale"

        ledger.expectations.append(
            ReaderExpectation(
                expectation_id=f"re_{entry.thread_id}",
                reader_question=_to_reader_question(entry),
                source_thread_id=entry.thread_id,
                importance=_foreshadow_importance(entry),
                opened_at=entry.setup_point,
                last_advanced_at=last_adv,
                advancement_count=adv_count,
                window_plotunits=window_plotunits,
                status=status,
            )
        )
    return ledger


def _to_reader_question(entry) -> str:
    """把伏笔内容翻译成读者视角的问题.

    伏笔 content 常是陈述（如『墨痕来历与改写代价』），
    读者视角的问题是『墨痕到底是什么、会带来什么后果？』。
    规则：若 content 已带疑问词则保留；否则尝试转为『…是什么/为什么/会怎样』。
    """
    content = entry.content
    # 已含疑问词（什么/为什么/如何/会怎样/是真是假 等）→ 保留
    if any(w in content for w in ("?", "？", "什么", "为什么", "如何", "会怎样", "是否", "是真是假")):
        return content
    # 按 expected_payoff 补提问方向
    payoff = entry.expected_payoff or ""
    if "揭晓" in payoff or "真相" in payoff or "揭示" in payoff:
        return f"{content}，真相是什么？"
    if "回收" in payoff or "下落" in payoff or "命运" in payoff:
        return f"{content}，最终会怎样？"
    if "代价" in payoff or "后果" in payoff:
        return f"{content}，要付出什么代价？"
    return f"{content}，究竟是怎么回事？"
