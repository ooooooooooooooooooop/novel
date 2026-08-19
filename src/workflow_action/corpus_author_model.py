"""Deterministic Author extraction with a local staged inference exchange.

The persisted model contains aggregate metrics and neutral evidence only. Small
chapter samples are read solely into the local prompt for the operator's staged
analysis; they are never serialized into ``author_models``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from src.object_state.corpusauthormodel import (
    Author,
    AuthorRuntime,
    ChapterEvidence,
    SelectionPattern,
)

PROMPT_NAME = "corpus_author_model_prompt.txt"
RESPONSE_NAME = "corpus_author_model_response.json"

_SENTENCE_RE = re.compile(r"[^。！？!?.!?]+[。！？!?.!?]?")
_DIALOGUE_RE = re.compile(r"[“\"『「].*?[”\"』」]", re.S)
_SIGNAL_RE = re.compile(r"突然|忽然|就在这时|下一刻|然而|却|竟然|原来|没想到")
_CONFLICT_RE = re.compile(r"冲突|争执|质问|反驳|威胁|拒绝|对抗|危险|危机|失败|代价|必须|不能")
_TURN_RE = re.compile(r"突然|忽然|然而|却|竟然|原来|没想到|转身|沉默|决定|答应|拒绝")
_TAG_RE = re.compile(r"说道|说着|问道|答道|喊道|笑道|冷声道|开口")
_FIRST_RE = re.compile(r"我|我们|咱们|自己")
_THIRD_RE = re.compile(r"他|她|它|他们|她们|其")


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode chapter file: {path.name}")


def _chapter_files(root: Path) -> list[Path]:
    chapter_dir = root / "chapters"
    if chapter_dir.is_dir():
        return sorted(chapter_dir.glob("*.txt"))
    return sorted(root.rglob("*.txt"))


def _numeric_keys(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key, child in value.items():
            if key.lower() not in {"author", "book", "novel", "path", "text", "content", "prose"}:
                result.extend(_numeric_keys(child, f"{prefix}.{key}" if prefix else key))
        return result
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [prefix]
    if isinstance(value, list):
        result: list[str] = []
        for child in value:
            result.extend(_numeric_keys(child, prefix))
        return result
    return []


def _density(count: int, chars: int) -> float:
    return round(count * 1000 / chars, 6) if chars else 0.0


def _method_stats(chapters: list[str]) -> dict[str, float]:
    total_chars = sum(len(text) for text in chapters)
    sentences = [sentence for text in chapters for sentence in _SENTENCE_RE.findall(text) if sentence.strip()]
    sentence_chars = sum(len(sentence) for sentence in sentences)
    dialogue_chars = sum(len(match.group(0)) for text in chapters for match in _DIALOGUE_RE.finditer(text))
    signal_hits = sum(len(_SIGNAL_RE.findall(text)) for text in chapters)
    conflict_hits = sum(len(_CONFLICT_RE.findall(text)) for text in chapters)
    turn_hits = sum(len(_TURN_RE.findall(text)) for text in chapters)
    dialogue_turns = sum(len(_TAG_RE.findall(text)) for text in chapters)
    first_hits = sum(len(_FIRST_RE.findall(text)) for text in chapters)
    third_hits = sum(len(_THIRD_RE.findall(text)) for text in chapters)
    hook_chapters = sum(
        bool(_SIGNAL_RE.search(text[-500:])) for text in chapters if text.strip()
    )
    paragraphs = sum(sum(1 for line in text.splitlines() if line.strip()) for text in chapters)
    return {
        "chapter_count": float(len(chapters)),
        "total_chars": float(total_chars),
        "avg_chapter_chars": round(total_chars / len(chapters), 6) if chapters else 0.0,
        "sentence_count": float(len(sentences)),
        "avg_sentence_chars": round(sentence_chars / len(sentences), 6) if sentences else 0.0,
        "dialogue_ratio": round(dialogue_chars / total_chars, 6) if total_chars else 0.0,
        "dialogue_turn_density_per_1000": _density(dialogue_turns, total_chars),
        "hook_signal_rate": round(hook_chapters / len(chapters), 6) if chapters else 0.0,
        "hook_signal_density_per_1000": _density(signal_hits, total_chars),
        "conflict_signal_density_per_1000": _density(conflict_hits, total_chars),
        "turning_point_signal_density_per_1000": _density(turn_hits, total_chars),
        "first_person_marker_density_per_1000": _density(first_hits, total_chars),
        "third_person_marker_density_per_1000": _density(third_hits, total_chars),
        "paragraph_count": float(paragraphs),
    }


def _metadata_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".json":
        return [root]
    return sorted(root.rglob("*.json")) if root.is_dir() else []


def _sample_indexes(chapter_count: int, sample_chapters: int) -> list[int]:
    if sample_chapters < 1:
        raise ValueError("sample_chapters must be at least 1")
    if chapter_count <= sample_chapters:
        return list(range(chapter_count))
    if sample_chapters == 1:
        return [0]
    last = chapter_count - 1
    return sorted({round(index * last / (sample_chapters - 1)) for index in range(sample_chapters)})


def inspect_corpus(
    input_path: str | Path,
    sample_chapters: int = 3,
) -> tuple[dict[str, int], dict[str, float], str, list[tuple[int, str]]]:
    """Read local corpus text for metrics, returning only neutral aggregates."""
    root = Path(input_path).expanduser().resolve()
    if sample_chapters < 1:
        raise ValueError("sample_chapters must be at least 1")
    if not root.exists():
        raise FileNotFoundError(str(input_path))
    if not root.is_dir() and root.suffix.lower() != ".json":
        raise ValueError("--input must be a metadata JSON file or a corpus directory")

    metadata_files = _metadata_files(root)
    chapter_paths = _chapter_files(root) if root.is_dir() else []
    chapters: list[str] = []
    digest = hashlib.sha256()
    for path in chapter_paths:
        text = _read_text(path)
        chapters.append(text)
        digest.update(path.name.encode("utf-8"))
        digest.update(text.encode("utf-8"))
    metric_keys: set[str] = set()
    numeric_count = 0
    for path in metadata_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid metadata JSON: {path.name}") from exc
        keys = _numeric_keys(payload)
        numeric_count += len(keys)
        metric_keys.update(key for key in keys if key and len(key) <= 80)
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())

    samples: list[tuple[int, str]] = []
    if chapters:
        indexes = _sample_indexes(len(chapters), sample_chapters)
        samples = [(index + 1, chapters[index][:1600]) for index in indexes]
    size = {
        "chapter_files": len(chapters),
        "metadata_files": len(metadata_files),
        "numeric_metadata_metrics": numeric_count,
        "sampled_chapters": len(samples),
    }
    stats = _method_stats(chapters)
    stats["metadata_metric_key_count"] = float(len(metric_keys))
    return size, stats, digest.hexdigest(), samples


def _neutralize_ref(value: str | None) -> str | None:
    if not value:
        return None
    candidate = Path(value).name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", candidate):
        return None
    return candidate


def _prompt(size: dict[str, int], stats: dict[str, float], digest: str, samples: list[tuple[int, str]]) -> str:
    sample_block = "\n\n".join(
        f"--- chapter evidence sample {index} ---\n{text}" for index, text in samples
    ) or "(no chapter samples available; use aggregate metrics only)"
    return (
        "You are extracting reusable selection-pattern evidence for a neutral Author model.\n"
        "This is not an identity claim and not a production gate. Do not copy prose, names,\n"
        "titles, paths, or private identifiers into the response. Return JSON only:\n"
        '{"selection_patterns":[{"pattern_id":"pattern-001","statement":"neutral pattern",'
        '"confidence":0.0,"chapter_evidence":[{"chapter_index":1,"metric":"signal",'
        '"value":"aggregate observation"}]}]}\n\n'
        f"Corpus size metadata: {json.dumps(size, sort_keys=True)}\n"
        f"Deterministic method statistics: {json.dumps(stats, sort_keys=True)}\n"
        f"Input digest: {digest[:16]} (reference only)\n\n"
        "Use the following local-only samples to ground the inference; never reproduce their wording:\n"
        f"{sample_block}\n"
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def extract_authors(inputs: list[str | Path], author_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Batch-friendly extraction; one neutral Author instance per corpus input."""
    ids = author_ids or [f"corpus-author-{index:03d}" for index in range(1, len(inputs) + 1)]
    if len(ids) != len(inputs):
        raise ValueError("author_ids must have one neutral id per corpus input")
    results = []
    for author_id, input_path in zip(ids, inputs):
        size, stats, digest, _ = inspect_corpus(input_path)
        results.append({"author_id": author_id, "corpus_size": size, "method_layer_stats": stats, "source_digest": digest})
    return results


def run(
    input_path: str | Path,
    output_dir: str | Path,
    author_id: str = "corpus-author-a",
    sample_chapters: int = 3,
) -> dict[str, Any]:
    size, stats, digest, samples = inspect_corpus(input_path, sample_chapters=sample_chapters)
    generation = "deep-v2" if sample_chapters > 3 else "deterministic-metadata-v1"
    output = Path(output_dir).expanduser().resolve()
    model_path = output / "author_models" / f"{author_id}.json"
    history_path = output / "author_models" / f"{author_id}.generations.json"
    response_path = output / RESPONSE_NAME
    prompt_path = output / PROMPT_NAME
    if model_path.exists():
        existing = Author.model_validate_json(model_path.read_text(encoding="utf-8"))
        existing_samples = existing.corpus_size.get("sampled_chapters", 0)
        if (
            existing.source_digest == digest
            and existing.author_id == author_id
            and existing.extraction_generation == generation
            and existing_samples >= size["sampled_chapters"]
        ):
            return {"status": "materialized", "path": str(model_path), "model": existing.model_dump(mode="json")}
        if (
            generation == "deep-v2"
            and existing.source_digest == digest
            and existing.author_id == author_id
            and existing.extraction_generation != generation
        ):
            _atomic_json(
                history_path,
                {
                    "schema_version": 1,
                    "generations": [existing.model_dump(mode="json")],
                },
            )
    if not response_path.exists():
        _atomic_json(
            prompt_path.with_suffix(".txt"),
            {"prompt": _prompt(size, stats, digest, samples)},
        )
        return {"status": "waiting", "prompt": str(prompt_path.with_suffix(".txt")), "response": str(response_path), "source_digest": digest}
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
        raw_patterns = payload["selection_patterns"]
        if not isinstance(raw_patterns, list) or not raw_patterns:
            raise ValueError("selection_patterns must be a non-empty list")
        patterns = [SelectionPattern.model_validate(item) for item in raw_patterns]
        if len({pattern.pattern_id for pattern in patterns}) != len(patterns):
            raise ValueError("selection pattern IDs must be unique")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid corpus author model response: {exc}") from exc
    prompt_hash = hashlib.sha256(prompt_path.with_suffix(".txt").read_bytes()).hexdigest() if prompt_path.with_suffix(".txt").exists() else ""
    response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest()
    runtime = AuthorRuntime(status="materialized", prompt_hash=prompt_hash, response_hash=response_hash)
    model = Author(
        author_id=author_id,
        method_layer_stats=stats,
        selection_patterns=patterns,
        corpus_size=size,
        source_digest=digest,
        extraction_generation=generation,
        runtime=runtime,
    )
    _atomic_json(model_path, model.model_dump(mode="json"))
    return {"status": "materialized", "path": str(model_path), "model": model.model_dump(mode="json")}
