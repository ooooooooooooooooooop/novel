"""Deterministic distillation and storage for AuthorTemplate.

It consumes explicit JSON evidence and never invents identity, persona, or prose facts.
Templates remain prior/shadow material and are not a production hard gate.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from src.object_state.authortemplate import AuthorTemplate, EvidenceRef, TemplatePrinciple

ROOT = Path(__file__).resolve().parents[2]

def template_dir(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("AUTHOR_TEMPLATES_DIR", ROOT / "author_templates"))

def _safe_source(source_id: str) -> str:
    """Hide local names while retaining a deterministic evidence handle."""
    digest = hashlib.sha256(str(source_id).encode("utf-8")).hexdigest()[:12]
    return f"source-{digest}"


def _safe_decision(decision_id: str) -> str:
    """Hide private decision labels while preserving stable lookup identity."""
    digest = hashlib.sha256(str(decision_id).encode("utf-8")).hexdigest()[:12]
    return f"decision-{digest}"

def _ledger(payload: dict[str, Any]) -> list[dict[str, Any]]:
    choices = payload.get("choices", payload.get("entries", []))
    if not isinstance(choices, list):
        raise ValueError("choice ledger choices must be a list")
    return [item for item in choices if isinstance(item, dict)]

def distill(payload: dict[str, Any], *, source_id: str = "choice-ledger.json", style: dict[str, Any] | None = None, twin: dict[str, Any] | None = None, kernel: dict[str, Any] | None = None) -> list[AuthorTemplate]:
    """Create up to three neutral candidates from real ChoiceLedger entries."""
    entries = _ledger(payload)
    source = _safe_source(source_id)
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        decision_id = str(entry.get("decision_id", "")).strip()
        if not decision_id:
            continue
        ref = EvidenceRef(decision_id=_safe_decision(decision_id), source_id=source)
        conflicts = entry.get("value_conflicts") or []
        for key in conflicts:
            if isinstance(key, str) and key.strip():
                groups.setdefault(key.strip(), []).append({"entry": entry, "ref": ref, "category": "value_conflict"})
        if str(entry.get("tradeoff", "")).strip():
            groups.setdefault("tradeoff_observed", []).append({"entry": entry, "ref": ref, "category": "tradeoff"})
        if str(entry.get("selected_candidate", "")).strip():
            groups.setdefault("selection_observed", []).append({"entry": entry, "ref": ref, "category": "selection"})
    keys = sorted(groups)[:3]
    result: list[AuthorTemplate] = []
    for index, key in enumerate(keys, 1):
        rows = groups[key]
        refs = [row["ref"] for row in rows]
        category = rows[0]["category"]
        label = "value conflict" if category == "value_conflict" else category
        principles = [TemplatePrinciple(category=category, key=key, description=f"Recorded evidence groups a recurring {label} pattern.", supporting_choices=refs)]
        hindsight_refs = [row["ref"] for row in rows if row["entry"].get("hindsight") in {"partial_regret", "overturned", "complex"}]
        if hindsight_refs:
            principles.append(TemplatePrinciple(category="hindsight", key=f"hindsight:{key}", description=f"Later evidence revisits choices touching {key}.", supporting_choices=hindsight_refs))
        result.append(AuthorTemplate(template_id=f"neutral-template-{index:03d}", hard_facts=[f"{len(rows)} recorded decisions reference {key}"], principles=principles, inference_notes=["Deterministic grouping of explicit choice evidence; not an identity claim."], style_references=[str(style.get("style_profile_id"))] if style and style.get("style_profile_id") else [], kernel_reference="available" if kernel else None, measurement_evidence=[EvidenceRef(decision_id=r["ref"].decision_id, source_id=source) for r in rows] if twin else [],))
    return result

def save(template: AuthorTemplate, path: str | Path | None = None) -> Path:
    directory = template_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{template.template_id}.json"
    target.write_text(json.dumps(template.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target

def load(template_id: str, path: str | Path | None = None) -> AuthorTemplate:
    return AuthorTemplate.model_validate_json((template_dir(path) / f"{template_id}.json").read_text(encoding="utf-8"))

def list_templates(path: str | Path | None = None) -> list[AuthorTemplate]:
    directory = template_dir(path)
    if not directory.exists(): return []
    return [load(item.stem, directory) for item in sorted(directory.glob("*.json"))]

def search(query: str, path: str | Path | None = None) -> list[AuthorTemplate]:
    q = query.casefold().strip()
    items = list_templates(path)
    def score(item: AuthorTemplate) -> tuple[int, str]:
        hay = json.dumps(item.model_dump(mode="json"), ensure_ascii=False).casefold()
        return (0 if q and q in hay else 1, item.template_id)
    return sorted(items, key=score)
