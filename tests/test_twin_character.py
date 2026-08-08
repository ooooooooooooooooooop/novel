"""Twin Character Harness tests — 作者性 Phase A Task 4.

验证最小理论（设计文档 §31-36 / Gate A §46）：不同经历 → 新情境中的稳定不同选择。

覆盖：
- 同初始模型 + 不同经历 → 分叉（choice_divergence）
- 同经历 → 不分叉（对照）
- 路径可预测性 / 记忆遮蔽保持率 / prompt 翻转率 / 适应率 五个指标
- Gate A 判定与四类失败形态的信号（完全不分叉 / 只活在压力里 / 只是 Persona / 固化规则）
- 经历经 Task 2 写回（schema 校验 + 动态字段 apply）
- oracle 可插拔（协议）+ 离线 CLI（--spec → --report）
"""

import json
import subprocess
import sys

import pytest

from src.experiment.twin_character import (
    CharacterFieldOracle,
    ChoiceOracle,
    ChoiceOutcome,
    MIN_DIVERGENCE,
    run_twin_character_experiment,
)
from src.object_state.charactermodel import CharacterModel


def _initial(**overrides) -> CharacterModel:
    base = dict(
        character_id="c_twin",
        name="双生子",
        identity="新手",
        outer_goal="生存",
        inner_need="被认可",
        fear="未知",
        flaw="经验不足",
        strength="韧性",
        stance="中立",
    )
    base.update(overrides)
    return CharacterModel(**base)


def _seq_a() -> list[dict]:
    """Twin A：设防 / 独立 经历（formative——长期写回门禁需 permanence=long）. """
    return [
        {"character_id": "c_twin", "observed_consequence": "主动坦白后被人利用",
         "affected_dimension": "self_image", "update_type": "shift",
         "proposed_after": "独自扛下一切", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "再次被利用",
         "affected_dimension": "fear", "update_type": "reinforce",
         "proposed_after": "被利用", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "求助被羞辱",
         "affected_dimension": "goal", "update_type": "shift",
         "proposed_after": "自保优先", "permanence": "long", "confidence": 0.9},
    ]


def _seq_b() -> list[dict]:
    """Twin B：信任 / 开放 经历（formative——长期写回门禁需 permanence=long）. """
    return [
        {"character_id": "c_twin", "observed_consequence": "主动坦白后被理解",
         "affected_dimension": "self_image", "update_type": "shift",
         "proposed_after": "信任他人", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "求助获得帮助",
         "affected_dimension": "goal", "update_type": "shift",
         "proposed_after": "建立可信赖关系", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "及时沟通修复了关系",
         "affected_dimension": "trajectory", "update_type": "shift",
         "proposed_after": "从孤立到愿意托付", "permanence": "long", "confidence": 0.9},
    ]


def _scenarios() -> list:
    from src.experiment.twin_character import TwinOption, TwinScenario

    return [
        TwinScenario(scenario_id="s1", situation="朋友消失三天归来，说需要空间", options=[
            TwinOption(option_id="o1", text="主动询问、想要真话", prefer=["信任", "坦白"]),
            TwinOption(option_id="o2", text="保持距离、不追问", prefer=["独自", "设防", "自保"]),
        ]),
        TwinScenario(scenario_id="s2", situation="对方请求帮助", options=[
            TwinOption(option_id="o3", text="答应帮助", prefer=["托付", "信任", "帮助"]),
            TwinOption(option_id="o4", text="拒绝帮助", prefer=["独自", "自保", "设防"]),
        ]),
        TwinScenario(scenario_id="s3", situation="有人承诺支持你", options=[
            TwinOption(option_id="o5", text="接受支持", prefer=["托付", "信任", "帮助"]),
            TwinOption(option_id="o6", text="婉拒支持", prefer=["独自", "自保", "设防"]),
        ]),
    ]


def _adaptation() -> list[dict]:
    """给 A 的大量新正向沟通经验（formative——长期写回门禁需 permanence=long）."""
    return [
        {"character_id": "c_twin", "observed_consequence": "多次求助被接纳",
         "affected_dimension": "self_image", "update_type": "shift",
         "proposed_after": "可以信任他人", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "托付得到回报",
         "affected_dimension": "trajectory", "update_type": "shift",
         "proposed_after": "从设防到愿意托付", "permanence": "long", "confidence": 0.9},
        {"character_id": "c_twin", "observed_consequence": "关系修复成功",
         "affected_dimension": "goal", "update_type": "shift",
         "proposed_after": "建立可信赖关系", "permanence": "long", "confidence": 0.9},
    ]


def _run(seq_a, seq_b, scenarios=None, **kw):
    return run_twin_character_experiment(
        initial=_initial(),
        seq_a=seq_a,
        seq_b=seq_b,
        scenarios=scenarios if scenarios is not None else _scenarios(),
        **kw,
    )


# ---- 最小理论：不同经历 → 分叉，同经历 → 不分叉 ----


def test_different_history_diverges():
    r = _run(_seq_a(), _seq_b())
    assert r["metrics"]["choice_divergence"] == 1.0
    assert all(row["divergent"] for row in r["per_scenario"])


def test_same_history_no_divergence():
    r = _run(_seq_a(), _seq_a())
    assert r["metrics"]["choice_divergence"] == 0.0


def test_divergence_range():
    for seq_a, seq_b in ((_seq_a(), _seq_b()), (_seq_a(), _seq_a()), ([], _seq_b())):
        r = _run(seq_a, seq_b)
        d = r["metrics"]["choice_divergence"]
        assert 0.0 <= d <= 1.0


# ---- 五个指标 ----


def test_path_predictability_high_for_consistent_history():
    """一致经历 → 从经历信号能预测选择（路径可预测性高）."""
    r = _run(_seq_a(), _seq_b())
    assert r["metrics"]["path_predictability"] == 1.0


def test_memory_occlusion_retains_divergence_in_stable_fields():
    """分叉承载在稳定字段（self_image/fear/goal）→ 遮蔽压力后保留."""
    r = _run(_seq_a(), _seq_b())
    assert r["metrics"]["memory_occlusion_retention"] == 1.0
    assert r["occlusion_explained"]["occluded_field"] == "current_pressure"


def test_memory_occlusion_drops_when_divergence_lives_in_pressure():
    """只有 current_pressure 承载分叉 → 遮蔽后差异消失（保留率低）.

    这验证遮蔽实验真的测到了『差异的承载层』：若差异只活在当下压力里，
    遮蔽记忆后分叉消失——不是形成，只是情境。
    """
    from src.experiment.twin_character import TwinOption, TwinScenario

    initial = _initial(current_pressure=[])
    scenarios = [
        TwinScenario(scenario_id="p1", situation="眼前有急事", options=[
            TwinOption(option_id="oA", text="先处理眼前", prefer=["限期", "紧迫"]),
            TwinOption(option_id="oB", text="先稳住关系", prefer=["关系", "信任"]),
        ]),
    ]
    seq_a = [
        {"character_id": "c_twin", "observed_consequence": "处决期限逼近",
         "affected_dimension": "pressure", "update_type": "shift",
         "proposed_after": "限期紧迫"}]
    seq_b = [
        {"character_id": "c_twin", "observed_consequence": "与朋友和好",
         "affected_dimension": "pressure", "update_type": "shift",
         "proposed_after": "关系修复"}]
    r = run_twin_character_experiment(
        initial=initial, seq_a=seq_a, seq_b=seq_b, scenarios=scenarios
    )
    # 基线：压力让 A/B 在 oA/oB 上分叉
    assert r["metrics"]["choice_divergence"] == 1.0
    # 遮蔽 current_pressure 后：双方都没有『限期/关系』信号 → 同选（平局首项）→ 分叉消失
    assert r["metrics"]["memory_occlusion_retention"] == 0.0


def test_prompt_flip_rate_between_zero_and_one():
    """统一强 prompt：设防的 A 被撬动、已信任的 B 不被撬动 → 翻转率居中.

    翻转率既不是 0（完全固化到连 prompt 都无效）也不是 1（只是 Persona）.
    """
    r = _run(_seq_a(), _seq_b())
    flip = r["metrics"]["prompt_flip_rate"]
    assert 0.0 < flip < 1.0


def test_adaptation_rate_positive_after_new_experience():
    r = _run(_seq_a(), _seq_b(), adaptation_sequence=_adaptation())
    assert r["metrics"]["adaptation_rate"] > 0.0
    assert r["verdict"]["reasons"]["adaptation_measured"] is True


def test_adaptation_not_measured_without_sequence():
    r = _run(_seq_a(), _seq_b())
    assert r["metrics"]["adaptation_rate"] == 0.0
    assert r["verdict"]["reasons"]["adaptation_measured"] is False


# ---- Gate A 判定 ----


def test_gate_a_pass_for_formed_twins():
    r = _run(_seq_a(), _seq_b(), adaptation_sequence=_adaptation())
    assert r["verdict"]["gate_a_pass"] is True
    assert r["verdict"]["reasons"]["divergence_threshold_met"] is True


def test_gate_a_fail_when_no_divergence():
    r = _run(_seq_a(), _seq_a())
    assert r["verdict"]["gate_a_pass"] is False
    assert r["verdict"]["reasons"]["divergence_threshold_met"] is False


def test_gate_a_fail_when_rigid_no_adaptation():
    """适应率 0（给新经验仍不变选）→ 固化规则信号 → Gate A FAIL.

    用中性 adaptation（只加不命中选项关键词的压力词，不碰形成字段）隔离出
    『给新经验也改不了选择』的刚性：分叉满足，但 adaptation_possible=False。
    """
    from src.experiment.twin_character import TwinOption, TwinScenario

    scenarios = [
        TwinScenario(scenario_id="s", situation="test", options=[
            TwinOption(option_id="x", text="信任方向", prefer=["信任", "托付"]),
            TwinOption(option_id="y", text="设防方向", prefer=["独自", "设防"]),
        ]),
    ]
    neutral_adaptation = [
        {"character_id": "c_twin", "observed_consequence": "下了一场雨",
         "affected_dimension": "pressure", "update_type": "shift",
         "proposed_after": "天气不佳"},
    ]
    r = run_twin_character_experiment(
        initial=_initial(), seq_a=_seq_a(), seq_b=_seq_b(),
        scenarios=scenarios, adaptation_sequence=neutral_adaptation,
    )
    assert r["metrics"]["choice_divergence"] == 1.0
    assert r["metrics"]["adaptation_rate"] == 0.0
    assert r["verdict"]["reasons"]["adaptation_measured"] is True
    assert r["verdict"]["reasons"]["adaptation_possible"] is False
    assert r["verdict"]["gate_a_pass"] is False


# ---- 输入校验 ----


def test_empty_scenarios_rejected():
    with pytest.raises(ValueError):
        _run(_seq_a(), _seq_b(), scenarios=[])


def test_empty_both_sequences_rejected():
    with pytest.raises(ValueError):
        _run([], [])


def test_experience_goes_through_task2_schema():
    """坏经历（未知 dimension）在 CharacterUpdate 层被拒."""
    bad = dict(_seq_a()[0], affected_dimension="mood")
    with pytest.raises(ValueError):
        _run([bad], _seq_b())


def test_experience_apply_records_before():
    from src.object_state.characterupdate import CharacterUpdate
    from src.workflow_action.character_updates import apply_update_to_character

    c = _initial(self_image="可以信任他人")
    u = CharacterUpdate(**dict(_seq_a()[0], trigger="twin_exp"))
    before = apply_update_to_character(c, u)
    assert before == "可以信任他人"
    assert c.self_image == "独自扛下一切"
    assert u.before == "可以信任他人"


def test_experience_apply_mutates_fields():
    from src.experiment.twin_character import apply_experience

    c = _initial()
    for raw in _seq_a():
        apply_experience(c, raw)
    assert c.self_image == "独自扛下一切"
    assert c.fear == "被利用"
    assert c.outer_goal == "自保优先"


# ---- oracle 可插拔 ----


class FixedOracle(ChoiceOracle):
    """测试用固定 oracle：一律选最后一个选项."""

    def decide(self, character, scenario, *, bias_text=""):
        return ChoiceOutcome(
            selected=scenario.options[-1].option_id,
            scores={o.option_id: 1.0 for o in scenario.options},
            confidence=1.0,
        )


def test_oracle_pluggable():
    r = _run(_seq_a(), _seq_b(), oracle=FixedOracle())
    # 固定 oracle：A/B 永远同选 → 不分叉
    assert r["metrics"]["choice_divergence"] == 0.0
    assert all(row["choice_a"] == row["choice_b"] for row in r["per_scenario"])


def test_default_oracle_is_character_field():
    assert isinstance(CharacterFieldOracle().decide(_initial(), _scenarios()[0]), ChoiceOutcome)


# ---- 离线 CLI ----


def test_cli_offline_runner(tmp_path):
    spec = {
        "initial": _initial().model_dump(mode="json"),
        "seq_a": _seq_a(),
        "seq_b": _seq_b(),
        "scenarios": [s.model_dump(mode="json") for s in _scenarios()],
        "adaptation_sequence": _adaptation(),
    }
    spec_path = tmp_path / "spec.json"
    report_path = tmp_path / "report.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "src.experiment.twin_character",
         "--spec", str(spec_path), "--report", str(report_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["metrics"]["choice_divergence"] == 1.0
    assert report["verdict"]["gate_a_pass"] is True
    assert "Gate A: PASS" in result.stdout


def test_cli_offline_runner_missing_spec(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "src.experiment.twin_character",
         "--spec", str(tmp_path / "nope.json"), "--report", str(tmp_path / "r.json")],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 1
    assert "Error: spec not found" in result.stdout
