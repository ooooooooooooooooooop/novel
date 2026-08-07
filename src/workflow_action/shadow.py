"""Shadow Mode — 作者性 6C（§40）：生产 Selector 出 A，Author Selector 出 B，B 不进正文.

实验（Gate D）通过后仍不接生产。当前生产选择照常出实际结果（A），作者感知选择
并行出影子结果（B），**B 永远不进正文**——只用于记录：A/B 何时一致、何时分叉、
分叉原因、B 后来是否更好（hindsight）→ 积累真实生产数据，供 Phase 13 盲评。

零成本契约：`--shadow off`（默认）→ `run_shadow_selection` 返回 None、不产文件；
`--shadow on` 且 kernel 为空 → 仍记录基线分叉（style/reader 维度），诚实标注
`kernel_formed=False`。

隐私：ShadowComparison 含作品语境（候选标签/理由），sidecar 存本地 gitignored
（`novels/<名>/output/shadow/shadow_ledger.json`），不入库。
"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import AuthorKernel
from src.object_state.styleprofile import StyleProfile
from src.workflow_action.author_selector import (
    evaluate_candidates,
    select_candidate,
)
from src.workflow_action.review import ReviewUnit

ShadowHindsight = Literal[
    "still_supported", "partial_regret", "overturned", "complex", "unclear"
]


class ShadowComparison(BaseModel):
    """一次生产 vs 影子选择的对照记录（B 不进正文，只记数据）."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(description="决策唯一标识")
    timestamp: str = Field(description="决策时刻（ISO）")
    state_ref: str = Field(default="", description="决策输入状态 state_id")
    production_label: str = Field(description="生产 Selector 实际结果（进正文的 A）")
    shadow_label: str = Field(description="Author Selector 影子结果（不进正文的 B）")
    divergent: bool = Field(description="A != B（是否分叉）")
    divergence_kind: Literal["author_veto", "author_preference", "baseline", "aligned"] = Field(
        description=(
            "author_veto：生产选了被作者硬禁忌否决的候选；author_preference：kernel "
            "驱动的偏好差异；baseline：无 kernel 时的 style/reader 维度差异；aligned：一致"
        )
    )
    shadow_reasons: list[str] = Field(
        default_factory=list, description="为什么影子选 B（拒绝理由/作者视角理由）"
    )
    production_reasons: list[str] = Field(
        default_factory=list, description="生产选 A 的作者视角理由（若有）"
    )
    shadow_tradeoff: str = Field(default="", description="影子选择的 tradeoff（放弃 X 换 Y）")
    kernel_formed: bool = Field(description="对照时 AuthorKernel 是否已形成")
    hindsight: Optional[ShadowHindsight] = Field(
        default=None, description="几章后回看：影子 B 后来是否更好（由后续补写）"
    )


class ShadowLedger(BaseModel):
    """影子对照台账（sidecar，本地 gitignored）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    comparisons: list[ShadowComparison] = Field(default_factory=list)

    @property
    def divergence_rate(self) -> float:
        if not self.comparisons:
            return 0.0
        return sum(1 for c in self.comparisons if c.divergent) / len(self.comparisons)


def load_shadow_ledger(path: Path) -> Optional[ShadowLedger]:
    """读台账；缺失返回 None（主流程 no-op）."""
    if not path.exists():
        return None
    return ShadowLedger.model_validate_json(path.read_text(encoding="utf-8"))


def save_shadow_ledger(path: Path, ledger: ShadowLedger) -> Path:
    """写台账（sidecar，含作品语境，本地 gitignored）."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return path


def record_shadow_comparison(ledger: ShadowLedger, comparison: ShadowComparison) -> ShadowLedger:
    """追加一条对照（保持时间序）."""
    ledger.comparisons.append(comparison)
    return ledger


def run_shadow_selection(
    packages: list[dict],
    objects: list,
    *,
    production_label: str,
    decision_id: str,
    timestamp: str,
    state_ref: str = "",
    kernel: Optional[AuthorKernel] = None,
    style_profile: Optional[StyleProfile] = None,
    current_state_ref: str = "",
    review: Optional[ReviewUnit] = None,
) -> Optional[ShadowComparison]:
    """并行跑作者感知影子选择 + 与生产结果对照（B 不进正文）.

    Args:
        packages: 候选包列表（proposal_generator 产出，含 plotunit/new_state/tradeoff_hint）
        objects: Consistency Gate 用到的对象列表
        production_label: 生产 Selector 已选出的实际结果标签（进正文的 A）
        其余：传给 evaluate_candidates / select_candidate 的作者感知参数

    Returns:
        ShadowComparison；空 packages 返回 None（主流程 no-op）。
    """
    if not packages:
        return None
    evals = evaluate_candidates(
        packages, objects,
        kernel=kernel, style_profile=style_profile,
        current_state_ref=current_state_ref, review=review,
    )
    shadow = select_candidate(packages, evals, kernel=kernel)
    divergent = shadow.selected_label != production_label

    kernel_formed = kernel is not None and bool(kernel.all_principles())
    prod_eval = evals.get(production_label)
    prod_notes = prod_eval.author_notes if prod_eval is not None else []
    prod_veto = prod_eval.author_veto if prod_eval is not None else False

    if not divergent:
        kind = "aligned"
    elif kernel_formed and prod_veto:
        kind = "author_veto"  # 生产选了被作者硬禁忌否决的候选
    elif kernel_formed:
        kind = "author_preference"
    else:
        kind = "baseline"  # 无 kernel：style/reader 维度差异

    return ShadowComparison(
        decision_id=decision_id,
        timestamp=timestamp,
        state_ref=state_ref,
        production_label=production_label,
        shadow_label=shadow.selected_label,
        divergent=divergent,
        divergence_kind=kind,
        shadow_reasons=[r["reason"] for r in shadow.rejected],
        production_reasons=prod_notes,
        shadow_tradeoff=shadow.tradeoff,
        kernel_formed=kernel_formed,
    )


def render_shadow_comparison(comparison: ShadowComparison) -> str:
    """人类可读的对照摘要（CLI 打印用）."""
    tag = "DIVERGE" if comparison.divergent else "aligned"
    kind = comparison.divergence_kind
    lines = [
        f"[{tag}/{kind}] {comparison.decision_id}: production={comparison.production_label} "
        f"shadow={comparison.shadow_label}"
    ]
    if comparison.divergent:
        lines.append(f"  shadow_tradeoff: {comparison.shadow_tradeoff}")
        for reason in comparison.shadow_reasons:
            lines.append(f"  shadow: {reason}")
    return "\n".join(lines)
