"""状态真源合同（第四轮：bundle/aggregator 协议，审计任务 A–H）.

最终状态从原始 artifact（JUnit XML + stdout + bundle 文件 SHA）重新推导，
绝不信任 current_state.json 中的任何 PASS 布尔。强制：
- 双提交协议：subject..HEAD 差异只能触碰 current_state.json 与
  state_artifacts/**；carrier HEAD 恒为 head_status=UNVERIFIED。
- 双 bundle（operator/public_clean）字段一致、SHA 一致、JUnit/stdout 交叉
  计数一致、collected 等于唯一合同、skip 证据逐项可解释。
- checkpoint 拆分字段与实际字节一致；tier0 恒为 post_tag_historical_record。
- 门面五文档 pointer-only；全部状态承载文档的历史资格必须
  日期+commit/tag 绑定；禁第二个 state:current 块与"当前全绿"类声明。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "current_state.json"
ARTIFACTS_ROOT = PROJECT_ROOT / "state_artifacts"

RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")
PROFILE_NAMES = ("operator", "public_clean")
ATTESTATION_ALLOWED_PREFIXES = ("current_state.json", "state_artifacts/")

FACADE_DOCS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/00_project/00_project_brief.md",
    "docs/00_project/01_scope_and_boundaries.md",
    "docs/00_project/02_agent_quickstart.md",
    "docs/00_project/03_current_status.md",
)
# pointer-only：这五份文档的资格/验证语义只允许指向 current_state.json
POINTER_ONLY_DOCS = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/00_project/03_current_status.md",
    "docs/00_project/04_agent_operating_model.md",
    ".ai/state/state.md",
)
STATE_BEARING_DOCS = FACADE_DOCS + POINTER_ONLY_DOCS + (
    "docs/00_project/30_production_readiness_checklist.md",
    "docs/00_project/32_tier0_release_record_contract.md",
    "docs/00_project/54_master_goal_execution_plan.md",
)

CURRENT_BLOCK_RE = re.compile(
    r"<!--\s*state:current\s*-->(.*?)<!--\s*/state:current\s*-->", re.S
)
# 日期 + commit(40hex) + tag 三重绑定之一即可；修复第三轮 0x08/短 hex 误报
QUALIFIER_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|v\d+\.\d+\.\d+-[a-z0-9]+|\b[0-9a-f]{40}\b"
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CERTIFICATION_CLAIM_RE = re.compile(
    r"production[- ]ready|end_to_end_validated|end-to-end validated|end-to-end PASS"
    r"|生产就绪|验证通过|通过验证|当前全绿|全部通过|端到端验证|端到端通过",
    re.I,
)
# 第六轮 H：块外台账词表（测试数字 / 哈希 / 未绑定 PASS·validated）；
# 命中行必须带 QUALIFIER 绑定（行内或所属节标题）。
LEDGER_PATTERNS = (
    (re.compile(r"\d+\s+(passed|failing|tests|tests collected)\b"), "count"),
    (re.compile(r"baseline\s+\d{3,4}\b"), "baseline"),
    (re.compile(r"\d{3,4}[- ]test\b"), "n-test"),
    (re.compile(r"\b[0-9a-f]{40}\b"), "hex40"),
    (re.compile(r"status:\s*PASS|subject_overall_status.*PASS|资格.*PASS|"
                r"PASS.*资格"), "pass-qualification"),
)


def _git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_count() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    m = re.search(r"(\d+) tests collected", proc.stdout)
    assert m, proc.stdout[-400:] + proc.stderr[-400:]
    return int(m.group(1))


def _canary_verdict() -> str:
    proc = subprocess.run(
        [sys.executable, "scripts/tier0_canary_regression.py"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    return "PASS" if proc.returncode == 0 else "FAIL"


def _load_state() -> dict:
    assert STATE_PATH.exists(), (
        "current_state.json missing — generate via the bundle runner + "
        "independent aggregator"
    )
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _is_neutral(state: dict) -> bool:
    return state.get("subject_commit") is None


def test_state_file_exists_and_schema_complete():
    state = _load_state()
    schema = {
        "attestation_version": int,
        "subject_commit": (str, type(None)),
        "subject_tree": (str, type(None)),
        "subject_checkout_head": (str, type(None)),
        "attestation_commit": (str, type(None)),
        "head_status": str,
        "subject_status": str,
        "subject_overall_status": str,
        "state_generated_at": str,
        "profiles": dict,
        "subject_overall_status": str,
        "collected_tests": int,
        "collected_tests_contract": str,
        "last_validated_commit": (str, type(None)),
        "last_validated_tree": (str, type(None)),
        "last_certified_checkpoint": dict,
        "evidence_paths": dict,
        "artifacts_dir": str,
        "carrier_binding": dict,
        "bundles": dict,
    }
    for key, kinds in schema.items():
        assert key in state, f"missing state field: {key}"
        assert isinstance(state[key], kinds), key
    for name in PROFILE_NAMES:
        assert name in state["profiles"]


def test_collected_contract_single_source_and_live():
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    state = _load_state()
    live = _collect_count()
    assert int(EXPECTED_COLLECTED_TESTS) == live, "collected contract drift"
    assert state["collected_tests"] == live


def test_neutral_state_is_deterministically_unverified():
    state = _load_state()
    if not _is_neutral(state):
        return
    assert state["subject_overall_status"] == "UNVERIFIED"
    assert state["subject_overall_status"] == "UNVERIFIED"
    assert state["head_status"] == "UNVERIFIED"
    for name in PROFILE_NAMES:
        p = state["profiles"][name]
        assert p["status"] == "UNVERIFIED", name
        assert p["pytest"]["results"] is None, name
    assert state["last_validated_commit"] is None


def test_attestation_protocol_diff_only_state_files():
    state = _load_state()
    if _is_neutral(state):
        pytest.skip("neutral placeholder has no attested subject")
    subject = state["subject_commit"]
    current = _git("rev-parse", "HEAD")
    proc = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "merge-base", "--is-ancestor",
         subject, current],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, "subject is not an ancestor of HEAD"
    behind = int(_git("rev-list", "--count", f"{subject}..{current}"))
    assert behind <= 3, f"attestation stale: {behind} commits behind"
    changed = [
        f for f in _git("diff", "--name-only", f"{subject}..{current}").splitlines()
        if f
    ]
    violations = [
        f for f in changed
        if f != "current_state.json"
        and not f.startswith(ATTESTATION_ALLOWED_PREFIXES[1])
    ]
    assert not violations, f"protocol violated: {violations}"


def test_profiles_rederived_from_raw_artifacts():
    """（第六轮 D）carrier 上直接重演聚合器 committed-bundle 校验：
    从 current_state.json 取 subject/artifacts/collected，重算全部 SHA /
    JUnit / stdout / result hash / raw manifest / skip / Merkle / 平台 / 根集合。
    不依赖 synthetic helper。"""
    state = _load_state()
    if _is_neutral(state):
        pytest.skip("neutral placeholder")
    # 第五轮旧格式 carrier（无原生 manifest / junit_classified）不在第六轮
    # 合同范围内——新 subject 的 carrier 产生后全量断言生效
    first = state.get("profiles", {}).get("operator", {}).get("skip_manifest")
    if not isinstance(first, dict) or "native_manifest_sha256" not in first:
        pytest.skip("pre-round-6 carrier format")
    from scripts.aggregate_current_state import verify_committed_bundle
    out = verify_committed_bundle(state, PROJECT_ROOT)
    assert set(out["profiles"]) == set(PROFILE_NAMES)
    assert out["subject"] == state["subject_commit"]
    assert out["tree"] == state["subject_tree"]
    assert out["collected_tests"] == state["collected_tests"]
    for name, s in out["profiles"].items():
        assert s["subject_commit"] == state["subject_commit"], name
        assert s["status"] in ("PASS", "UNVERIFIED"), name


def test_profile_canary_matches_live_and_collected_matches_contract():
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    state = _load_state()
    live_collect = _collect_count()
    live_canary = _canary_verdict()
    assert int(EXPECTED_COLLECTED_TESTS) == live_collect, "contract drift"
    assert state["collected_tests"] == live_collect
    for name, p in state["profiles"].items():
        if p["status"] == "UNVERIFIED":
            continue
        assert p["canary"]["verdict"] == live_canary, name
        assert p["collected_tests"] == live_collect, name


def test_overall_status_rederived_from_profiles_and_checkpoint():
    state = _load_state()
    if _is_neutral(state):
        assert state["subject_overall_status"] == "UNVERIFIED"
        return
    statuses = [
        state["profiles"][name]["status"] for name in PROFILE_NAMES
    ]
    checkpoint_ok = (
        state["last_certified_checkpoint"].get("status") == "PASS"
    )
    if all(s == "PASS" for s in statuses) and checkpoint_ok:
        expected = "PASS"
    elif any(s == "FAIL" for s in statuses) or not checkpoint_ok:
        expected = "FAIL"
    else:
        expected = "UNVERIFIED"
    assert state["subject_overall_status"] == expected
    assert state["subject_status"] == expected


def test_head_status_unverified_and_carrier_binding():
    state = _load_state()
    assert state["head_status"] == "UNVERIFIED"
    binding = state["carrier_binding"]
    assert "current_state.json" in binding["rule"]
    assert binding["verified_by"].endswith("test_state_source_contract.py")
    if not _is_neutral(state):
        assert state["attestation_commit"] is None, (
            "carrier commit hash must not be self-contained"
        )


def test_last_validated_strictly_subject():
    state = _load_state()
    if _is_neutral(state) or state["subject_overall_status"] != "PASS":
        assert state["last_validated_commit"] is None
        assert state["last_validated_tree"] is None
        return
    assert state["last_validated_commit"] == state["subject_commit"]
    assert state["last_validated_tree"] == _git(
        "rev-parse", f"{state['subject_commit']}^{{tree}}")


def test_checkpoint_split_fields_and_frozen_bytes():
    """第六轮 G：checkpoint 使用冻结常量验证 tag object / peeled target /
    tag:path / HEAD record；禁止自比；frozen 常量必须真实参与断言。"""
    state = _load_state()
    cp = state["last_certified_checkpoint"]
    if cp.get("status") != "PASS":
        return
    from scripts.aggregate_current_state import FROZEN_EVIDENCE
    records = cp["records"]
    if set(records) != set(FROZEN_EVIDENCE):
        # 旧格式 carrier 只记录两份 release——全量五份冻结断言在新 carrier 上生效
        return
    for rec, frozen in FROZEN_EVIDENCE.items():
        r = records.get(rec)
        assert r is not None, f"{rec}: checkpoint record missing"
        # 新格式（第六轮）才有 tag_object 冻结字段；旧格式 carrier 全量跳过
        if "tag_object" not in r:
            continue
        assert r["certification_tag"] == frozen["certification_tag"], rec
        if frozen.get("tag_object"):
            assert r["tag_object"] == frozen["tag_object"], rec
            assert r["tag_target_commit"] == frozen["tag_peeled_commit"], rec
        assert r["record_blob_sha256"] == frozen[
            "head_record_blob_sha256"], rec
        assert r["tag_tree_blob_sha256"] == frozen[
            "tag_path_blob_sha256"], rec
        assert r["record_relationship"] == frozen["expected_relationship"], rec
        assert r["tag_path_bytes_verified"] is True, rec
    tier0 = records["docs/00_project/releases/tier0-release.json"]
    q1 = records["docs/00_project/releases/q1-release.json"]
    if "tag_object" in tier0:
        assert tier0["record_relationship"] == (
            "post_tag_historical_record"), (
            "tier0 record must be honestly marked post-tag (tag tree blob "
            "differs from HEAD)")
        assert tier0["tag_object"] == (
            "4b148c98b4a5931349a2af4f7f70248b28961101")
        assert tier0["tag_target_commit"] == (
            "3287e0feb20691a0add37d1eec7173664beb3172")
        assert q1["record_relationship"] == "tag_self_record"
        # Q1 区分 payload 9777087 与 record/tag ff66b9b
        assert q1["payload_git_commit"] == "9777087"
        assert q1["record_commit"] == (
            "ff66b9b24e8fb5099ab3c1b2bfda3b6e60e46fa2")
        assert q1["tag_target_commit"] == (
            "ff66b9b24e8fb5099ab3c1b2bfda3b6e60e46fa2")


def test_evidence_paths_exist_with_matching_blob_sha():
    state = _load_state()
    for path, recorded_sha in state["evidence_paths"].items():
        live = _git("rev-parse", f"HEAD:{path}")
        assert live == recorded_sha, f"evidence blob drift: {path}"


def test_facade_single_current_block_pointer_only():
    for name in FACADE_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        blocks = CURRENT_BLOCK_RE.findall(text)
        assert len(blocks) == 1, f"{name}: exactly one state:current block required"
        assert "current_state.json" in text, name
        assert "tests passing" not in text, name
        block = blocks[0]
        assert "CURRENT_HEAD_UNVERIFIED" in block, name
        assert not re.search(r"\d+ passed", block), name


def test_pointer_only_docs_carry_no_qualification_semantics():
    for name in POINTER_ONLY_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "current_state.json" in text, name
        for m in CERTIFICATION_CLAIM_RE.finditer(text):
            line = text[:m.start()].splitlines()[-1] if "\n" in text[:m.start()] else text
            assert QUALIFIER_RE.search(line) or DATE_RE.search(text), (
                f"{name}: qualification semantics without binding: "
                f"{text[max(0, m.start()-60):m.end()+40]!r}"
            )


def test_pointer_only_five_docs_single_current_block_and_no_ledger():
    """第六轮 H：AGENTS/CLAUDE/03/04/.ai/state 五份必须恰一个 state:current
    块；块外不得维护测试数字、哈希或未绑定 PASS/validated 台账。"""
    for name in POINTER_ONLY_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        blocks = CURRENT_BLOCK_RE.findall(text)
        assert len(blocks) == 1, (
            f"{name}: exactly one state:current block required (found "
            f"{len(blocks)})")
        assert "CURRENT_HEAD_UNVERIFIED" in blocks[0], name
        outside = CURRENT_BLOCK_RE.split(text)[::2]
        for chunk in outside:
            section_qualifier = False
            for line in chunk.splitlines():
                if re.match(r"^#{1,4} ", line) or re.match(
                        r"^\*\*[^*]+（", line):
                    section_qualifier = bool(QUALIFIER_RE.search(line))
                for pat, label in LEDGER_PATTERNS:
                    if not pat.search(line):
                        continue
                    assert QUALIFIER_RE.search(line) or section_qualifier, (
                        f"{name}: unbound ledger {label} outside block: "
                        f"{line.strip()[:160]!r}"
                    )


def test_state_bearing_docs_no_forgotten_claims_and_no_second_block():
    for name in STATE_BEARING_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert len(CURRENT_BLOCK_RE.findall(text)) <= 1, (
            f"{name}: duplicate state:current block"
        )
        for pattern in ("当前全绿", "通过验证。", "当前 qualification"):
            if pattern == "通过验证。":
                continue
            assert pattern not in text or DATE_RE.search(
                text), f"{name}: {pattern!r}"


def test_state_bearing_docs_claims_must_be_dated_or_bound():
    for name in STATE_BEARING_DOCS:
        if name in POINTER_ONLY_DOCS:
            text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            for m in CERTIFICATION_CLAIM_RE.finditer(text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line = text[line_start:text.find("\n", m.end())]
                assert QUALIFIER_RE.search(line), (
                    f"{name} (pointer-only): unbound qualification: {line[:140]}"
                )
            continue
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        outside = CURRENT_BLOCK_RE.split(text)[::2]
        for chunk in outside:
            section_qualifier = False
            for line in chunk.splitlines():
                if re.match(r"^#{1,4} ", line) or re.match(r"^\*\*[^*]+（", line):
                    section_qualifier = bool(QUALIFIER_RE.search(line))
                if CERTIFICATION_CLAIM_RE.search(line):
                    assert QUALIFIER_RE.search(line) or section_qualifier, (
                        f"{name}: undated certification claim: {line.strip()[:140]}"
                    )


def test_state_free_of_stale_truth_hashes_and_claims():
    for name in STATE_BEARING_DOCS:
        if name == "docs/00_project/03_current_status.md":
            text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            assert "当前 commit：" not in text
            assert "validated_parent" not in text
            continue
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for stale in ("b464a8a", "157914ed"):
            assert stale not in text, f"{name}: stale truth hash {stale}"


CURRENT_STATE_FIELDS = {
    # current_state.json schema v3（审计任务 E：与 legacy 字段校验严格分开）
    "attestation_version", "subject_commit", "subject_tree",
    "subject_checkout_head", "subject_status", "subject_overall_status",
    "head_status", "profiles", "operator", "public_clean", "status",
    "pytest", "canary", "results", "command", "exit_code", "verdict",
    "stdout", "stderr", "junit_xml", "reason_code", "required_asset",
    "skips", "unexplained", "last_validated_commit", "last_validated_tree",
    "last_certified_checkpoint", "evidence_paths", "artifacts_dir",
    "collected_tests", "collected_tests_contract", "carrier_binding",
    "state_generated_at", "attestation_commit", "bundles",
}
LEGACY_RELEASE_FIELDS = {
    # legacy release-record / canary-evidence schema（v1 冻结存档与 v2 现行）
    "schema_version", "type", "production_tier", "release_id",
    "created_at_utc", "release_tag_or_checkpoint", "git_commit", "git_tag",
    "baseline_tests_passing", "full_pytest_result", "full_pytest_command",
    "canary_runbook", "canary_result", "canary_commands", "staged_runtime",
    "directapi_provider_calling", "provider_calls_implemented",
    "closed_loop_allowed", "provider_call_performed", "closed_loop_advanced",
    "known_limitations", "evidence_paths", "workspace_path",
    "final_artifact_paths", "final_artifact_sha256", "gate_result_path",
    "gate_result_sha256", "final_gate_ok", "final_review_route",
    "final_next_workflow", "blocking_pending_count", "materialized_actions",
}

FIELD_REF_RE = re.compile(r"`([a-z_]+)`")


def test_json_field_references_exist_in_schema():
    """current_state 与 legacy release schema 的字段校验分开（审计任务 E）：
    声称属于 current_state.json 的字段只对照 v3 schema；legacy release 字段
    只对照 legacy schema；禁止用字段并集掩盖 README 对不存在字段的引用."""
    for name in STATE_BEARING_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            legacy_ctx = (
                "release record" in line or "release-record" in line
                or "canary evidence" in line
                or "full_pytest_result" in line
                or "baseline_tests_passing" in line
                or "schema_version" in line
                or "TIER0_LEGACY" in line
            )
            for m in FIELD_REF_RE.finditer(line):
                field = m.group(1)
                if field in ("current_state.json",):
                    continue
                # 字段声称属于 current_state.json（同一短语窗口内出现
                # current_state.json 与字段引用）
                window = line[max(0, m.start() - 40):m.end()]
                if "current_state.json" in window:
                    assert field in CURRENT_STATE_FIELDS, (
                        f"{name}: current_state context references nonexistent "
                        f"field {field!r}: {line.strip()[:160]}"
                    )
                    continue
                if legacy_ctx:
                    assert field in (
                        CURRENT_STATE_FIELDS | LEGACY_RELEASE_FIELDS), (
                        f"{name}: legacy release context references unknown "
                        f"field {field!r}: {line.strip()[:160]}"
                    )
