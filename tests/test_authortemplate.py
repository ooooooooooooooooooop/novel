import json
from pathlib import Path
import pytest
from src.object_state.authortemplate import AuthorTemplate
from src.workflow_action.authortemplate import distill, list_templates, save, search, load
from src.novel_cli import main


def ledger():
    return {"schema_version": 1, "choices": [
        {"decision_id": "d1", "value_conflicts": ["consequence_visible"], "hindsight": "still_supported"},
        {"decision_id": "d2", "value_conflicts": ["consequence_visible", "information_permission"], "hindsight": "overturned"},
    ]}


def test_schema_extra_forbid():
    with pytest.raises(Exception):
        AuthorTemplate.model_validate({"template_id": "x", "unexpected": 1})


def test_empty_evidence_produces_no_principles():
    assert all(not item.principles for item in distill({"choices": []}))


def test_distill_supporting_refs_and_no_persona():
    result = distill(ledger(), source_id="private/path.json")
    assert result and all(p.supporting_choices for item in result for p in item.principles)
    assert all("persona" not in json.dumps(item.model_dump()).lower() for item in result)
    assert all(ref.decision_id.startswith("decision-") for item in result for p in item.principles for ref in p.supporting_choices)
    assert all(ref.source_id.startswith("source-") for item in result for p in item.principles for ref in p.supporting_choices)
    assert all("/" not in ref.source_id and "\\" not in ref.source_id for item in result for p in item.principles for ref in p.supporting_choices)


def test_store_and_search(tmp_path):
    for item in distill(ledger()): save(item, tmp_path)
    assert [x.template_id for x in list_templates(tmp_path)] == ["neutral-template-001", "neutral-template-002"]
    assert load("neutral-template-001", tmp_path).template_id == "neutral-template-001"
    assert search("information_permission", tmp_path)[0].template_id == "neutral-template-002"


def test_cli_list_show_distill_and_missing_input(tmp_path, capsys):
    for item in distill(ledger()): save(item, tmp_path)
    assert main(["author-template", "list", "--output-dir", str(tmp_path), "--json"]) == 0
    assert "neutral-template-001" in capsys.readouterr().out
    assert main(["author-template", "show", "neutral-template-001", "--output-dir", str(tmp_path), "--json"]) == 0
    assert "supporting_choices" in capsys.readouterr().out
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger()), encoding="utf-8")
    out = tmp_path / "generated"
    assert main(["author-template", "distill", "--choice-ledger", str(ledger_path), "--output-dir", str(out), "--json"]) == 0
    assert (out / "neutral-template-001.json").exists()
    assert main(["author-template", "distill", "--output-dir", str(tmp_path)]) == 1
