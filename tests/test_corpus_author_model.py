from pathlib import Path
import json

import pytest

from src.object_state.corpusauthormodel import Author, SelectionPattern
from src.workflow_action.corpus_author_model import extract_authors, run


def test_author_requires_chapter_evidence():
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="neutral pattern",
            confidence=0.5,
            chapter_evidence=[],
        )


def test_author_schema_forbids_identity_and_extra_fields():
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="author prefers this",
            confidence=0.5,
            chapter_evidence=[{"chapter_index": 1, "metric": "signal", "value": "1"}],
        )
    with pytest.raises(ValueError):
        SelectionPattern(
            pattern_id="p1",
            statement="neutral pattern",
            confidence=0.5,
            chapter_evidence=[{"chapter_index": 1, "metric": "signal", "value": "1", "extra": 1}],
        )


def test_metadata_workflow_waits_then_materializes_without_persisting_samples(tmp_path: Path):
    corpus = tmp_path / "corpus"
    (corpus / "chapters").mkdir(parents=True)
    (corpus / "chapters" / "chapter_001.txt").write_text("人物突然转身。", encoding="utf-8")
    (corpus / "chapters" / "chapter_002.txt").write_text("“他说道：继续。”", encoding="utf-8")
    (corpus / "metrics.json").write_text(json.dumps({"metrics": {"mean_length": 10}}), encoding="utf-8")
    output = tmp_path / "out"
    first = run(corpus, output)
    assert first["status"] == "waiting"
    prompt = (output / "corpus_author_model_prompt.txt").read_text(encoding="utf-8")
    assert "chapter evidence sample" in prompt
    response = output / "corpus_author_model_response.json"
    response.write_text(
        json.dumps(
            {
                "selection_patterns": [
                    {
                        "pattern_id": "pattern-001",
                        "statement": "turning points cluster near chapter endings",
                        "confidence": 0.8,
                        "chapter_evidence": [
                            {"chapter_index": 1, "metric": "hook_signal_rate", "value": "1"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    second = run(corpus, output)
    assert second["status"] == "materialized"
    model_path = output / "author_models" / "corpus-author-a.json"
    model = Author.model_validate_json(model_path.read_text(encoding="utf-8"))
    assert model.corpus_size["chapter_files"] == 2
    assert model.method_layer_stats["dialogue_ratio"] > 0
    assert "突然转身" not in model_path.read_text(encoding="utf-8")
    before = model_path.read_bytes()
    assert run(corpus, output)["status"] == "materialized"
    assert model_path.read_bytes() == before


def test_batch_extraction_supports_multiple_author_instances(tmp_path: Path):
    roots = []
    for index in range(2):
        root = tmp_path / f"corpus-{index}"
        (root / "chapters").mkdir(parents=True)
        (root / "chapters" / "chapter_001.txt").write_text("一章。", encoding="utf-8")
        roots.append(root)
    result = extract_authors(roots, ["author-a", "author-b"])
    assert [item["author_id"] for item in result] == ["author-a", "author-b"]
    assert result[0]["source_digest"] != ""
