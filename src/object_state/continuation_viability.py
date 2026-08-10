"""ContinuationViability — 续写可行性判定（Q1 R1）.

R1：生成 PlotUnit 之前回答——故事是否已完成主要情感闭环；是否仍有真实外部冲突/未完成
选择/未兑现承诺；下一章能否产生新的状态变化；继续写是在打开新故事还是重新解释已结束
的故事；若不能继续需要什么新前提。

输出三态 verdict：`continue` / `needs_premise` / `stop`，不能只有 pass/block。

本模块是纯数据（判定结果），不进 serialization.py 状态机层——与 choicerecord /
authorkernel / readerexpectation 同类的 sidecar 模型；判定逻辑在
src/workflow_action/continuation_viability.py。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ViabilityVerdict = Literal["continue", "needs_premise", "stop"]

# 结构模板中的终止型节点（公式节点名来自 src/domain_layer/web_fiction.py GENRE_FORMULAS）
TERMINAL_FORMULA_NODES = frozenset(
    {"resolution", "act3_resolution", "payoff", "catastrophe", "return", "exit"}
)


class ContinuationViabilitySignal(BaseModel):
    """单条确定性证据信号（纯代码可判定，无 LLM）。"""

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(description="信号标识, 如 no_active_frame / open_threads / terminal_node")
    direction: Literal["continue", "stop"] = Field(description="信号方向")
    strength: Literal["weak", "strong"] = Field(description="信号强度")
    evidence: str = Field(description="证据描述/来源（可追溯）")


class ContinuationViabilityDecision(BaseModel):
    """续写可行性判定结果."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    verdict: ViabilityVerdict = Field(
        description="continue / needs_premise / stop——三态，不能只有 pass/block"
    )
    deterministic: bool = Field(
        description="True=纯代码判定可直接放行/阻断；False=信号冲突，须操作者/LLM 确认"
    )
    reasons: list[str] = Field(default_factory=list, description="判定理由（面向操作者）")
    signals: list[ContinuationViabilitySignal] = Field(
        default_factory=list, description="判定依据的证据信号"
    )
    required_premise: Optional[str] = Field(
        default=None, description="verdict=needs_premise 时所需的新前提描述"
    )
    generated_at_utc: Optional[str] = Field(default=None)

    def to_prompt_context(self) -> str:
        """渲染为操作者确认 prompt 的上下文段（不展示给生成模型，零成本）。"""
        lines = [f"预判定: {self.verdict}", f"确定性: {self.deterministic}"]
        for reason in self.reasons:
            lines.append(f"- {reason}")
        if self.required_premise:
            lines.append(f"需要的新前提: {self.required_premise}")
        return "\n".join(lines)
