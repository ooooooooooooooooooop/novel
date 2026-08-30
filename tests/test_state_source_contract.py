"""状态真源合同（第三轮 attestation 协议，审计任务 A/B/D/E）.

current_state.json 是唯一机器真源。合同强制：
- 中性占位态（subject_commit=null）必须全 UNVERIFIED 且 collected 等于唯一合同；
- attestation 态：subject 是 HEAD 祖先且 subject..HEAD 差异只能是
  current_state.json + state_artifacts/**（双提交协议）；
- profile 结果五项合计自洽、failed/errors=0（PASS 时）、collected 等于唯一
  合同且等于实时收集数；canary 与实时回归一致；artifact SHA 重算一致；
  head_status 恒为 UNVERIFIED（carrier 不能自证）；last_validated 严格等于
  subject；checkpoint 拆分字段（tag/tree/blob/relationship）与实际字节一致；
- 门面与状态承载文档：current 块语义、历史资格必须带日期、禁陈旧真源哈希、
  禁未日期化的中英文生产就绪/验证通过声明；.ai/state/state.md 纳入管辖。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "current_state.json"

REQUIRED_KEYS = (
    "attestation_version",
    "subject_commit",
    "subject_tree",
    "repository_head",
    "attestation_commit",
    "head_status",
    "subject_status",
    "state_generated_at",
    "profiles",
    "overall_status",
    "collected_tests",
    "collected_tests_contract",
    "last_validated_commit",
    "last_validated_tree",
    "last_certified_checkpoint",
    "evidence_paths",
)
PROFILE_NAMES = ("public_clean", "operator")
RESULT_KEYS = ("passed", "skipped", "failed", "errors", "collected")
FRESHNESS_LIMIT = 3
ATTESTATION_ALLOWED_PATHS = {"current_state.json", "state_artifacts"}

FACADE_DOCS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/00_project/00_project_brief.md",
    "docs/00_project/01_scope_and_boundaries.md",
    "docs/00_project/02_agent_quickstart.md",
    "docs/00_project/03_current_status.md",
)
STATE_BEARING_DOCS = FACADE_DOCS + (
    ".ai/state/state.md",
    "docs/00_project/04_agent_operating_model.md",
    "docs/00_project/30_production_readiness_checklist.md",
    "docs/00_project/32_tier0_release_record_contract.md",
    "docs/00_project/54_master_goal_execution_plan.md",
)

CURRENT_BLOCK_RE = re.compile(
    r"<!--\s*state:current\s*-->(.*?)<!--\s*/state:current\s*-->", re.S
)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# 历史资格的合格绑定：日期、commit 哈希或不可变 tag 引用（审计任务 E：日期+commit/tag）
QUALIFIER_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}|[0-9a-f]{7,40}|v\d+\.\d+\.\d+-[a-z0-9]+"
)
# 中英文生产就绪/验证通过语义（状态承载文档里未日期化出现即为违例）
CERTIFICATION_CLAIM_RE = re.compile(
    r"production[- ]ready|end_to_end_validated|end-to-end validated"
    r"|生产就绪|验证通过|端到端通过|端到端验证通过|全部通过",
    re.I,
)
STALE_TRUTH_HASHES = ("b464a8a", "157914ed")


def _git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *args],
        capture_output=True, text=True, check=check,
    ).stdout.strip()


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
        "current_state.json missing — run scripts/generate_current_state.py"
    )
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _is_neutral(state: dict) -> bool:
    return state.get("subject_commit") is None


def test_state_file_exists_and_is_complete():
    state = _load_state()
    missing = [k for k in REQUIRED_KEYS if k not in state]
    assert not missing, missing


def test_collected_contract_single_source_and_live():
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    state = _load_state()
    live = _collect_count()
    assert int(EXPECTED_COLLECTED_TESTS) == live, (
        "collected contract drift"
    )
    assert state["collected_tests"] == live


def test_neutral_state_is_deterministically_unverified():
    state = _load_state()
    if not _is_neutral(state):
        return
    assert state["overall_status"] == "UNVERIFIED"
    assert state["subject_status"] == "UNVERIFIED"
    assert state["head_status"] == "UNVERIFIED"
    assert state["last_certified_checkpoint"].get("status") == "UNVERIFIED"
    for name in PROFILE_NAMES:
        p = state["profiles"][name]
        assert p["status"] == "UNVERIFIED", name
        assert p["pytest"]["results"] is None, name
    assert state["last_validated_commit"] is None


def test_attested_subject_protocol_diff_only_state_files():
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
    assert behind <= FRESHNESS_LIMIT, f"attestation stale: {behind} behind"
    changed = [
        f for f in _git("diff", "--name-only", f"{subject}..{current}").splitlines()
        if f
    ]
    violations = [
        f for f in changed
        if f != "current_state.json" and not f.startswith("state_artifacts/")
    ]
    assert not violations, (
        f"attestation protocol violated ({subject}..{current}): {violations}"
    )


def test_attested_profiles_semantics_and_sha_recomputation():
    state = _load_state()
    if _is_neutral(state):
        pytest.skip("neutral placeholder")
    artifacts_root = Path(state.get("artifacts_dir", ""))
    for name in PROFILE_NAMES:
        p = state["profiles"][name]
        assert p["status"] in ("PASS", "FAIL"), name
        results = p["pytest"]["results"]
        assert tuple(results) == RESULT_KEYS, name
        total = (results["passed"] + results["skipped"]
                 + results["failed"] + results["errors"])
        assert total == results["collected"], name
        if p["status"] == "PASS":
            assert p["pytest"]["exit_code"] == 0, name
            assert results["failed"] == 0 and results["errors"] == 0, name
            assert p["canary"]["exit_code"] == 0, name
            assert p["canary"]["verdict"] == "PASS", name
        # artifact SHA 重算：磁盘上的运行 artifact 必须与记录一致
        arts = artifacts_root / name
        for field, artifact_name in (
            ("stdout_sha256", "pytest-stdout.txt"),
            ("stderr_sha256", "pytest-stderr.txt"),
            ("junit_xml_sha256", "pytest-junit.xml"),
        ):
            f = arts / artifact_name
            assert f.exists(), f"{name}: missing artifact {artifact_name}"
            assert hashlib.sha256(f.read_bytes()).hexdigest() == p["pytest"][field], (
                f"{name}: {artifact_name} SHA mismatch"
            )
        canary_stdout = arts / "canary-stdout.txt"
        assert canary_stdout.exists()
        assert (
            hashlib.sha256(canary_stdout.read_bytes()).hexdigest()
            == p["canary"]["stdout_sha256"]
        ), name
        # 大小写探针与 autocrlf 必须如实记录
        assert "case_sensitive_filesystem" in p["filesystem_case_probe"]
        assert "core.autocrlf" in p or p.get("core.autocrlf") is not None


def test_attested_public_clean_requires_real_linux_case_fs():
    state = _load_state()
    if _is_neutral(state):
        pytest.skip("neutral placeholder")
    p = state["profiles"]["public_clean"]
    if p["status"] != "PASS":
        return
    probe = p["filesystem_case_probe"]
    assert probe["a_txt_and_A_TXT_coexist"] is True, (
        "public_clean PASS requires a case-sensitive filesystem "
        "(a.txt and A.TXT coexisting)"
    )


def test_canary_matches_live_regression():
    state = _load_state()
    live = _canary_verdict()
    for name, p in state["profiles"].items():
        if p["status"] == "UNVERIFIED":
            continue
        assert p["canary"]["verdict"] == live, (
            f"{name}: recorded canary {verdict} vs live {live}"
        )


def test_subject_and_head_status_split():
    state = _load_state()
    assert state["head_status"] == "UNVERIFIED", (
        "carrier commit cannot attest itself"
    )
    if _is_neutral(state):
        assert state["subject_status"] == "UNVERIFIED"
    else:
        assert state["subject_status"] == state["overall_status"]


def test_last_validated_strictly_subject():
    state = _load_state()
    if _is_neutral(state) or state["subject_status"] != "PASS":
        assert state["last_validated_commit"] is None
        assert state["last_validated_tree"] is None
        return
    assert state["last_validated_commit"] == state["subject_commit"], (
        "last_validated must be strictly the attested subject"
    )
    tree_of = _git("rev-parse", f"{state['subject_commit']}^{{tree}}")
    assert state["last_validated_tree"] == tree_of


def test_checkpoint_split_fields_and_tag_bytes():
    state = _load_state()
    cp = state["last_certified_checkpoint"]
    if cp.get("status") != "PASS":
        return
    for rec in cp["records"].values():
        tag = rec["certification_tag"]
        tag_target = _git("rev-parse", f"{tag}^{{commit}}")
        assert tag_target == rec["tag_target_commit"]
        tag_path_bytes = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
             f"{tag}:{rec['record_path']}"],
            capture_output=True,
        ).stdout
        assert hashlib.sha256(tag_path_bytes).hexdigest() == rec[
            "tag_tree_blob_sha256"
        ], f"{rec['record_path']}: tag:path bytes disagree with recorded blob"
        head_path_bytes = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "cat-file", "blob",
             f"HEAD:{rec['record_path']}"],
            capture_output=True,
        ).stdout
        assert hashlib.sha256(head_path_bytes).hexdigest() == rec[
            "record_blob_sha256"
        ]
        if rec["record_relationship"] == "post_tag_historical_record":
            assert rec["tag_tree_blob_sha256"] != rec["record_blob_sha256"]
        if rec["record_commit"] is not None:
            probe = subprocess.run(
                ["git", "-C", str(PROJECT_ROOT), "cat-file", "-t",
                 rec["record_commit"]],
                capture_output=True, text=True,
            )
            assert probe.stdout.strip() == "commit"


def test_evidence_paths_exist_with_matching_blob_sha():
    state = _load_state()
    for path, recorded_sha in state["evidence_paths"].items():
        live = _git("rev-parse", f"HEAD:{path}")
        assert live == recorded_sha, f"evidence blob drift: {path}"


def test_state_generated_after_all_completed_at():
    state = _load_state()
    generated = state["state_generated_at"]
    for name, p in state["profiles"].items():
        for stamp in (p.get("started_at"), p.get("completed_at")):
            if stamp:
                assert stamp <= generated, f"{name}: {stamp} > generated"


def test_facade_docs_have_current_blocks_and_no_number_claims():
    for name in FACADE_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        assert "current_state.json" in text, name
        assert "tests passing" not in text, name
        m = CURRENT_BLOCK_RE.search(text)
        assert m, f"{name} missing <!-- state:current --> block"
        block = m.group(1)
        assert "CURRENT_HEAD_UNVERIFIED" in block, name
        assert not re.search(r"\d+ passed", block), name


def test_state_bearing_docs_claims_must_be_dated():
    for name in STATE_BEARING_DOCS:
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        outside = CURRENT_BLOCK_RE.split(text)[::2]
        for chunk in outside:
            # 小节继承：资格声明行若自身无日期/commit/tag，则其所属小节标题
            # （到上一个空行/标题为止最近的标题行）必须带限定符。
            section_qualifier = False
            for line in chunk.splitlines():
                if re.match(r"^#{1,4} ", line) or re.match(r"^\*\*[^*]+（", line):
                    section_qualifier = bool(QUALIFIER_RE.search(line))
                if CERTIFICATION_CLAIM_RE.search(line):
                    assert QUALIFIER_RE.search(line) or section_qualifier, (
                        f"{name}: undated certification claim: "
                        f"{line.strip()[:140]}"
                    )


def test_facade_docs_free_of_stale_truth_hashes_and_claims():
    for name in FACADE_DOCS:
        if name == "docs/00_project/03_current_status.md":
            text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            assert "当前 commit：" not in text
            assert "validated_parent" not in text
            continue
        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for stale in STALE_TRUTH_HASHES:
            assert stale not in text, f"{name}: stale truth hash {stale}"


def test_ai_state_md_included_and_pointer_only():
    text = (PROJECT_ROOT / ".ai/state/state.md").read_text(encoding="utf-8")
    assert "唯一机器真源" not in text or "current_state.json" in text
    for stale in STALE_TRUTH_HASHES:
        assert stale not in text, f".ai/state/state.md: {stale}"
