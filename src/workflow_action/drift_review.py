"""Author Drift Review — 作者性 6E（§42）：区分无意识漂移 vs 作者主动突破.

最终流程：Proposal → Selection → Commit → Prose → Post-Prose Consistency Review
→ Reader Review → **Author Drift Review**。

**不是**「不符合 Kernel 就自动 Rewrite」：先问这是无意识漂移，还是作者主动突破
旧习惯？四类变化各走各的账本（§44），Author Drift Review 只看 Author Change 的
那条线：

- **aligned**：选中文本与所有 stable/weak 原则不冲突 → 无事。
- **active_break**：冲突 stable 原则但**有记录理由**（tradeoff/plot_context 说明
  为什么放弃）→ 允许（§43 Growth：有来由地变），产出 `KernelChallenge` → 进入
  下次 Consolidation（作为反例，触发 challenged_principles + growth 信号）。
- **drift**：冲突 stable 原则且**无记录理由**（无因果经历、无 tradeoff）→ 要防
  （§43 无因果漂移）。Drift Review 只出信号，**不自动 Rewrite**——由人工/后续判断。

零成本契约：`--drift-review off`（默认）→ 无注入、无检测、无产物；kernel 未形成
→ `verdict="aligned"`（没有原则可漂移）。

隐私：challenge 引作品内 decision_id，sidecar 存本地 gitignored；渲染只出中性
方法论语义。
"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import (
    VALUE_VOCAB_DESCRIPTIONS,
    AuthorKernel,
    value_direction,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    RejectedRecord,
)

TS = "2026-08-07T12:00:00"


class KernelChallenge(BaseModel):
    """作者主动突破旧习惯 → 形成的挑战（进入下次 Consolidation 作为反例）."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(description="挑战唯一标识")
    decision_id: str = Field(description="引发挑战的 ChoiceRecord.decision_id")
    vocab_key: str = Field(description="被挑战的原则词汇键（受限词汇表）")
    category: str = Field(description="原则类别（value/prohibition/...）")
    direction: str = Field(description="违反方向（contra）")
    timestamp: str = Field(description="挑战时刻（ISO）")
    reason: str = Field(description="为什么主动突破（deliberate tradeoff/理由）")
    status: Literal["open", "absorbed"] = Field(
        default="open", description="open=等待并入 Consolidation；absorbed=已并入"
    )


class DriftReviewResult(BaseModel):
    """一次 Author Drift Review 的判定."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["aligned", "active_break", "drift"]
    principle: Optional[str] = Field(
        default=None, description="被冲突的原则 vocab_key（aligned 时为 None）"
    )
    direction: str = Field(default="", description="该选择相对原则的方向（contra）")
    tradeoff_present: bool = Field(description="是否记录了放弃理由")
    challenge: Optional[KernelChallenge] = Field(
        default=None, description="active_break 时产出的 KernelChallenge"
    )
    reason: str = Field(description="判定一句话")


class ChallengeLedger(BaseModel):
    """KernelChallenge 台账（sidecar，本地 gitignored）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    challenges: list[KernelChallenge] = Field(default_factory=list)

    @property
    def open_challenges(self) -> list[KernelChallenge]:
        return [c for c in self.challenges if c.status == "open"]


def load_challenge_ledger(path: Path) -> Optional[ChallengeLedger]:
    if not path.exists():
        return None
    return ChallengeLedger.model_validate_json(path.read_text(encoding="utf-8"))


def save_challenge_ledger(path: Path, ledger: ChallengeLedger) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")
    return path


def record_challenge(ledger: ChallengeLedger, challenge: KernelChallenge) -> ChallengeLedger:
    ledger.challenges.append(challenge)
    return ledger


def review_author_drift(
    kernel: Optional[AuthorKernel],
    selected_text: str,
    *,
    tradeoff: str = "",
    decision_id: str = "d_unknown",
    timestamp: str = TS,
) -> DriftReviewResult:
    """判定一次选择是 aligned / active_break / drift（§42，不自动 Rewrite）.

    对 kernel 每个 stable/weak 原则做方向敏感检查（value_direction）：命中
    contra（违反价值/犯禁忌）才冲突；pro（符合/回避）不冲突。冲突时看是否
    `tradeoff` 有记录理由——有=主动突破（active_break，允许），无=无因果漂移
    （drift，要防）。
    """
    if kernel is None or not kernel.all_principles():
        return DriftReviewResult(
            verdict="aligned",
            tradeoff_present=bool(tradeoff),
            reason="kernel 未形成，无稳定原则可漂移",
        )
    for p in kernel.all_principles():
        if p.status not in ("stable", "weak"):
            continue
        direction = value_direction(selected_text, p.vocab_key)
        if direction == "pro":
            continue  # 符合/回避该原则，不冲突
        if direction != "contra":
            continue  # 未触及
        # direction == "contra"：违反该稳定原则
        if tradeoff.strip():
            challenge = KernelChallenge(
                challenge_id=f"ch_{decision_id}",
                decision_id=decision_id,
                vocab_key=p.vocab_key,
                category=p.category,
                direction=direction,
                timestamp=timestamp,
                reason=tradeoff.strip(),
            )
            return DriftReviewResult(
                verdict="active_break",
                principle=p.vocab_key,
                direction=direction,
                tradeoff_present=True,
                challenge=challenge,
                reason=(
                    f"冲突稳定原则[{VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)}]"
                    f"但记录理由——作者主动突破，进入下次 Consolidation"
                ),
            )
        return DriftReviewResult(
            verdict="drift",
            principle=p.vocab_key,
            direction=direction,
            tradeoff_present=False,
            reason=(
                f"冲突稳定原则[{VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)}]"
                f"且无记录理由——无因果漂移，要防"
            ),
        )
    return DriftReviewResult(
        verdict="aligned",
        tradeoff_present=bool(tradeoff),
        reason="与所有稳定原则一致",
    )


def _contra_text(vocab_key: str) -> str:
    from src.object_state.authorkernel import VALUE_VOCAB_CONTRA_KEYWORDS

    kw = next((k for k in VALUE_VOCAB_CONTRA_KEYWORDS.get(vocab_key, ()) if k), vocab_key)
    return f"作者选择了「{kw}」"


def challenge_to_choice(
    challenge: KernelChallenge, *, timestamp: str = TS
) -> ChoiceRecord:
    """把 KernelChallenge 转成一条反例 ChoiceRecord（供下次 Consolidation 消费）.

    闭环（§43 Growth）：主动突破 → KernelChallenge → 反例 → 下次 Consolidation
    把这条反例并入被挑战原则的 counterexamples → challenged/growth 信号。
    """
    pu_text = {
        "unit_id": "pu_x",
        "level": "scene",
        "goal": _contra_text(challenge.vocab_key),
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": [],
        "released_information": [],
        "is_effective": True,
    }
    return ChoiceRecord(
        decision_id=challenge.decision_id,
        decision_timestamp=challenge.timestamp,
        plot_context=challenge.reason,
        state_ref="ns_in",
        candidates=[
            CandidateRecord(
                candidate_id="A", summary="主动突破",
                plotunit=pu_text, new_state_ref="ns_out",
            ),
            CandidateRecord(
                candidate_id="B", summary="符合旧习惯",
                plotunit={"unit_id": "pu_y", "level": "scene", "goal": "无关的推进",
                          "conflict": "", "input_state_ref": "ns_in",
                          "output_state_ref": "ns_out", "consequences": [],
                          "released_information": [], "is_effective": True},
                new_state_ref="ns_out",
            ),
        ],
        selected_candidate="A",
        rejected=[RejectedRecord(candidate_id="B", reason="未选")],
        tradeoff=challenge.reason,
        value_conflicts=[challenge.vocab_key],
    )


def challenges_to_choices(
    challenges: list[KernelChallenge], *, timestamp: str = TS
) -> list[ChoiceRecord]:
    """批量转反例（供把整个台账并入 ChoiceLedger 后 Consolidation）."""
    return [challenge_to_choice(c, timestamp=timestamp) for c in challenges]
