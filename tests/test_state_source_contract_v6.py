"""第六轮反例锁定负测（审计任务 A-I）.

每个反例必须被机制拒绝；任一仍可通过则最终状态必须保持
ATTESTATION_PROTOCOL_FAIL / UNVERIFIED。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.aggregate_current_state import (  # noqa: E402
    NEUTRAL_STATE_GENERATED_AT,
    Reject,
    _checkpoint_attestation,
    _verify_profile,
    verify_committed_bundle,
    verify_merkle_inventory,
)
from scripts.run_attestation_bundle import (  # noqa: E402
    _venv_validation,
    _worktree_forbidden,
)
from tests.test_state_source_contract_v5 import (  # noqa: E402
    _synthetic_public_clean_bundle,
)

EXTERNAL_INPUT_ROOTS = (
    "reference_texts/a1_benchmark",
    "runtime/refs/deepseek_active",
    "runtime/refs/cpa_active",
    "novels/s6-canary-offdom/output",
    "novels/s6-canary-mythic/output",
    "novels/s6-canary-hist/output",
)


def _load(bundle: Path, profile: str = "public_clean", repo_root=None) -> dict:
    from scripts.aggregate_current_state import _load_bundle
    return _load_bundle("public_clean", profile, repo_root or bundle.parent)


# ---- 反例 1：根级 untracked/ignored conftest 假绿（A）----

def test_neg_runner_preflight_rejects_root_untracked_conftest(tmp_path):
    """根级 untracked conftest.py 必须在任何 subprocess 之前被拒绝."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"],
                   capture_output=True, check=True)
    (tmp_path / "tracked.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "init"],
                   capture_output=True, check=True)
    (tmp_path / "conftest.py").write_text(
        "import pytest\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    raise SystemExit(0)\n", encoding="utf-8")
    bad = _worktree_forbidden(tmp_path, "state_artifacts/x/operator", False)
    assert bad["untracked"] == ["conftest.py"], bad
    assert bad["tracked"] == [] and bad["ignored"] == [], bad


def test_neg_runner_preflight_rejects_foreign_ignored_input(tmp_path):
    """ignored 输入（如被 .gitignore 掩盖的插件目录）必须拒绝."""
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"],
                   capture_output=True, check=True)
    (tmp_path / ".gitignore").write_text("plugins/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "init"],
                   capture_output=True, check=True)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "evil_plugin.py").write_text("", encoding="utf-8")
    bad = _worktree_forbidden(tmp_path, "state_artifacts/x/operator", False)
    assert bad["ignored"] and all(
        p.startswith("plugins/") for p in bad["ignored"]), bad


def test_runner_pytest_cmd_confcutdir_binds_tests(tmp_path):
    """机制级修复：--confcutdir tests 使根级 conftest 不可被 pytest 加载."""
    from scripts.run_attestation_bundle import main as runner_main
    # 静态断言构造（不经 runner 主流程）：pytest_cmd 由 main 构造——
    # 直接验证 main 的 argparse 之后、构造 pytest_cmd 的源码级约束。
    src = (PROJECT_ROOT / "scripts" / "run_attestation_bundle.py").read_text(
        encoding="utf-8")
    assert '"--confcutdir", "tests"' in src


# ---- 反例 2：editable venv 指向外部 src（B）----

def test_neg_venv_validation_rejects_external_src(tmp_path, monkeypatch):
    """另一 checkout 的 editable .venv：src.__file__ 解析到外部 → 拒绝."""
    from scripts.run_attestation_bundle import _venv_validation
    venv = tmp_path / ".venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    py.parent.mkdir(parents=True)
    py.write_bytes(b"placeholder")
    sp = venv / ("Lib/site-packages" if os.name == "nt" else "lib/python3.11/site-packages")
    sp.mkdir(parents=True)
    real_probe = subprocess.run

    def fake_probe(cmd, **kw):
        class R:
            returncode = 0
            stdout = ("C:/elsewhere/python.exe\n"
                      "C:/elsewhere/src/__init__.py\n")
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_probe)
    rec = _venv_validation(tmp_path, ".venv")
    assert rec.get("ok") is False, rec
    assert "not bound to subject checkout" in rec.get("error", ""), rec
    monkeypatch.undo()
    subprocess.run = real_probe


def test_venv_validation_records_exec_pth_src_binding():
    """正演：含 venv 的 checkout 必须记录 sys.executable / .pth / src.__file__
    全部解析到 subject checkout（B 的绑定三元组）。public_clean fresh clone
    无 venv（operator 侧环境概念）→ 跳过。"""
    if not (PROJECT_ROOT / ".venv").exists():
        pytest.skip("no in-checkout venv (public_clean fresh clone)")
    rec = _venv_validation(PROJECT_ROOT, ".venv")
    assert rec.get("ok") is True, rec
    assert rec["sys_executable"].replace("\\", "/").startswith(
        str(PROJECT_ROOT.resolve()).replace("\\", "/")), rec
    norm = rec["src_module_file"].replace("\\", "/")
    assert norm.startswith(str(PROJECT_ROOT.resolve()).replace("\\", "/")), rec
    assert rec.get("external_pth") == [], rec


# ---- 反例 3：external_inputs roots={} 空跑（C）----

def test_neg_merkle_inventory_rejects_empty_roots():
    with pytest.raises(Reject, match="roots set mismatch"):
        verify_merkle_inventory({"roots": {}, "files": {}})


def test_neg_profile_rejects_missing_root_key(tmp_path):
    """六根键集合缺一根 → profile 校验拒绝."""
    from scripts.aggregate_current_state import _load_bundle
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    del section["external_inputs"]["pre"]["roots"]["runtime/refs/cpa_active"]
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = _load_bundle("public_clean", "public_clean", tmp_path)
    with pytest.raises(Reject, match="roots set mismatch"):
        _verify_profile(loaded, int(EXPECTED_COLLECTED_TESTS), PROJECT_ROOT)


def test_neg_profile_rejects_file_type_and_size_tamper(tmp_path):
    """file type != file / size 非法 / absent 根残留 → 拒绝（C 逐项核对）."""
    from scripts.aggregate_current_state import _load_bundle
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    # absent 根下残留文件必须被拒
    inv = {"roots": {r: {"present": False, "merkle": None, "file_count": 0}
                     for r in EXTERNAL_INPUT_ROOTS},
           "files": {"runtime/refs/deepseek_active/live.db": {
               "type": "dir", "size": 8,
               "sha256": hashlib.sha256(b"AAAAAAAA").hexdigest()}}}
    with pytest.raises(Reject, match="absent root"):
        verify_merkle_inventory(inv)
    # 根在场但 type=dir → 拒绝；恢复 type=file 后 size 非法 → 拒绝
    inv["roots"]["runtime/refs/deepseek_active"]["present"] = True
    inv["roots"]["runtime/refs/deepseek_active"]["file_count"] = 1
    inv["roots"]["runtime/refs/deepseek_active"]["merkle"] = (
        hashlib.sha256(b"AA").hexdigest())
    with pytest.raises(Reject, match="unknown file type"):
        verify_merkle_inventory(inv)
    inv["files"]["runtime/refs/deepseek_active/live.db"]["type"] = "file"
    inv["files"]["runtime/refs/deepseek_active/live.db"]["size"] = -1
    with pytest.raises(Reject, match="bad size"):
        verify_merkle_inventory(inv)


# ---- 反例 4：仓外 cwd 相对 bundle / symlink——v5 已锁定（C）----
# （test_state_source_contract_v5.py::test_aggregator_rejects_nonportable_bundle_paths）

# ---- 反例 5：carrier 单独修改 raw manifest / canary-stderr（D/F）----

def test_neg_verify_committed_rejects_tampered_canary_stderr(tmp_path):
    """carrier 上 verify_committed_bundle：canary-stderr.txt 被改 → 拒绝."""
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    (bundle / "canary-stderr.txt").write_bytes(b"tampered\n")
    state = {
        "subject_commit": section["subject_commit"],
        "subject_tree": section["subject_tree"],
        "collected_tests": int(EXPECTED_COLLECTED_TESTS),
        "profiles": {
            "operator": {"status": "UNVERIFIED"},
            "public_clean": {"status": "PASS"},
        },
        "bundles": {"public_clean": "public_clean"},
    }
    with pytest.raises(Reject, match="canary-stderr.txt SHA mismatch"):
        verify_committed_bundle(state, tmp_path)


def test_neg_verify_committed_rejects_tampered_raw_manifest_carrier(tmp_path):
    """carrier 上 verify_committed_bundle：raw skip-manifest 被改 → 拒绝."""
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    (bundle / "skip-manifest.json").write_bytes(b"{}\n")
    state = {
        "subject_commit": section["subject_commit"],
        "subject_tree": section["subject_tree"],
        "collected_tests": int(EXPECTED_COLLECTED_TESTS),
        "profiles": {
            "operator": {"status": "UNVERIFIED"},
            "public_clean": {"status": "PASS"},
        },
        "bundles": {"public_clean": "public_clean"},
    }
    with pytest.raises(Reject, match="SHA mismatch"):
        verify_committed_bundle(state, tmp_path)


# ---- 反例 6：result/Merkle/file_count/type/size/根增删/absent 残留（C）----

def test_neg_profile_rejects_result_artifact_drift(tmp_path):
    """result_artifact_sha256 被改 → 拒绝（C：独立重推导）."""
    from scripts.aggregate_current_state import _load_bundle
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    section["pytest"]["result_artifact_sha256"] = "0" * 64
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = _load_bundle("public_clean", "public_clean", tmp_path)
    with pytest.raises(Reject, match="result_artifact_sha256 mismatch"):
        _verify_profile(loaded, int(EXPECTED_COLLECTED_TESTS), PROJECT_ROOT)


def test_neg_merkle_rejects_extra_unknown_root_and_stray_file():
    """未知根 + 根外残留文件 → 拒绝."""
    inv = {
        "roots": {r: {"present": False, "merkle": None, "file_count": 0}
                  for r in EXTERNAL_INPUT_ROOTS},
        "files": {"state_artifacts/evil.json": {
            "type": "file", "size": 1,
            "sha256": hashlib.sha256(b"x").hexdigest()}},
    }
    with pytest.raises(Reject, match="outside any known root"):
        verify_merkle_inventory(inv)
    inv["roots"]["sneaky/root"] = {"present": False, "merkle": None,
                                   "file_count": 0}
    with pytest.raises(Reject, match="roots set mismatch"):
        verify_merkle_inventory(inv)


# ---- 反例 7：文档块与台账——由合同测试锁定（H）----
# （test_state_source_contract.py::test_pointer_only_five_docs_single_current_block_and_no_ledger）

# ---- 反例 8：tag 自比 / frozen 未用（G）----

def test_checkpoint_frozen_constants_actually_enforced(monkeypatch):
    """冻结常量必须真实参与断言：任一 key 被篡改 → checkpoint FAIL."""
    from scripts.aggregate_current_state import FROZEN_EVIDENCE
    ok = _checkpoint_attestation(PROJECT_ROOT)
    assert ok["status"] == "PASS", ok.get("failures")
    saved = dict(FROZEN_EVIDENCE)
    try:
        bad = json.loads(json.dumps(FROZEN_EVIDENCE))
        bad["docs/00_project/releases/tier0-release.json"]["tag_object"] = (
            "0" * 40)
        from scripts import aggregate_current_state as agg
        agg.FROZEN_EVIDENCE = bad
        out = _checkpoint_attestation(PROJECT_ROOT)
        assert out["status"] == "FAIL", out
        assert any("tag object moved" in f for f in out["failures"]), out
    finally:
        from scripts import aggregate_current_state as agg
        agg.FROZEN_EVIDENCE = saved


def test_checkpoint_records_use_frozen_not_self_compare():
    """tag_path_bytes_verified 必须对比冻结值（非现算自比）."""
    from scripts.aggregate_current_state import FROZEN_EVIDENCE
    out = _checkpoint_attestation(PROJECT_ROOT)
    assert out["status"] == "PASS", out.get("failures")
    for rec, r in out["records"].items():
        frozen = FROZEN_EVIDENCE[rec]
        assert r["tag_tree_blob_sha256"] == frozen["tag_path_blob_sha256"]
        assert r["record_blob_sha256"] == frozen["head_record_blob_sha256"]
        assert r["tag_path_bytes_verified"] is True
        # 关系与冻结语义一致：不是"看现算是否相等"的自比逻辑
        expect_self = frozen["expected_relationship"] == "tag_self_record"
        assert (r["tag_tree_blob_sha256"] == r["record_blob_sha256"]) == (
            expect_self)


# ---- 反例 9：neutral 写父 tree / 时间戳非确定性（I）----

def test_neutral_state_null_tree_deterministic_timestamp(tmp_path):
    """--neutral 两次输出字节一致；subject_tree=null；时间戳为确定性占位."""
    from scripts.aggregate_current_state import main as agg_main
    out1 = tmp_path / "s1.json"
    out2 = tmp_path / "s2.json"
    rc1 = agg_main(["--neutral", "--out", str(out1)])
    rc2 = agg_main(["--neutral", "--out", str(out2)])
    assert rc1 == 0 and rc2 == 0
    b1 = out1.read_bytes()
    b2 = out2.read_bytes()
    assert b1 == b2, "neutral state must be deterministic"
    state = json.loads(b1.decode("utf-8"))
    assert state["subject_tree"] is None
    assert state["subject_commit"] is None
    assert state["subject_checkout_head"] is None
    assert state["state_generated_at"] == NEUTRAL_STATE_GENERATED_AT
    assert state["head_status"] == "UNVERIFIED"
    assert state["subject_overall_status"] == "UNVERIFIED"


# ---- 反例 5/6 补充：JUnit skip message 篡改（E）----

def test_neg_profile_rejects_skip_message_drift(tmp_path):
    """JUnit skip message 与映射语义不符 → 拒绝（E 交叉核对）."""
    from scripts.aggregate_current_state import _load_bundle
    from tests.test_cli_runtime_contract import EXPECTED_COLLECTED_TESTS
    bundle, section = _synthetic_public_clean_bundle(tmp_path)
    xml = bundle / "pytest-junit.xml"
    text = xml.read_text(encoding="utf-8")
    text = text.replace("neutral placeholder carries no attested bundles",
                        "synthetic skip")
    xml.write_text(text, encoding="utf-8")
    # 同步声明 sha 与 classified message（模拟篡改者同步指纹），使 SHA 与
    # classified 一致检查通过、语义（message↔reason）检查失败
    section["pytest"]["junit_xml_sha256"] = hashlib.sha256(
        xml.read_bytes()).hexdigest()
    for c in section["skip_manifest"]["junit_classified"]:
        if "neutral" in c["message"]:
            c["message"] = "synthetic skip"
            c["message_ok"] = True
    (bundle / "profile-attestation.json").write_text(
        json.dumps(section, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = _load_bundle("public_clean", "public_clean", tmp_path)
    with pytest.raises(Reject, match="skip message semantics"):
        _verify_profile(loaded, int(EXPECTED_COLLECTED_TESTS), PROJECT_ROOT)