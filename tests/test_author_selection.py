"""author_selection CLI 助手 tests — 作者性任务 #14（CLI 全链路透传）.

验证：
- `run_author_selection` 整条选择链（多视角评估 → 选择 → ChoiceLedger →
  Shadow → Drift Review）落盘三个 sidecar，且按 decision_id 幂等（Review 等
  后续阶段保存 response 后重跑不产生重复记录）。
- `--proposals 1`（默认）零成本：kernel/风格档案缺失时各视角中性、不产额外文件。
- CLI 合约：extend/compose 默认 proposals=1、author_mode/shadow/drift_review=off；
  接受 on / N / --kernel；两个短表单 --help 暴露全部作者感知 flag。
- resume config 校验接受新配置键（VALID_CONFIG_FIELDS 扩展）。
"""

import json
import subprocess
import sys

import pytest

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.object_state.scene_experience import SceneExperience
from src.workflow_action.author_selection import (
    load_style_profile,
    resolve_kernel,
    run_author_selection,
)
from src.workflow_action.choiceledger import load_choice_ledger
from src.workflow_action.shadow import load_shadow_ledger
from src.workflow_action.drift_review import load_challenge_ledger


# ---------------------------------------------------------------------------
# fixtures（对齐 test_author_selector 的包构造）
# ---------------------------------------------------------------------------
def _scene() -> SceneExperience:
    return SceneExperience(
        protagonist_sees="窗外檐雨成线",
        obstacles=["对手堵在门口"],
        choice_grounding="身为长子，不能退",
        outcome="他留下对峙",
        cognition_shift="有些事放下，也放不下",
    )


def _pu(cid: str, goal: str, **overrides) -> PlotUnit:
    base = dict(
        unit_id=f"pu_{cid}",
        level="scene",
        goal=goal,
        participants=["c001"],
        conflict="坦白还是隐瞒",
        input_state_ref="ns_in",
        output_state_ref=f"ns_{cid}",
        hook="门外响起脚步声",
        consequences=["对方起了疑心"],
        is_effective=True,
        scene_experience=_scene(),
    )
    base.update(overrides)
    return PlotUnit(**base)


def _ns(state_id: str) -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="深夜",
        current_location="旧宅前厅",
        active_characters=["c001"],
        current_situation="对峙中",
    )


def _package(cid: str, goal: str, tradeoff_hint: str = "") -> dict:
    return {
        "plotunit": _pu(cid, goal),
        "new_state": _ns(f"ns_{cid}"),
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": tradeoff_hint,
    }


def _kernel(*principles) -> AuthorKernel:
    kw = dict(
        values=[],
        prohibitions=[],
        commitments=[],
        tensions=[],
        attention_biases=[],
        interpretive_biases=[],
    )
    for p in principles:
        field = {
            "value": "values",
            "prohibition": "prohibitions",
            "commitment": "commitments",
            "tension": "tensions",
            "attention_bias": "attention_biases",
            "interpretive_bias": "interpretive_biases",
        }[p.category]
        kw[field].append(p)
    return AuthorKernel(kernel_id="k_test", **kw)


def _prohibition(vocab_key: str, strength: float = 0.8) -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id=f"pro_{vocab_key}",
        category="prohibition",
        vocab_key=vocab_key,
        description="d",
        status="stable",
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=strength,
    )


def _objects() -> list:
    return [_ns("ns_in")]


def _run(tmp_path: pytest.TempPathFactory, packages, **kw):
    """薄封装：跑一次 run_author_selection，返回返回值."""
    defaults = dict(
        output_dir=tmp_path,
        decision_context="对峙中，需要选择如何推进",
        state_ref="ns_in",
        current_state_ref="ns_in",
        review=None,
    )
    defaults.update(kw)
    return run_author_selection(packages, _objects(), **defaults)


# ---------------------------------------------------------------------------
# run_author_selection：三 sidecar 落盘 + 幂等
# ---------------------------------------------------------------------------
def test_run_author_selection_writes_choice_ledger(tmp_path):
    packages = [
        _package("A", "他选择当众摊牌"),
        _package("B", "他隐瞒并继续调查"),
        _package("C", "他一次道歉就修复了关系"),
    ]
    kernel = _kernel(_prohibition("no_instant_forgiveness"))
    result = _run(tmp_path, packages, kernel=kernel, author_mode_on=True)

    ledger = load_choice_ledger(tmp_path)
    assert len(ledger.choices) == 1
    choice = ledger.choices[0]
    assert choice.decision_id == result["decision_id"]
    # 禁止 4：全候选 + 拒绝理由 + tradeoff 全量留痕
    assert [c.candidate_id for c in choice.candidates] == ["A", "B", "C"]
    assert choice.rejected
    assert choice.tradeoff


def test_run_author_selection_writes_shadow_and_drift(tmp_path):
    packages = [
        _package("A", "他选择当众摊牌"),
        _package("B", "他隐瞒并继续调查"),
        _package("C", "他一次道歉就修复了关系"),
    ]
    kernel = _kernel(_prohibition("no_instant_forgiveness"))
    _run(
        tmp_path, packages,
        kernel=kernel,
        author_mode_on=True,
        shadow_on=True,
        drift_review_on=True,
    )

    shadow_ledger = load_shadow_ledger(tmp_path / "shadow" / "shadow_ledger.json")
    assert shadow_ledger is not None
    assert len(shadow_ledger.comparisons) == 1
    assert shadow_ledger.comparisons[0].decision_id.startswith("dec_pu_")

    drift_path = tmp_path / "drift_review" / "drift_review.json"
    assert drift_path.exists()
    verdict = json.loads(drift_path.read_text(encoding="utf-8"))["verdict"]
    assert verdict in ("aligned", "active_break", "drift")


def test_run_author_selection_idempotent_on_rerun(tmp_path):
    """Review 阶段保存 response 后重跑：选择侧车不产生重复记录."""
    packages = [
        _package("A", "他选择当众摊牌"),
        _package("B", "他隐瞒并继续调查"),
        _package("C", "他一次道歉就修复了关系"),
    ]
    kernel = _kernel(_prohibition("no_instant_forgiveness"))
    _run(
        tmp_path, packages,
        kernel=kernel, author_mode_on=True,
        shadow_on=True, drift_review_on=True,
    )
    _run(
        tmp_path, packages,
        kernel=kernel, author_mode_on=True,
        shadow_on=True, drift_review_on=True,
    )

    assert len(load_choice_ledger(tmp_path).choices) == 1
    shadow_ledger = load_shadow_ledger(tmp_path / "shadow" / "shadow_ledger.json")
    assert len(shadow_ledger.comparisons) == 1


def test_drift_review_records_challenge_on_active_break(tmp_path):
    """active_break：冲突稳定原则但有 tradeoff 理由 → KernelChallenge 进台账."""
    packages = [
        _package("A", "他一次道歉就修复了长期隔阂"),
        _package("B", "他也用一次道歉化解了积怨"),
    ]
    kernel = _kernel(_prohibition("no_instant_forgiveness", strength=0.8))
    result = _run(
        tmp_path, packages,
        kernel=kernel, author_mode_on=True, drift_review_on=True,
    )
    assert result["drift_result"].verdict == "active_break"
    challenge_ledger = load_challenge_ledger(tmp_path / "drift_review" / "challenge_ledger.json")
    assert challenge_ledger is not None
    assert len(challenge_ledger.challenges) == 1
    assert challenge_ledger.challenges[0].decision_id == result["decision_id"]


def test_load_style_profile_and_resolve_kernel_missing_return_none(tmp_path):
    assert load_style_profile(tmp_path, "") is None
    assert resolve_kernel(tmp_path, "") is None


def test_resolve_kernel_explicit_path(tmp_path):
    kernel = _kernel(_prohibition("no_instant_forgiveness"))
    path = tmp_path / "kernel.json"
    path.write_text(kernel.model_dump_json(indent=2), encoding="utf-8")
    loaded = resolve_kernel(tmp_path, str(path))
    assert loaded is not None
    assert len(loaded.all_principles()) == 1


# ---------------------------------------------------------------------------
# Phase 8→9 接线：台账攒够 → consolidate → save author_kernel.json
# ---------------------------------------------------------------------------

def _consolidation_package(cid: str) -> list[dict]:
    """一组候选：选中 A 命中 trust_earned_over_time 支持证据（冲突含『坦白』）."""
    return [
        _package(cid, "他选择当众摊牌"),
        _package(cid + "_b", "他隐瞒并继续调查"),
    ]


def test_consolidation_writes_kernel_after_threshold(tmp_path):
    """攒够 CONSOLIDATION_MIN_CHOICES 条选择 → author_kernel.json 自动落盘."""
    for cid in "ABCDE":
        _run(tmp_path, _consolidation_package(cid), author_mode_on=True)
    kernel_path = tmp_path / "author_kernel.json"
    assert kernel_path.exists()
    kernel = AuthorKernel.model_validate_json(kernel_path.read_text(encoding="utf-8"))
    assert any(p.status in ("stable", "weak") for p in kernel.all_principles())


def test_consolidation_below_threshold_no_kernel(tmp_path):
    """未攒够阈值 → 零成本不写 kernel 文件，resolve_kernel 仍返回 None."""
    for cid in "ABC":  # 3 < CONSOLIDATION_MIN_CHOICES(5)
        _run(tmp_path, _consolidation_package(cid), author_mode_on=True)
    assert not (tmp_path / "author_kernel.json").exists()
    assert resolve_kernel(tmp_path, "") is None


def test_consolidated_kernel_auto_consumed_by_resolve_kernel(tmp_path):
    """Phase 8→9 闭环：kernel 落盘后，后续 --author-mode on 无 --kernel 自动消费."""
    for cid in "ABCDE":
        _run(tmp_path, _consolidation_package(cid), author_mode_on=True)
    resolved = resolve_kernel(tmp_path, "")
    assert resolved is not None
    assert resolved.status == "formed"
    assert any(p.status in ("stable", "weak") for p in resolved.all_principles())


def test_consolidation_grows_and_is_idempotent(tmp_path):
    """追加选择 → 原则强化（supporting 增多）；重跑同一 decision 不重复计入."""
    for cid in "ABCDEF":
        _run(tmp_path, _consolidation_package(cid), author_mode_on=True)
    kernel = AuthorKernel.model_validate_json(
        (tmp_path / "author_kernel.json").read_text(encoding="utf-8")
    )
    trust = next(
        p for p in kernel.all_principles()
        if p.vocab_key == "trust_earned_over_time"
    )
    assert len(trust.supporting_choices) == 6
    # 重跑已有决策（decision_id 已存在）→ 台账不重复、支持证据不膨胀
    _run(tmp_path, _consolidation_package("A"), author_mode_on=True)
    assert len(load_choice_ledger(tmp_path).choices) == 6
    kernel2 = AuthorKernel.model_validate_json(
        (tmp_path / "author_kernel.json").read_text(encoding="utf-8")
    )
    trust2 = next(
        p for p in kernel2.all_principles()
        if p.vocab_key == "trust_earned_over_time"
    )
    assert len(trust2.supporting_choices) == 6


# ---------------------------------------------------------------------------
# CLI 合约：默认 off / 接受 flag / 短表单 --help
# ---------------------------------------------------------------------------
def _build_parser():
    from src.novel_cli import build_parser

    return build_parser(emit_json_errors=False)


def test_cli_parser_author_defaults_off():
    parser = _build_parser()
    ext = parser.parse_args(["extend", "x"])
    comp = parser.parse_args(["compose", "x"])
    for ns in (ext, comp):
        assert ns.proposals == 1
        assert ns.author_mode == "off"
        assert ns.shadow == "off"
        assert ns.drift_review == "off"


def test_cli_parser_accepts_author_flags():
    parser = _build_parser()
    ext = parser.parse_args(
        ["extend", "x", "--proposals", "3", "--author-mode", "on",
         "--kernel", "k.json", "--shadow", "on", "--drift-review", "on"]
    )
    comp = parser.parse_args(
        ["compose", "x", "--proposals", "2", "--shadow", "on"]
    )
    assert ext.proposals == 3
    assert ext.author_mode == "on"
    assert ext.kernel == "k.json"
    assert ext.shadow == "on"
    assert ext.drift_review == "on"
    assert comp.proposals == 2
    assert comp.shadow == "on"
    assert comp.author_mode == "off"


def test_short_form_help_exposes_author_flags():
    for script in ("src/compose_short_form.py", "src/extend_short_form.py"):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, script
        for flag in ("--proposals", "--author-mode", "--kernel", "--shadow", "--drift-review"):
            assert flag in result.stdout, f"{script} missing {flag}"


def test_resume_config_validation_accepts_author_keys(tmp_path):
    """run_config.json 写新配置键，resume 的 _read_config 校验须通过."""
    from src.novel_cli import _read_config

    novel_dir = tmp_path / "novel_x"
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / "run_config.json").write_text(
        json.dumps(
            {
                "mode": "extend",
                "proposals": 3,
                "author_mode": "on",
                "kernel": "k.json",
                "shadow": "on",
                "drift_review": "on",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = _read_config(novel_dir)
    assert config["proposals"] == 3
    assert config["author_mode"] == "on"
    assert config["shadow"] == "on"
