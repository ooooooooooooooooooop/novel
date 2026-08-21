"""Validate one privacy-safe author-personality run directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


_HEADER = re.compile(
    r"--- chapter evidence sample (?P<chapter>\d+) "
    r"\((?P<work>work-\d{3}), (?P<stage>early|middle|late)\) ---"
)
_KINDS = {"signature_choice", "signature_refusal", "sacrifice_pattern", "obsession"}
_CLAIM_KEYS = {
    "claim_id", "kind", "statement", "confidence", "scope",
    "supporting_evidence", "counterevidence", "status",
}
_EVIDENCE_KEYS = {"work_slot", "stage", "chapter_index", "metric", "value"}
_FORBIDDEN = re.compile(r"author|book|novel|path|prose|content", re.IGNORECASE)


def _read_json(directory: Path, names: tuple[str, ...], errors: list[str]) -> Any:
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                errors.append("invalid_json")
                return None
    errors.append("missing_file")
    return None


def _response_owned_strings(response: Any):
    if not isinstance(response, dict) or not isinstance(response.get("selection_patterns"), list):
        return
    for pattern in response["selection_patterns"]:
        if not isinstance(pattern, dict):
            continue
        for key in ("statement",):
            if isinstance(pattern.get(key), str):
                yield pattern[key]
        evidence = pattern.get("chapter_evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if isinstance(item, dict):
                    for key in ("metric", "value"):
                        if isinstance(item.get(key), str):
                            yield item[key]


def _sidecar_owned_strings(sidecar: Any):
    if not isinstance(sidecar, dict):
        return
    claims = sidecar.get("claims")
    if isinstance(claims, list):
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if isinstance(claim.get("statement"), str):
                yield claim["statement"]
            supporting = claim.get("supporting_evidence")
            if isinstance(supporting, list):
                for item in supporting:
                    if isinstance(item, dict):
                        for key in ("metric", "value"):
                            if isinstance(item.get(key), str):
                                yield item[key]
            counterevidence = claim.get("counterevidence")
            if isinstance(counterevidence, list):
                for item in counterevidence:
                    if isinstance(item, str):
                        yield item
                    elif isinstance(item, dict):
                        for key in ("metric", "value"):
                            if isinstance(item.get(key), str):
                                yield item[key]
    pairs = sidecar.get("counterfactual_pairs")
    if isinstance(pairs, list):
        for pair in pairs:
            if isinstance(pair, dict) and isinstance(pair.get("predicted_divergence"), str):
                yield pair["predicted_divergence"]


def _prompt_samples(prompt: Any) -> list[str]:
    if not isinstance(prompt, str):
        return []
    matches = list(_HEADER.finditer(prompt))
    return [
        prompt[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(prompt)]
        for index, match in enumerate(matches)
    ]


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _has_verbatim_sample_overlap(owned: str, samples: list[str]) -> bool:
    normalized_owned = _normalize_whitespace(owned)
    if len(normalized_owned) < 24:
        return False
    for sample in samples:
        normalized_sample = _normalize_whitespace(sample)
        if len(normalized_sample) < 24:
            continue
        if normalized_owned in normalized_sample:
            return True
        if any(
            normalized_sample[index : index + 24] in normalized_owned
            for index in range(len(normalized_sample) - 23)
        ):
            return True
    return False


def _prompt_header_matches(prompt: Any) -> list[tuple[int, tuple[str, str]]]:
    if not isinstance(prompt, str):
        return []
    return [
        (int(match.group("chapter")), (match.group("work"), match.group("stage")))
        for match in _HEADER.finditer(prompt)
    ]


def validate_personality_run(run_dir: str | Path, author_id: str, run_id: str) -> list[str]:
    """Return stable, non-sensitive error codes; an empty list means valid."""
    errors: list[str] = []
    directory = Path(run_dir)
    prompt_data = _read_json(directory, ("corpus_author_model_prompt.txt",), errors)
    response = _read_json(directory, ("corpus_author_model_response.json",), errors)
    sidecar = _read_json(directory, ("personality_sidecar.json",), errors)

    prompt = prompt_data.get("prompt") if isinstance(prompt_data, dict) else None
    header_matches = _prompt_header_matches(prompt)
    headers = dict(header_matches)
    samples = _prompt_samples(prompt)
    if not isinstance(prompt, str):
        errors.append("prompt_string")
    if not header_matches:
        errors.append("prompt_headers")
    if len(headers) != len(header_matches):
        errors.append("prompt_headers")

    if any(_FORBIDDEN.search(value) for value in _response_owned_strings(response)):
        errors.append("forbidden_response_token")
    if not isinstance(response, dict) or set(response) != {"selection_patterns"}:
        errors.append("response_keys")
    patterns = response.get("selection_patterns") if isinstance(response, dict) else None
    if not isinstance(patterns, list) or len(patterns) != 4:
        errors.append("selection_patterns_count")
    else:
        pattern_ids: set[str] = set()
        for pattern in patterns:
            if not isinstance(pattern, dict) or set(pattern) != {
                "pattern_id", "statement", "confidence", "chapter_evidence"
            }:
                errors.append("pattern_keys")
                continue
            pattern_id = pattern["pattern_id"]
            if not isinstance(pattern_id, str) or pattern_id in pattern_ids:
                errors.append("pattern_id_unique")
            elif pattern_id not in pattern_ids:
                pattern_ids.add(pattern_id)
            evidence = pattern["chapter_evidence"]
            if not isinstance(evidence, list) or not evidence:
                errors.append("evidence_shape")
                continue
            for item in evidence:
                if not isinstance(item, dict) or set(item) != {
                    "chapter_index", "metric", "value"
                }:
                    errors.append("evidence_keys")

    if any(_FORBIDDEN.search(value) for value in _sidecar_owned_strings(sidecar)):
        errors.append("forbidden_sidecar_token")
    if not isinstance(sidecar, dict) or set(sidecar) != {
        "schema_version", "author_id", "run_id", "source_generation", "claims",
        "counterfactual_pairs", "uniqueness",
    }:
        errors.append("sidecar_keys")
    else:
        if sidecar["author_id"] != author_id or sidecar["run_id"] != run_id:
            errors.append("run_identity")
        uniqueness = sidecar["uniqueness"]
        if not isinstance(uniqueness, dict) or set(uniqueness) != {
            "status", "transferable_author_count"
        } or uniqueness["status"] != "not_run" or uniqueness["transferable_author_count"] is not None:
            errors.append("uniqueness")
        claims = sidecar["claims"]
        if not isinstance(claims, list) or len(claims) != 4:
            errors.append("claims_count")
        else:
            kinds: set[str] = set()
            for claim in claims:
                if not isinstance(claim, dict) or set(claim) != _CLAIM_KEYS:
                    errors.append("claim_keys")
                    continue
                kinds.add(claim["kind"])
                if claim["status"] != "candidate":
                    errors.append("claim_status")
                if claim["scope"] != "author_global":
                    errors.append("claim_scope")
                if not isinstance(claim["confidence"], (int, float)) or isinstance(
                    claim["confidence"], bool
                ) or claim["confidence"] < 0.85:
                    errors.append("claim_confidence")
                supporting = claim["supporting_evidence"]
                if not isinstance(supporting, list):
                    errors.append("supporting_evidence")
                    continue
                works: set[str] = set()
                stages: set[str] = set()
                for item in supporting:
                    if not isinstance(item, dict) or set(item) != _EVIDENCE_KEYS:
                        errors.append("supporting_evidence_keys")
                        continue
                    chapter = item["chapter_index"]
                    anchor = headers.get(chapter)
                    if anchor is None or (item["work_slot"], item["stage"]) != anchor:
                        errors.append("supporting_evidence_anchor")
                    works.add(item["work_slot"])
                    stages.add(item["stage"])
                if len(works) < 2:
                    errors.append("supporting_evidence_works")
                if len(stages) < 2:
                    errors.append("supporting_evidence_stages")
                counterevidence = claim["counterevidence"]
                if not isinstance(counterevidence, list) or any(
                    not isinstance(item, (str, dict))
                    or (isinstance(item, dict) and set(item) != _EVIDENCE_KEYS)
                    for item in counterevidence
                ):
                    errors.append("counterevidence")
            if kinds != _KINDS:
                errors.append("claim_kinds")
    owned_strings = list(_response_owned_strings(response)) + list(_sidecar_owned_strings(sidecar))
    if any(_has_verbatim_sample_overlap(value, samples) for value in owned_strings):
        errors.append("verbatim_sample_overlap")
    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("run_dir")
    parser.add_argument("--author-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    errors = validate_personality_run(args.run_dir, args.author_id, args.run_id)
    if not errors:
        print("PASS")
        return 0
    print(" ".join(f"{code}=1" for code in errors))
    return 1


if __name__ == "__main__":
    sys.exit(main())
