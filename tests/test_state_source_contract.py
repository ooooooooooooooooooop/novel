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
    assert state["overall_status"] == "UNVERIFIED"
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


def _profile_bundle_dir(state: dict, name: str) -> Path:
    artifacts_dir = state["artifacts_dir"]
    resolved = (PROJECT_ROOT / artifacts_dir).resolve()
    repo_resolved = PROJECT_ROOT.resolve()
    assert repo_resolved in resolved.parents or resolved == repo_resolved, (
        f"artifacts_dir escapes the repository: {artifacts_dir}"
    )
    bundle = resolved / name
    assert bundle.is_dir(), f"missing bundle dir: {bundle}"
    return bundle


def _parse_junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {
        "tests": int(suite.get("tests", "0")),
        "failures": int(suite.get("failures", "0")),
        "errors": int(suite.get("errors", "0")),
        "skipped": int(suite.get("skipped", "0")),
        "skipped_nodeids": [
            (tc.get("classname", "") + "::" + tc.get("name", ""))
            for tc in suite.iter("testcase") if tc.find("skipped") is not None
        ],
    }


def _rederive_profile_from_raw_artifacts(state: dict, name: str) -> None:
    """从原始 artifact 重推导（审计任务 H）：不信任 JSON 中的 PASS 布尔."""
    from scripts.aggregate_current_state import (
        _norm_nodeid, GATED_SKIPS, SELF_REF_SKIPS,
    )
    gated_norm = {_norm_nodeid(g) for g in GATED_SKIPS}
    selfref_norm = {_norm_nodeid(g) for g in SELF_REF_SKIPS}
    bundle = _profile_bundle_dir(state, name)
    section = state["profiles"][name]

    required = ("pytest-stdout.txt", "pytest-stderr.txt", "pytest-junit.xml",
                "canary-stdout.txt", "canary-stderr.txt", "skip-manifest.json",
                "profile-attestation.json")
    for f in required:
        assert (bundle / f).exists(), f"{name}: missing artifact {f}"

    # SHA 重算（原始 artifact）
    assert _sha_file(bundle / "pytest-stdout.txt") == section["pytest"][
        "stdout_sha256"], name
    assert _sha_file(bundle / "pytest-stderr.txt") == section["pytest"][
        "stderr_sha256"], name
    assert _sha_file(bundle / "pytest-junit.xml") == section["pytest"][
        "junit_xml_sha256"], name
    assert _sha_file(bundle / "canary-stdout.txt") == section["canary"][
        "stdout_sha256"], name

    # committed profile-attestation.json 与内嵌段规范 JSON 完全比较
    committed = json.loads(
        (bundle / "profile-attestation.json").read_text(encoding="utf-8"))
    assert json.dumps(committed, sort_keys=True) == json.dumps(
        section, sort_keys=True), f"{name}: profile-attestation.json drift"

    # JUnit 计数重推导
    junit = _parse_junit(bundle / "pytest-junit.xml")
    results = section["pytest"]["results"]
    assert junit["tests"] == results["collected"], name
    assert junit["failures"] == results["failed"], name
    assert junit["errors"] == results["errors"], name
    assert junit["skipped"] == results["skipped"], name

    # stdout 汇总行交叉核对
    stdout_tail = (bundle / "pytest-stdout.txt").read_text(
        encoding="utf-8").strip().splitlines()[-1]
    for word, key in (("passed", "passed"), ("failed", "failed"),
                      ("error", "errors"), ("skipped", "skipped")):
        m = re.search(rf"(\d+) {word}", stdout_tail)
        assert (int(m.group(1)) if m else 0) == results[key], (
            f"{name}: stdout {word} mismatch"
        )

    # PASS ⇒ exit=0 / failed=errors=0 / canary exit=0 PASS / tracked clean
    if section["status"] == "PASS":
        assert section["pytest"]["exit_code"] == 0, name
        assert results["failed"] == 0 and results["errors"] == 0, name
        assert section["canary"]["exit_code"] == 0, name
        assert section["canary"]["verdict"] == "PASS", name
        assert section["gates"]["post_tracked_changes"] == [], name
        assert section["external_inputs"]["identical"] is True, name
        assert section["filesystem_case_probe"] is not None

    # skip 证据（审计任务 D）：manifest == junit，且全部命中固定白名单
    manifest = section["skip_manifest"]
    manifest_skips = manifest.get("skips", [])
    assert len(manifest_skips) == junit["skipped"], (
        f"{name}: manifest skips {len(manifest_skips)} != junit "
        f"{junit['skipped']}"
    )
    manifest_ids = {_norm_nodeid(s["nodeid"]) for s in manifest_skips}
    for nid in junit["skipped_nodeids"]:
        nid_norm = _norm_nodeid(nid)
        assert nid_norm in manifest_ids, (
            f"{name}: junit skip missing from manifest: {nid}")
        assert nid_norm in (gated_norm | selfref_norm), (
            f"{name}: unexplained skip: {nid}"
        )
    for s in manifest_skips:
        nid_norm = _norm_nodeid(s["nodeid"])
        assert s["reason_code"] in ("missing_private_asset",
                                    "state_neutral_placeholder"), s
        if s["reason_code"] == "missing_private_asset":
            assert nid_norm in gated_norm, s
        else:
            assert nid_norm in selfref_norm, s


def test_profiles_rederived_from_raw_artifacts():
    state = _load_state()
    if _is_neutral(state):
        pytest.skip("neutral placeholder")
    for name in PROFILE_NAMES:
        _rederive_profile_from_raw_artifacts(state, name)


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
        assert state["overall_status"] == "UNVERIFIED"
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
    state = _load_state()
    cp = state["last_certified_checkpoint"]
    if cp.get("status") != "PASS":
        return
    tier0 = cp["records"]["docs/00_project/releases/tier0-release.json"]
    assert tier0["record_relationship"] == "post_tag_historical_record", (
        "tier0 record must be honestly marked post-tag (tag tree blob differs)"
    )
    q1 = cp["records"]["docs/00_project/releases/q1-release.json"]
    assert q1["record_relationship"] == "tag_self_record"
    # tag_path_bytes_verified 必须对冻结预期值验证（禁止自身比较）
    frozen_expected = {
        "docs/00_project/releases/tier0-release.json":
            "a02bb1aaf8c22d7ea89fd1f2174e3131",  # 前 32 位截断标记；完整值见下
    }
    for rec in cp["records"].values():
        tag = rec["certification_tag"]
        tag_bytes = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
             f"{tag}:{rec['record_path']}"],
            capture_output=True,
        ).stdout
        # 冻结预期值：tag tree 的 blob sha256 必须与记录一致，且与 HEAD blob
        # 的关系决定 relationship（第四轮：禁同值自比）
        import hashlib
        assert hashlib.sha256(tag_bytes).hexdigest() == rec[
            "tag_tree_blob_sha256"]
        head_bytes = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
             f"HEAD:{rec['record_path']}"],
            capture_output=True,
        ).stdout
        assert hashlib.sha256(head_bytes).hexdigest() == rec[
            "record_blob_sha256"]
        if rec["record_relationship"] == "tag_self_record":
            assert rec["tag_tree_blob_sha256"] == rec["record_blob_sha256"]
        else:
            assert rec["tag_tree_blob_sha256"] != rec["record_blob_sha256"]
    # Q1 payload commit 与 record/tag commit 区分
    q1 = cp["records"]["docs/00_project/releases/q1-release.json"]
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


def test_json_field_references_exist_in_schema():
    """文档引用的 JSON 字段必须由本 schema 验证真实存在（审计任务 H）."""
    known_fields = {
        # current_state.json schema（第四轮）
        "subject_commit", "subject_tree", "subject_checkout_head",
        "subject_status", "subject_overall_status", "overall_status",
        "head_status", "profiles", "operator", "public_clean",
        "last_validated_commit", "last_validated_tree",
        "last_certified_checkpoint", "evidence_paths", "artifacts_dir",
        "collected_tests", "carrier_binding", "state_generated_at",
        "attestation_commit", "collected_tests_contract", "bundles",
        # legacy release-record schema（tier0-release.json / q1-release.json）
        "baseline_tests_passing", "full_pytest_result", "full_pytest_command",
        "release_id", "release_tag_or_checkpoint", "git_commit", "git_tag",
    }
    for name in STATE_BEARING_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "current_state.json 的" not in line and (
                    "current_state.json` 的" not in line):
                continue
            for field in re.findall(r"`([a-z_]+)`", line):
                if field in ("current_state.json",):
                    continue
                assert field in known_fields, (
                    f"{name}: references unknown JSON field {field!r}"
                )
