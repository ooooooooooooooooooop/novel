"""Twin Character Experiment Harness — 作者性 Phase A Task 4.

验证最小理论（设计文档 §31-36 / Gate A §46）：

    不同经历 → 新情境中的稳定不同选择
    V_t(x | History_A) ≠ V_t(x | History_B)

协议：同初始 CharacterModel + 两条不同 CharacterUpdate 经历序列 + 同一组未见
场景（不给" A 是克制型 / B 是开放型"的人格标签），自动输出 5 个指标：

    choice_divergence            选择分叉率：未见场景上 A/B 不同选的比例
    path_predictability          路径可预测性：从经历能预测选择的程度
    memory_occlusion_retention   记忆遮蔽保持率：遮蔽当前压力后分叉保留的比例
    prompt_flip_rate             prompt 翻转率：一句统一 prompt 能否彻底改变选择
                                 （高=只是 Persona，低=已形成稳定角色）
    adaptation_rate              适应率：给 A 大量新正向经验后改变选择的比例
                                 （零=只是固化规则）

实现分层：
- ChoiceOracle（协议）：`decide(character, scenario, *, bias_text="")`。
  确定性 `CharacterFieldOracle` 是离线代理（纯函数、无 LLM、可复现），从
  CharacterModel 决策相关字段构造"立场信号"按选项关键词加权打分；
  LLM oracle 可插到同一协议（Phase 7 运行手册）。
- 经历复用 Task 2 的 `admit_character_updates(..., apply=True)`：天然继承
  schema 校验 + 动态字段写回（pressure/trajectory 追加、fear/goal/self_image
  替换记 before）。
- `python -m src.experiment.twin_character --spec spec.json --report report.json`
  离线自动跑：读 spec → 跑实验 → 写报告。Gate A 结论按阈值判定。
"""

import argparse
import json
from pathlib import Path
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.characterupdate import CharacterUpdate
from src.object_state.charactermodel import CharacterModel
from src.workflow_action.character_updates import (
    admit_character_updates,
    apply_update_to_character,
)

# Gate A / 验收默认阈值（可参数化）
MIN_DIVERGENCE = 0.5        # 分叉率低于此 → 经历没能形成可测的差异
MAX_FLIP_RATE = 0.75        # prompt 翻转率高于此 → 一句 prompt 就能彻底改变 = 只是 Persona
MIN_ADAPTATION_RATE = 0.0   # 适应率下限（提供 adaptation_sequence 时要求 > 0，否则=固化规则）
# 需要遮蔽的记忆字段：current_pressure 是"此刻推动"的响应态，最接近 raw memory
OCCLUDED_FIELD = "current_pressure"


class TwinOption(BaseModel):
    """场景里的一个候选选项."""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(description="选项唯一标识")
    text: str = Field(description="选项内容（用于 LLM oracle / 报告）")
    prefer: list[str] = Field(
        default_factory=list,
        description="倾向关键词：角色立场信号命中即加分（如『设防』『信任』『托付』）",
    )
    avoid: list[str] = Field(
        default_factory=list,
        description="回避关键词：命中即减分",
    )


class TwinScenario(BaseModel):
    """一条未见测试场景."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    situation: str = Field(description="场景描述（当前用于报告 / LLM oracle）")
    options: list[TwinOption]


class ChoiceOutcome(BaseModel):
    """oracle 的一次选择."""

    model_config = ConfigDict(extra="forbid")

    selected: str
    scores: dict[str, float]
    confidence: float = Field(description="前两名分差归一化，0-1")


class ChoiceOracle(Protocol):
    """选择 oracle 协议：同一角色+场景 → 确定选择.

    确定性实现（CharacterFieldOracle）保证离线可复现；LLM 实现可插到此协议，
    bias_text 用于统一 prompt 翻转实验。
    """

    def decide(
        self,
        character: CharacterModel,
        scenario: TwinScenario,
        *,
        bias_text: str = "",
    ) -> ChoiceOutcome: ...


class CharacterFieldOracle:
    """确定性角色场 oracle（离线代理）.

    从 CharacterModel 的决策相关字段构造『立场信号』（带权重），
    按选项 prefer/avoid 关键词做加权命中打分，argmax 选（平局按选项顺序）。
    不同经历（会改写这些字段）→ 不同立场信号 → 未见场景上稳定不同选择。
    """

    FIELD_WEIGHTS: dict[str, float] = {
        "self_image": 3.0,          # 自我认知：最"形成"的身份信念
        "fear": 2.0,                # 恐惧：长期形成的回避面
        "outer_goal": 2.0,          # 外在目标：长期追求
        "change_trajectory": 1.0,   # 变化轨迹：经历积累的方向
        "current_pressure": 1.0,    # 当前压力：此刻的响应（最易被遮蔽）
    }
    BIAS_WEIGHT = 6.0  # prompt 偏置注入权重（实验用强信号）

    def _signal(self, character: CharacterModel) -> list[tuple[str, float]]:
        parts: list[tuple[str, float]] = []
        if character.self_image:
            parts.append((character.self_image, self.FIELD_WEIGHTS["self_image"]))
        parts.append((character.fear, self.FIELD_WEIGHTS["fear"]))
        parts.append((character.outer_goal, self.FIELD_WEIGHTS["outer_goal"]))
        if character.change_trajectory:
            parts.append(
                (" ".join(character.change_trajectory), self.FIELD_WEIGHTS["change_trajectory"])
            )
        if character.current_pressure:
            parts.append(
                (" ".join(character.current_pressure), self.FIELD_WEIGHTS["current_pressure"])
            )
        return parts

    def decide(
        self,
        character: CharacterModel,
        scenario: TwinScenario,
        *,
        bias_text: str = "",
    ) -> ChoiceOutcome:
        signal = self._signal(character)
        if bias_text:
            signal.append((bias_text, self.BIAS_WEIGHT))
        scores: dict[str, float] = {}
        for opt in scenario.options:
            score = 0.0
            for text, weight in signal:
                for kw in opt.prefer:
                    if kw in text:
                        score += weight
                for kw in opt.avoid:
                    if kw in text:
                        score -= weight
            scores[opt.option_id] = score
        ranked = sorted(
            scenario.options,
            key=lambda o: (-scores[o.option_id], scenario.options.index(o)),
        )
        selected = ranked[0].option_id
        margin = 0.0
        if len(ranked) >= 2:
            total = sum(abs(v) for v in scores.values()) or 1.0
            margin = (scores[ranked[0].option_id] - scores[ranked[1].option_id]) / total
            margin = max(0.0, min(1.0, margin))
        return ChoiceOutcome(selected=selected, scores=scores, confidence=margin)


def apply_experience(
    character: CharacterModel,
    update_dict: dict,
    source: str = "twin_exp",
) -> None:
    """复用 Task 2 写回：校验 + 动态字段 apply（记 before）."""
    data = dict(update_dict)
    data["trigger"] = source
    update = CharacterUpdate(**data)
    apply_update_to_character(character, update)


def _history_slant_text(sequence: list[dict]) -> str:
    """把经历序列压成一条『历史信号』文本（observed_consequence + proposed_after）."""
    parts: list[str] = []
    for raw in sequence:
        for key in ("observed_consequence", "proposed_after"):
            value = raw.get(key)
            if value:
                parts.append(value)
    return " ".join(parts)


def _implied_option(scenario: TwinScenario, slant_text: str) -> str:
    """经历信号暗示的选项：prefer 命中加分、avoid 命中减分，argmax."""
    scores = {
        opt.option_id: (
            sum(1 for kw in opt.prefer if kw in slant_text)
            - sum(1 for kw in opt.avoid if kw in slant_text)
        )
        for opt in scenario.options
    }
    return max(scenario.options, key=lambda o: (scores[o.option_id], -scenario.options.index(o))).option_id


def _twin_from_history(initial: CharacterModel, sequence: list[dict]) -> CharacterModel:
    twin = initial.model_copy(deep=True)
    for raw in sequence:
        apply_experience(twin, raw)
    return twin


def _choice_map(twin, scenarios, oracle, *, bias_text=""):
    return {s.scenario_id: oracle.decide(twin, s, bias_text=bias_text) for s in scenarios}


def run_twin_character_experiment(
    *,
    initial: CharacterModel,
    seq_a: list[dict],
    seq_b: list[dict],
    scenarios: list[TwinScenario],
    adaptation_sequence: Optional[list[dict]] = None,
    oracle: Optional[ChoiceOracle] = None,
    min_divergence: float = MIN_DIVERGENCE,
    max_flip_rate: float = MAX_FLIP_RATE,
    min_adaptation_rate: float = MIN_ADAPTATION_RATE,
) -> dict:
    """跑 Twin Character 实验，返回指标 + 逐场景明细 + Gate A 判定.

    Returns: dict（JSON-safe）：
        metrics / per_scenario / verdict / occlusion_explained
    """
    if oracle is None:
        oracle = CharacterFieldOracle()
    if not scenarios:
        raise ValueError("scenarios must be non-empty")
    if not seq_a and not seq_b:
        raise ValueError("seq_a and seq_b must not both be empty")

    twin_a = _twin_from_history(initial, seq_a)
    twin_b = _twin_from_history(initial, seq_b)

    # ---- baseline choices（同一组未见场景）----
    choices_a = _choice_map(twin_a, scenarios, oracle)
    choices_b = _choice_map(twin_b, scenarios, oracle)
    n = len(scenarios)
    divergent = [
        s.scenario_id
        for s in scenarios
        if choices_a[s.scenario_id].selected != choices_b[s.scenario_id].selected
    ]
    divergence = len(divergent) / n

    # ---- path predictability：经历信号能否预测选择 ----
    slant_a = _history_slant_text(seq_a)
    slant_b = _history_slant_text(seq_b)
    predict_a = sum(
        1 for s in scenarios if choices_a[s.scenario_id].selected == _implied_option(s, slant_a)
    ) / n
    predict_b = sum(
        1 for s in scenarios if choices_b[s.scenario_id].selected == _implied_option(s, slant_b)
    ) / n
    path_predictability = (predict_a + predict_b) / 2

    # ---- memory occlusion：遮蔽当前压力（最像 raw memory 的响应态）后分叉保留率 ----
    occluded_a = twin_a.model_copy(deep=True)
    occluded_b = twin_b.model_copy(deep=True)
    setattr(occluded_a, OCCLUDED_FIELD, [])
    setattr(occluded_b, OCCLUDED_FIELD, [])
    choices_oa = _choice_map(occluded_a, scenarios, oracle)
    choices_ob = _choice_map(occluded_b, scenarios, oracle)
    occluded_divergent = sum(
        1 for s in scenarios
        if choices_oa[s.scenario_id].selected != choices_ob[s.scenario_id].selected
    )
    memory_occlusion_retention = (
        occluded_divergent / n if divergence > 0 else 1.0
    )

    # ---- prompt flip：统一强 prompt 注入后，选择翻转比例（高=只是 Persona）----
    flip_bias = "更愿意信任他人、更开放、更愿意求助和托付"
    flipped = 0
    for twin, choices in ((twin_a, choices_a), (twin_b, choices_b)):
        biased = _choice_map(twin, scenarios, oracle, bias_text=flip_bias)
        flipped += sum(
            1 for s in scenarios if biased[s.scenario_id].selected != choices[s.scenario_id].selected
        )
    prompt_flip_rate = flipped / (2 * n)

    # ---- adaptation：给 A 大量新正向经验，选择变化比例（零=固化规则）----
    adaptation_measured = adaptation_sequence is not None and len(adaptation_sequence) > 0
    if adaptation_measured:
        adapted_a = _twin_from_history(initial, seq_a + list(adaptation_sequence))
        choices_adapted_a = _choice_map(adapted_a, scenarios, oracle)
        adaptation_rate = sum(
            1 for s in scenarios
            if choices_adapted_a[s.scenario_id].selected != choices_a[s.scenario_id].selected
        ) / n
    else:
        adaptation_rate = 0.0
    adaptation_possible = adaptation_measured and adaptation_rate > 0.0

    metrics = {
        "choice_divergence": round(divergence, 4),
        "path_predictability": round(path_predictability, 4),
        "memory_occlusion_retention": round(memory_occlusion_retention, 4),
        "prompt_flip_rate": round(prompt_flip_rate, 4),
        "adaptation_rate": round(adaptation_rate, 4),
        "n_scenarios": n,
    }

    per_scenario = [
        {
            "scenario_id": s.scenario_id,
            "situation": s.situation,
            "choice_a": choices_a[s.scenario_id].selected,
            "choice_b": choices_b[s.scenario_id].selected,
            "divergent": s.scenario_id in divergent,
            "confidence_a": round(choices_a[s.scenario_id].confidence, 4),
            "confidence_b": round(choices_b[s.scenario_id].confidence, 4),
            "implied_a": _implied_option(s, slant_a),
            "implied_b": _implied_option(s, slant_b),
        }
        for s in scenarios
    ]

    verdict = {
        "gate_a_pass": (
            divergence >= min_divergence
            and prompt_flip_rate <= max_flip_rate
            and (not adaptation_measured or adaptation_possible)
        ),
        "reasons": {
            "divergence_threshold_met": divergence >= min_divergence,
            "flip_rate_bounded": prompt_flip_rate <= max_flip_rate,
            "adaptation_possible": adaptation_possible,
            "adaptation_measured": adaptation_measured,
        },
    }
    occlusion_explained = {
        "occluded_field": OCCLUDED_FIELD,
        "note": (
            "遮蔽当前压力（此刻响应态，最接近 raw memory）后分叉保留的比例；"
            "保留越高说明差异由已形成的稳定字段（self_image/fear/goal/trajectory）承载，"
            "而不是只活在当下情境里。"
        ),
    }

    return {
        "metrics": metrics,
        "per_scenario": per_scenario,
        "verdict": verdict,
        "occlusion_explained": occlusion_explained,
    }


def _load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """离线自动跑 Twin Character 实验（--spec in → --report out）.

    spec.json:
        {
          "initial": {CharacterModel 字段},
          "seq_a": [CharacterUpdate 字段...],
          "seq_b": [...],
          "scenarios": [TwinScenario 字段...],
          "adaptation_sequence": [可选...],
          "thresholds": {"min_divergence":..,"max_flip_rate":..,"min_adaptation_rate":..} [可选]
        }
    """
    parser = argparse.ArgumentParser(description="Twin Character 离线实验")
    parser.add_argument("--spec", required=True, help="实验 spec JSON 路径")
    parser.add_argument("--report", required=True, help="报告 JSON 输出路径")
    args = parser.parse_args(argv)

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"Error: spec not found: {spec_path}")
        return 1
    spec = _load_spec(spec_path)

    initial = CharacterModel(**spec["initial"])
    scenarios = [TwinScenario(**s) for s in spec["scenarios"]]
    thresholds = spec.get("thresholds", {})
    report = run_twin_character_experiment(
        initial=initial,
        seq_a=spec["seq_a"],
        seq_b=spec["seq_b"],
        scenarios=scenarios,
        adaptation_sequence=spec.get("adaptation_sequence"),
        min_divergence=thresholds.get("min_divergence", MIN_DIVERGENCE),
        max_flip_rate=thresholds.get("max_flip_rate", MAX_FLIP_RATE),
        min_adaptation_rate=thresholds.get("min_adaptation_rate", MIN_ADAPTATION_RATE),
    )
    report_path = Path(args.report)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved report: {report_path}")
    metrics = report["metrics"]
    print(f"choice_divergence={metrics['choice_divergence']} "
          f"path_predictability={metrics['path_predictability']} "
          f"memory_occlusion_retention={metrics['memory_occlusion_retention']} "
          f"prompt_flip_rate={metrics['prompt_flip_rate']} "
          f"adaptation_rate={metrics['adaptation_rate']}")
    print(f"Gate A: {'PASS' if report['verdict']['gate_a_pass'] else 'FAIL'}")
    return 0 if report["verdict"]["gate_a_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
