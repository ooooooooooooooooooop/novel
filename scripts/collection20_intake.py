"""Inventory a local collection into privacy-safe Author method-layer artifacts.

The collection itself and the identity map remain outside the repository. Repository
artifacts contain only stable neutral IDs, aggregate metrics, digests, and counts.
No staged selection-pattern inference or prose persistence is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.boundary_control.chunking import split_by_chapters
from src.object_state.corpusauthormodel import Author, AuthorRuntime, ChapterEvidence, SelectionPattern
from src.workflow_action.corpus_author_model import extract_authors, _read_text

COLLECTION_NAME = "collection20"
DEFAULT_COLLECTION_ROOT = Path("D:/Download") / "网络小说20年精华合集：100多位大神作家代表作全收录(2)"
DEFAULT_IDENTITY_MAP = Path("D:/datasets/archive-novels") / "collection20_identity_map.local.json"
EXPECTED_TXT_COUNT = 651

_SAFE_REPO_KEYS = frozenset(
    {"author_name", "work_name", "title", "path", "source_path", "identity_key", "content", "text", "prose"}
)
_SEPARATOR_RE = re.compile(r"\s+|[|｜:：、_\-—]+")


class IntakeConflictError(RuntimeError):
    """An existing external identity map differs from this run."""


def _atomic_json(path: Path, payload: dict[str, Any], *, force: bool = True) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == text:
            return "unchanged"
        if not force:
            raise IntakeConflictError(str(path))
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return "written"


def _normalise_label(value: str) -> str:
    return " ".join(value.strip().split())


def _author_and_work(folder_name: str) -> tuple[str, str, bool]:
    """Split the conventional ``author work`` folder name conservatively."""
    name = _normalise_label(folder_name)
    parts = [part for part in _SEPARATOR_RE.split(name) if part]
    if len(parts) < 2:
        return name, name, True
    author = parts[0]
    work = name[len(author) :].strip(" \t|｜:：、_-—") or name
    return author, work, False


def _iter_work_dirs(root: Path) -> list[tuple[str, Path]]:
    """Return ``(genre, work_dir)`` pairs without reading file contents."""
    result: list[tuple[str, Path]] = []
    if not root.is_dir():
        return result
    for genre_dir in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda p: p.name):
        def visit(candidate: Path) -> None:
            direct_txt = [item for item in candidate.iterdir() if item.is_file() and item.suffix.lower() == ".txt"]
            chapter_txt = [
                item
                for item in (candidate / "chapters").iterdir()
                if item.is_file() and item.suffix.lower() == ".txt"
            ] if (candidate / "chapters").is_dir() else []
            if direct_txt or chapter_txt:
                result.append((genre_dir.name, candidate))
                return
            for child in sorted((item for item in candidate.iterdir() if item.is_dir()), key=lambda p: p.name):
                visit(child)
        visit(genre_dir)
    return result


def _txt_files(directory: Path, recursive: bool) -> list[Path]:
    """文本文件发现统一走 suffix.lower()——Windows 大小写不敏感文件系统曾掩盖
    glob("*.txt") 在 Linux 上漏掉 .TXT/.Txt 的事实（状态真源收敛 2026-08-30）。"""
    iterator = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        item for item in iterator if item.is_file() and item.suffix.lower() == ".txt"
    )


def _files_for_work(work_dir: Path) -> tuple[list[Path], str]:
    chapters = work_dir / "chapters"
    chapter_files = _txt_files(chapters, recursive=False) if chapters.is_dir() else []
    if chapter_files:
        return chapter_files, "existing_chapters"
    return _txt_files(work_dir, recursive=True), "split_source"


def _read_collection_text(path: Path) -> str:
    try:
        return _read_text(path)
    except (UnicodeDecodeError, ValueError):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be", "big5"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"cannot decode collection text: {path.name}")


def _read_chunks(work_dir: Path) -> tuple[list[tuple[str, str]], str, int]:
    files, mode = _files_for_work(work_dir)
    chunks: list[tuple[str, str]] = []
    fallback_count = 0
    for source in files:
        text = _read_collection_text(source)
        if mode == "existing_chapters":
            if text.strip():
                chunks.append((source.name, text))
            continue
        split = split_by_chapters(text)
        if len(split) == 1 and split[0].chapter_title == "全文":
            fallback_count += 1
        for index, chunk in enumerate(split, start=1):
            if chunk.text.strip():
                chunks.append((f"{source.stem}-{index:04d}.txt", chunk.text))
    return chunks, mode, fallback_count


def _safe_repo_payload(payload: dict[str, Any]) -> None:
    """Reject identity/prose-shaped fields before writing a repository artifact."""
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if _SAFE_REPO_KEYS.intersection(value):
                raise ValueError("repository payload contains an identity or prose field")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            if re.search(r"(?:[A-Za-z]:[\\/]|\\\\|/Users/|/home/)", value):
                raise ValueError("repository payload contains an absolute path")
    visit(payload)


def _neutral_model(author_id: str, result: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    pattern = SelectionPattern(
        pattern_id="method-layer-only",
        statement="deterministic aggregate metrics only; no inference",
        confidence=0.0,
        chapter_evidence=[
            ChapterEvidence(
                chapter_index=1,
                metric="aggregate_metric",
                value="deterministic_aggregate_only",
            )
        ],
    )
    size = {key: int(value) for key, value in result["corpus_size"].items()}
    size.update({key: int(value) for key, value in counts.items()})
    model = Author(
        author_id=author_id,
        method_layer_stats=result["method_layer_stats"],
        selection_patterns=[pattern],
        corpus_size=size,
        source_digest=result["source_digest"],
        extraction_generation="deterministic-metadata-v1",
        runtime=AuthorRuntime(algorithm="collection20-method-layer-v1", status="materialized"),
    )
    return model.model_dump(mode="json")


def _count_files(work_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in work_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() != ".txt":
            suffix = path.suffix.lower().lstrip(".") or "no_extension"
            counts[suffix] = counts.get(suffix, 0) + 1
    return counts


def _source_digest(paths: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _assert_external_identity_path(identity_map: Path, repo_root: Path) -> None:
    try:
        identity_map.relative_to(repo_root)
    except ValueError:
        return
    raise ValueError("identity map must be outside the repository")


def _remove_stale_models(model_dir: Path, active_ids: set[str]) -> int:
    removed = 0
    for path in model_dir.glob("collection20-a*.json"):
        if not re.fullmatch(r"collection20-a\d{3}\.json", path.name):
            continue
        if path.stem in active_ids:
            continue
        path.unlink()
        removed += 1
    return removed


def run_intake(
    collection_root: Path,
    repo_root: Path,
    identity_map: Path,
    *,
    expected_txt_count: int = EXPECTED_TXT_COUNT,
    force_identity_map: bool = False,
) -> dict[str, Any]:
    """Run the bounded collection inventory and write all requested artifacts."""
    output_dir = repo_root / "output"
    model_dir = repo_root / "author_models" / COLLECTION_NAME
    _assert_external_identity_path(identity_map.resolve(), repo_root.resolve())
    errors: list[dict[str, str]] = []
    if not collection_root.is_dir():
        receipt = {
            "schema_version": 1,
            "collection_id": COLLECTION_NAME,
            "status": "blocked",
            "source": {"genre_count": 0, "work_count": 0, "txt_count": 0, "expected_txt_count": expected_txt_count},
            "outputs": {"roster": "output/collection20_roster.json", "receipt": "output/collection20_receipt.json"},
            "errors": [{"code": "collection_root_unavailable"}],
        }
        roster = {
            "schema_version": 1,
            "collection_id": COLLECTION_NAME,
            "status": "blocked",
            "author_count": 0,
            "work_count": 0,
            "txt_count": 0,
            "expected_txt_count": expected_txt_count,
            "authors": [],
        }
        _safe_repo_payload(roster)
        _safe_repo_payload(receipt)
        _atomic_json(output_dir / "collection20_roster.json", roster)
        _atomic_json(output_dir / "collection20_receipt.json", receipt)
        return receipt

    work_dirs = _iter_work_dirs(collection_root)
    author_buckets: dict[str, dict[str, Any]] = {}
    unsupported: dict[str, int] = {}
    txt_count = 0
    fallback_work_count = 0
    failed_work_count = 0

    for work_index, (genre, work_dir) in enumerate(work_dirs, start=1):
        author_label, work_label, ambiguous = _author_and_work(work_dir.name)
        key = _normalise_label(author_label) or work_dir.name
        bucket = author_buckets.setdefault(key, {"works": [], "chunks": [], "source_paths": [], "txt_count": 0, "fallback_count": 0, "unsupported": {}})
        files, _ = _files_for_work(work_dir)
        txt_count += len(files)
        work_record: dict[str, Any] = {
            "genre": genre,
            "folder_name": work_dir.name,
            "work_label": work_label,
            "ambiguous_folder_name": ambiguous,
            "txt_files": [str(path) for path in files],
            "source_path": str(work_dir.resolve()),
            "status": "ok",
        }
        try:
            chunks, mode, fallback_count = _read_chunks(work_dir)
            work_record.update({"chapter_mode": mode, "chapter_count": len(chunks), "fallback_count": fallback_count})
            bucket["chunks"].extend((work_dir.name, name, text) for name, text in chunks)
            bucket["source_paths"].extend(files)
            bucket["txt_count"] += len(files)
            bucket["fallback_count"] += fallback_count
            if fallback_count:
                fallback_work_count += 1
        except UnicodeError:
            work_record["status"] = "failed"
            failed_work_count += 1
            errors.append({"code": "work_decode_error", "work_ordinal": str(work_index)})
        except OSError:
            work_record["status"] = "failed"
            failed_work_count += 1
            errors.append({"code": "work_read_error", "work_ordinal": str(work_index)})
        except ValueError:
            work_record["status"] = "failed"
            failed_work_count += 1
            errors.append({"code": "work_text_unreadable", "work_ordinal": str(work_index)})
        file_counts = _count_files(work_dir)
        work_record["unsupported_file_counts"] = file_counts
        for suffix, count in file_counts.items():
            unsupported[suffix] = unsupported.get(suffix, 0) + count
            bucket["unsupported"][suffix] = bucket["unsupported"].get(suffix, 0) + count
        bucket["works"].append(work_record)

    ordered_authors = sorted(author_buckets, key=lambda value: (value.casefold(), value))
    active_ids = {f"collection20-a{index:03d}" for index in range(1, len(ordered_authors) + 1)}
    stale_models_removed = 0
    try:
        stale_models_removed = _remove_stale_models(model_dir, active_ids)
    except OSError:
        errors.append({"code": "stale_model_cleanup_failed"})
    model_entries: list[dict[str, Any]] = []
    roster_authors: list[dict[str, Any]] = []
    identity_authors: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="collection20-") as temp_root:
        temp_root_path = Path(temp_root)
        for index, key in enumerate(ordered_authors, start=1):
            author_id = f"collection20-a{index:03d}"
            bucket = author_buckets[key]
            corpus_dir = temp_root_path / author_id / "chapters"
            corpus_dir.mkdir(parents=True, exist_ok=True)
            for chapter_index, (_work_name, source_name, text) in enumerate(bucket["chunks"], start=1):
                (corpus_dir / f"{chapter_index:06d}-{source_name}").write_text(text, encoding="utf-8")
            status = "materialized"
            model_path = f"author_models/{COLLECTION_NAME}/{author_id}.json"
            if bucket["chunks"]:
                try:
                    result = extract_authors([temp_root_path / author_id], [author_id])[0]
                    result["source_digest"] = _source_digest(bucket["source_paths"], collection_root)
                    counts = {
                        "work_count": len(bucket["works"]),
                        "source_txt_count": bucket["txt_count"],
                        "fallback_work_count": bucket["fallback_count"],
                        "unsupported_file_count": sum(bucket["unsupported"].values()),
                    }
                    model = _neutral_model(author_id, result, counts)
                    _safe_repo_payload(model)
                    _atomic_json(model_dir / f"{author_id}.json", model)
                    model_entries.append(model)
                except (OSError, ValueError):
                    status = "failed"
                    errors.append({"code": "author_method_layer_failed", "author_id": author_id})
            else:
                status = "failed"
                errors.append({"code": "author_has_no_readable_txt", "author_id": author_id})
            roster_authors.append({
                "author_id": author_id,
                "work_count": len(bucket["works"]),
                "txt_count": bucket["txt_count"],
                "fallback_work_count": bucket["fallback_count"],
                "unsupported_file_count": sum(bucket["unsupported"].values()),
                "status": status,
            })
            identity_authors.append({
                "author_id": author_id,
                "identity_key": key,
                "works": bucket["works"],
            })

    if txt_count != expected_txt_count:
        errors.append({"code": "txt_count_mismatch", "observed": str(txt_count), "expected": str(expected_txt_count)})
    status = "blocked" if not work_dirs or not model_entries else ("partial" if errors else "completed")
    roster = {
        "schema_version": 1,
        "collection_id": COLLECTION_NAME,
        "status": status,
        "author_count": len(ordered_authors),
        "work_count": len(work_dirs),
        "txt_count": txt_count,
        "expected_txt_count": expected_txt_count,
        "fallback_work_count": fallback_work_count,
        "failed_work_count": failed_work_count,
        "stale_models_removed": stale_models_removed,
        "unsupported_file_counts": unsupported,
        "authors": roster_authors,
    }
    _safe_repo_payload(roster)
    identity_payload = {
        "schema_version": 1,
        "collection_id": COLLECTION_NAME,
        "source_root": str(collection_root.resolve()),
        "authors": identity_authors,
    }
    try:
        _atomic_json(identity_map, identity_payload, force=force_identity_map)
    except IntakeConflictError:
        errors.append({"code": "identity_map_conflict"})
        status = "partial"
    roster["status"] = status
    receipt = {
        "schema_version": 1,
        "collection_id": COLLECTION_NAME,
        "status": status,
        "source": {
            "genre_count": len({genre for genre, _ in work_dirs}),
            "work_count": len(work_dirs),
            "txt_count": txt_count,
            "expected_txt_count": expected_txt_count,
            "fallback_work_count": fallback_work_count,
            "failed_work_count": failed_work_count,
            "stale_models_removed": stale_models_removed,
            "unsupported_file_counts": unsupported,
        },
        "outputs": {
            "roster": "output/collection20_roster.json",
            "receipt": "output/collection20_receipt.json",
            "author_models": f"author_models/{COLLECTION_NAME}/",
            "identity_map": "external_only",
        },
        "errors": errors,
        "privacy": {"repository_payload": "neutral_allowlist_checked", "selection_inference": "not_run", "prose_persisted": False},
    }
    _safe_repo_payload(receipt)
    _atomic_json(output_dir / "collection20_roster.json", roster)
    _atomic_json(output_dir / "collection20_receipt.json", receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inventory collection20 into neutral method-layer artifacts")
    parser.add_argument("--root", type=Path, default=DEFAULT_COLLECTION_ROOT)
    parser.add_argument("--identity-map", type=Path, default=DEFAULT_IDENTITY_MAP)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-txt-count", type=int, default=EXPECTED_TXT_COUNT)
    parser.add_argument("--force", action="store_true", help="replace a conflicting external identity map")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = run_intake(
            args.root.expanduser().resolve(),
            args.repo_root.expanduser().resolve(),
            args.identity_map.expanduser().resolve(),
            expected_txt_count=args.expected_txt_count,
            force_identity_map=args.force,
        )
    except (OSError, ValueError, IntakeConflictError) as exc:
        print(f"collection20 intake failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
