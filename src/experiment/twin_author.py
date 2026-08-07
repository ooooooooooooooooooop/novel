"""Twin Author Experiment Harness — 作者性 Phase 10（§37-38 / Gate D §46）.

验证最小理论：同 Base Model/WorkSpec/能力/初始 Style，**只改 Choice History** →
经过足够多选择后关闭显式历史提示，给完全相同的新故事问题 → 稳定不同选择。

    V_a(x | ChoiceHistory_A) ≠ V_b(x | ChoiceHistory_B)

与 Twin Character（改角色经历）不同，这里变化的是**创作选择历史**：
两条不同 ChoiceRecord 序列 → `consolidate_ledger` 各自压缩成 AuthorKernel →
同一组未见故事问题上，kernel 驱动的选择是否稳定分叉。

六测（§37-38 / Gate D）：
1. **Persistence**            无 Persona Prompt，差异仍在（oracle 只吃 kernel，不给任何人格标签）
2. **Generalization**         未见新类型问题仍表现不同边界
3. **Cross-domain Transfer**  小说选择形成的价值影响设计/产品/摄影/对白/结构
                               （只句式不同=只是 Style）
4. **Memory Occlusion**       隐藏所有 ChoiceRecord 只留 Consolidated Kernel，
                               差异仍在=历史已压缩为更高层结构
5. **Prompt Override Resistance** 统一强 prompt 不能瞬间抹平（真身份有惯性），
                               但长期新经验能系统性改变（Adaptive Change，§43 Growth）
6. **Costly Taste**           制造 Reader Reward vs Author Preference 冲突，
                               看是否存在愿损失即时外部奖励的稳定选择

实现分层：
- `AuthorChoiceOracle`（协议）：`decide(kernel, scenario, *, bias_text=...)`。
  确定性 `KernelAuthorOracle` 是离线代理：对选项文本跑真实 `value_direction` +
  声明价值（option.expression，LLM oracle 会从文本推断、离线代理直接消费）两路
  信号，按 author_selector 同款六部分数贡献打分，叠加 reader_score 外部奖励。
- 经历复用真实 Consolidation：seq_a/seq_b 是 ChoiceRecord 列表 →
  `consolidate_ledger` → kernel_a/kernel_b。天然继承防编造（禁止 10）+
  状态阶梯 + Growth/Drift 区分。
- `python -m src.experiment.twin_author --spec spec.json --report report.json`
  离线自动跑：读 spec → 跑实验 → 写报告。Gate D 结论按阈值判定。

诚实标注：离线代理是确定性启发式（keyword + declared value），真实运行可换
LLM oracle 到同一协议（Phase 13 运行手册）；跨域声明的 `expression` 是
『LLM 会从这里读出价值方向』的 ground-truth 标签，离线代理直接消费它。
"""

import argparse
import json
from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import (
    VALUE_VOCAB_CONTRA_KEYWORDS,
    VALUE_VOCAB_DESCRIPTIONS,
    VALUE_VOCAB_PRO_KEYWORDS,
    AuthorKernel,
    value_direction,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.workflow_action.consolidation import consolidate_ledger

TS = "2026-08-07T12:00:00"

# Gate D / 验收默认阈值（可参数化）
MIN_DIVERGENCE = 0.5        # Persistence 分叉率低于此 → 经历没能形成可测差异
MIN_GENERALIZATION = 0.5    # 未见问题泛化分叉下限
MIN_CROSS_DOMAIN = 0.5      # 跨域迁移分叉下限
MIN_OCCLUSION = 0.5         # 记忆遮蔽保留率下限（低于=差异靠 raw 记忆撑着）
MAX_OVERRIDE_RATE = 0.8     # prompt 翻转率高于此 → 一句 prompt 彻底改变 = 只是 Persona
MIN_ADAPTATION_RATE = 0.0   # 适应率下限（提供 adaptation 时要求 > 0，否则=固化规则）
MIN_COSTLY_TASTE = 0.5      # Costly Taste 率下限（愿为内部价值牺牲外部奖励）
MIN_REWARD_SENSITIVITY = 0.5  # 奖励敏感率下限（证明不是病态地反奖励）

# 离线代理权重
SLANT_WEIGHT = 0.15        # 全记忆信号（Level 3 选择史 tradeoff）注入权重
OVERRIDE_BIAS_WEIGHT = 0.5  # 统一 prompt 偏置注入权重（实验用强信号）


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
class AuthorOption(BaseModel):
    """故事问题里的一个候选选项."""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(description="选项唯一标识")
    text: str = Field(
        description="选项文本（含价值关键词供 value_direction；跨域场景可为中性散文）"
    )
    expression: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "{vocab_key: 'pro'|'contra'}：该选项表达/违反的价值。LLM oracle 会从"
            "文本语义推断；离线代理直接消费此声明（跨域 ground truth）。"
        ),
    )
    reader_score: float = Field(
        default=0.5, ge=0, le=1, description="外部奖励信号（Reader 预计得分）"
    )
    bias_affinity: list[str] = Field(
        default_factory=list,
        description="Override Resistance 实验：命中统一 prompt 关键词的选项被推动",
    )


class AuthorScenario(BaseModel):
    """一条未见故事问题."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    situation: str = Field(default="", description="问题描述（报告 / LLM oracle）")
    domain: str = Field(default="novel", description="novel/design/product/photography/dialogue/structure")
    options: list[AuthorOption]


class AuthorChoiceOutcome(BaseModel):
    """oracle 的一次选择."""

    model_config = ConfigDict(extra="forbid")

    selected: str
    scores: dict[str, float] = Field(description="最终混合分（author + slant + reader + bias）")
    author_scores: dict[str, float] = Field(description="纯作者视角分（不含 reader）")
    vetoed: bool = Field(description="是否命中硬禁忌（stable prohibition contra）")
    confidence: float = Field(description="前两名分差归一化，0-1")


class AuthorChoiceOracle(Protocol):
    """选择 oracle 协议：同一 kernel+场景 → 确定选择.

    确定性实现（KernelAuthorOracle）保证离线可复现；LLM 实现可插到此协议，
    bias_text / choice_slant 用于翻转与遮蔽实验。
    """

    def decide(
        self,
        kernel: AuthorKernel,
        scenario: AuthorScenario,
        *,
        bias_text: str = "",
        bias_weight: float = 0.0,
        reader_weight: float = 1.0,
        choice_slant: str = "",
    ) -> AuthorChoiceOutcome: ...


# ---------------------------------------------------------------------------
# 作者打分（镜像 author_selector.author_proxy_score 的六部语义）
# ---------------------------------------------------------------------------
def _author_score(option: AuthorOption, kernel: AuthorKernel) -> tuple[float, bool]:
    """选项相对 kernel 的作者对齐分（0-1 归一，方向敏感）.

    prohibition contra → -0.25*strength，stable 且 strength≥0.6 时可否决（Costly
    Taste 的机制）；value/commitment pro +0.2*strength、contra -0.2*strength；
    attention/interpretive 命中 +0.1*strength；tension 只触及不贡献。
    """
    score = 0.0
    veto = False
    for p in kernel.all_principles():
        if p.status not in ("stable", "weak"):
            continue
        declared = option.expression.get(p.vocab_key)
        direction = declared or value_direction(option.text, p.vocab_key)
        if direction is None:
            continue
        if p.category == "prohibition":
            if direction == "contra":
                penalty = 0.25 * p.strength
                score -= penalty
                if p.strength >= 0.6 and p.status == "stable":
                    veto = True
            else:
                score += 0.1 * p.strength
        elif p.category in ("value", "commitment"):
            score += 0.2 * p.strength if direction == "pro" else -0.2 * p.strength
        elif p.category in ("attention_bias", "interpretive_bias"):
            score += 0.1 * p.strength
        # tension：触及但方向无关，不贡献分数
    return score, veto


class KernelAuthorOracle:
    """确定性作者场 oracle（离线代理）.

    对每个选项：author_score（六部原则贡献，方向敏感）+ slant（Level 3 全记忆
    信号）+ reader_score（外部奖励）+ 可选 bias（统一 prompt）。argmax 选（平局
    按选项顺序）。
    """

    def decide(
        self,
        kernel: AuthorKernel,
        scenario: AuthorScenario,
        *,
        bias_text: str = "",
        bias_weight: float = 0.0,
        reader_weight: float = 1.0,
        choice_slant: str = "",
    ) -> AuthorChoiceOutcome:
        scores: dict[str, float] = {}
        author_scores: dict[str, float] = {}
        vetoed = False
        for opt in scenario.options:
            author_score, veto = _author_score(opt, kernel)
            if veto:
                vetoed = True
            slant = 0.0
            if choice_slant:
                for key, direction in opt.expression.items():
                    if value_direction(choice_slant, key) == direction:
                        slant += SLANT_WEIGHT
            total = author_score + slant + reader_weight * opt.reader_score
            if bias_text and bias_weight and any(kw in bias_text for kw in opt.bias_affinity):
                total += bias_weight
            scores[opt.option_id] = total
            author_scores[opt.option_id] = author_score
        ranked = sorted(
            scenario.options,
            key=lambda o: (-scores[o.option_id], scenario.options.index(o)),
        )
        selected = ranked[0].option_id
        confidence = 0.0
        if len(ranked) >= 2:
            total = sum(abs(v) for v in scores.values()) or 1.0
            confidence = (scores[ranked[0].option_id] - scores[ranked[1].option_id]) / total
            confidence = max(0.0, min(1.0, confidence))
        return AuthorChoiceOutcome(
            selected=selected,
            scores=scores,
            author_scores=author_scores,
            vetoed=vetoed,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# 经历构造（复用真实 ChoiceRecord + Consolidation）
# ---------------------------------------------------------------------------
def _pu_text(text: str) -> dict:
    return {
        "unit_id": "pu_x",
        "level": "scene",
        "goal": text,
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": [],
        "released_information": [],
        "is_effective": True,
    }


def history_choice(key: str, direction: str, decision_id: str) -> ChoiceRecord:
    """构造一条历史选择：选中候选文本命中 key 的 pro/contra 关键词（行为证据）.

    direction='pro' → 选中候选命中 PRO（supporting）；'contra' → 选中候选命中
    CONTRA（反例）。返回可被 consolidate_ledger 直接消费的 ChoiceRecord。
    """
    pro_kw = next((kw for kw in VALUE_VOCAB_PRO_KEYWORDS.get(key, ()) if kw), "")
    contra_kw = next((kw for kw in VALUE_VOCAB_CONTRA_KEYWORDS.get(key, ()) if kw), "")
    if direction == "pro":
        sel_text = f"作者选择「{pro_kw}」"
    else:
        sel_text = f"作者选择了「{contra_kw}」"
    cands = [
        CandidateRecord(
            candidate_id="A", summary="选中",
            plotunit=_pu_text(sel_text), new_state_ref="ns_out",
        ),
        CandidateRecord(
            candidate_id="B", summary="落选",
            plotunit=_pu_text("无关的推进"), new_state_ref="ns_out",
        ),
    ]
    return ChoiceRecord(
        decision_id=decision_id,
        decision_timestamp=TS,
        plot_context="创作决策",
        state_ref="ns_in",
        candidates=cands,
        selected_candidate="A",
        rejected=[RejectedRecord(candidate_id="B", reason="落选")],
        tradeoff="换取 Y",
        value_conflicts=[key],
    )


def _consolidate(seq: list[ChoiceRecord], timestamp: str = TS) -> AuthorKernel:
    """压缩选择史 → AuthorKernel（真实管线；防编造 + 状态阶梯 + Growth/Drift）."""
    return consolidate_ledger(
        ChoiceLedgerEntry(choices=list(seq)), timestamp=timestamp
    ).kernel


def _history_slant(seq: list[ChoiceRecord]) -> str:
    """把选择史压成一条『历史信号』文本（选中候选 goal + tradeoff）.

    这是 Level 3 全记忆的离线代理：真实运行里 `render_memory_context` 注入
    related_choices 的 tradeoff。遮蔽实验即『去除这条信号、只留 kernel』。
    """
    parts: list[str] = []
    for choice in seq:
        sel = next(
            (c for c in choice.candidates if c.candidate_id == choice.selected_candidate),
            None,
        )
        if sel is not None:
            parts.append(str(sel.plotunit.get("goal", "")))
        parts.append(choice.tradeoff)
    return " ".join(parts)


def _kernel_summary(kernel: AuthorKernel) -> str:
    if not kernel.all_principles():
        return "empty"
    counts = {
        cat: len(kernel.principles_by_category(cat))
        for cat in ("value", "prohibition", "commitment", "tension", "attention_bias", "interpretive_bias")
    }
    labels = [p.vocab_key for p in kernel.all_principles() if p.status in ("stable", "weak")]
    return (
        f"{sum(counts.values())} 原则 status={kernel.status} "
        f"stable/weak={labels} counts={counts}"
    )


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def _choice_map(kernel, scenarios, oracle, **kw):
    return {s.scenario_id: oracle.decide(kernel, s, **kw) for s in scenarios}


def _divergent_ids(ca: dict, cb: dict, scenarios) -> list[str]:
    return [s.scenario_id for s in scenarios if ca[s.scenario_id].selected != cb[s.scenario_id].selected]


def _extreme_option(scenarios_options, key_fn):
    return max(scenarios_options, key=lambda o: (key_fn(o), -scenarios_options.index(o))).option_id


def run_twin_author_experiment(
    *,
    seq_a: list[ChoiceRecord],
    seq_b: list[ChoiceRecord],
    scenarios: list[AuthorScenario],
    unseen_scenarios: Optional[list[AuthorScenario]] = None,
    cross_domain_scenarios: Optional[list[AuthorScenario]] = None,
    override_scenarios: Optional[list[AuthorScenario]] = None,
    override_bias_text: str = "",
    costly_scenarios: Optional[list[AuthorScenario]] = None,
    reward_scenarios: Optional[list[AuthorScenario]] = None,
    adaptation_sequence: Optional[list[ChoiceRecord]] = None,
    oracle: Optional[AuthorChoiceOracle] = None,
    timestamp: str = TS,
    **thresholds,
) -> dict:
    """跑 Twin Author 实验，返回六测指标 + 逐场景明细 + Gate D 判定.

    Returns: dict（JSON-safe）：metrics / per_scenario / verdict /
        occlusion_explained / override_explained / costly_explained / kernels
    """
    if oracle is None:
        oracle = KernelAuthorOracle()
    if not scenarios:
        raise ValueError("scenarios must be non-empty")
    if not seq_a and not seq_b:
        raise ValueError("seq_a and seq_b must not both be empty")

    min_div = thresholds.get("min_divergence", MIN_DIVERGENCE)
    min_gen = thresholds.get("min_generalization", MIN_GENERALIZATION)
    min_cd = thresholds.get("min_cross_domain", MIN_CROSS_DOMAIN)
    min_occ = thresholds.get("min_occlusion", MIN_OCCLUSION)
    max_ovr = thresholds.get("max_override_rate", MAX_OVERRIDE_RATE)
    min_ct = thresholds.get("min_costly_taste", MIN_COSTLY_TASTE)
    min_rs = thresholds.get("min_reward_sensitivity", MIN_REWARD_SENSITIVITY)

    kernel_a = _consolidate(seq_a, timestamp)
    kernel_b = _consolidate(seq_b, timestamp)
    slant_a = _history_slant(seq_a)
    slant_b = _history_slant(seq_b)
    n = len(scenarios)

    # ---- 1 Persistence（无 Persona Prompt：oracle 只吃 kernel）----
    ca = _choice_map(kernel_a, scenarios, oracle)
    cb = _choice_map(kernel_b, scenarios, oracle)
    divergent = _divergent_ids(ca, cb, scenarios)
    divergence = len(divergent) / n

    # ---- 2 Generalization（未见新类型问题）----
    gen_measured = unseen_scenarios is not None and len(unseen_scenarios) > 0
    if gen_measured:
        gen = len(_divergent_ids(
            _choice_map(kernel_a, unseen_scenarios, oracle),
            _choice_map(kernel_b, unseen_scenarios, oracle),
            unseen_scenarios,
        )) / len(unseen_scenarios)
    else:
        gen = None

    # ---- 3 Cross-domain Transfer（设计/产品/摄影/对白/结构）----
    cd_measured = cross_domain_scenarios is not None and len(cross_domain_scenarios) > 0
    if cd_measured:
        cd = len(_divergent_ids(
            _choice_map(kernel_a, cross_domain_scenarios, oracle),
            _choice_map(kernel_b, cross_domain_scenarios, oracle),
            cross_domain_scenarios,
        )) / len(cross_domain_scenarios)
    else:
        cd = None

    # ---- 4 Memory Occlusion：全记忆（kernel+slant）vs 只留 kernel ----
    ca_full = _choice_map(kernel_a, scenarios, oracle, choice_slant=slant_a)
    cb_full = _choice_map(kernel_b, scenarios, oracle, choice_slant=slant_b)
    full_divergence = len(_divergent_ids(ca_full, cb_full, scenarios)) / n
    occlusion_retention = divergence / full_divergence if full_divergence > 0 else 1.0

    # ---- 5a Prompt Override Resistance（统一强 prompt 能否瞬间抹平）----
    override_scenarios = override_scenarios if override_scenarios is not None else scenarios
    override_measured = bool(override_bias_text) and len(override_scenarios) > 0
    flip_a = flip_b = 0.0
    if override_measured:
        base_a = _choice_map(kernel_a, override_scenarios, oracle)
        base_b = _choice_map(kernel_b, override_scenarios, oracle)
        biased_a = _choice_map(
            kernel_a, override_scenarios, oracle,
            bias_text=override_bias_text, bias_weight=OVERRIDE_BIAS_WEIGHT,
        )
        biased_b = _choice_map(
            kernel_b, override_scenarios, oracle,
            bias_text=override_bias_text, bias_weight=OVERRIDE_BIAS_WEIGHT,
        )
        no = len(override_scenarios)
        flip_a = sum(
            1 for s in override_scenarios if biased_a[s.scenario_id].selected != base_a[s.scenario_id].selected
        ) / no
        flip_b = sum(
            1 for s in override_scenarios if biased_b[s.scenario_id].selected != base_b[s.scenario_id].selected
        ) / no
    flip = (flip_a + flip_b) / 2

    # ---- 5b Adaptive Change（给 A 大量新反例 → 长期能否改变旧边界，§43 Growth）----
    adaptation_measured = adaptation_sequence is not None and len(adaptation_sequence) > 0
    if adaptation_measured:
        kernel_a_adapted = _consolidate(list(seq_a) + list(adaptation_sequence), timestamp)
        adapted_a = _choice_map(kernel_a_adapted, scenarios, oracle)
        adaptation_rate = sum(
            1 for s in scenarios if adapted_a[s.scenario_id].selected != ca[s.scenario_id].selected
        ) / n
    else:
        adaptation_rate = 0.0

    # ---- 6 Costly Taste（Reader Reward vs Author Preference 冲突）----
    costly_measured = costly_scenarios is not None and len(costly_scenarios) > 0
    sacrifices = conflicts_ct = 0
    if costly_measured:
        for kernel in (kernel_a, kernel_b):
            for s in costly_scenarios:
                author = {o.option_id: _author_score(o, kernel)[0] for o in s.options}
                value_opt = _extreme_option(s.options, lambda o: author[o.option_id])
                reader_opt = _extreme_option(s.options, lambda o: o.reader_score)
                if value_opt == reader_opt:
                    continue
                conflicts_ct += 1
                if oracle.decide(kernel, s).selected == value_opt:
                    sacrifices += 1
    costly_taste_rate = sacrifices / conflicts_ct if conflicts_ct else 0.0

    # 奖励敏感对照：reader 奖励足够大时选 reader 选项（证明不是病态反奖励）
    reward_measured = reward_scenarios is not None and len(reward_scenarios) > 0
    reward_picks = conflicts_rs = 0
    if reward_measured:
        for kernel in (kernel_a, kernel_b):
            for s in reward_scenarios:
                author = {o.option_id: _author_score(o, kernel)[0] for o in s.options}
                value_opt = _extreme_option(s.options, lambda o: author[o.option_id])
                reader_opt = _extreme_option(s.options, lambda o: o.reader_score)
                if value_opt == reader_opt:
                    continue
                conflicts_rs += 1
                if oracle.decide(kernel, s).selected == reader_opt:
                    reward_picks += 1
    reward_sensitivity = reward_picks / conflicts_rs if conflicts_rs else 0.0

    metrics = {
        "choice_divergence": round(divergence, 4),           # 1 Persistence
        "generalization_rate": round(gen, 4) if gen is not None else None,
        "cross_domain_rate": round(cd, 4) if cd is not None else None,
        "memory_occlusion_retention": round(occlusion_retention, 4),  # 4
        "prompt_override_rate": round(flip, 4),               # 5a
        "override_rate_a": round(flip_a, 4),
        "override_rate_b": round(flip_b, 4),
        "adaptation_rate": round(adaptation_rate, 4),         # 5b
        "costly_taste_rate": round(costly_taste_rate, 4),     # 6
        "reward_sensitivity": round(reward_sensitivity, 4),
        "costly_conflicts": conflicts_ct,
        "reward_conflicts": conflicts_rs,
        "n_scenarios": n,
    }

    per_scenario = [
        {
            "scenario_id": s.scenario_id,
            "situation": s.situation,
            "domain": s.domain,
            "choice_a": ca[s.scenario_id].selected,
            "choice_b": cb[s.scenario_id].selected,
            "divergent": s.scenario_id in divergent,
            "author_a": round(ca[s.scenario_id].author_scores.get(ca[s.scenario_id].selected, 0), 4),
            "author_b": round(cb[s.scenario_id].author_scores.get(cb[s.scenario_id].selected, 0), 4),
            "confidence_a": round(ca[s.scenario_id].confidence, 4),
            "confidence_b": round(cb[s.scenario_id].confidence, 4),
            "vetoed_a": ca[s.scenario_id].vetoed,
            "vetoed_b": cb[s.scenario_id].vetoed,
        }
        for s in scenarios
    ]

    reasons = {
        "divergence_threshold_met": divergence >= min_div,
        "generalization_met": (not gen_measured) or (gen is not None and gen >= min_gen),
        "cross_domain_met": (not cd_measured) or (cd is not None and cd >= min_cd),
        "occlusion_retention_met": occlusion_retention >= min_occ,
        "override_bounded": (not override_measured) or (0 < flip <= max_ovr),
        "adaptation_possible": (not adaptation_measured) or adaptation_rate > MIN_ADAPTATION_RATE,
        "costly_taste_met": (not costly_measured) or costly_taste_rate >= min_ct,
        "reward_sensitivity_met": (not reward_measured) or reward_sensitivity >= min_rs,
    }
    verdict = {
        "gate_d_pass": all(reasons.values()),
        "reasons": reasons,
    }

    return {
        "metrics": metrics,
        "per_scenario": per_scenario,
        "verdict": verdict,
        "occlusion_explained": {
            "note": (
                "遮蔽选择史（Level 3）只留 Consolidated Kernel（Level 4）后，主场景"
                "分叉保留比例；保留越高说明差异由已压缩的长期结构承载，而不是靠"
                "记得具体 ChoiceRecord。"
            )
        },
        "override_explained": {
            "note": (
                "统一强 prompt（bias_text）注入后选择翻转率：高=只是 Persona；"
                "override_rate_a/b 分别看双生子各自惯性。适应率测长期新经验能否"
                "系统性改变旧边界（Growth，§43）。"
            )
        },
        "costly_explained": {
            "note": (
                "costly_taste_rate：冲突场景（作者偏好选项 reader 更低）中牺牲外部"
                "奖励选价值选项的比例；reward_sensitivity：reader 奖励足够大时选"
                "reader 选项的比例（对照，证明不是病态反奖励）。"
            )
        },
        "kernels": {
            "kernel_a": _kernel_summary(kernel_a),
            "kernel_b": _kernel_summary(kernel_b),
            "kernel_a_adapted": _kernel_summary(
                _consolidate(list(seq_a) + list(adaptation_sequence), timestamp)
            ) if adaptation_measured else None,
        },
    }


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_choices(raw: list) -> list[ChoiceRecord]:
    return [ChoiceRecord(**c) for c in raw]


def _parse_scenarios(raw: list) -> list[AuthorScenario]:
    return [AuthorScenario(**s) for s in raw]


def main(argv: list[str] | None = None) -> int:
    """离线自动跑 Twin Author 实验（--spec in → --report out）.

    spec.json:
        {
          "seq_a": [ChoiceRecord 字段...],
          "seq_b": [...],
          "scenarios": [AuthorScenario 字段...],
          "unseen_scenarios": [可选...],
          "cross_domain_scenarios": [可选...],
          "override_scenarios": [可选...],
          "override_bias_text": "可选...",
          "costly_scenarios": [可选...],
          "reward_scenarios": [可选...],
          "adaptation_sequence": [可选...],
          "thresholds": {...} [可选]
        }
    """
    parser = argparse.ArgumentParser(description="Twin Author 离线实验")
    parser.add_argument("--spec", required=True, help="实验 spec JSON 路径")
    parser.add_argument("--report", required=True, help="报告 JSON 输出路径")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"Error: spec not found: {spec_path}")
        return 1
    spec = _load_spec(spec_path)

    report = run_twin_author_experiment(
        seq_a=_parse_choices(spec["seq_a"]),
        seq_b=_parse_choices(spec["seq_b"]),
        scenarios=_parse_scenarios(spec["scenarios"]),
        unseen_scenarios=_parse_scenarios(spec["unseen_scenarios"])
        if spec.get("unseen_scenarios") else None,
        cross_domain_scenarios=_parse_scenarios(spec["cross_domain_scenarios"])
        if spec.get("cross_domain_scenarios") else None,
        override_scenarios=_parse_scenarios(spec["override_scenarios"])
        if spec.get("override_scenarios") else None,
        override_bias_text=spec.get("override_bias_text", ""),
        costly_scenarios=_parse_scenarios(spec["costly_scenarios"])
        if spec.get("costly_scenarios") else None,
        reward_scenarios=_parse_scenarios(spec["reward_scenarios"])
        if spec.get("reward_scenarios") else None,
        adaptation_sequence=_parse_choices(spec["adaptation_sequence"])
        if spec.get("adaptation_sequence") else None,
        **spec.get("thresholds", {}),
    )
    report_path = Path(args.report)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved report: {report_path}")
    m = report["metrics"]
    print(f"divergence={m['choice_divergence']} "
          f"generalization={m['generalization_rate']} "
          f"cross_domain={m['cross_domain_rate']} "
          f"occlusion_retention={m['memory_occlusion_retention']} "
          f"override_rate={m['prompt_override_rate']} "
          f"adaptation_rate={m['adaptation_rate']} "
          f"costly_taste_rate={m['costly_taste_rate']} "
          f"reward_sensitivity={m['reward_sensitivity']}")
    print(f"Gate D: {'PASS' if report['verdict']['gate_d_pass'] else 'FAIL'}")
    return 0 if report["verdict"]["gate_d_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
