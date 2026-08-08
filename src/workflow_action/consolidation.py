"""Choice Consolidation — 从选择史归纳作者（作者性第四工作包 §22-27、§43）.

4A（§22-23）：攒 N 个 ChoiceRecord 后寻找重复选择结构，而非每次 Choice 就改
Kernel（禁止 5：短期压力与长期身份分离）。

```
Choice 001...050 → 寻找重复选择结构 → 生成 Author Principle Candidate
→ 寻找反例 → 仍成立？→ 形成弱原则
```

错误归纳教训（§23）：连续 5 次没选强钩子，**不能直接得出「作者讨厌强钩子」**——
这 5 个钩子可能都需要「角色突然变聪明」。真正的原则是「角色因果 > 局部戏剧性」。
本模块通过 `infer_value_conflicts` 把表面文本映射到受限价值词汇表（VALUE_VOCAB），
即完成这一层「挖到深层原则」的动作。

防编造（禁止 10）：每条原则（a）映射到受限价值词汇表（vocab_key 校验），
（b）附 supporting_choices 引用（行为证据），（c）必须产出 counterexamples，
（d）反例过多自动降级 contested。模型说一句「我相信……」不算——行为证据优先。

4C（§27/§43）：允许「有来由地变」，严格区分：
- **Drift（要防）**：没有相关新经历、没有明确 tradeoff、没有新价值冲突，但输出
  突然大变——无因果漂移（本模块检测：原则强度骤降但其价值键本轮无任何新选择触及）。
- **Growth（要允许）**：旧原则遭遇长期反例 → 产生 tension → 多次选择开始改变 →
  形成新稳定边界——有历史原因的成长（本模块检测：反例增长但原则仍成立 →
  标记为被挑战/张力显式化）。

隐私：ChoiceLedger/AuthorKernel 含作品语境，sidecar 存本地 gitignored
（`novels/<名>/output/<mode>/`）；风格库只放中性方法论。
"""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import (
    _CATEGORY_VOCAB,
    VALUE_VOCAB_DESCRIPTIONS,
    AuthorKernel,
    AuthorPrinciple,
    principle_id_for,
    value_direction,
)
from src.object_state.choicerecord import ChoiceLedgerEntry, ChoiceRecord

# 价值键 → 类别（词汇表按类别划分，一键一类别）
_KEY_TO_CATEGORY: dict[str, str] = {}
for _cat, _keys in _CATEGORY_VOCAB.items():
    for _k in _keys:
        _KEY_TO_CATEGORY[_k] = _cat


class PrincipleEvidence(BaseModel):
    """单一价值键在本次台账里的行为证据."""

    model_config = ConfigDict(extra="forbid")

    vocab_key: str
    supporting: list[str] = Field(
        default_factory=list, description="选中候选文本命中该价值关键词的 decision_id"
    )
    counterexamples: list[str] = Field(
        default_factory=list,
        description="拒绝候选文本命中/事后懊悔的 decision_id（反例）",
    )

    @property
    def support_count(self) -> int:
        return len(self.supporting)

    @property
    def counter_count(self) -> int:
        return len(self.counterexamples)


class ConsolidationResult(BaseModel):
    """一次 Consolidation 的结果（含 Growth/Drift 信号，供报告/审查）."""

    model_config = ConfigDict(extra="forbid")

    kernel: AuthorKernel = Field(description="合并后的内核")
    new_principles: list[str] = Field(
        default_factory=list, description="本轮新形成的原则 vocab_key"
    )
    reinforced_principles: list[str] = Field(
        default_factory=list, description="本轮被强化/更新的原则 vocab_key"
    )
    challenged_principles: list[dict] = Field(
        default_factory=list,
        description="[{vocab_key, counterexamples, status_before, status_after, reason}] 被反例挑战的原则",
    )
    growth_signals: list[dict] = Field(
        default_factory=list,
        description="[{vocab_key, description, reason}] 有来由地变（允许）",
    )
    drift_signals: list[dict] = Field(
        default_factory=list,
        description="[{vocab_key, description, reason}] 无因果经历的突变（要防）",
    )
    touched_keys: list[str] = Field(
        default_factory=list, description="本轮被证据触及的价值键"
    )
    summary: str = Field(description="一句话概要（报告/CLI）")


# ---------------------------------------------------------------------------
# 证据提取（行为证据，禁止 10）
# ---------------------------------------------------------------------------
def _candidate_text(pu: dict) -> str:
    """从候选 plotunit 字典渲染文本（与 Selector._package_text 一致口径）."""
    parts = [
        pu.get("goal", ""),
        pu.get("conflict", ""),
        pu.get("hook", "") or "",
    ]
    parts += pu.get("consequences") or []
    parts += pu.get("released_information") or []
    se = pu.get("scene_experience") or {}
    for field in ("protagonist_sees", "choice_grounding", "outcome", "cognition_shift"):
        parts.append(se.get(field, ""))
    parts += se.get("obstacles") or []
    return " ".join(parts)


def _candidate_for(choice: ChoiceRecord, candidate_id: str) -> Optional[dict]:
    for c in choice.candidates:
        if c.candidate_id == candidate_id:
            return c.plotunit
    return None


def extract_evidence(
    ledger: ChoiceLedgerEntry,
    *,
    category: Optional[str] = None,
    challenges: Optional[list] = None,
) -> dict[str, PrincipleEvidence]:
    """从 ChoiceLedger 提取每价值键的行为证据.

    规则（确定性，非 LLM；方向敏感，§23）：
    - supporting：选中候选文本命中该价值的 PRO 方向关键词（作者选择了表达该价值）。
    - counterexample：① 该选择事后 hindsight ∈ {overturned, partial_regret}（作者
      自己判定失当）；② 选中候选命中 CONTRA 方向（作者选了违反该价值的方向）；
      ③ 选中未命中、但某个被拒候选命中 PRO（作者拒绝了表达该价值的选项）；
      ④ 该 decision_id 有 open KernelChallenge（Author Drift Review 记录的
      主动突破/漂移——作者自己的判定或事后审查）。
    - 两者都不命中 → 仅「触及未决」（tension 候选证据），不计入任何一边。
    """
    challenge_map: dict[str, set[str]] = {}
    if challenges:
        for ch in challenges:
            if getattr(ch, "status", "open") == "open":
                challenge_map.setdefault(ch.decision_id, set()).add(ch.vocab_key)

    evidence: dict[str, PrincipleEvidence] = {}
    for choice in ledger.choices:
        touched = set(choice.value_conflicts)
        if category is not None:
            touched = touched & set(_CATEGORY_VOCAB.get(category, ()))
        if not touched:
            continue
        sel_pu = _candidate_for(choice, choice.selected_candidate)
        sel_text = _candidate_text(sel_pu) if sel_pu else ""
        rejected_ids = {r.candidate_id for r in choice.rejected}
        rejected_texts = [
            _candidate_text(c.plotunit)
            for c in choice.candidates
            if c.candidate_id in rejected_ids
        ]
        retro_bad = choice.hindsight in ("overturned", "partial_regret")
        challenged_keys = challenge_map.get(choice.decision_id, set())

        for key in touched:
            entry = evidence.setdefault(key, PrincipleEvidence(vocab_key=key))
            if key in challenged_keys or retro_bad:
                entry.counterexamples.append(choice.decision_id)
            elif value_direction(sel_text, key) == "contra":
                entry.counterexamples.append(choice.decision_id)
            elif value_direction(sel_text, key) == "pro":
                entry.supporting.append(choice.decision_id)
            elif any(value_direction(t, key) == "pro" for t in rejected_texts):
                entry.counterexamples.append(choice.decision_id)
    return evidence


# ---------------------------------------------------------------------------
# 原则形成 / 合并（防编造：反例过多自动降级）
# ---------------------------------------------------------------------------
def _status_for(support: int, counter: int, *, min_support: int, contested_ratio: float) -> str:
    """candidate→weak→stable→contested（§26；反例过多自动 contested）."""
    total = support + counter
    if total == 0:
        return "candidate"
    if counter / total >= contested_ratio:
        return "contested"
    if support < min_support:
        return "candidate"
    if support >= 3:
        return "stable"
    return "weak"


def _build_principle(
    key: str,
    ev: PrincipleEvidence,
    *,
    timestamp: str,
    min_support: int,
    contested_ratio: float,
    existing: Optional[AuthorPrinciple] = None,
) -> AuthorPrinciple:
    """合并证据到（新/既有）原则."""
    support = ev.support_count
    counter = ev.counter_count
    total = support + counter

    if existing is None:
        return AuthorPrinciple(
            principle_id=principle_id_for(_KEY_TO_CATEGORY.get(key, "value"), key, 1),
            category=_KEY_TO_CATEGORY.get(key, "value"),
            vocab_key=key,
            description=VALUE_VOCAB_DESCRIPTIONS.get(key, key),
            supporting_choices=list(ev.supporting),
            counterexamples=list(ev.counterexamples),
            first_formed_at=timestamp,
            last_reinforced=timestamp if support else None,
            last_challenged=timestamp if counter else None,
            strength=support / total if total else 0.0,
            confidence=min(1.0, total / 5.0),
            status=_status_for(support, counter, min_support=min_support, contested_ratio=contested_ratio),
        )

    # 合并：去重并集 + 重算强度/置信/状态
    supporting = list(dict.fromkeys(existing.supporting_choices + ev.supporting))
    counterexamples = list(dict.fromkeys(existing.counterexamples + ev.counterexamples))
    return existing.model_copy(
        update={
            "supporting_choices": supporting,
            "counterexamples": counterexamples,
            "last_reinforced": timestamp if support else existing.last_reinforced,
            "last_challenged": timestamp if counter else existing.last_challenged,
            "strength": (support / total) if total else existing.strength,
            "confidence": min(1.0, (len(supporting) + len(counterexamples)) / 5.0),
            "status": _status_for(
                len(supporting), len(counterexamples),
                min_support=min_support, contested_ratio=contested_ratio,
            ),
        }
    )


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def consolidate_ledger(
    ledger: ChoiceLedgerEntry,
    *,
    kernel: Optional[AuthorKernel] = None,
    timestamp: str,
    min_support: int = 2,
    contested_ratio: float = 0.5,
    challenges: Optional[list] = None,
) -> ConsolidationResult:
    """把 ChoiceLedger 压缩进 AuthorKernel（4A/4B），并输出 Growth/Drift 信号（4C）.

    禁止 3：内核必须从台账压缩出来，不接受人工创建的原则输入。
    challenges：可选 open KernelChallenge 列表，作为反例证据并入（Author Drift
    Review → Consolidation 闭环，§43 Growth）。
    """
    evidence = extract_evidence(ledger, challenges=challenges)
    touched = sorted(evidence)

    # 先克隆既有内核（无则新建空内核）
    new_kernel = (
        kernel.model_copy(deep=True)
        if kernel is not None
        else AuthorKernel(kernel_id="kernel_auto")
    )

    new_principles: list[str] = []
    reinforced: list[str] = []
    challenged: list[dict] = []
    growth: list[dict] = []

    for key in touched:
        ev = evidence[key]
        existing = _find_principle(new_kernel, key)
        status_before = existing.status if existing else None
        counter_before = len(existing.counterexamples) if existing else 0
        status_after = "candidate"
        if existing is None:
            principle = _build_principle(
                key, ev, timestamp=timestamp, min_support=min_support,
                contested_ratio=contested_ratio,
            )
            _attach_principle(new_kernel, principle)
            status_after = principle.status
            if principle.supporting_choices:
                new_principles.append(key)
        else:
            principle = _build_principle(
                key, ev, timestamp=timestamp, min_support=min_support,
                contested_ratio=contested_ratio, existing=existing,
            )
            _replace_principle(new_kernel, principle)
            status_after = principle.status
            if principle.supporting_choices:
                reinforced.append(key)
            # 挑战检测：反例增长 → 原则被历史挑战
            if len(principle.counterexamples) > counter_before:
                reason = (
                    f"反例增长 {counter_before}→{len(principle.counterexamples)}，"
                    f"状态 {status_before}→{status_after}"
                )
                challenged.append(
                    {
                        "vocab_key": key,
                        "counterexamples": principle.counterexamples,
                        "status_before": status_before,
                        "status_after": status_after,
                        "reason": reason,
                    }
                )
                # Growth：有历史反例但原则仍成立 → 张力显式化（允许）
                if principle.supporting_choices:
                    growth.append(
                        {
                            "vocab_key": key,
                            "description": VALUE_VOCAB_DESCRIPTIONS.get(key, key),
                            "reason": (
                                "长期反例 → 张力 → 原则仍成立但被挑战，进入重新解释路径"
                            ),
                        }
                    )

    # Drift 检测（§43 要防）：旧原则强度骤降，但该价值键本轮无任何新选择触及
    drift: list[dict] = detect_drift(kernel, new_kernel, set(touched))

    # 触达键即使无支持也不丢弃（新内核至少把它们列为 candidate，信息不丢失）
    for key in touched:
        if not _find_principle(new_kernel, key):
            principle = _build_principle(
                key, evidence[key], timestamp=timestamp,
                min_support=min_support, contested_ratio=contested_ratio,
            )
            _attach_principle(new_kernel, principle)

    new_kernel.last_consolidation = timestamp
    summary = (
        f"合并 {len(ledger.choices)} 条选择 → 触达 {len(touched)} 价值键，"
        f"新原则 {len(new_principles)}，强化 {len(reinforced)}，"
        f"挑战 {len(challenged)}，growth {len(growth)}，drift {len(drift)}"
    )
    return ConsolidationResult(
        kernel=new_kernel,
        new_principles=new_principles,
        reinforced_principles=reinforced,
        challenged_principles=challenged,
        growth_signals=growth,
        drift_signals=drift,
        touched_keys=touched,
        summary=summary,
    )


def _find_principle(kernel: AuthorKernel, vocab_key: str) -> Optional[AuthorPrinciple]:
    for p in kernel.all_principles():
        if p.vocab_key == vocab_key:
            return p
    return None


def _attach_principle(kernel: AuthorKernel, principle: AuthorPrinciple) -> None:
    field = _category_field(principle.category)
    getattr(kernel, field).append(principle)


def _replace_principle(kernel: AuthorKernel, principle: AuthorPrinciple) -> None:
    field = _category_field(principle.category)
    lst = getattr(kernel, field)
    for i, p in enumerate(lst):
        if p.vocab_key == principle.vocab_key:
            lst[i] = principle
            return
    lst.append(principle)


def _category_field(category: str) -> str:
    return {
        "value": "values",
        "prohibition": "prohibitions",
        "commitment": "commitments",
        "tension": "tensions",
        "attention_bias": "attention_biases",
        "interpretive_bias": "interpretive_biases",
    }[category]


def detect_drift(
    previous_kernel: Optional[AuthorKernel],
    new_kernel: AuthorKernel,
    touched_keys: set[str],
    threshold: float = 0.3,
) -> list[dict]:
    """Drift 检测（§43 要防）：无因果经历的突变.

    若某稳定/弱原则强度骤降（>threshold），但该价值键本轮没有任何新选择触及
    （touched_keys 不含它），说明变化没有因果来源——无意识漂移。返回信号列表；
    consolidation 本身从不产生 drift（只改被证据触及的键），此函数主要防御
    外部对内核的篡改/异常。
    """
    if previous_kernel is None:
        return []
    signals: list[dict] = []
    for old in previous_kernel.all_principles():
        if old.status not in ("stable", "weak"):
            continue
        if old.vocab_key in touched_keys:
            continue  # 本轮有因果经历，不算无因果突变
        new_p = _find_principle(new_kernel, old.vocab_key)
        if new_p is None:
            continue
        if new_p.strength < old.strength - threshold:
            signals.append(
                {
                    "vocab_key": old.vocab_key,
                    "description": VALUE_VOCAB_DESCRIPTIONS.get(old.vocab_key, old.vocab_key),
                    "reason": (
                        f"强度 {old.strength:.2f}→{new_p.strength:.2f}，"
                        f"但本轮无新选择触及该价值"
                    ),
                }
            )
    return signals


def render_consolidation_report(result: ConsolidationResult) -> str:
    """人类可读的 Consolidation 报告（CLI 打印用）."""
    lines = [f"Consolidation: {result.summary}"]
    if result.new_principles:
        lines.append("新形成原则:")
        for key in result.new_principles:
            lines.append(f"  - {VALUE_VOCAB_DESCRIPTIONS.get(key, key)} [{key}]")
    if result.reinforced_principles:
        lines.append("被强化原则: " + ", ".join(
            VALUE_VOCAB_DESCRIPTIONS.get(k, k) for k in result.reinforced_principles
        ))
    for c in result.challenged_principles:
        lines.append(
            f"被挑战[{c['vocab_key']}] {c['status_before']}→{c['status_after']}: {c['reason']}"
        )
    for g in result.growth_signals:
        lines.append(f"Growth（允许）[{g['vocab_key']}]: {g['reason']}")
    for d in result.drift_signals:
        lines.append(f"Drift（要防）[{d['vocab_key']}]: {d['reason']}")
    return "\n".join(lines)
