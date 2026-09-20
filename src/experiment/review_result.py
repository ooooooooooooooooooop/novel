"""Shared research Review acceptance and receipt-based source reporting.

These helpers do not call a provider or confer production/research validity.
Private drivers keep material and raw responses outside the public repository.
"""

import json
import os
import uuid
from pathlib import Path

from src.experiment.recorded_call import provenance_for_text
from src.workflow_action.review import ReviewUnit


def combined_review_issues(objects: list, llm_issues: list) -> list:
    """Model suggestions cannot erase deterministic findings."""
    review = ReviewUnit()
    review.validate_input(objects)
    return review._hard_rules(objects) + review._domain_rules(objects) + llm_issues


def validate_cached_review(case_dir: Path, stem: str, objects: list, prose: str) -> None:
    """Reject stale Review caches before callers can skip prompt validation."""
    expected = ReviewUnit().build_prompt(objects, context="extend", prose_text=prose)
    response = case_dir / f"{stem}_response.txt"
    prompt = case_dir / f"{stem}_prompt.txt"
    if response.exists() and (
        not prompt.exists() or prompt.read_text(encoding="utf-8") != expected
    ):
        raise ValueError(f"CACHED_REVIEW_CONTEXT_MISMATCH: {response.name}; preserve and reconcile old evidence")


def _receipt_attributed(item: dict) -> bool:
    """A response is attributed when its source request is unambiguous.

    KNOWN is exact. AMBIGUOUS still counts when every matching success receipt
    shares one requested_model — pooled upstreams may report different
    response_model labels for identical short adjudication outputs, which is
    a metadata-quality limit, not an attribution failure.
    """
    if item.get("status") == "KNOWN":
        return True
    return bool(
        item.get("status") == "AMBIGUOUS"
        and item.get("requested_model_consistent") is True
    )


def response_provenance(case_dir: Path, evidence_dir: Path) -> dict:
    """Report current response files; never infer identity from configuration."""
    responses = {}
    for path in sorted(case_dir.glob("*response*.txt")):
        if "_bad" not in path.stem:
            responses[path.name] = provenance_for_text(
                path.read_text(encoding="utf-8"), evidence_dir
            )
    generation = [responses.get(name, {"status": "UNKNOWN"}) for name in
                  ("continue_response.txt", "prose_response.txt")]
    if (case_dir / "revise_response.txt").exists():
        generation.append(responses["revise_response.txt"])
    if any(item["status"] != "KNOWN" for item in generation):
        model = "UNKNOWN"
    else:
        models = {item["response_model"] for item in generation}
        model = next(iter(models)) if len(models) == 1 else "MIXED"
    return {
        "gen_model": model,
        "response_receipts_complete": bool(responses) and all(
            _receipt_attributed(item) for item in responses.values()
        ),
        "responses": responses,
    }


def preflight_cached_contexts(material_dir: Path, output_dir: Path,
                              case_ids: list, seed_objects) -> dict:
    """Zero-call inspection, including cases skipped by a terminal cache."""
    from src.workflow_action.continuation import ContinueUnit

    rows = []
    for case_id in case_ids:
        case_dir = output_dir / case_id
        response = case_dir / "continue_response.txt"
        row = {"case": case_id, "input_status": "NOT_GENERATED"}
        if response.exists():
            try:
                prior = (material_dir / f"{case_id}.txt").read_text(encoding="utf-8")[-6000:]
                state, cast = seed_objects(case_id, prior)
                unit, next_state, _, _ = ContinueUnit().parse_response(
                    response.read_text(encoding="utf-8")
                )
                ReviewUnit.validate_input([state, *cast, unit, next_state])
                row["input_status"] = "VALID"
            except Exception as error:
                row.update(input_status="INVALID", reason=str(error))
        provenance = response_provenance(case_dir, output_dir / "_call_receipts")
        row.update(gen_model=provenance["gen_model"],
                   response_receipts_complete=provenance["response_receipts_complete"])
        rows.append(row)
    hold = output_dir / "LEGACY_INFLIGHT_HOLD.json"
    return {"network_calls": 0, "cases": rows, "legacy_request_unresolved": hold.exists()}


def _write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_review_result(case_dir: Path, audit: dict, objects: list,
                        issues: list, route: str, prose: str,
                        evidence_dir: Path) -> dict:
    """Only an accepted, nonempty review result gets the final-prose filename.

    ``issues`` is the combined list after specialist adjudication. Validate
    context even when the caller reused a cached model response.
    """
    review = ReviewUnit()
    review.validate_input(objects)
    route = review.resolve_route(issues, route)
    blocking = [issue.issue_type for issue in issues if issue.is_blocking()]
    accepted = route == "pass" and not blocking and bool(prose.strip())
    audit.update(route_final=route, blocking_final=blocking,
                 outcome="pass" if accepted else "blocked")
    provenance = response_provenance(case_dir, evidence_dir)
    audit.update(gen_model=provenance["gen_model"],
                 response_receipts_complete=provenance["response_receipts_complete"])
    _write(case_dir / "PROVENANCE.json", json.dumps(provenance, ensure_ascii=False, indent=2))
    final = case_dir / "prose_final.txt"
    if not accepted and final.exists():
        # Preserve the old artifact, but remove its misleading accepted name.
        final.rename(case_dir / f"prose_final_unaccepted_{uuid.uuid4().hex}.txt")
    _write(final if accepted else case_dir / "prose_rejected.txt", prose)
    _write(case_dir / "RESULT.json", json.dumps(audit, ensure_ascii=False, indent=2))
    return audit
