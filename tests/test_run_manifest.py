"""Q1 Phase 2 — RunManifest 模型测试：五态 / 哈希 / 序列化 / 链头推号."""

import json

from src.object_state.run_manifest import (
    RunManifest,
    read_run_manifest,
    sha256_text,
)


def _manifest(**overrides) -> RunManifest:
    base = dict(
        run_id="compose-1",
        mode="compose",
        status="committed",
        chapter_ref="chapter_1",
        chapter_number=1,
        artifacts={"chapters/chapter_1.txt": "a" * 64},
        created_at_utc="2026-08-10T00:00:00+00:00",
        committed_at_utc="2026-08-10T00:00:00+00:00",
    )
    base.update(overrides)
    return RunManifest(**base)


def test_run_manifest_round_trip():
    """序列化往返：model_dump → validate 语义不变."""
    m = _manifest()
    data = json.loads(m.model_dump_json())
    m2 = RunManifest.model_validate(data)
    assert m2 == m
    assert m2.status == "committed"
    assert m2.kind == "run"


def test_run_manifest_forbids_extra_fields():
    import pytest

    with pytest.raises(Exception):
        RunManifest(
            run_id="compose-1",
            mode="compose",
            status="staged",
            unexpected_field=True,
        )


def test_run_manifest_valid_statuses():
    assert RunManifest(
        run_id="x", mode="compose", status="staged"
    ).status == "staged"
    assert RunManifest(
        run_id="x", mode="extend", status="rejected"
    ).status == "rejected"


def test_run_manifest_invalid_status_rejected():
    import pytest

    with pytest.raises(Exception):
        RunManifest(run_id="x", mode="compose", status="partial")


def test_five_state_transition_table():
    """合法迁移：staged→draft→reviewed→{committed,rejected}; 非法迁移被拒."""
    legal = [
        ("staged", "draft"),
        ("draft", "reviewed"),
        ("reviewed", "committed"),
        ("reviewed", "rejected"),
    ]
    for src, dst in legal:
        m = _manifest(status=src)
        assert m.transition_allowed(dst), f"{src} -> {dst} should be allowed"

    illegal = [
        ("staged", "committed"),
        ("draft", "rejected"),
        ("draft", "committed"),
        ("committed", "draft"),
        ("rejected", "committed"),
    ]
    for src, dst in illegal:
        m = _manifest(status=src)
        assert not m.transition_allowed(dst), f"{src} -> {dst} should be blocked"

    # 幂等重设同态允许
    for s in ("staged", "draft", "reviewed", "committed", "rejected"):
        m = _manifest(status=s)
        assert m.transition_allowed(s)


def test_next_chapter_number_from_chain_head():
    assert _manifest(chapter_number=23).next_chapter_number() == 24
    assert _manifest(chapter_number=None).next_chapter_number() == 1
    # 非 committed 不推号
    m = _manifest(status="draft", chapter_number=5)
    assert m.next_chapter_number() is None


def test_seed_kind_baseline():
    """迁移种子：committed + kind=seed 是合法基线，推号连续."""
    seed = _manifest(kind="seed", run_id="migrate-v2-extend", mode="migrate",
                     chapter_number=1205, seeded=True, seeded_from_flow="2")
    assert seed.next_chapter_number() == 1206


def test_sha256_helpers():
    assert len(sha256_text("你好")) == 64
    assert sha256_text("a") != sha256_text("b")


def test_read_run_manifest_missing_returns_none(tmp_path):
    assert read_run_manifest(tmp_path) is None


def test_read_run_manifest_round_trip(tmp_path):
    m = _manifest()
    (tmp_path / "run_manifest.json").write_text(
        m.model_dump_json(indent=2), encoding="utf-8"
    )
    loaded = read_run_manifest(tmp_path)
    assert loaded is not None
    assert loaded.run_id == "compose-1"
    assert loaded.status == "committed"


def test_read_run_manifest_corrupt_returns_none(tmp_path):
    (tmp_path / "run_manifest.json").write_text("{not json", encoding="utf-8")
    assert read_run_manifest(tmp_path) is None
