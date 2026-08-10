"""Q1 Phase 3 — ReaderContract：建立/注入/合规检查 + SceneExperience 强制.

R3：逐作品的「读者为什么选择这本书」规格。sidecar 文件（reader_contract.json，
不进 serialization.py 状态机层）。确定性检查（forbidden_drifts 子串命中）+
v3 Pre-Review 闸（关键单元必须携带 scene_experience）。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.object_state import NarrativeState, PlotUnit
from src.object_state.readercontract import ReaderContract
from src.workflow_action.reader_contract import (
    ReaderContractUnit,
    build_initial_contract,
    contract_violations,
    evaluate_opening_compliance,
    load_reader_contract,
    save_reader_contract,
    scene_experience_guard_issues,
    scene_experience_guard_review_issues,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _plotunit(**overrides) -> PlotUnit:
    base = dict(
        unit_id="pu_t",
        level="scene",
        goal="目标",
        participants=["c001"],
        conflict="冲突",
        released_information=["信息"],
        input_state_ref="ns_in",
        output_state_ref="ns_out",
        is_effective=True,
    )
    base.update(overrides)
    return PlotUnit(**base)


def _state(situation: str = "当前局势") -> NarrativeState:
    return NarrativeState(
        state_id="ns_t",
        current_time="夜晚",
        current_location="场景",
        current_situation=situation,
        active_characters=["c001"],
    )


def test_reader_contract_validation():
    """core_pleasures 2–4 项；文本字段非空."""
    ReaderContract(
        contract_id="default",
        audience="大众",
        core_pleasures=["快感1", "快感2"],
        follow_reason="值得跟",
        core_tension="张力",
        chapter_pacing="推进",
        opening_minimum_promise="承诺",
    )
    with pytest.raises(Exception):
        ReaderContract(
            contract_id="default",
            audience="大众",
            core_pleasures=[],
            follow_reason="值得跟",
            core_tension="张力",
            chapter_pacing="推进",
            opening_minimum_promise="承诺",
        )
    with pytest.raises(Exception):
        ReaderContract(
            contract_id="default",
            audience="",
            core_pleasures=["快感1", "快感2"],
            follow_reason="值得跟",
            core_tension="张力",
            chapter_pacing="推进",
            opening_minimum_promise="承诺",
        )


def test_build_initial_contract_deterministic():
    """从 WorkSpec（或空）的确定性默认——只做默认，不做作品内容推断."""
    c = build_initial_contract(contract_id="default", workspec=None)
    assert c.contract_id == "default"
    assert c.audience == "大众网文读者"
    assert 2 <= len(c.core_pleasures) <= 4
    assert c.valid_hooks  # 默认钩子枚举
    assert c.opening_minimum_promise


def test_to_prompt_context_renders_core_fields():
    c = build_initial_contract(workspec=None)
    ctx = c.to_prompt_context()
    assert "目标读者" in ctx
    assert "核心张力" in ctx
    assert "章节推进" in ctx


def test_contract_violations_substring():
    """forbidden_drifts 在 goal/conflict/choice_grounding 的确定性子串命中."""
    c = build_initial_contract(workspec=None)
    c = c.model_copy(update={"forbidden_drifts": ["超能力", "穿越"]})
    pu = _plotunit(goal="主角尝试超能力解决问题", conflict="冲突")
    assert contract_violations(pu, c) == ["超能力"]
    pu2 = _plotunit(goal="正常推进", conflict="冲突")
    assert contract_violations(pu2, c) == []
    assert contract_violations(pu, None) == []


def test_evaluate_opening_compliance():
    """首章最小承诺：has_choice / has_cost / has_follow_alignment / q1_ready."""
    c = build_initial_contract(workspec=None)
    c = c.model_copy(update={"core_tension": "「核心矛盾」驱动下的持续对抗"})
    pu = _plotunit(
        goal="主角在持续对抗中围绕核心矛盾做出选择",
        conflict="代价明确",
        scene_experience={
            "protagonist_sees": "画面",
            "obstacles": ["阻碍"],
            "choice_grounding": "主角基于身份作出选择",
            "outcome": "选择产生了可见代价",
            "cognition_shift": "认知变化",
        },
        consequences=["后果"],
    )
    res = evaluate_opening_compliance(pu, c)
    assert res["has_choice"] is True
    assert res["has_cost"] is True
    assert res["q1_ready"] is True


def test_scene_experience_guard_key_units_only():
    """关键单元（conflict/released_information 非空）必须携带 scene_experience；过渡单元不强制."""
    # 关键单元缺 scene_experience → issue
    assert scene_experience_guard_issues(_plotunit())
    # 关键单元带合法 scene_experience → 通过
    pu = _plotunit(
        scene_experience={
            "protagonist_sees": "画面",
            "obstacles": ["阻碍"],
            "choice_grounding": "依据",
            "outcome": "结果",
            "cognition_shift": "变化",
        }
    )
    assert scene_experience_guard_issues(pu) == []
    # 非关键单元（is_effective=False，过渡/氛围单元）不强制
    pu_transition = _plotunit(is_effective=False)
    assert scene_experience_guard_issues(pu_transition) == []


def test_scene_experience_guard_partial_fields():
    """选择依据/结果任一缺失 → 对应 issue（防御性：合法 SceneExperience 恒非空）."""
    class _FakeSE:
        choice_grounding = ""
        outcome = "结果"

    pu = _plotunit()
    pu.scene_experience = _FakeSE()
    issues = scene_experience_guard_issues(pu)
    assert any("choice_grounding" in i for i in issues)


def test_scene_experience_guard_review_issues_blocking():
    """v3 闸产出 blocking ReviewIssue（缺失整体→missing_consequence；缺依据→motivation_gap）."""
    issues = scene_experience_guard_review_issues(_plotunit())
    assert issues
    assert all(issue.is_blocking() for issue in issues)

    class _FakeSE:
        choice_grounding = ""
        outcome = "结果"

    pu_partial = _plotunit()
    pu_partial.scene_experience = _FakeSE()
    partial_issues = scene_experience_guard_review_issues(pu_partial)
    assert partial_issues
    assert all(issue.is_blocking() for issue in partial_issues)
    assert all("motivation_gap" == i.issue_type for i in partial_issues)


def test_save_load_sidecar_roundtrip(tmp_path):
    """sidecar 保存/读取往返；缺失/损坏 → None（零成本）."""
    c = build_initial_contract(workspec=None)
    path = save_reader_contract(tmp_path, c)
    assert path.name == "reader_contract.json"
    loaded = load_reader_contract(tmp_path)
    assert loaded is not None
    assert loaded.contract_id == c.contract_id
    assert loaded.to_prompt_context() == c.to_prompt_context()
    # 缺失 → None
    assert load_reader_contract(tmp_path / "missing") is None
    # 损坏 → None
    (tmp_path / "reader_contract.json").write_text("{bad json", encoding="utf-8")
    assert load_reader_contract(tmp_path) is None


def test_reader_contract_unit_staged_prompt_and_parse():
    """staged 单元：prompt 含作品约束/初始草稿/输出格式；parse 往返."""
    unit = ReaderContractUnit()
    prompt = unit.build_prompt(mode="extend", workspec_context="【作品约束】\n测试约束")
    assert "为一部extend作品建立【读者契约】" in prompt
    assert "作品约束" in prompt
    assert "forbidden_drifts" in prompt
    # 初始草稿段（编辑时）
    initial = build_initial_contract(workspec=None)
    prompt2 = unit.build_prompt(
        mode="compose", initial_contract=initial, workspec_context="约束"
    )
    assert "初始草稿" in prompt2
    assert "目标读者" in prompt2

    response = json.dumps(
        {
            "contract_id": "test-001",
            "audience": "测试读者",
            "core_pleasures": ["快感1", "快感2", "快感3"],
            "follow_reason": "理由",
            "core_tension": "张力",
            "chapter_pacing": "推进",
            "must_keep": ["声音"],
            "forbidden_drifts": ["漂移1"],
            "valid_hooks": ["cliffhanger"],
            "ending_conditions": ["结束"],
            "opening_minimum_promise": "承诺",
        },
        ensure_ascii=False,
    )
    parsed = unit.parse_response(response)
    assert parsed.contract_id == "test-001"
    assert parsed.forbidden_drifts == ["漂移1"]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_selector_contract_violation_blocks_candidate():
    """Proposal Selector 的 Consistency Gate 把命中 forbidden_drifts 的候选阻断（零 LLM）."""
    from src.workflow_action.author_selector import evaluate_candidates

    contract = build_initial_contract(workspec=None)
    contract = contract.model_copy(update={"forbidden_drifts": ["超能力"]})

    def _pkg(goal: str, unit_id: str, state_id: str) -> dict:
        pu = _plotunit(
            unit_id=unit_id, goal=goal, conflict="冲突", output_state_ref=state_id
        )
        ns = NarrativeState(
            state_id=state_id,
            current_time="夜晚",
            current_location="场景",
            current_situation="推进",
            active_characters=["c001"],
        )
        return {
            "plotunit": pu,
            "new_state": ns,
            "new_facts": [],
            "confidence_gaps": [],
        }

    good = _pkg("正常推进", "pu_good", "ns_good")
    bad = _pkg("主角觉醒超能力解决问题", "pu_bad", "ns_bad")
    # objects 需含 input_state_ref 对应的当前 NarrativeState（hard_rules 检查）
    current = NarrativeState(
        state_id="ns_in",
        current_time="夜晚",
        current_location="场景",
        current_situation="调查中",
        active_characters=["c001"],
    )
    evals = evaluate_candidates([good, bad], [current], contract=contract)
    assert evals["A"].consistency_pass is True
    assert evals["B"].consistency_pass is False
    issue_types = [i["issue_type"] for i in evals["B"].consistency_issues]
    assert "contract_violation" in issue_types
    # 无契约 → 不检查（零成本契约）
    evals_no_contract = evaluate_candidates([good, bad], [current], contract=None)
    assert evals_no_contract["B"].consistency_pass is True


def test_contract_script_default_and_staged(tmp_path):
    """contract_short_form：--default 零 LLM 保存；staged prompt → response → 保存."""
    output_dir = tmp_path / "output" / "extend"
    r = _run_script(
        "src/contract_short_form.py",
        "--output-dir",
        str(output_dir),
        "--mode",
        "extend",
        "--default",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    contract_path = output_dir / "reader_contract.json"
    assert contract_path.exists()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["contract_id"] == "default"
    assert contract["audience"]

    # 已存在 → 检查模式打印摘要
    r2 = _run_script(
        "src/contract_short_form.py",
        "--output-dir",
        str(output_dir),
        "--mode",
        "extend",
    )
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "ReaderContract: default" in r2.stdout

    # staged 编辑：prompt → response → 保存
    out2 = tmp_path / "output" / "compose"
    r3 = _run_script(
        "src/contract_short_form.py", "--output-dir", str(out2), "--mode", "compose"
    )
    assert r3.returncode == 0 and "[WAITING]" in r3.stdout, r3.stdout + r3.stderr
    assert (out2 / "contract_prompt.txt").exists()
    response = json.dumps(
        {
            "contract_id": "staged-001",
            "audience": "测试读者",
            "core_pleasures": ["快感1", "快感2"],
            "follow_reason": "理由",
            "core_tension": "张力",
            "chapter_pacing": "推进",
            "must_keep": [],
            "forbidden_drifts": [],
            "valid_hooks": [],
            "ending_conditions": [],
            "opening_minimum_promise": "承诺",
        },
        ensure_ascii=False,
    )
    (out2 / "contract_response.txt").write_text(response, encoding="utf-8")
    r4 = _run_script(
        "src/contract_short_form.py", "--output-dir", str(out2), "--mode", "compose"
    )
    assert r4.returncode == 0, r4.stdout + r4.stderr
    saved = json.loads((out2 / "reader_contract.json").read_text(encoding="utf-8"))
    assert saved["contract_id"] == "staged-001"
