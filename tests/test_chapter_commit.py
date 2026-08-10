"""Q1 Phase 2 — ChapterCommitBoundary 事务提交与崩溃恢复门禁.

门禁原文：正文写入/状态写入/Frame 推进任一点模拟失败后，重启只能识别完整
提交，不产生「正文已存在但状态未更新」或相反的半提交。

失败注入：failpoint 在指定写步骤前抛错，模拟进程崩溃；测试随后用**全新**
boundary 实例（模拟重启）调 recover() 判定。
"""

import json

import pytest

from src.boundary_control.chapter_commit import (
    ChapterCommitBoundary,
    UnmanagedArtifactError,
    derive_run_id,
    read_flow_version,
    set_run_status,
)
from src.object_state.run_manifest import (
    read_run_manifest,
    sha256_file,
    sha256_text,
)


def _crash_at(step: str):
    def _fp(name: str) -> None:
        if name == step:
            raise RuntimeError(f"simulated crash before {name}")
    return _fp


@pytest.fixture()
def ws(tmp_path):
    """合成工作区：novel/chapters + novel/output/compose + .flow_version=3."""
    novel = tmp_path / "novel"
    chapters = novel / "chapters"
    output_dir = novel / "output" / "compose"
    chapters.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")
    return {
        "novel": novel,
        "chapters": chapters,
        "output_dir": output_dir,
    }


def _commit_kwargs(ws, *, chapter_number=1, chapter_text="第一章正文。\n"):
    return dict(
        run_id=derive_run_id("compose", chapter_number),
        mode="compose",
        chapter_number=chapter_number,
        chapter_text=chapter_text,
        state_path=ws["output_dir"] / "compose_state.json",
        state_json=json.dumps(
            {"state_id": f"ns_{chapter_number}", "value": chapter_number},
            ensure_ascii=False,
        ),
        frames_path=ws["output_dir"] / "compose_frames.json",
        frames_json=json.dumps(
            {"current_frame_id": f"scene_{chapter_number}"}, ensure_ascii=False
        ),
        archive_text=chapter_text,
        provenance_json=json.dumps(
            {
                "schema_version": 1,
                "chapters": {
                    f"chapter_{chapter_number}": {
                        "chapter_number": chapter_number,
                        "flow_version": "3",
                        "review_version": "post-prose-v1",
                        "prose_review_enabled": True,
                        "draft_commit_enabled": True,
                        "review_issues": [],
                        "final_draft_chars": len(chapter_text),
                        "committed_at_utc": None,
                    }
                },
            },
            ensure_ascii=False,
        ),
        prev_chapter_ref=None,
        source_text_hash="workspec-hash-0001",
        review_route="pass",
    )


# ---- 完整提交：recover 识别 ----
def test_commit_then_recover_recognized(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    result = boundary.commit(**_commit_kwargs(ws))

    assert result.ok
    assert result.run_manifest is not None
    assert result.run_manifest.status == "committed"
    assert (ws["chapters"] / "chapter_1.txt").read_text(encoding="utf-8") == "第一章正文。\n"

    # 重启（新实例）
    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is True
    assert report.reason == "committed"
    assert report.manifest is not None
    assert report.orphans == []
    assert report.missing == []
    assert report.mismatched == []


def test_commit_records_hashes(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    result = boundary.commit(**_commit_kwargs(ws))
    m = result.run_manifest
    chapter_file = ws["chapters"] / "chapter_1.txt"
    assert m.artifacts["chapters/chapter_1.txt"] == sha256_file(chapter_file)
    assert m.artifacts["output/compose/compose_state.json"] == sha256_file(
        ws["output_dir"] / "compose_state.json"
    )
    assert m.artifacts["output/compose/compose_frames.json"] == sha256_file(
        ws["output_dir"] / "compose_frames.json"
    )
    assert m.draft_hash == sha256_text("第一章正文。\n")
    assert m.state_after_hash is not None
    assert m.frame_hash is not None
    assert m.state_before_hash is None  # 首次提交无旧状态
    assert m.source_text_hash == "workspec-hash-0001"


def test_commit_state_before_hash_after_first(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws, chapter_number=1))
    boundary.commit(**_commit_kwargs(ws, chapter_number=2, chapter_text="第二章正文。\n"))

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is True
    assert report.manifest.chapter_number == 2
    assert report.manifest.state_before_hash is not None
    assert report.orphans == []


# ---- 崩溃恢复门禁：任一点失败都不产生半提交 ----
@pytest.mark.parametrize("step", ["chapter", "archive", "provenance", "frames", "state", "manifest"])
def test_failure_at_any_write_point_never_recognized(ws, step):
    """正文/状态/Frame/归档/provenance/manifest 任一点失败 → 重启不识别为已提交."""
    boundary = ChapterCommitBoundary(
        ws["output_dir"], ws["chapters"], failpoint=_crash_at(step)
    )
    with pytest.raises(RuntimeError):
        boundary.commit(**_commit_kwargs(ws))

    # 重启（全新实例）
    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False, (
        f"crash at {step} must not be recognized as a complete commit"
    )
    assert report.reason in (
        "no_manifest",
        "status_staged",
        "status_draft",
        "status_reviewed",
        "status_rejected",
    )
    # manifest 提交记录绝不允许存在（或即使存在也不 recognized）
    if (ws["output_dir"] / "run_manifest.json").exists():
        m = read_run_manifest(ws["output_dir"])
        assert m is None or m.status != "committed"


def test_crash_at_state_write_leaves_no_valid_half_commit(ws):
    """「正文已写入但状态未写入」→ 不得被识别为合法提交."""
    boundary = ChapterCommitBoundary(
        ws["output_dir"], ws["chapters"], failpoint=_crash_at("state")
    )
    with pytest.raises(RuntimeError):
        boundary.commit(**_commit_kwargs(ws))

    # 正文确实已存在（半提交现场）
    assert (ws["chapters"] / "chapter_1.txt").exists()
    # 但状态未写入
    assert not (ws["output_dir"] / "compose_state.json").exists()

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    # 孤立正文被点名，操作者可据此处理
    assert any("chapter_1.txt" in p for p in report.orphans)


def test_crash_at_state_write_does_not_recognize_state_when_body_missing(ws):
    """「状态已写入但正文未写入」的相反半提交也不得产生."""
    # 先构造场景：状态文件已存在（模拟旧状态），正文写入失败
    state_path = ws["output_dir"] / "compose_state.json"
    state_path.write_text(json.dumps({"state_id": "ns_old"}), encoding="utf-8")

    boundary = ChapterCommitBoundary(
        ws["output_dir"], ws["chapters"], failpoint=_crash_at("chapter")
    )
    with pytest.raises(RuntimeError):
        boundary.commit(**_commit_kwargs(ws))

    assert not (ws["chapters"] / "chapter_1.txt").exists()

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    # 旧的 state 文件保留，但没有任何「新提交」被识别
    assert (ws["output_dir"] / "compose_state.json").read_text(encoding="utf-8") == json.dumps(
        {"state_id": "ns_old"}
    )


def test_crash_at_manifest_replace_leaves_stale_tmp(ws):
    """tmp 已写、os.replace 前崩溃 → 遗留 .tmp、无正式 manifest，提交不识别."""
    boundary = ChapterCommitBoundary(
        ws["output_dir"], ws["chapters"], failpoint=_crash_at("manifest.replace")
    )
    with pytest.raises(RuntimeError):
        boundary.commit(**_commit_kwargs(ws))

    assert (ws["output_dir"] / "run_manifest.json.tmp").exists()
    assert not (ws["output_dir"] / "run_manifest.json").exists()

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    assert report.reason == "no_manifest"
    assert report.stale_tmp  # 遗留 tmp 被点名


# ---- 篡改/损坏：提交后任一产物不一致 → 不再识别 ----
def test_tampered_chapter_after_commit_not_recognized(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws))

    # 篡改正文
    chapter_file = ws["chapters"] / "chapter_1.txt"
    chapter_file.write_text("被改过的正文。\n", encoding="utf-8")

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    assert report.reason == "artifact_mismatch"
    assert any("chapters/chapter_1.txt" in m["path"] for m in report.mismatched)


def test_deleted_state_after_commit_not_recognized(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws))

    (ws["output_dir"] / "compose_state.json").unlink()

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    assert report.reason == "artifact_missing"
    assert "output/compose/compose_state.json" in report.missing


# ---- 孤儿产物 / 拒绝覆盖 ----
def test_refuse_overwrite_unmanaged_chapter(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws))

    # 同一章号再次提交（覆盖已管理正文）→ 拒绝
    with pytest.raises(UnmanagedArtifactError):
        boundary.commit(**_commit_kwargs(ws, chapter_number=1))

    # 未管理的孤儿章（无人管理的编号）也被拒绝覆盖
    orphan = ws["chapters"] / "chapter_9.txt"
    orphan.write_text("孤儿。\n", encoding="utf-8")
    with pytest.raises(UnmanagedArtifactError):
        boundary.commit(**_commit_kwargs(ws, chapter_number=9))


def test_orphan_detected_when_manifest_absent(ws):
    """无 manifest 但存在 chapter 文件（崩溃遗留）→ 不识别且点名孤立文件."""
    (ws["chapters"] / "chapter_3.txt").write_text("孤儿章。\n", encoding="utf-8")
    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is False
    assert report.reason == "no_manifest"
    assert any("chapter_3.txt" in p for p in report.orphans)


def test_orphan_after_committed_head_detected(ws):
    """manifest 链头=1，崩溃遗留 chapter_2 → 孤儿被点名."""
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws, chapter_number=1))

    (ws["chapters"] / "chapter_2.txt").write_text("孤儿章。\n", encoding="utf-8")

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    report = fresh.recover()
    assert report.recognized is True  # 链头提交本身完好
    assert any("chapter_2.txt" in p for p in report.orphans)


# ---- 五态状态机 + flow v2 零成本 ----
def test_set_run_status_flow_v2_no_manifest(tmp_path):
    """flow v2 工作区：set_run_status 是 no-op，不产生任何产物（零成本契约）."""
    output_dir = tmp_path / "output" / "compose"
    output_dir.mkdir(parents=True)
    (output_dir / ".flow_version").write_text("2", encoding="utf-8")

    result = set_run_status(
        output_dir,
        run_id="compose-1",
        mode="compose",
        status="draft",
        chapter_number=1,
    )
    assert result is None
    assert not (output_dir / "run_manifest.json").exists()


def test_set_run_status_flow_v3_state_machine(ws):
    """flow v3：staged→draft→reviewed→committed 逐步落盘，非法迁移被拒."""
    for status, chapter in [
        ("staged", 1),
        ("draft", 1),
        ("reviewed", 1),
        ("committed", 1),
    ]:
        m = set_run_status(
            ws["output_dir"],
            run_id=derive_run_id("compose", 1),
            mode="compose",
            status=status,
            chapter_number=chapter,
        )
        assert m is not None
        assert m.status == status

    # 非法迁移：committed → draft 被拒
    with pytest.raises(ValueError):
        set_run_status(
            ws["output_dir"],
            run_id=derive_run_id("compose", 1),
            mode="compose",
            status="draft",
            chapter_number=1,
        )


def test_set_run_status_stable_run_id_updates_in_place(ws):
    """同 run_id 重跑：manifest 原地更新，不新建历史条目."""
    set_run_status(
        ws["output_dir"],
        run_id="compose-1",
        mode="compose",
        status="staged",
        chapter_number=1,
    )
    set_run_status(
        ws["output_dir"],
        run_id="compose-1",
        mode="compose",
        status="draft",
        chapter_number=1,
    )
    m = read_run_manifest(ws["output_dir"])
    assert m is not None
    assert m.run_id == "compose-1"
    assert m.status == "draft"


def test_set_run_status_new_run_after_commit_archives_prior(ws):
    """多章续写：新 run_id + 旧 run 终态 → 归档旧提交记录、从新 run 重新开始."""
    # 第一章走完 staged→draft→reviewed→committed
    for status in ("staged", "draft", "reviewed", "committed"):
        set_run_status(
            ws["output_dir"],
            run_id="extend-1",
            mode="extend",
            status=status,
            chapter_number=1,
        )
    m1 = read_run_manifest(ws["output_dir"])
    assert m1 is not None and m1.status == "committed"

    # 第二章（新 run_id）：不再报 committed→draft 非法，而是归档旧 run 开新 run
    m2 = set_run_status(
        ws["output_dir"],
        run_id="extend-2",
        mode="extend",
        status="draft",
        chapter_number=2,
    )
    assert m2 is not None
    assert m2.run_id == "extend-2"
    assert m2.status == "draft"
    assert m2.chapter_number == 2
    # 旧提交记录已归档到 run_history/，且备注标注归档
    hist = list((ws["output_dir"] / "run_history").glob("extend-1-*.json"))
    assert hist, "旧 run 提交记录应归档到 run_history/"
    archived = json.loads(hist[0].read_text(encoding="utf-8"))
    assert archived["status"] == "committed"
    assert archived["run_id"] == "extend-1"
    assert "archived prior run extend-1" in " / ".join(m2.notes or [])

    # 同 run_id 仍严格：第二章走完 committed 后，再向 extend-2 设 draft 仍非法
    set_run_status(
        ws["output_dir"],
        run_id="extend-2",
        mode="extend",
        status="reviewed",
        chapter_number=2,
    )
    set_run_status(
        ws["output_dir"],
        run_id="extend-2",
        mode="extend",
        status="committed",
        chapter_number=2,
    )
    with pytest.raises(ValueError):
        set_run_status(
            ws["output_dir"],
            run_id="extend-2",
            mode="extend",
            status="draft",
            chapter_number=2,
        )


# ---- 迁移种子 ----
def test_seed_manifest_is_recognized_baseline(tmp_path):
    novel = tmp_path / "novel"
    chapters = novel / "chapters"
    output_dir = novel / "output" / "extend"
    chapters.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    # v2 链已到 1205
    (chapters / "chapter_1205.txt").write_text("前文。\n", encoding="utf-8")
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    seed = set_run_status(
        output_dir,
        run_id="migrate-v2-extend",
        mode="extend",
        status="committed",
        chapter_number=1205,
        notes=["migrated from flow v2 preserving old artifacts"],
    )
    assert seed is not None

    fresh = ChapterCommitBoundary(output_dir, chapters)
    report = fresh.recover()
    # 种子是合法基线：recognized，无孤儿
    assert report.recognized is True
    assert report.manifest is not None
    assert report.manifest.chapter_number == 1205
    assert report.orphans == []

    # 下一章续写从 1206 开始
    assert report.manifest.next_chapter_number() == 1206


# ---- inspect ----
def test_inspect_reports_recovery(ws):
    boundary = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    boundary.commit(**_commit_kwargs(ws))

    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    info = fresh.inspect()
    assert info["flow_version"] == "3"
    assert info["manifest"] is not None
    assert info["recovery"]["recognized"] is True
    assert info["run_history"]  # 提交后有历史快照


def test_inspect_no_manifest(ws):
    fresh = ChapterCommitBoundary(ws["output_dir"], ws["chapters"])
    info = fresh.inspect()
    assert info["manifest"] is None
    assert info["recovery"]["recognized"] is False
    assert info["recovery"]["reason"] == "no_manifest"
