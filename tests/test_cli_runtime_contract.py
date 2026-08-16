"""CLI runtime contract tests for Codex-native staged workflows."""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# A1 闭环生产测试（autonomous_contracts + provider_adapter + autonomous_runner）
# 使基线从 Q1 的 2470 升至 2508。基线变化必须与新增测试一一对应，禁止删测试降基线。
# A1 T4（needs_premise 自动前提搜索 + 事件指纹/语义接缝）：新增
# test_premise_search.py(29) + test_semantic_seam.py(27) + runner 前提/接缝集成
# （T3 单测 1 拆为前提搜索 2，净 +1；新增接缝阻断 +1 → +2），基线 2508 → 2566。
# A1 T5（PlotUnit 候选 + 多版正文 + EvaluatorPrecommit + JudgeClaim）：新增
# test_plan_search.py(27) + test_precommit.py(11) + test_judge_claim.py(34)，基线 2566 → 2638。
# A1 T6（匿名 A/B 换位 + 帕累托前沿）：新增 test_pareto_tournament.py(31) + runner
# 位置偏置夹具(1)，基线 2638 → 2670。
# A1 T7（长程对账 + 读者响应 + 自动校准）：新增 test_long_horizon.py(15) +
# test_reader_responses.py(7) + test_auto_calibrate.py(20) + runner 长程集成(3) +
# contracts 长程优先级(3) + auto-calibrate CLI(test_auto_calibrate_cli.py,6)，
# 基线 2670 → 2724。
# A1 G9（统一发布验证）：新增 test_a1_release_validation.py(7)，基线 2724 → 2731。
# A1 G9 隐私聚合锁：新增 test_a1_release_validation.py 聚合隐私回归(2)，基线 2731 → 2733。
# G7 内容无关评审协议：新增 test_preference_review.py(87)、test_pareto_tournament.py
#   锚定仲裁夹具(+1)，基线 2733 → 2764。
# A1 G8 根因（prism 评审 JSON 前导散文/围栏/未转义引号）：工作区 Phase 2/G8 未提交
#   测试（test_preference_review.py 扩展、test_provider_qualification.py、
#   test_auto_calibrate.py 等）+33 → 2797；再新增前导散文提取回归(+2) → 2799；
#   散文内花括号逐个候选提取回归(+1) → 2800；G8 评审锚点偏移重映射回归
#   （test_judge_claim.py,+1）→ 2801；G8 评审越界偏移重映射 + 非标 position
#   推导回归（test_judge_claim.py,+2）→ 2803。
# k3 thinking_disabled provider 能力（test_provider_adapter.py,+3：注入开关 /
#   缺省字节等价 / 按角色隔离），基线 2803 → 2806。
# M1 单次调用契约（test_preference_review.py 重写 3 个重试测试 → 3 个单次契约测试，
#   数量不变）+ deepseek_active bundle 重建入口（test_build_deepseek_active_bundle.py,+7：
#   四文件/幂等/隐私/阈值与 v2 划分字节校验/ProviderProfile/AutonomousPolicy/活动选择器）
# + M1 生产调用链回归（test_autonomous_runner.py,+1：协议违规→单次调用/终态/零污染），
# 基线 2806 → 2814；M1b upstream_url 校验（+1 adapter 调用前 mismatch 测试）
# + 2 builder 测试（env 注入/缺失失败）→ 2817。
# M2 deepseek profile 冻结（f8b9965，test_build_deepseek_active_bundle.py,+4：
#   live DB provider 身份 / 拒绝非 deepseek / 拒绝 failover / judge thinking_disabled）
# → 2817 + 4 = 2821。
# G7 计分合同封死（docs/00_project/49_next_phase_plan.md 阶段 1；test_auto_calibrate.py,+4：
#   混合弃权计错 / 全部耗尽 position=0 / 分层采样非前缀 / 整 tag 弃权 FAIL）→ 2821 + 4 = 2825。
# Track A 时间一致性门禁对抗性注入（test_temporal_adversarial.py,+7：死亡后活跃 blocking /
#   活跃先于死亡负控制 / 过期持有 warning / 未过期持有负控制 / 时间否定 blocking /
#   不相交否定负控制 / 干净台账零误报）→ 2825 + 7 = 2832。
# Track A 确定性防火墙不变量（test_consistency_firewall_adversarial.py,+5：viability 幂等 /
#   required_premise 提及承诺内容 / reveal 意译负控制 / reveal 逐字正控 / 时间检出顺序无关）
# → 2832 + 5 = 2837。
# P1 长程因果防线（test_causal_defense.py,+20）+ 提交点接入（test_reader_gate.py,+3）
# → 2837 + 23 = 2860。
# P2 长程叙事编排器（test_narrative_orchestrator.py,+10）→ 2860 + 10 = 2870。
# P3 结构搜索与Rollout（test_structural_search.py,+10）→ 2870 + 10 = 2880。
# P4 Taste Stack 统一质量报告（test_taste_stack.py,+8）→ 2880 + 8 = 2888。
# P5 AuthorModel V3（test_authormodel_v3.py,+4）→ 2888 + 4 = 2892。
# P6 因果编译器与人物策略（test_causal_compiler.py,+4, test_character_policy.py,+2）→ 2892 + 6 = 2898。
# P7 人类盲评与长程授权（test_human_eval.py,+5）→ 2898 + 5 = 2903。
# R1-R9 大神级系统整改（taste_stack,+4; narrative_orchestrator,+2; structural_search,+3; causal_defense,+3; authormodel_v3,+2; human_eval,+3; test_remediation_integration.py,+1）
# → 2903 + 18 = 2921。
EXPECTED_TEST_BASELINE = "2921"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def test_collected_test_baseline_matches_contract():
    """收集的测试数必须等于文档契约基线（防漂移）. 依赖 --collect-only 不执行测试，无递归风险."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"(\d+) tests collected", result.stdout)
    assert match, f"could not parse collect count: {result.stdout!r}"
    assert match.group(1) == EXPECTED_TEST_BASELINE


def test_audit_output_dir_waiting_isolated(tmp_path):
    input_path = tmp_path / "audit_input.txt"
    output_dir = tmp_path / "audit_run"
    input_path.write_text("A short test narrative.", encoding="utf-8")

    result = run_script(
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0
    assert "[WAITING]" in result.stdout
    assert (output_dir / "rebuild_prompt.txt").exists()


def test_extend_output_dir_waiting_isolated(tmp_path):
    input_path = tmp_path / "extend_input.txt"
    output_dir = tmp_path / "extend_run"
    input_path.write_text("A short partial narrative.", encoding="utf-8")

    result = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0
    assert "[WAITING]" in result.stdout
    assert (output_dir / "rebuild_prompt.txt").exists()


def test_compose_output_dir_waiting_isolated(tmp_path):
    output_dir = tmp_path / "compose_run"

    result = run_script(
        "src/compose_short_form.py",
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 0
    assert "[WAITING]" in result.stdout
    assert (output_dir / "compose_continue_prompt.txt").exists()


def test_extend_resume_missing_state_fails(tmp_path):
    input_path = tmp_path / "extend_input.txt"
    output_dir = tmp_path / "extend_run"
    input_path.write_text("A short partial narrative.", encoding="utf-8")

    result = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--resume",
    )

    assert result.returncode == 1
    assert "requires saved state file" in result.stdout


def test_extend_resume_missing_frame_fails(tmp_path):
    from src.boundary_control.serialization import SerializationBoundaryUnit
    from src.object_state import NarrativeState, WorkSpec

    input_path = tmp_path / "extend_input.txt"
    output_dir = tmp_path / "extend_run"
    input_path.write_text("A short partial narrative.", encoding="utf-8")
    output_dir.mkdir()

    package = SerializationBoundaryUnit().build_package(
        WorkSpec(
            genre="test",
            audience="test",
            theme="test",
            tone="test",
            pacing="test",
        ),
        NarrativeState(
            state_id="ns_test",
            current_time="test",
            current_location="test",
            current_situation="test",
        ),
    )
    SerializationBoundaryUnit().save(package, output_dir / "extend_rebuild_package.json")

    result = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--resume",
    )

    assert result.returncode == 1
    assert "requires saved frame file" in result.stdout


def test_compose_resume_missing_state_fails(tmp_path):
    output_dir = tmp_path / "compose_run"

    result = run_script(
        "src/compose_short_form.py",
        "--output-dir",
        str(output_dir),
        "--resume",
    )

    assert result.returncode == 1
    assert "requires saved state file" in result.stdout


def test_compose_resume_missing_frame_fails(tmp_path):
    from src.boundary_control.serialization import SerializationBoundaryUnit
    from src.object_state import NarrativeState, WorkSpec

    output_dir = tmp_path / "compose_run"
    output_dir.mkdir()

    package = SerializationBoundaryUnit().build_package(
        WorkSpec(
            genre="test",
            audience="test",
            theme="test",
            tone="test",
            pacing="test",
        ),
        NarrativeState(
            state_id="ns_test",
            current_time="test",
            current_location="test",
            current_situation="test",
        ),
    )
    SerializationBoundaryUnit().save(package, output_dir / "compose_state.json")

    result = run_script(
        "src/compose_short_form.py",
        "--output-dir",
        str(output_dir),
        "--resume",
    )

    assert result.returncode == 1
    assert "requires saved frame file" in result.stdout


def test_input_hash_mismatch_preserves_responses(tmp_path):
    input_path = tmp_path / "audit_input.txt"
    output_dir = tmp_path / "audit_run"
    input_path.write_text("Original narrative.", encoding="utf-8")

    first = run_script(
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )
    assert first.returncode == 0

    response_path = output_dir / "rebuild_response.txt"
    response_path.write_text('{"preserve": true}', encoding="utf-8")

    input_path.write_text("Changed narrative.", encoding="utf-8")
    second = run_script(
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )

    assert second.returncode == 1
    assert "hash mismatch" in second.stdout
    assert response_path.read_text(encoding="utf-8") == '{"preserve": true}'


@pytest.mark.parametrize("script", ["src/audit_short_form.py", "src/extend_short_form.py"])
def test_missing_input_hash_in_non_empty_output_fails(script, tmp_path):
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "run"
    input_path.write_text("Original narrative.", encoding="utf-8")
    output_dir.mkdir()
    response_path = output_dir / "rebuild_response.txt"
    response_path.write_text('{"preserve": true}', encoding="utf-8")

    result = run_script(
        script,
        str(input_path),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 1
    assert "missing input file hash" in result.stdout
    assert response_path.read_text(encoding="utf-8") == '{"preserve": true}'


def test_compose_workspec_hash_mismatch_preserves_responses(tmp_path):
    output_dir = tmp_path / "compose_run"
    workspec_a = tmp_path / "workspec_a.json"
    workspec_b = tmp_path / "workspec_b.json"
    workspec_a.write_text(
        json.dumps(
            {
                "genre": "fantasy",
                "audience": "young adult",
                "theme": "growth",
                "tone": "restrained",
                "pacing": "steady",
            }
        ),
        encoding="utf-8",
    )
    workspec_b.write_text(
        json.dumps(
            {
                "genre": "mystery",
                "audience": "adult",
                "theme": "truth",
                "tone": "tense",
                "pacing": "fast",
            }
        ),
        encoding="utf-8",
    )

    first = run_script(
        "src/compose_short_form.py",
        str(workspec_a),
        "--output-dir",
        str(output_dir),
    )
    assert first.returncode == 0
    assert (output_dir / ".workspec_hash").exists()

    response_path = output_dir / "compose_continue_response.txt"
    response_path.write_text('{"preserve": true}', encoding="utf-8")
    second = run_script(
        "src/compose_short_form.py",
        str(workspec_b),
        "--output-dir",
        str(output_dir),
    )

    assert second.returncode == 1
    assert "WorkSpec hash mismatch" in second.stdout
    assert response_path.read_text(encoding="utf-8") == '{"preserve": true}'


def test_deployment_docs_are_consistent():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    agents = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    brief = (PROJECT_ROOT / "docs/00_project/00_project_brief.md").read_text(
        encoding="utf-8"
    )
    scope = (
        PROJECT_ROOT / "docs/00_project/01_scope_and_boundaries.md"
    ).read_text(encoding="utf-8")
    quickstart = (
        PROJECT_ROOT / "docs/00_project/02_agent_quickstart.md"
    ).read_text(encoding="utf-8")
    status = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8"
    )
    decision = (
        PROJECT_ROOT / "docs/00_project/27_deployment_shape_decision.md"
    ).read_text(encoding="utf-8")

    for text in (readme, agents, brief, scope, quickstart, status):
        assert "tests passing" in text
        assert "DirectAPI" in text

    counts = {
        label: set(re.findall(r"(\d+) tests passing", text))
        for label, text in {
            "README.md": readme,
            "AGENTS.md": agents,
            "00_project_brief.md": brief,
            "01_scope_and_boundaries.md": scope,
            "02_agent_quickstart.md": quickstart,
            "03_current_status.md": status,
        }.items()
    }
    assert counts == {
        "README.md": {EXPECTED_TEST_BASELINE},
        "AGENTS.md": {EXPECTED_TEST_BASELINE},
        "00_project_brief.md": {EXPECTED_TEST_BASELINE},
        "01_scope_and_boundaries.md": {EXPECTED_TEST_BASELINE},
        "02_agent_quickstart.md": {EXPECTED_TEST_BASELINE},
        "03_current_status.md": {EXPECTED_TEST_BASELINE},
    }

    assert "Codex-native staged CLI" in decision
    assert "DirectAPI implementation" in decision
    for label, text in {
        "AGENTS.md": agents,
        "00_project_brief.md": brief,
        "01_scope_and_boundaries.md": scope,
        "02_agent_quickstart.md": quickstart,
        "03_current_status.md": status,
        "27_deployment_shape_decision.md": decision,
        }.items():
        assert "DirectAPI remains stub" not in text, label
        assert "deferred/stubbed" not in text, label
        assert not re.search(r"(?<!\d)86 tests passing", text), label
        assert not re.search(r"(?<!\d)116 tests passing", text), label
        assert not re.search(r"(?<!\d)144 tests passing", text), label
        assert "provider calls remain unimplemented" in text or (
            "provider 调用仍未实现" in text
        ), label


def test_automation_readiness_boundary_docs_contract():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    status = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8"
    )
    boundary = (
        PROJECT_ROOT / "docs/00_project/29_automation_readiness_boundary.md"
    ).read_text(encoding="utf-8")

    assert "docs/00_project/29_automation_readiness_boundary.md" in readme
    assert "29_automation_readiness_boundary.md" in status

    required_phrases = [
        "Automation Readiness Boundary",
        "FileExchangeInterface remains the default v0 runtime",
        "staged CLI",
        "DirectAPI provider calling is not implemented",
        "string `next_route`",
        "must fail",
        "handoff_header.source",
        "handoff_header.target",
        "supported workflow strings",
        "handoff source and target must be different workflows",
        "handoff transition must be supported",
        "handoff_header.reason",
        "standard handoff must include handoff_header.reason",
        "must be a non-empty string when present",
        "must match `next_route.route_reason`",
        "Outer handoff container fields",
        "must remain a structured `NextRoute` object",
        "confidence_and_gaps.gaps",
        "must be a list of non-empty strings when present",
        "confidence_gap open items",
        "content must be a non-empty string",
        "confidence_gap open items must match confidence_and_gaps.gaps",
        "standard handoff anchor fields",
        "input_anchor.source_text",
        "input_anchor.review_target_ref",
        "output_anchor.state_ref",
        "output_anchor.reconstructed_objects",
        "next_route.must_read_first must include standard input anchors",
        "must_read_first and do_not_skip entries must be unique",
        "standard workflow handoffs must include next_route.do_not_skip",
        "RebuildUnit handoff do_not_skip must include review reconstructed object layers",
        "ReviewUnit handoff do_not_skip must include ReviewIssue and ReviewReminder state",
        "workflow standard anchors",
        "RebuildUnit -> ReviewUnit handoffs must include",
        "ReviewUnit handoffs must include",
        "ReviewUnit handoffs must include review change_set evidence",
        "change_set entries must include non-empty action",
        "review change_set route must match",
        "review change_set issue_count and reminder_count must match open_items",
        "ReviewUnit handoffs must include exactly one review change_set entry",
        "RebuildUnit handoffs must include create change_set evidence",
        "rebuild change_set objects must match output_anchor.reconstructed_objects",
        "RebuildUnit handoffs must include exactly one create change_set entry",
        "rebuild change_set objects entries must be unique",
        "Outer handoff object keys",
        "non-string handoff keys",
        "unknown review issue fields",
        "runtime model",
        "Handoff `ReviewIssue` open items",
        "Handoff `ReviewReminder` open items",
        "build_review_route()",
        "review_object_contracts.py",
        "payloads must be JSON objects",
        "payload keys must be strings",
        "open item must be an object",
        "conflicting `type` values",
        "gate violations",
        "`repair_control`",
        "Package outer container fields",
        "Malformed package container fields",
        "Package `confidence` and `metadata` keys",
        "Serialized package layer buckets",
        "Non-string type keys",
        "non-object bucket entries",
        "SerializationBoundaryUnit.check_separation()",
        "Unknown serialized types",
        "wrong package layer",
        "SerializationBoundaryUnit.deserialize_package()",
        "stable-state deserialization gate",
        "ReviewReminder",
        "unknown reminder fields",
        "window",
        "escalation_issue_type",
        "StagedResponseResult",
        "not response content",
        "interface_name must not contain whitespace",
        "result paths must be absolute",
        "response slot paths must be absolute",
        "result payload generation validates before returning",
        "result payloads must not include credential fields",
        "result payloads must not include execution claim fields",
        "result payloads must not include pending automation metadata fields",
        "result payloads must not include prompt or response content fields",
        "result payload keys must be strings",
        "automation_ready",
        "automation_blockers",
        "automation_contracts.py",
        "exact field-order declarations",
        "metadata builders",
        "metadata fragment extractors",
        "metadata source payloads must not include credential fields",
        "metadata payloads must reject credential fields before unknown-field handling",
        "metadata payloads must not include execution claim fields",
        "metadata source payloads must not include cross-contract metadata fields",
        "in-payload metadata validators",
        "metadata-only",
        "exact-field CLI JSON payloads must not include credential fields",
        "exact-field CLI JSON payloads must not include execution claim fields",
        "exact-field CLI JSON payloads must not include prompt or response content fields",
        "exact-field CLI JSON payloads must not include cross-contract metadata fields",
        "exact-field validator call sites must declare cross-contract metadata policy",
        "object-shaped CLI JSON payload literals with ok must declare schema_version and command",
        "ok=true CLI JSON payload literals must not declare error fields",
        "ok=false CLI JSON payload literals outside _json_error_payload() must declare error fields",
        "CLI stdout JSON dumps must emit only payload or rows contract variables",
        "CLI JSON object payload emits must validate payload before print",
        "CLI JSON object payload emits must validate after last payload assignment before print",
        "CLI JSON object payload emits must validate after last payload mutation before print",
        "CLI list JSON rows emits must validate rows before print",
        "CLI list JSON rows emits must validate after last rows mutation before print",
        "CLI list JSON rows emits must validate after last rows in-place mutation before print",
        "CLI empty list JSON emits must validate empty list before print",
        "pending metadata exact-field validation",
        "materialization metadata exact-field validation",
        "metadata payload keys",
        "CLI JSON error payload",
        "CLI JSON error payloads must be built through _json_error_payload()",
        "CLI JSON error payload call sites must be guarded by JSON mode",
        "runtime CLI JSON error payload call sites must include runtime context",
        "Only NovelArgumentParser.error may emit the base argument JSON error payload",
        "CLI JSON error payload call sites must declare literal error_stage by context",
        "CLI JSON error payload call sites must declare error_type by context",
        "CLI JSON error payload call sites must declare error message source by context",
        "error payload keys must be strings",
        "error payloads must not include credential fields",
        "error payloads must not include execution claim fields",
        "error payloads must not include cross-contract metadata fields",
        "error payloads must not include prompt or response content fields",
        "exact error fields",
        "CLI pending JSON payload",
        "exact-field contract",
        "CLI mode whitelist",
        "workspace novel names",
        "output_dir must be absolute",
        "output_dir must be output/<mode>",
        "pending slot paths must be under output_dir",
        "pending slot paths must be absolute",
        "pending slot entries must not include credential fields",
        "pending slot entries must not include execution claim fields",
        "pending slot entries must not include prompt or response content fields",
        "pending slot entries must not include cross-contract metadata fields",
        "pending response paths must not already exist",
        "pending discovery output_dir must be absolute",
        "pending_count",
        "pending entries",
        "all_pending entries must match current pending discovery",
        "staged prompt/response/slot identity",
        "staged prompt/response paths must be absolute",
        "respond staged paths must be under output/<mode>",
        "pending slot prompt hashes",
        "positive pending prompt bytes",
        "pending slot prompt hashes and byte counts must match current prompt files",
        "pending slot prompt mtime must match current prompt files",
        "pending/list JSON prompt evidence must match current prompt files",
        "pending response paths must not already exist",
        "expected prompt hashes",
        "expected prompt hash binding",
        "selection method contract",
        "pending preflight requires slot_id selection",
        "pending slot prompt mtime",
        "freshness timestamps",
        "route_artifact_mtime must match current route artifacts",
        "prompt_mtime must be newer than effective freshness cutoff",
        "effective freshness cutoff",
        "CLI respond JSON payload",
        "content hashes",
        "byte and character counts",
        "positive response materialization counts",
        "response_bytes must be at least response_chars",
        "response_source_bytes must not be less than response_bytes",
        "response_source must be an absolute path",
        "response_source must not match staged prompt_path or response_path",
        "respond JSON file evidence must match current files",
        "respond JSON source text must match staged response file",
        "respond JSON response text must be non-empty",
        "respond JSON response_source mtime must not be older than prompt_path",
        "respond JSON response_path mtime must not be older than prompt_path",
        "prompt_hash_verified",
        "CLI gate JSON payload",
        "exact gate fields",
        "gate review route matrix",
        "gate verdict consistency",
        "gate artifact paths must be absolute",
        "gate JSON artifact existence must match current files",
        "gate JSON route handoff content must match current handoff file",
        "gate JSON verdict fields must match current gate verdict",
        "artifact paths must be under output/<mode>",
        "artifact paths must share output directory",
        "gate package file must match mode",
        "route handoff file must be route_handoff.json",
        "blocking_pending_count",
        "blocking prompt files must be staged prompt filenames",
        "ContinueUnit pass requires package_present",
        "blocking prompt files",
        "CLI list JSON row payload",
        "exact list row fields",
        "list row status/pending consistency",
        "list route/status/workflow consistency",
        "list route artifact consistency",
        "list gate artifact consistency",
        "list gate metadata completeness",
        "final result file must match mode",
        "list JSON final result route content must match current result file",
        "route handoff file must be route_handoff.json",
        "list artifact paths must be absolute",
        "list JSON artifact existence must match current files",
        "list JSON route handoff content must match current handoff file",
        "list JSON gate verdict fields must match current gate verdict",
        "artifact paths must be under output/<mode>",
        "artifact paths must share output directory",
        "artifact file fields must match path names",
        "list JSON detail must match status and route evidence",
        "pending response paths must not already exist",
        "list waiting rows must match current pending discovery",
        "latest_mtime",
        "finite non-negative latest_mtime",
        "latest_date must match latest_mtime",
        "latest_mtime must match current workspace files",
        "list row pending prompt mtime",
        "pending_prompt_mtime must not exceed latest_mtime",
        "pending_prompt_mtime must be newer than current route artifacts",
        "list row pending prompt bytes",
        "top-level list output remains an array",
        "gate blocking counts",
        "exact JSON booleans",
        "self-validate",
        "--require-automation-ready",
        "materialize_staged_response_only",
        "no retry",
        "fallback provider",
        "schema_version",
        "type",
    ]

    for phrase in required_phrases:
        assert phrase in boundary, phrase

    assert "response text" in boundary
    assert "DirectAPIInterface.call()" in boundary
    assert "interface name snapshot" in boundary
    assert "route mutation" in boundary


def test_production_readiness_checklist_contract():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    status = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8"
    )
    checklist = (
        PROJECT_ROOT / "docs/00_project/30_production_readiness_checklist.md"
    ).read_text(encoding="utf-8")

    assert "docs/00_project/30_production_readiness_checklist.md" in readme
    assert "30_production_readiness_checklist.md" in status

    required_phrases = [
        "Production Readiness Checklist",
        "local staged CLI v0",
        "internal operator-in-the-loop production",
        "DirectAPI provider calling is not implemented",
        "closed-loop automation remains disallowed",
        "FileExchangeInterface remains the default v0 runtime",
        "single pending slot",
        "same staged response materialization path",
        "must not parse workflow JSON",
        "must not select routes",
        "must not write final artifacts",
        "provider errors must surface",
        "no retry",
        "fallback provider",
        "secrets",
        "timeout",
        "audit log",
        "release tag",
        "clean full pytest",
        f"{EXPECTED_TEST_BASELINE} tests passing",
    ]

    for phrase in required_phrases:
        assert phrase in checklist, phrase


def test_tier0_canary_runbook_contract():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    status = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8"
    )
    checklist = (
        PROJECT_ROOT / "docs/00_project/30_production_readiness_checklist.md"
    ).read_text(encoding="utf-8")
    runbook = (
        PROJECT_ROOT / "docs/00_project/31_tier0_canary_runbook.md"
    ).read_text(encoding="utf-8")

    assert "docs/00_project/31_tier0_canary_runbook.md" in readme
    assert "31_tier0_canary_runbook.md" in status
    assert "docs/00_project/31_tier0_canary_runbook.md" in checklist

    required_phrases = [
        "Tier 0 Canary Runbook",
        "local staged CLI v0",
        "internal operator-in-the-loop",
        "NOVELS_ROOT",
        "FileExchangeInterface",
        "Do not write directly to `*_response.txt`",
        "Do not parse workflow JSON",
        "Do not select routes",
        "Do not write final artifacts",
        "novel audit tier0-canary --input canary_input.txt",
        "novel pending tier0-canary --require-automation-ready --json",
        "novel respond tier0-canary --slot-id rebuild",
        "novel resume tier0-canary",
        "novel respond tier0-canary --slot-id review",
        "novel gate tier0-canary --json",
        "rebuild_prompt.txt",
        "review_prompt.txt",
        "audit_report.json",
        "route_handoff.json",
        "automation_ready=true",
        "provider_calls_implemented=false",
        "closed_loop_allowed=false",
        "provider_call_performed=false",
        "closed_loop_advanced=false",
        "materialized_action=materialize_staged_response_only",
        "review_route=pass",
        "next_workflow=ContinueUnit",
        "blocking_pending_count=0",
        "fallback provider",
        "closed-loop automation",
    ]

    for phrase in required_phrases:
        assert phrase in runbook, phrase


def test_tier0_release_record_contract():
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    status = (PROJECT_ROOT / "docs/00_project/03_current_status.md").read_text(
        encoding="utf-8"
    )
    checklist = (
        PROJECT_ROOT / "docs/00_project/30_production_readiness_checklist.md"
    ).read_text(encoding="utf-8")
    runbook = (
        PROJECT_ROOT / "docs/00_project/31_tier0_canary_runbook.md"
    ).read_text(encoding="utf-8")
    contract = (
        PROJECT_ROOT / "docs/00_project/32_tier0_release_record_contract.md"
    ).read_text(encoding="utf-8")
    example = json.loads(
        (
            PROJECT_ROOT / "docs/00_project/tier0_release_record.example.json"
        ).read_text(encoding="utf-8")
    )
    canary_evidence = json.loads(
        (
            PROJECT_ROOT / "docs/00_project/tier0_canary_evidence.example.json"
        ).read_text(encoding="utf-8")
    )

    assert "docs/00_project/32_tier0_release_record_contract.md" in readme
    assert "32_tier0_release_record_contract.md" in status
    assert "docs/00_project/32_tier0_release_record_contract.md" in checklist
    assert "docs/00_project/32_tier0_release_record_contract.md" in runbook
    assert "docs/00_project/tier0_release_record.example.json" in contract

    expected_fields = (
        "schema_version",
        "type",
        "production_tier",
        "release_id",
        "created_at_utc",
        "release_tag_or_checkpoint",
        "git_commit",
        "baseline_tests_passing",
        "full_pytest_command",
        "full_pytest_result",
        "canary_runbook",
        "canary_result",
        "canary_commands",
        "staged_runtime",
        "directapi_provider_calling",
        "provider_calls_implemented",
        "closed_loop_allowed",
        "provider_call_performed",
        "closed_loop_advanced",
        "known_limitations",
        "evidence_paths",
    )
    assert tuple(example) == expected_fields
    assert example["schema_version"] == 1
    assert example["type"] == "tier0_release_record"
    assert example["production_tier"] == "local_staged_cli_v0"
    assert example["release_id"] == "tier0-canary-20260706"
    assert example["created_at_utc"] == "2026-07-06T00:00:00Z"
    assert example["git_commit"] == "0123456789abcdef0123456789abcdef01234567"
    assert example["baseline_tests_passing"] == int(EXPECTED_TEST_BASELINE)
    assert example["full_pytest_command"].startswith(
        "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-"
    )
    assert example["full_pytest_command"].endswith("-p no:cacheprovider")
    assert example["full_pytest_result"] == f"{EXPECTED_TEST_BASELINE} passed"
    assert example["canary_runbook"] == "docs/00_project/31_tier0_canary_runbook.md"
    assert example["canary_result"] == "pass"
    assert example["staged_runtime"] == "FileExchangeInterface"
    for field in (
        "directapi_provider_calling",
        "provider_calls_implemented",
        "closed_loop_allowed",
        "provider_call_performed",
        "closed_loop_advanced",
    ):
        assert example[field] is False, field
    assert example["canary_commands"] == [
        "novel audit tier0-canary --input canary_input.txt",
        "novel pending tier0-canary --require-automation-ready --json",
        "novel respond tier0-canary --slot-id rebuild --prompt-hash <rebuild_prompt_hash> --response-file canary_rebuild_response.json --json",
        "novel resume tier0-canary",
        "novel pending tier0-canary --require-automation-ready --json",
        "novel respond tier0-canary --slot-id review --prompt-hash <review_prompt_hash> --response-file canary_review_response.json --json",
        "novel resume tier0-canary",
        "novel gate tier0-canary --json",
    ]
    required_limitations = {
        "DirectAPI provider calling is not implemented",
        "closed-loop automation remains disallowed",
        "Tier 0 is not a public product surface",
        "release record does not replace a release tag or immutable checkpoint",
    }
    assert required_limitations <= set(example["known_limitations"])
    assert len(set(example["known_limitations"])) == len(example["known_limitations"])
    assert "docs/00_project/30_production_readiness_checklist.md" in example[
        "evidence_paths"
    ]
    assert "docs/00_project/31_tier0_canary_runbook.md" in example["evidence_paths"]
    assert "docs/00_project/tier0_canary_evidence.example.json" in example[
        "evidence_paths"
    ]
    assert "docs/00_project/tier0_canary_gate.example.json" in example[
        "evidence_paths"
    ]
    assert "docs/00_project/tier0_release_record.example.json" in example[
        "evidence_paths"
    ]
    assert canary_evidence["schema_version"] == 1
    assert canary_evidence["type"] == "tier0_canary_evidence"
    assert canary_evidence["release_id"] == example["release_id"]
    assert canary_evidence["canary_result"] == example["canary_result"]
    assert canary_evidence["canary_commands"] == example["canary_commands"]
    assert canary_evidence["workspace_path"] == "novels/tier0-canary"
    assert canary_evidence["final_gate_ok"] is True
    assert canary_evidence["final_review_route"] == "pass"
    assert canary_evidence["final_next_workflow"] == "ContinueUnit"
    assert canary_evidence["blocking_pending_count"] == 0
    assert set(canary_evidence["final_artifact_sha256"]) == set(
        canary_evidence["final_artifact_paths"]
    )
    assert len(set(canary_evidence["final_artifact_paths"])) == len(
        canary_evidence["final_artifact_paths"]
    )
    artifact_names = [
        Path(item).name for item in canary_evidence["final_artifact_paths"]
    ]
    assert len(set(artifact_names)) == len(artifact_names)
    assert canary_evidence["gate_result_path"].endswith(
        "tier0_canary_gate.example.json"
    )
    assert len(canary_evidence["gate_result_sha256"]) == 64
    assert canary_evidence["materialized_actions"] == [
        "materialize_staged_response_only",
        "materialize_staged_response_only",
    ]
    for forbidden in (
        "secrets",
        "raw prompt text",
        "raw response text",
        "fallback provider",
        "closed-loop automation",
        "provider execution",
    ):
        assert forbidden in contract
    assert "novel-release-record" in contract
    assert "--generate" in contract
    assert "`tier0-canary-YYYYMMDD`" in contract
    assert "date must be valid and must match `created_at_utc`" in contract
    assert "YYYY-MM-DDTHH:MM:SSZ" in contract
    assert "40-character lowercase hexadecimal git commit hash" in contract
    assert "--require-git-checkpoint" in contract
    assert "full repo pytest command" in contract
    assert "python -m pytest -q --basetemp" in contract
    assert "-p no:cacheprovider" in contract
    assert "non-empty single directory-name suffix" in contract
    assert "path separators" in contract
    assert "parent directory references" in contract
    assert "--canary-evidence" in contract
    assert "--canary-gate-result" in contract
    assert "--require-canary-artifacts" in contract
    assert "--require-evidence-files --evidence-root ." in contract
    assert "--require-git-checkpoint --repo-root ." in contract
    assert "single combined validation command" in contract
    assert "final Tier 0 release validation" in contract
    assert "--canary-artifact-root" in contract
    assert "tier0_canary_evidence" in contract
    assert "`workspace_path`: `novels/tier0-canary`" in contract
    assert "final_artifact_paths" in contract
    assert "`final_artifact_paths` entries must be unique" in contract
    assert "`final_artifact_paths` artifact names must be unique" in contract
    assert "`final_artifact_paths` must match ordered workspace `output/audit` final artifacts" in contract
    assert "final_artifact_sha256" in contract
    assert "gate_result_path" in contract
    assert "gate_result_sha256" in contract
    assert "64-character sha256" in contract
    assert "`known_limitations` entries must be unique" in contract
    assert "`evidence_paths` entries must be unique" in contract
    assert "`evidence_paths` must preserve the required evidence order" in contract
    assert "release record path must be the final evidence path" in contract
    assert "canary evidence record path must appear before" in contract
    assert "must resolve to an existing file" in contract
    assert "under `workspace_path`" in contract
    assert "computed sha256 must match" in contract
    assert "expected JSON artifact shape" in contract
    assert "runtime JSON shape" in contract
    assert "semantically consistent" in contract
    assert "cross-artifact consistent" in contract
    assert "materialize_staged_response_only" in contract
    assert "release_tag_or_checkpoint" in contract
    assert "local `refs/tags/...` tag that resolves to `git_commit`" in contract
    assert "moving refs such as `HEAD` are not accepted" in contract
    assert "refuses to overwrite" in contract


def test_directapi_boundary_docs_contract():
    boundary = (
        PROJECT_ROOT / "docs/00_project/28_directapi_boundary_note.md"
    ).read_text(encoding="utf-8")
    readiness = (
        PROJECT_ROOT / "docs/00_project/29_automation_readiness_boundary.md"
    ).read_text(encoding="utf-8")

    required_phrases = [
        "DirectAPI provider calling is not implemented",
        "FileExchangeInterface",
        "action payload generation validates before returning",
        "action blocks must not include credential fields",
        "action blocks must not include execution claim fields",
        "action blocks must not include automation or materialization metadata fields",
        "canonical decimal",
        "positive prompt_bytes",
        "DirectAPIRequest(prompt, model)",
        "DirectAPIResponse(text, model)",
        "to_payload() validates before returning",
        "parse_direct_api_payload()",
        "parse_direct_api_payload() enforces the DirectAPI credential-field ban before type dispatch",
        "schema_version",
        "type",
        "payload keys must be strings",
        "CLI JSON error payload",
        "exact error fields",
        "CLI pending JSON payload",
        "exact pending fields",
        "workspace novel names",
        "output_dir must be absolute",
        "output_dir must be output/<mode>",
        "pending slot paths must be under output_dir",
        "pending slot paths must be absolute",
        "pending response paths must not already exist",
        "pending discovery output_dir must be absolute",
        "pending_count",
        "all_pending entries must match current pending discovery",
        "staged prompt/response/slot identity",
        "staged prompt/response paths must be absolute",
        "respond staged paths must be under output/<mode>",
        "pending slot prompt hashes",
        "positive pending prompt bytes",
        "pending slot prompt hashes and byte counts must match current prompt files",
        "pending slot prompt mtime must match current prompt files",
        "pending/list JSON prompt evidence must match current prompt files",
        "pending response paths must not already exist",
        "expected prompt hashes",
        "expected prompt hash binding",
        "selection method contract",
        "pending preflight requires slot_id selection",
        "pending slot prompt mtime",
        "freshness timestamps",
        "route_artifact_mtime must match current route artifacts",
        "prompt_mtime must be newer than effective freshness cutoff",
        "effective freshness cutoff",
        "CLI respond JSON payload",
        "CLI mode whitelist",
        "exact respond fields",
        "content hashes",
        "positive response materialization counts",
        "response_bytes must be at least response_chars",
        "response_source_bytes must not be less than response_bytes",
        "response_source must be an absolute path",
        "response_source must not match staged prompt_path or response_path",
        "respond JSON file evidence must match current files",
        "respond JSON source text must match staged response file",
        "respond JSON response text must be non-empty",
        "respond JSON response_source mtime must not be older than prompt_path",
        "respond JSON response_path mtime must not be older than prompt_path",
        "prompt_hash_verified",
        "CLI gate JSON payload",
        "exact gate fields",
        "gate review route matrix",
        "gate verdict consistency",
        "gate artifact paths must be absolute",
        "gate JSON artifact existence must match current files",
        "gate JSON route handoff content must match current handoff file",
        "gate JSON verdict fields must match current gate verdict",
        "artifact paths must be under output/<mode>",
        "artifact paths must share output directory",
        "gate package file must match mode",
        "route handoff file must be route_handoff.json",
        "blocking_pending_count",
        "blocking prompt files must be staged prompt filenames",
        "ContinueUnit pass requires package_present",
        "CLI list JSON row payload",
        "exact list row fields",
        "list row status/pending consistency",
        "list route/status/workflow consistency",
        "list route artifact consistency",
        "list gate artifact consistency",
        "list gate metadata completeness",
        "final result file must match mode",
        "list JSON final result route content must match current result file",
        "route handoff file must be route_handoff.json",
        "list artifact paths must be absolute",
        "list JSON artifact existence must match current files",
        "list JSON route handoff content must match current handoff file",
        "list JSON gate verdict fields must match current gate verdict",
        "artifact paths must be under output/<mode>",
        "artifact paths must share output directory",
        "artifact file fields must match path names",
        "list JSON detail must match status and route evidence",
        "pending response paths must not already exist",
        "list waiting rows must match current pending discovery",
        "latest_mtime",
        "finite non-negative latest_mtime",
        "latest_date must match latest_mtime",
        "latest_mtime must match current workspace files",
        "list row pending prompt mtime",
        "pending_prompt_mtime must not exceed latest_mtime",
        "pending_prompt_mtime must be newer than current route artifacts",
        "list row pending prompt bytes",
        "top-level list output remains an array",
        "before dispatching to the request or response parser",
        "DirectAPIInterface.call()",
        "interface name snapshot",
        "interface_name must not contain whitespace",
        "result paths must be absolute",
        "response slot paths must be absolute",
        "object-level",
        "provider request objects are checked against their prompt/model snapshots",
        "provider response objects are revalidated before returning text",
        "DirectAPI audit payloads must not include credential fields",
        "credential-field violations before generic unknown-field handling",
        "DirectAPI audit payloads must not include execution claim fields",
        "execution-claim violations before generic unknown-field handling",
        "DirectAPI audit payloads must not include automation or materialization metadata fields",
        "DirectAPI audit payload cross-contract metadata violations before generic unknown-field handling",
        "does not convert",
        "payload dictionaries",
        "automatic retry",
        "fallback provider",
        "DirectAPI must expose provider and schema errors to its caller",
    ]

    for phrase in required_phrases:
        assert phrase in boundary, phrase

    assert "parse_direct_api_payload()" in readiness
    assert "instead of branching on raw" in readiness
    assert "non-string keys must fail" in readiness
    assert "closed-loop automation" in readiness


def test_staged_entrypoints_do_not_call_direct_response_automation():
    entrypoints = [
        PROJECT_ROOT / "src/audit_short_form.py",
        PROJECT_ROOT / "src/extend_short_form.py",
        PROJECT_ROOT / "src/compose_short_form.py",
        PROJECT_ROOT / "src/rewrite_short_form.py",
        PROJECT_ROOT / "src/novel_cli.py",
    ]

    for path in entrypoints:
        text = path.read_text(encoding="utf-8")
        assert "DirectAPIInterface" not in text, path
        assert "StagedResponseRunner" not in text, path


def test_novel_cli_exact_field_call_sites_declare_cross_contract_metadata_policy():
    # F8 拆分：校验函数簇移至 src/cli/validation.py，跨两文件扫描保持覆盖
    sources = [
        (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8"),
        (PROJECT_ROOT / "src/cli/validation.py").read_text(encoding="utf-8"),
    ]
    call_sites = []
    for text in sources:
        tree = ast.parse(text)
        call_sites += [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_validate_exact_fields"
        ]

    assert call_sites
    missing_policy = [
        node.lineno
        for node in call_sites
        if not any(
            keyword.arg == "forbidden_cross_contract_metadata_fields"
            for keyword in node.keywords
        )
    ]
    assert missing_policy == []


def test_novel_cli_ok_json_payload_literals_declare_identity_fields():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    missing_identity_fields = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "payload"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        if enclosing_function_name(node) == "_json_error_payload":
            continue
        literal_keys = {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if "ok" not in literal_keys:
            continue
        required_identity = {"schema_version", "command"}
        if not required_identity.issubset(literal_keys):
            missing_identity_fields.append(node.lineno)

    assert missing_identity_fields == []


def test_novel_cli_ok_true_json_payload_literals_do_not_declare_error_fields():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)

    ok_true_payload_error_fields = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "payload"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        literal_items = {
            key.value: value
            for key, value in zip(node.value.keys, node.value.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        ok_value = literal_items.get("ok")
        if not (
            isinstance(ok_value, ast.Constant)
            and ok_value.value is True
        ):
            continue
        error_fields = {"error_stage", "error_type", "error"} & set(literal_items)
        if error_fields:
            ok_true_payload_error_fields.append((node.lineno, sorted(error_fields)))

    assert ok_true_payload_error_fields == []


def test_novel_cli_ok_false_json_payload_literals_declare_error_fields():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    ok_false_payload_missing_error_fields = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "payload"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        if enclosing_function_name(node) == "_json_error_payload":
            continue
        literal_items = {
            key.value: value
            for key, value in zip(node.value.keys, node.value.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        ok_value = literal_items.get("ok")
        if not (
            isinstance(ok_value, ast.Constant)
            and ok_value.value is False
        ):
            continue
        required_error_fields = {"error_stage", "error_type", "error"}
        missing_fields = required_error_fields - set(literal_items)
        if missing_fields:
            ok_false_payload_missing_error_fields.append(
                (node.lineno, sorted(missing_fields))
            )

    assert ok_false_payload_missing_error_fields == []


def test_novel_cli_stdout_json_dumps_use_contract_variables():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)

    def is_json_dumps_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
        )

    def is_printing_json_dumps(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_call(node.args[0])
        )

    non_contract_stdout_dumps = []
    for node in ast.walk(tree):
        if not is_printing_json_dumps(node):
            continue
        dumped_value = node.args[0].args[0]
        if (
            isinstance(dumped_value, ast.Name)
            and dumped_value.id in {"payload", "rows"}
        ):
            continue
        non_contract_stdout_dumps.append(node.lineno)

    assert non_contract_stdout_dumps == []


def test_novel_cli_json_object_payload_emits_validate_before_print():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    def is_json_dumps_payload_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "payload"
        )

    def is_printing_json_payload(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_payload_call(node.args[0])
        )

    def enclosing_statement(node: ast.AST) -> ast.stmt:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if isinstance(current, ast.stmt):
                return current
        raise AssertionError("call has no enclosing statement")

    def sibling_body(statement: ast.stmt) -> list[ast.stmt]:
        parent = parent_by_child[statement]
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(parent, attr, None)
            if isinstance(body, list) and statement in body:
                return body
        raise AssertionError("statement has no sibling body")

    def assigns_payload_from_helper(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "payload"
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "_json_error_payload"
        )

    def validates_payload(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id.startswith("_validate_")
            and statement.value.func.id.endswith("_json_payload")
            and len(statement.value.args) == 1
            and isinstance(statement.value.args[0], ast.Name)
            and statement.value.args[0].id == "payload"
        )

    unvalidated_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_payload(node):
            continue
        statement = enclosing_statement(node)
        body = sibling_body(statement)
        index = body.index(statement)
        previous = body[:index]
        if any(assigns_payload_from_helper(stmt) for stmt in previous):
            continue
        if any(validates_payload(stmt) for stmt in previous):
            continue
        unvalidated_emits.append(statement.lineno)

    assert unvalidated_emits == []


def test_novel_cli_json_object_payload_emits_validate_after_last_assignment():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    def is_json_dumps_payload_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "payload"
        )

    def is_printing_json_payload(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_payload_call(node.args[0])
        )

    def enclosing_statement(node: ast.AST) -> ast.stmt:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if isinstance(current, ast.stmt):
                return current
        raise AssertionError("call has no enclosing statement")

    def sibling_body(statement: ast.stmt) -> list[ast.stmt]:
        parent = parent_by_child[statement]
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(parent, attr, None)
            if isinstance(body, list) and statement in body:
                return body
        raise AssertionError("statement has no sibling body")

    def assigns_payload(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "payload"
                for target in statement.targets
            )
        )

    def assigns_payload_from_helper(statement: ast.stmt) -> bool:
        return (
            assigns_payload(statement)
            and isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "_json_error_payload"
        )

    def validates_payload(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id.startswith("_validate_")
            and statement.value.func.id.endswith("_json_payload")
            and len(statement.value.args) == 1
            and isinstance(statement.value.args[0], ast.Name)
            and statement.value.args[0].id == "payload"
        )

    stale_validation_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_payload(node):
            continue
        statement = enclosing_statement(node)
        body = sibling_body(statement)
        index = body.index(statement)
        previous = body[:index]
        assignment_indexes = [
            prior_index
            for prior_index, prior_statement in enumerate(previous)
            if assigns_payload(prior_statement)
        ]
        if not assignment_indexes:
            stale_validation_emits.append(statement.lineno)
            continue
        last_assignment_index = assignment_indexes[-1]
        last_assignment = previous[last_assignment_index]
        if assigns_payload_from_helper(last_assignment):
            continue
        if any(
            validates_payload(prior_statement)
            for prior_statement in previous[last_assignment_index + 1 :]
        ):
            continue
        stale_validation_emits.append(statement.lineno)

    assert stale_validation_emits == []


def test_novel_cli_json_object_payload_emits_validate_after_last_mutation():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def is_json_dumps_payload_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "payload"
        )

    def is_printing_json_payload(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_payload_call(node.args[0])
        )

    def enclosing_function(node: ast.AST) -> ast.FunctionDef:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return current
        raise AssertionError("call has no enclosing function")

    def assigns_payload_name(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "payload"
                for target in node.targets
            )
        )

    def assigns_payload_subscript(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "payload"
                for target in node.targets
            )
        )

    def mutates_payload_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {"clear", "pop", "popitem", "setdefault", "update"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "payload"
        )

    def assigns_payload_from_helper(node: ast.AST) -> bool:
        return (
            assigns_payload_name(node)
            and isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_json_error_payload"
        )

    def validates_payload_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("_validate_")
            and node.func.id.endswith("_json_payload")
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "payload"
        )

    stale_mutation_validation_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_payload(node):
            continue
        print_line = node.lineno
        function = enclosing_function(node)
        mutations = [
            candidate
            for candidate in ast.walk(function)
            if hasattr(candidate, "lineno")
            and candidate.lineno < print_line
            and (
                assigns_payload_name(candidate)
                or assigns_payload_subscript(candidate)
                or mutates_payload_call(candidate)
            )
        ]
        if not mutations:
            stale_mutation_validation_emits.append(print_line)
            continue
        last_mutation = max(mutations, key=lambda candidate: candidate.lineno)
        if assigns_payload_from_helper(last_mutation):
            continue
        validation_lines = [
            candidate.lineno
            for candidate in ast.walk(function)
            if hasattr(candidate, "lineno")
            and last_mutation.lineno < candidate.lineno < print_line
            and validates_payload_call(candidate)
        ]
        if not validation_lines:
            stale_mutation_validation_emits.append(print_line)

    assert stale_mutation_validation_emits == []


def test_novel_cli_json_list_rows_emits_validate_before_print():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    def is_json_dumps_rows_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "rows"
        )

    def is_printing_json_rows(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_rows_call(node.args[0])
        )

    def enclosing_statement(node: ast.AST) -> ast.stmt:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if isinstance(current, ast.stmt):
                return current
        raise AssertionError("call has no enclosing statement")

    def sibling_body(statement: ast.stmt) -> list[ast.stmt]:
        parent = parent_by_child[statement]
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(parent, attr, None)
            if isinstance(body, list) and statement in body:
                return body
        raise AssertionError("statement has no sibling body")

    def validates_rows(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "_validate_list_json_payload"
            and len(statement.value.args) == 1
            and isinstance(statement.value.args[0], ast.Name)
            and statement.value.args[0].id == "rows"
        )

    unvalidated_rows_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_rows(node):
            continue
        statement = enclosing_statement(node)
        body = sibling_body(statement)
        index = body.index(statement)
        previous = body[:index]
        if any(validates_rows(stmt) for stmt in previous):
            continue
        unvalidated_rows_emits.append(statement.lineno)

    assert unvalidated_rows_emits == []


def test_novel_cli_json_list_rows_emits_validate_after_last_mutation():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def is_json_dumps_rows_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "rows"
        )

    def is_printing_json_rows(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_rows_call(node.args[0])
        )

    def enclosing_function(node: ast.AST) -> ast.FunctionDef:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return current
        raise AssertionError("call has no enclosing function")

    def is_rows_assignment(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "rows"
                for target in node.targets
            )
        )

    def is_rows_mutating_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend", "insert", "clear", "pop", "remove"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "rows"
        )

    def is_rows_validation_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_validate_list_json_payload"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "rows"
        )

    stale_rows_validation_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_rows(node):
            continue
        print_line = node.lineno
        function = enclosing_function(node)
        mutation_lines = [
            candidate.lineno
            for candidate in ast.walk(function)
            if hasattr(candidate, "lineno")
            and candidate.lineno < print_line
            and (is_rows_assignment(candidate) or is_rows_mutating_call(candidate))
        ]
        if not mutation_lines:
            stale_rows_validation_emits.append(print_line)
            continue
        last_mutation_line = max(mutation_lines)
        validation_lines = [
            candidate.lineno
            for candidate in ast.walk(function)
            if hasattr(candidate, "lineno")
            and last_mutation_line < candidate.lineno < print_line
            and is_rows_validation_call(candidate)
        ]
        if not validation_lines:
            stale_rows_validation_emits.append(print_line)

    assert stale_rows_validation_emits == []


def test_novel_cli_json_list_rows_emits_validate_after_in_place_mutation():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def is_json_dumps_rows_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "rows"
        )

    def is_printing_json_rows(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) >= 1
            and is_json_dumps_rows_call(node.args[0])
        )

    def enclosing_function(node: ast.AST) -> ast.FunctionDef:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return current
        raise AssertionError("call has no enclosing function")

    def assigns_rows_subscript(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "rows"
                for target in node.targets
            )
        )

    def augassigns_rows(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "rows"
        )

    def validates_rows_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_validate_list_json_payload"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "rows"
        )

    stale_in_place_validation_emits = []
    for node in ast.walk(tree):
        if not is_printing_json_rows(node):
            continue
        print_line = node.lineno
        function = enclosing_function(node)
        mutations = [
            candidate
            for candidate in ast.walk(function)
            if hasattr(candidate, "lineno")
            and candidate.lineno < print_line
            and (assigns_rows_subscript(candidate) or augassigns_rows(candidate))
        ]
        for mutation in mutations:
            validation_lines = [
                candidate.lineno
                for candidate in ast.walk(function)
                if hasattr(candidate, "lineno")
                and mutation.lineno < candidate.lineno < print_line
                and validates_rows_call(candidate)
            ]
            if not validation_lines:
                stale_in_place_validation_emits.append((print_line, mutation.lineno))

    assert stale_in_place_validation_emits == []


def test_novel_cli_empty_list_json_emits_validate_before_print():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    def is_printing_empty_json_list(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "[]"
        )

    def enclosing_statement(node: ast.AST) -> ast.stmt:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if isinstance(current, ast.stmt):
                return current
        raise AssertionError("call has no enclosing statement")

    def sibling_body(statement: ast.stmt) -> list[ast.stmt]:
        parent = parent_by_child[statement]
        for attr in ("body", "orelse", "finalbody"):
            body = getattr(parent, attr, None)
            if isinstance(body, list) and statement in body:
                return body
        raise AssertionError("statement has no sibling body")

    def validates_empty_list(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "_validate_list_json_payload"
            and len(statement.value.args) == 1
            and isinstance(statement.value.args[0], ast.List)
            and statement.value.args[0].elts == []
        )

    unvalidated_empty_list_emits = []
    for node in ast.walk(tree):
        if not is_printing_empty_json_list(node):
            continue
        statement = enclosing_statement(node)
        body = sibling_body(statement)
        index = body.index(statement)
        previous = body[:index]
        if any(validates_empty_list(stmt) for stmt in previous):
            continue
        unvalidated_empty_list_emits.append(statement.lineno)

    assert unvalidated_empty_list_emits == []


def test_novel_cli_json_error_payloads_are_built_by_helper():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    direct_error_literals = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        literal_items = {
            key.value: value
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant)
        }
        literal_keys = set(literal_items)
        base_error_keys = {
            "ok",
            "schema_version",
            "error_stage",
            "error_type",
            "error",
        }
        runtime_error_keys = {*base_error_keys, "command", "novel"}
        if not (
            literal_keys in (base_error_keys, runtime_error_keys)
            and enclosing_function_name(node) != "_json_error_payload"
        ):
            continue
        direct_error_literals.append(node.lineno)

    assert direct_error_literals == []


def test_novel_cli_runtime_error_payload_call_sites_include_runtime_context():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_json_error_payload"
    ]

    assert call_sites
    for node in call_sites:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        if enclosing_function_name(node) == "error":
            assert "include_runtime_context" not in keywords
            continue
        include_runtime_context = keywords.get("include_runtime_context")
        assert isinstance(include_runtime_context, ast.Constant), node.lineno
        assert include_runtime_context.value is True, node.lineno
        for required_context in ("command", "novel"):
            assert required_context in keywords, node.lineno


def test_novel_cli_base_json_error_payload_call_site_is_argument_parser_only():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    classes = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    def enclosing_class_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in classes:
                return classes[current]
        return None

    base_call_sites = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_json_error_payload"
        ):
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        include_runtime_context = keywords.get("include_runtime_context")
        if (
            isinstance(include_runtime_context, ast.Constant)
            and include_runtime_context.value is True
        ):
            continue
        base_call_sites.append(
            (
                enclosing_class_name(node),
                enclosing_function_name(node),
            )
        )

    assert base_call_sites == [("NovelArgumentParser", "error")]


def test_novel_cli_json_error_payload_call_sites_declare_error_stage_by_context():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_json_error_payload"
    ]

    assert call_sites
    for node in call_sites:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        error_stage = keywords.get("error_stage")
        assert isinstance(error_stage, ast.Constant), node.lineno
        expected_stage = (
            "argument" if enclosing_function_name(node) == "error" else "runtime"
        )
        assert error_stage.value == expected_stage, node.lineno


def test_novel_cli_json_error_payload_call_sites_declare_error_type_by_context():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    classes = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    def enclosing_class_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in classes:
                return classes[current]
        return None

    def derives_from_exception_class_name(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "__name__"
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "type"
            and len(node.value.args) == 1
        )

    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_json_error_payload"
    ]

    assert call_sites
    for node in call_sites:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        error_type = keywords.get("error_type")
        if (
            enclosing_class_name(node) == "NovelArgumentParser"
            and enclosing_function_name(node) == "error"
        ):
            assert isinstance(error_type, ast.Constant), node.lineno
            assert error_type.value == "ArgumentError", node.lineno
            continue
        assert error_type is not None, node.lineno
        assert derives_from_exception_class_name(error_type), node.lineno


def test_novel_cli_json_error_payload_call_sites_declare_error_message_by_context():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    classes = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    def enclosing_class_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in classes:
                return classes[current]
        return None

    def derives_from_exception_message(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "exc"
        )

    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_json_error_payload"
    ]

    assert call_sites
    for node in call_sites:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        error = keywords.get("error")
        if (
            enclosing_class_name(node) == "NovelArgumentParser"
            and enclosing_function_name(node) == "error"
        ):
            assert isinstance(error, ast.Name), node.lineno
            assert error.id == "message", node.lineno
            continue
        assert error is not None, node.lineno
        assert derives_from_exception_message(error), node.lineno


def test_novel_cli_json_error_payload_call_sites_are_guarded_by_json_mode():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    parent_by_child: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_by_child[child] = parent

    functions = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    classes = {
        node: node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }

    def enclosing_function_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in functions:
                return functions[current]
        return None

    def enclosing_class_name(node: ast.AST) -> str | None:
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if current in classes:
                return classes[current]
        return None

    def ancestor_if_tests(node: ast.AST) -> list[ast.AST]:
        tests = []
        current = node
        while current in parent_by_child:
            current = parent_by_child[current]
            if isinstance(current, ast.If):
                tests.append(current.test)
        return tests

    def is_emit_json_errors_guard(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "emit_json_errors"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    def is_args_json_guard(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) == 3
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "args"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "json"
            and isinstance(node.args[2], ast.Constant)
            and node.args[2].value is False
        )

    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_json_error_payload"
    ]

    assert call_sites
    for node in call_sites:
        tests = ancestor_if_tests(node)
        if (
            enclosing_class_name(node) == "NovelArgumentParser"
            and enclosing_function_name(node) == "error"
        ):
            assert any(is_emit_json_errors_guard(test) for test in tests), node.lineno
            continue
        assert any(is_args_json_guard(test) for test in tests), node.lineno


def test_novel_cli_gate_surfaces_share_route_gate_verdict_helper():
    # F8 拆分：_route_gate_verdict 随校验簇移入 src/cli/validation.py
    helper_text = (PROJECT_ROOT / "src/cli/validation.py").read_text(encoding="utf-8")
    helper_tree = ast.parse(helper_text)
    helper = {
        node.name: node
        for node in helper_tree.body
        if isinstance(node, ast.FunctionDef)
    }["_route_gate_verdict"]

    helper_source = ast.get_source_segment(
        helper_text,
        helper,
    )
    assert "OrchestrationGateUnit" in helper_source
    assert "verify_entry" in helper_source

    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    for name in ("_run_gate", "_gate_metadata"):
        source = ast.get_source_segment(text, functions[name])
        calls = [
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_route_gate_verdict" in calls
        assert "OrchestrationGateUnit" not in source
        assert "verify_entry" not in source


def test_staged_entry_response_reads_are_bom_aware():
    entrypoints = [
        PROJECT_ROOT / "src/audit_short_form.py",
        PROJECT_ROOT / "src/extend_short_form.py",
        PROJECT_ROOT / "src/compose_short_form.py",
        PROJECT_ROOT / "src/rewrite_short_form.py",
    ]

    for path in entrypoints:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        assert 'encoding="utf-8-sig"' in text, path
        assert "_read_response_text" in text, path
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "read_text":
                continue
            encoding = next(
                (kw.value for kw in node.keywords if kw.arg == "encoding"),
                None,
            )
            if not (
                isinstance(encoding, ast.Constant)
                and encoding.value == "utf-8"
            ):
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and "response" in receiver.id:
                raise AssertionError(
                    f"{path}:{node.lineno} response reads must use "
                    "_read_response_text()"
                )
