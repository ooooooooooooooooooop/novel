"""S6（54 计划 §S6）无人连续生产链就绪检查测试.

锁住 verify_a1_chain_readiness 的 14 项代码级断言：
- 无人工干涉（auto 入口无 [WAITING] 执行路径）
- S2 终审闸（换位一致性约束 + reader gate hard_consistency 轴）
- S3 因果防线（reader gate 并入 run_causal_defense）
- 证据链完整（precommit 证伪 + reader gate 报告 + commit head 校验）
- 预算合规（四轴扣减 + 超限拒绝）
- checkpoint 自动比对（10/20/30 章）
"""
from __future__ import annotations

import json

from src.boundary_control.chapter_commit import ChapterCommitBoundary
from scripts.s6_canary_driver import (
    _ensure_campaign_identity,
    _last_committed_baseline,
    _mechanism_source_sha256,
    _sha256_file,
    _validate_committed_run,
)
from scripts.verify_a1_chain_readiness import verify_readiness


def test_all_checks_pass() -> None:
    checks = verify_readiness()
    failed = [label for label, passed in checks.items() if not passed]
    assert not failed, f"未通过: {failed}"


def test_exact_check_count() -> None:
    checks = verify_readiness()
    assert len(checks) == 14, f"预期 14 项检查, 实际 {len(checks)}"


def test_auto_no_waiting() -> None:
    assert verify_readiness()["auto 入口无 [WAITING] 执行路径"]


def test_reader_gate_hard_consistency() -> None:
    assert verify_readiness()["读者门禁 hard_consistency 轴恒跑"]


def test_budget_rejection() -> None:
    assert verify_readiness()["预算四轴超限拒绝（charge_usage）"]


def test_commit_head_verification() -> None:
    assert verify_readiness()["恢复只识别完整提交（拒绝猜提交头）"]


def test_checkpoint(tmp_path) -> None:
    assert verify_readiness()["10/20/30 章 checkpoint 自动比对"]

    # S6 分章 run 必须按章节/尝试数值选最后已提交基线，并从同一 run 继承
    # state + frames；字典序会错误地让 ch9 胜过 ch30。
    output = tmp_path / "output"
    output.mkdir()
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    for number in range(1, 9):
        (chapters / f"chapter_{number}.txt").write_text("基线正文", encoding="utf-8")
    identity_path = output / "campaign_identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign": tmp_path.name,
                "genre": "offdom",
                "base_state_sha256": "a" * 64,
                "policy_sha256": "b" * 64,
                "profile_sha256": "c" * 64,
                "mechanism_source_sha256": _mechanism_source_sha256(),
            }
        ),
        encoding="utf-8",
    )

    def provenance_for(number: int) -> str:
        issues = []
        review_hash = __import__("hashlib").sha256(
            json.dumps(issues, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return json.dumps(
            {
                "chapters": {
                    f"chapter_{number}": {
                        "review_version": "post-prose-v1",
                        "review_issues": issues,
                        "review_evidence_hash": review_hash,
                    }
                }
            }
        )

    def gate_for(number: int) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "chapter_ref": f"chapter_{number}",
                "route": "pass",
                "axes_armed": {"hard_consistency": True, "window": True},
                "reasons": [],
                "issues": [],
                "reconcile_issue_count": 0,
                "facts_package_hash": "f" * 64,
            }
        )

    def blind_for(number: int) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "chapter_ref": f"chapter_{number}",
                "clean": True,
                "findings": [],
            }
        )

    def serial_for(number: int) -> str:
        window = 5 if number >= 5 else 3
        return json.dumps(
            {
                "schema_version": 1,
                "window": window,
                "review_target": f"chapter_{number}",
                "chapter_refs": [
                    f"chapter_{item}"
                    for item in range(number - window + 1, number + 1)
                ],
                "findings": [],
                "overall": "good",
                "route": "none",
            }
        )

    ch9 = output / "ch9-try9"
    (ch9 / "state").mkdir(parents=True)
    ch9_state = ch9 / "state" / "state_package.json"
    ch9_state.write_text('{"state":"before-9"}', encoding="utf-8")
    ChapterCommitBoundary(ch9, chapters).commit(
        run_id="compose-9", mode="compose", chapter_number=9,
        chapter_text="第九章正文", state_path=ch9_state,
        state_json='{"state":"after-9"}',
        frames_path=ch9 / "state" / "frames.json", frames_json="[]",
        archive_text="第九章正文",
        provenance_json=provenance_for(9),
        reader_gate_report_json=gate_for(9),
        serial_reader_report_json=serial_for(9),
        blind_final_audit_json=blind_for(9),
        prev_chapter_ref="chapter_8", facts_package_hash="f" * 64,
        campaign_identity_path=identity_path, review_route="pass",
    )
    (ch9 / "manifest.json").write_text(
        json.dumps({"committed_chapters": 1}), encoding="utf-8"
    )
    for number in range(10, 30):
        (chapters / f"chapter_{number}.txt").write_text("基线正文", encoding="utf-8")

    ch30 = output / "ch30-try2"
    (ch30 / "state").mkdir(parents=True)
    ch30_state = ch30 / "state" / "state_package.json"
    ch30_state.write_bytes(ch9_state.read_bytes())
    ChapterCommitBoundary(ch30, chapters).commit(
        run_id="compose-30", mode="compose", chapter_number=30,
        chapter_text="第三十章正文", state_path=ch30_state,
        state_json='{"state":"after-30"}',
        frames_path=ch30 / "state" / "frames.json", frames_json="[]",
        archive_text="第三十章正文",
        provenance_json=provenance_for(30),
        reader_gate_report_json=gate_for(30),
        serial_reader_report_json=serial_for(30),
        blind_final_audit_json=blind_for(30),
        prev_chapter_ref="chapter_29", facts_package_hash="f" * 64,
        campaign_identity_path=identity_path, review_route="pass",
    )
    (ch30 / "manifest.json").write_text(
        json.dumps({"committed_chapters": 1}), encoding="utf-8"
    )
    incomplete = output / "ch31-try1"
    (incomplete / "state").mkdir(parents=True)
    (incomplete / "manifest.json").write_text(
        json.dumps({"committed_chapters": 1}), encoding="utf-8"
    )

    baseline = _last_committed_baseline(tmp_path, output)
    assert baseline is not None
    assert baseline[0].parent.parent.name == "ch30-try2"
    assert baseline[1].parent.parent.name == "ch30-try2"
    ok, reason = _validate_committed_run(
        ch30, chapter_number=30, input_state=ch9_state
    )
    assert ok and reason == "ok"
    ch30_manifest = json.loads((ch30 / "run_manifest.json").read_text(encoding="utf-8"))
    ch30_manifest["state_before_hash"] = "0" * 64
    (ch30 / "run_manifest.json").write_text(
        json.dumps(ch30_manifest), encoding="utf-8"
    )
    ok, reason = _validate_committed_run(
        ch30, chapter_number=30, input_state=ch9_state
    )
    assert ok is False and "state_before_hash" in reason

    identity_root = tmp_path / "identity"
    expected = {
        "schema_version": 1,
        "campaign": "new-campaign",
        "genre": "offdom",
        "base_state_sha256": "a" * 64,
        "policy_sha256": "b" * 64,
        "profile_sha256": "c" * 64,
        "mechanism_source_sha256": _mechanism_source_sha256(),
    }
    _ensure_campaign_identity(identity_root, expected)
    assert json.loads(
        (identity_root / "output" / "campaign_identity.json").read_text(encoding="utf-8")
    ) == expected
    mismatched = {**expected, "genre": "hist"}
    import pytest
    with pytest.raises(ValueError, match="identity mismatch"):
        _ensure_campaign_identity(identity_root, mismatched)
    legacy = tmp_path / "legacy"
    (legacy / "chapters").mkdir(parents=True)
    (legacy / "chapters" / "chapter_1.txt").write_text("正文", encoding="utf-8")
    with pytest.raises(ValueError, match="no campaign_identity"):
        _ensure_campaign_identity(legacy, expected)