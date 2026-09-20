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
    """一条读者预期：读者正在等什么答案.

    dim7 扩展（Information-Gap / Prediction Control）：
    - mode：curiosity=答案未知（"到底是什么"）；suspense=结果空间已知、
      关心哪个结果发生。suspense 才需要 stakes。
    - possibilities：读者当前合理可能性空间（来自 accepted prose 的
      grounded 抽取，非作者意图）。
    - dominant_prediction：正文已建立的读者默认预测——surprise 的
      earned/unearned 判定基线；无基线的反转不算 earned。
    - evidence_refs：支撑 possibilities/prediction 的证据引用
      （必须来自 accepted prose）。
    """

    model_config = ConfigDict(extra="forbid")

    expectation_id: str = Field(description="预期标识（对齐 Foreshadow thread_id）")
    reader_question: str = Field(
        description="读者视角的问题——把伏笔内容翻译成『读者想知道什么』"
    )
    source_thread_id: Optional[str] = Field(
        default=None,
        description="来源 Foreshadow thread_id；场景级即时悬念可无来源（None）",
    )
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
    status: Literal["waiting", "advanced", "overdue", "stale", "resolved"] = Field(
        default="waiting",
        description="waiting=在窗口内等待; advanced=已推进; "
        "overdue=超过窗口无推进（拖延）; stale=远超窗口（失去吸引力风险）; "
        "resolved=已兑现/已回答（保留审计不再追问）",
    )

    # ---- dim7 扩展字段（全部可空/默认空：旧序列化零回归契约）----
    mode: Literal["curiosity", "suspense"] = Field(
        default="curiosity",
        description="curiosity=答案本身未知；suspense=结果空间已知、"
        "关心哪个结果发生（需要 stakes）",
    )
    possibilities: list[str] = Field(
        default_factory=list,
        description="读者当前合理可能性空间（grounded 于 accepted prose）",
    )
    dominant_prediction: Optional[str] = Field(
        default=None,
        description="正文已建立的读者默认预测（surprise 判定基线）",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="支撑可能性/预测的证据引用（须来自 accepted prose）",
    )
    stakes: Optional[str] = Field(
        default=None, description="suspense 模式的代价/风险描述"
    )

    @field_validator("expectation_id", "reader_question", "opened_at")
    @classmethod
    def _text_must_be_non_blank(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @field_validator("source_thread_id", "dominant_prediction", "stakes")
    @classmethod
    def _opt_text_must_be_non_blank(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty when provided")
        return value

    @field_validator("possibilities", "evidence_refs")
    @classmethod
    def _dim7_list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        if any(not v.strip() for v in values):
            raise ValueError(f"{info.field_name} entries must be non-empty")
        return values


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

    def open_expectations(self) -> list[ReaderExpectation]:
        """未关闭的预期（dim7 due-event 判定的作用域）."""
        return [
            e for e in self.expectations if e.status != "resolved"
        ]

    def get(self, expectation_id: str) -> Optional[ReaderExpectation]:
        for e in self.expectations:
            if e.expectation_id == expectation_id:
                return e
        return None

    def upsert(self, entry: ReaderExpectation) -> None:
        """按 expectation_id 更新或追加（post-prose grounded 写回）."""
        for i, e in enumerate(self.expectations):
            if e.expectation_id == entry.expectation_id:
                self.expectations[i] = entry
                return
        self.expectations.append(entry)

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

    def to_open_context(self) -> str:
        """Continue 用的开放预期清单（带 expectation_id 供 intents 引用）."""
        open_items = self.open_expectations()
        if not open_items:
            return ""
        lines = [
            "当前开放预期（读者正在等待/怀疑/预测——expectation_intents 引用其 id）："
        ]
        for e in open_items:
            line = f"- [{e.expectation_id}] [{e.mode}/{e.status}] {e.reader_question}"
            if e.dominant_prediction:
                line += f"｜读者默认预测：{e.dominant_prediction}"
            elif e.possibilities:
                line += f"｜可能性空间：{'；'.join(e.possibilities[:4])}"
            if e.mode == "suspense" and e.stakes:
                line += f"｜代价：{e.stakes}"
            lines.append(line)
        return "\n".join(lines)

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
            line = (
                f"- [{e.importance}/{status_tag}] {e.reader_question}"
                f"（建立于 {e.opened_at}"
                + (f"，推进 {e.advancement_count} 次" if e.advancement_count else "，未推进")
                + "）"
            )
            if e.mode == "suspense":
                line += f"〔悬念：{e.stakes or '结果未定'}〕"
            if e.dominant_prediction:
                line += f"〔读者默认预测：{e.dominant_prediction}〕"
            elif e.possibilities:
                line += f"〔读者可能性空间：{'；'.join(e.possibilities[:4])}〕"
            lines.append(line)
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
