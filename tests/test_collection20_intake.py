from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.object_state.corpusauthormodel import Author
from scripts.collection20_intake import run_intake


def test_collection20_intake_is_neutral_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "collection"
    first = source / "genre-a" / "Alice Work One"
    second = source / "genre-a" / "Alice Work Two" / "chapters"
    third = source / "genre-b" / "Bob Work"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    third.mkdir(parents=True)
    (first / "book.txt").write_text("第一章 开始\n他看见门。\n第二章 冲突\n有人质问。", encoding="utf-8")
    (second / "001.txt").write_text("已有章节内容。", encoding="utf-8")
    (third / "book.TXT").write_text("没有标题的整本内容。", encoding="utf-8")
    (third / "cover.jpg").write_bytes(b"not prose")

    repo = tmp_path / "repo"
    identity = tmp_path / "outside" / "identity.json"
    receipt = run_intake(source, repo, identity, expected_txt_count=3)

    assert receipt["status"] == "completed"
    assert receipt["source"]["txt_count"] == 3
    assert receipt["source"]["fallback_work_count"] == 1
    assert receipt["source"]["unsupported_file_counts"] == {"jpg": 1}

    roster_path = repo / "output" / "collection20_roster.json"
    receipt_path = repo / "output" / "collection20_receipt.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    assert roster["author_count"] == 2
    assert {item["author_id"] for item in roster["authors"]} == {"collection20-a001", "collection20-a002"}

    model_paths = sorted((repo / "author_models" / "collection20").glob("*.json"))
    assert len(model_paths) == 2
    for path in model_paths:
        model = Author.model_validate_json(path.read_text(encoding="utf-8"))
        assert model.extraction_generation == "deterministic-metadata-v1"
        assert model.selection_patterns[0].pattern_id == "method-layer-only"
        assert "Alice" not in path.read_text(encoding="utf-8")
        assert "第一章" not in path.read_text(encoding="utf-8")

    public_text = "\n".join(
        [roster_path.read_text(encoding="utf-8"), receipt_path.read_text(encoding="utf-8")]
        + [path.read_text(encoding="utf-8") for path in model_paths]
    )
    assert "Alice" not in public_text
    assert "Bob" not in public_text
    assert "tmp_path" not in public_text
    identity_payload = json.loads(identity.read_text(encoding="utf-8"))
    assert identity_payload["authors"]
    assert "Alice" in identity.read_text(encoding="utf-8")

    before = {
        path: path.read_bytes()
        for path in [identity, roster_path, receipt_path, *model_paths]
    }
    second_receipt = run_intake(source, repo, identity, expected_txt_count=3)
    assert second_receipt == receipt
    assert {path: path.read_bytes() for path in before} == before

    with pytest.raises(ValueError, match="outside the repository"):
        run_intake(source, repo, repo / "identity.json", expected_txt_count=3)
