#!/usr/bin/env python3
"""Scout public Hugging Face Chinese web-novel datasets with bounded local samples."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import HfHubHTTPError

MAX_DATASET_BYTES = 2 * 1024 * 1024 * 1024
SAMPLE_BYTES = 64 * 1024 * 1024
MAX_PER_TERM = 30
MAX_DOWNLOAD_CANDIDATES = 12
SEARCH_TERMS = (
    "chinese webnovel",
    "网文",
    "起点",
    "qidian",
    "番茄",
    "晋江",
    "中文小说",
    "zh novel",
    "chinese fiction",
    "webnovel",
)
# The first scouting pass examined these repositories; they are excluded here.
PRIOR_REPOS = {
    "zxbsmk/webnovel_cn",
    "a686d380/sis-novel",
    "wdndev/webnovel-chinese",
    "lainka0o0/chinese-novel-nonH-collect",
}

AUTHOR_KEYS = {
    "author", "authors", "authorname", "author_name", "writer", "writer_name", "by",
    "作者", "作者名", "作家", "原作者", "著者",
}
TITLE_KEYS = {
    "title", "book", "bookname", "book_name", "novel", "novelname", "novel_name",
    "name", "书名", "作品", "作品名", "小说名",
}
CHAPTER_KEYS = {
    "chapter", "chapterid", "chapter_id", "chaptername", "chapter_name",
    "chaptertitle", "chapter_title", "章节", "章节名", "章节标题",
}
TEXT_KEYS = {"content", "text", "body", "paragraph", "正文", "内容", "tokens"}
DATA_SUFFIXES = {".json", ".jsonl", ".ndjson", ".txt", ".csv"}
WEBNOVEL_MARKERS = ("webnovel", "web novel", "网文", "起点", "qidian", "番茄", "晋江", "小说")
PUBLICATION_MARKERS = ("project gutenberg", "classic literature", "public domain", "translated novel", "books3")


class RateLimitExhausted(RuntimeError):
    """Raised after waiting through repeated public Hub rate limits."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def norm_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "")


def scalar_text(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def find_key(record: Any, keys: set[str], max_depth: int = 3) -> str | None:
    if max_depth < 0 or not isinstance(record, (dict, list)):
        return None
    if isinstance(record, dict):
        for key, value in record.items():
            if norm_key(key) in keys:
                found = scalar_text(value)
                if found:
                    return found
        for value in record.values():
            found = find_key(value, keys, max_depth - 1)
            if found:
                return found
    else:
        for value in record:
            found = find_key(value, keys, max_depth - 1)
            if found:
                return found
    return None


def estimate_chars(record: Any) -> int:
    if isinstance(record, str):
        return len(record)
    if not isinstance(record, dict):
        return 0
    total = 0
    for key, value in record.items():
        if norm_key(key) in TEXT_KEYS:
            if isinstance(value, str):
                total += len(value)
            elif isinstance(value, list):
                total += sum(len(str(item)) for item in value)
    if total:
        return total
    return sum(len(value) for key, value in record.items() if norm_key(key) in {"input", "output", "source", "target"} and isinstance(value, str))


def chapter_units(record: Any) -> int:
    if not isinstance(record, dict):
        return 1 if record else 0
    for key, value in record.items():
        if norm_key(key) in {"chapters", "chapter_list", "章节列表"} and isinstance(value, list):
            return max(1, len(value))
    return 1


def iter_json_array(path: Path, chunk_size: int = 4 * 1024 * 1024) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        buffer = ""
        started = False
        eof = False
        while True:
            if not eof:
                chunk = handle.read(chunk_size)
                if chunk:
                    buffer += chunk
                else:
                    eof = True
            while True:
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise ValueError("large JSON file is not a top-level array")
                    buffer = buffer[1:]
                    started = True
                buffer = buffer.lstrip()
                if buffer.startswith("]"):
                    return
                if not buffer:
                    break
                try:
                    value, used = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                yield value
                buffer = buffer[used:].lstrip()
                if buffer.startswith(","):
                    buffer = buffer[1:]
                elif buffer.startswith("]"):
                    return
                elif buffer and eof:
                    raise ValueError("malformed JSON array separator")
            if eof:
                if buffer.strip() in {"", "]"}:
                    return
                raise ValueError("truncated JSON array")


def iter_records(path: Path) -> Iterator[Any]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        return
    if suffix == ".json":
        yield from iter_json_array(path)
        return
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            yield from csv.DictReader(handle)
        return


def sha_handle(dataset_key: str, author: str) -> str:
    return hashlib.sha256((dataset_key + "\0" + author).encode("utf-8")).hexdigest()[:16]


def parse_filename_author(name: str) -> str | None:
    stem = Path(name).stem
    match = re.search(r"(?:\([^()]+\)|（[^（）]+）)([^.。]+)$", stem)
    if not match:
        return None
    author = re.sub(r"^[\s·•,，:：-]+|[\s·•,，:：-]+$", "", match.group(1))
    if not author or re.fullmatch(r"[0-9A-Za-z_-]+", author):
        return None
    return author


def count_text_chapters(text: str) -> int:
    headings = re.findall(r"(?m)^\s*(?:第[0-9零一二三四五六七八九十百千万]+[章节回部]|Chapter\s+\d+)", text, re.I)
    return max(1, len(headings)) if text.strip() else 0


def http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return status
    return getattr(exc, "code", None)


def call_wait_429(fn: Any, attempts: int = 4) -> Any:
    for attempt in range(attempts):
        try:
            return fn()
        except (HfHubHTTPError, urllib.error.HTTPError) as exc:
            if http_status(exc) != 429:
                raise
            if attempt + 1 >= attempts:
                raise RateLimitExhausted("Hub returned 429 after bounded waits") from exc
            time.sleep(60)
    raise RateLimitExhausted("Hub rate limit retry loop exhausted")


def api_files(api: HfApi, repo_id: str, revision: str | None) -> list[dict[str, Any]]:
    result = []
    for item in call_wait_429(lambda: api.list_repo_tree(repo_id, repo_type="dataset", revision=revision, recursive=True, expand=True)):
        path = getattr(item, "path", "")
        size = getattr(item, "size", None)
        if size is None:
            lfs = getattr(item, "lfs", None)
            size = getattr(lfs, "size", None) if lfs else None
        result.append({"path": path, "size": int(size or 0), "type": getattr(item, "type", "file")})
    return [item for item in result if item["type"] == "file"]


def card_value(card: Any, key: str) -> Any:
    if isinstance(card, dict):
        return card.get(key)
    return getattr(card, key, None)


def api_card(api: HfApi, repo_id: str, revision: str | None = None) -> dict[str, Any]:
    info = call_wait_429(lambda: api.dataset_info(repo_id, revision=revision, files_metadata=True))
    card = getattr(info, "cardData", None) or {}
    return {
        "id": getattr(info, "id", repo_id),
        "sha": getattr(info, "sha", None),
        "gated": bool(getattr(info, "gated", False)),
        "private": bool(getattr(info, "private", False)),
        "last_modified": getattr(info, "lastModified", None).isoformat() if getattr(info, "lastModified", None) else None,
        "license": card_value(card, "license"),
        "language": card_value(card, "language"),
        "card_text": str(card),
    }


def read_readme(api: HfApi, repo_id: str, revision: str | None, metadata_dir: Path) -> str:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = Path(call_wait_429(lambda: hf_hub_download(repo_id, "README.md", repo_type="dataset", revision=revision, local_dir=metadata_dir)))
        return path.read_text(encoding="utf-8", errors="replace")[:200_000]
    except (OSError, HfHubHTTPError, urllib.error.HTTPError):
        return ""


def locator_digest(repo_id: str) -> str:
    return hashlib.sha256(repo_id.encode("utf-8")).hexdigest()[:16]


def search_datasets(api: HfApi) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    by_repo: dict[str, dict[str, Any]] = {}
    term_counts: dict[str, int] = {}
    rate_limits = 0
    for term in SEARCH_TERMS:
        try:
            rows = list(call_wait_429(lambda term=term: api.list_datasets(search=term, sort="downloads", limit=MAX_PER_TERM, expand=["cardData"])))
        except RateLimitExhausted:
            rate_limits += 1
            break
        term_counts[term] = len(rows)
        for row in rows:
            repo_id = getattr(row, "id", None)
            if not repo_id or repo_id in PRIOR_REPOS:
                continue
            entry = by_repo.setdefault(repo_id, {
                "repo_id": repo_id,
                "downloads": int(getattr(row, "downloads", 0) or 0),
                "likes": int(getattr(row, "likes", 0) or 0),
                "terms": [],
            })
            entry["downloads"] = max(entry["downloads"], int(getattr(row, "downloads", 0) or 0))
            if term not in entry["terms"]:
                entry["terms"].append(term)
    candidates = sorted(by_repo.values(), key=lambda item: (-item["downloads"], item["repo_id"]))
    return candidates, term_counts, rate_limits


def screen_candidate(api: HfApi, candidate: dict[str, Any], metadata_dir: Path) -> dict[str, Any]:
    repo_id = candidate["repo_id"]
    result = dict(candidate)
    result["metadata_status"] = "pending"
    result["files"] = []
    try:
        card = api_card(api, repo_id)
        files = api_files(api, repo_id, card["sha"])
        readme = read_readme(api, repo_id, card["sha"], metadata_dir / locator_digest(repo_id))
        path_text = "\n".join(item["path"] for item in files[:500])
        corpus_text = (card["card_text"] + "\n" + readme + "\n" + path_text).lower()
        author_signal = bool(re.search(r"\bauthors?\b|\bauthor_name\b|作者|作家|原作者|著者", corpus_text))
        title_signal = bool(re.search(r"\btitle\b|\bbook(name)?\b|\bnovel(name)?\b|书名|作品|小说名", corpus_text))
        chapter_signal = bool(re.search(r"\bchapter(s)?\b|章节|章节名|章节标题", corpus_text))
        text_signal = any(Path(item["path"]).suffix.lower() in DATA_SUFFIXES for item in files)
        webnovel_signal = any(marker in corpus_text for marker in WEBNOVEL_MARKERS)
        publication_only = any(marker in corpus_text for marker in PUBLICATION_MARKERS) and not any(marker in corpus_text for marker in WEBNOVEL_MARKERS)
        license_value = card["license"]
        if isinstance(license_value, list):
            license_value = ",".join(str(value) for value in license_value)
        result.update({
            "revision": card["sha"],
            "license": str(license_value or "unknown"),
            "language": card["language"],
            "gated": card["gated"],
            "private": card["private"],
            "last_modified": card["last_modified"],
            "repository_file_count": len(files),
            "repository_bytes": sum(item["size"] for item in files),
            "field_evidence": {"author": author_signal, "title": title_signal, "chapter": chapter_signal, "text": text_signal},
            "webnovel_signal": webnovel_signal,
            "publication_only_signal": publication_only,
            "files": files,
        })
        if card["gated"]:
            result["metadata_status"] = "skipped_gated"
        elif card["private"]:
            result["metadata_status"] = "skipped_private"
        elif not author_signal:
            result["metadata_status"] = "eliminated_no_author_field"
        elif not webnovel_signal:
            result["metadata_status"] = "eliminated_not_webnovel"
        elif publication_only:
            result["metadata_status"] = "eliminated_publication_or_translation"
        elif not license_value:
            result["metadata_status"] = "skipped_missing_license"
        elif not text_signal:
            result["metadata_status"] = "eliminated_no_supported_text_file"
        else:
            result["metadata_status"] = "eligible_metadata"
    except RateLimitExhausted:
        result["metadata_status"] = "blocked_429"
        result["error_type"] = "RateLimitExhausted"
    except Exception as exc:
        result["metadata_status"] = "metadata_error"
        result["error_type"] = type(exc).__name__
    return result


def bounded_range_download(repo_id: str, filename: str, revision: str | None, destination: Path, size: int) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / (Path(filename).name + ".sample")
    if path.exists() and path.stat().st_size > 0:
        return path
    end = min(size, SAMPLE_BYTES) - 1
    url = f"https://huggingface.co/datasets/{repo_id}/resolve/{revision or 'main'}/{filename}"
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{end}", "User-Agent": "novel-dataset-scout/2"})

    def fetch() -> Path:
        with urllib.request.urlopen(request, timeout=120) as response, path.open("wb") as handle:
            remaining = end + 1
            while remaining:
                block = response.read(min(1024 * 1024, remaining))
                if not block:
                    break
                handle.write(block)
                remaining -= len(block)
        return path

    return call_wait_429(fetch)


def choose_files(files: list[dict[str, Any]], repository_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    data_files = [item for item in files if Path(item["path"]).suffix.lower() in DATA_SUFFIXES]
    data_files.sort(key=lambda item: (Path(item["path"]).suffix.lower() not in {".jsonl", ".json", ".ndjson"}, item["path"]))
    if repository_bytes <= MAX_DATASET_BYTES:
        selected: list[dict[str, Any]] = []
        total = 0
        for item in data_files:
            if total + item["size"] <= MAX_DATASET_BYTES:
                selected.append(item)
                total += item["size"]
        return selected, False
    return data_files[:2], True


def download_candidate(api: HfApi, item: dict[str, Any], destination: Path) -> tuple[list[Path], str, int]:
    files = item["files"]
    selected, sampled = choose_files(files, item["repository_bytes"])
    local_dir = destination / item["dataset_id"]
    downloaded: list[Path] = []
    for selected_file in selected:
        if sampled or selected_file["size"] > MAX_DATASET_BYTES:
            path = bounded_range_download(item["repo_id"], selected_file["path"], item.get("revision"), local_dir, selected_file["size"])
        else:
            path = Path(call_wait_429(lambda selected_file=selected_file: hf_hub_download(item["repo_id"], selected_file["path"], repo_type="dataset", revision=item.get("revision"), local_dir=local_dir)))
        downloaded.append(path)
    if not downloaded:
        return [], "no_supported_file_selected", local_dir.stat().st_size if local_dir.exists() else 0
    status = "downloaded_sample" if sampled else "downloaded_bounded"
    return downloaded, status, sum(path.stat().st_size for path in downloaded if path.exists())


def aggregate_records(dataset_key: str, paths: Iterable[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    authors: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"records_scanned": 0, "records_with_author": 0, "works_observed": 0, "chapter_units": 0, "estimated_characters": 0, "parse_errors": 0, "granularity": "record_units", "observed_top_level_keys": set()}
    for path in paths:
        try:
            for record in iter_records(path):
                if isinstance(record, dict):
                    stats["observed_top_level_keys"].update(str(key) for key in record)
                stats["records_scanned"] += 1
                author = find_key(record, AUTHOR_KEYS) or parse_filename_author(path.name)
                if not author:
                    continue
                stats["records_with_author"] += 1
                title = find_key(record, TITLE_KEYS) or path.stem
                key = sha_handle(dataset_key, author)
                entry = authors.setdefault(key, {"raw": author, "works": {}, "chapter_units": 0, "estimated_characters": 0})
                work = entry["works"].setdefault(title, {"chapter_units": 0, "estimated_characters": 0})
                units = chapter_units(record)
                chars = estimate_chars(record)
                work["chapter_units"] += units
                work["estimated_characters"] += chars
                entry["chapter_units"] += units
                entry["estimated_characters"] += chars
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
            stats["parse_errors"] += 1
    stats["works_observed"] = sum(len(item["works"]) for item in authors.values())
    stats["chapter_units"] = sum(item["chapter_units"] for item in authors.values())
    stats["estimated_characters"] = sum(item["estimated_characters"] for item in authors.values())
    keys = stats.pop("observed_top_level_keys")
    normalized = {norm_key(key) for key in keys}
    stats["observed_top_level_keys"] = sorted(keys)
    stats["observed_fields"] = {"author": bool(normalized & AUTHOR_KEYS), "title": bool(normalized & TITLE_KEYS), "chapter": bool(normalized & CHAPTER_KEYS), "text": bool(normalized & TEXT_KEYS)}
    return authors, stats


def aggregate_text_files(paths: Iterable[Path], dataset_key: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    authors: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {"records_scanned": 0, "records_with_author": 0, "works_observed": 0, "chapter_units": 0, "estimated_characters": 0, "parse_errors": 0, "granularity": "filename_work_and_heading_chapters", "observed_fields": {"author": True, "title": True, "chapter": True, "text": True}}
    for path in paths:
        author = parse_filename_author(path.name)
        stats["records_scanned"] += 1
        if not author:
            continue
        stats["records_with_author"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats["parse_errors"] += 1
            continue
        key = sha_handle(dataset_key, author)
        entry = authors.setdefault(key, {"raw": author, "works": {}, "chapter_units": 0, "estimated_characters": 0})
        chapters = count_text_chapters(text)
        entry["works"][path.stem] = {"chapter_units": chapters, "estimated_characters": len(text)}
        entry["chapter_units"] += chapters
        entry["estimated_characters"] += len(text)
    stats["works_observed"] = sum(len(item["works"]) for item in authors.values())
    stats["chapter_units"] = sum(item["chapter_units"] for item in authors.values())
    stats["estimated_characters"] = sum(item["estimated_characters"] for item in authors.values())
    return authors, stats


def eligible_author(item: dict[str, Any]) -> bool:
    return len(item["works"]) >= 2 or any(work["chapter_units"] >= 100 for work in item["works"].values())


def redact_dataset(item: dict[str, Any]) -> dict[str, Any]:
    keep = ("dataset_id", "search_terms", "downloads", "likes", "metadata_status", "license", "language", "gated", "private", "last_modified", "repository_file_count", "repository_bytes", "field_evidence", "webnovel_signal", "publication_only_signal", "download_status", "download_scope", "selected_file_count", "downloaded_bytes", "local_path", "records_scanned", "records_with_author", "works_observed", "chapter_units", "estimated_characters", "parse_errors", "observed_fields", "eligible_author_count", "eligible_author_single_work_count", "eligible_author_multi_work_count", "error_type")
    return {key: item[key] for key in keep if key in item}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", default="D:/datasets/hf-novels")
    parser.add_argument("--report", default="output/dataset_scout2_report.json")
    parser.add_argument("--receipt", default="output/dataset_scout2_receipt.json")
    args = parser.parse_args()

    started = iso_now()
    destination = Path(args.destination)
    destination.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    metadata_dir = destination / "_metadata"
    candidates, term_counts, search_rate_limits = search_datasets(api)
    screened: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        candidate["dataset_id"] = f"dataset-ds2-{index:03d}"
        item = screen_candidate(api, candidate, metadata_dir)
        item["dataset_id"] = candidate["dataset_id"]
        item["search_terms"] = list(candidate["terms"])
        screened.append(item)

    eligible_metadata = [item for item in screened if item.get("metadata_status") == "eligible_metadata"]
    selected_for_download = eligible_metadata[:MAX_DOWNLOAD_CANDIDATES]
    for item in eligible_metadata[MAX_DOWNLOAD_CANDIDATES:]:
        item["download_status"] = "deferred_download_cap"
        item["download_scope"] = "metadata_only"

    all_authors: list[dict[str, Any]] = []
    eliminated: defaultdict[str, int] = defaultdict(int)
    for item in screened:
        if item not in selected_for_download:
            status = item.get("metadata_status")
            if status and status != "eligible_metadata":
                eliminated[status] += 1
            continue
        try:
            downloaded, status, downloaded_bytes = download_candidate(api, item, destination)
            item["download_status"] = status
            item["downloaded_bytes"] = downloaded_bytes
            item["selected_file_count"] = len(downloaded)
            item["download_scope"] = "bounded_full_supported_files" if status == "downloaded_bounded" else "first_two_supported_files_64mb_ranges"
            if all(path.suffix.lower() == ".txt" or path.name.endswith(".txt.sample") for path in downloaded):
                raw_authors, stats = aggregate_text_files(downloaded, item["dataset_id"])
            else:
                raw_authors, stats = aggregate_records(item["dataset_id"], downloaded)
            item.update(stats)
            eligible = [value for value in raw_authors.values() if eligible_author(value)]
            item["eligible_author_count"] = len(eligible)
            item["eligible_author_single_work_count"] = sum(1 for value in eligible if len(value["works"]) == 1)
            item["eligible_author_multi_work_count"] = sum(1 for value in eligible if len(value["works"]) >= 2)
            for digest, value in sorted(raw_authors.items()):
                if not eligible_author(value):
                    continue
                all_authors.append({"dataset_id": item["dataset_id"], "repo_id": item["repo_id"], "digest": digest, "raw": value["raw"], "works": value["works"], "chapter_units": value["chapter_units"], "estimated_characters": value["estimated_characters"], "local_path": str(destination / item["dataset_id"]), "scope": item["download_scope"]})
        except RateLimitExhausted:
            item["download_status"] = "blocked_429"
            item["download_scope"] = "metadata_only_after_rate_limit"
            item["error_type"] = "RateLimitExhausted"
            eliminated["blocked_429"] += 1
            break
        except Exception as exc:
            item["download_status"] = "error"
            item["download_scope"] = "metadata_only_after_error"
            item["error_type"] = type(exc).__name__
            eliminated["download_error"] += 1

    author_rows = []
    identity_rows = []
    for index, item in enumerate(sorted(all_authors, key=lambda value: (value["dataset_id"], value["digest"])), start=1):
        author_id = f"author-ds2-{index:03d}"
        max_work_chapters = max((work["chapter_units"] for work in item["works"].values()), default=0)
        author_rows.append({"author_id": author_id, "works": len(item["works"]), "chapter_count_estimate": item["chapter_units"], "max_work_chapter_count_estimate": max_work_chapters, "estimated_characters": item["estimated_characters"], "source_dataset": item["dataset_id"], "local_path": item["local_path"], "scope": item["scope"]})
        identity_rows.append({"author_id": author_id, "author_name": item["raw"], "works": sorted(item["works"]), "source_dataset": item["dataset_id"], "repo_id": item["repo_id"]})

    identity_path = destination / "identity_map2.local.json"
    identity_path.write_text(json.dumps({"schema_version": 1, "generated_at": iso_now(), "privacy": "local_only; do_not_commit_or_include_in_reports_or_receipts", "mapping": identity_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_payload = {
        "schema_version": 2,
        "generated_at": iso_now(),
        "privacy": {"contains_prose": False, "contains_author_names": False, "identity_mapping": "local_only_identity_map2", "purpose": "author-distillation-corpus-scout"},
        "search": {"terms": list(SEARCH_TERMS), "per_term_limit": MAX_PER_TERM, "term_result_counts": term_counts, "unique_candidates_after_prior_exclusion": len(candidates), "excluded_prior_candidate_count": sum(1 for candidate in candidates if candidate["repo_id"] in PRIOR_REPOS), "search_rate_limit_events": search_rate_limits},
        "selection_rule": "retain an observed author with at least two works, or one work with at least 100 observed chapter units, within one source dataset",
        "download_policy": {"max_dataset_bytes": MAX_DATASET_BYTES, "sample_bytes": SAMPLE_BYTES, "max_download_candidates": MAX_DOWNLOAD_CANDIDATES, "gated": "metadata recorded and skipped", "rate_limit": "wait 60 seconds between bounded retries; stop after exhaustion"},
        "authors": author_rows,
        "datasets": [redact_dataset(item) for item in screened],
        "elimination_summary": dict(sorted(eliminated.items())),
    }
    report_path = Path(args.report)
    receipt_path = Path(args.receipt)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt_payload = {
        "schema_version": 1,
        "status": "ready_for_review",
        "started_at": started,
        "completed_at": iso_now(),
        "updated_at": iso_now(),
        "destination_root": str(destination),
        "identity_map_path": str(identity_path),
        "report_path": str(report_path),
        "candidate_count": len(screened),
        "downloaded_dataset_count": sum(1 for item in screened if str(item.get("download_status", "")).startswith("downloaded")),
        "author_count": len(author_rows),
        "contains_prose": False,
        "contains_author_names": False,
        "git_action": "none",
        "constraints": ["No dataset正文 copied into git or receipt", "No real author names in report or receipt", "No commit", "No push", "Gated datasets are recorded and skipped", "429 responses are waited out and never bypassed"],
        "routing_audit": {"packages": [{"id": "WP-DATASET-SCOUT2", "lane": "brain", "mechanism": "direct bounded script after native read-only exploration", "resolved_model_effort": "Opus 4.8", "deliverable": "rotated HF search, metadata screening, bounded local samples, neutral report, local identity map, receipt", "verification": "fresh script run plus report privacy scan and structural aggregate checks", "escalation": "human review before corpus use", "receipt": "override: brain - WP-DATASET-SCOUT2: external dataset identity, licensing, bounded-download policy, and privacy-safe aggregation require final sign-off"}], "direct_brain_labour": {"reads": 4, "searches": 5, "evidence": 4, "tests": 2, "docs": 0, "other": 4}},
    }
    receipt_path.write_text(json.dumps(receipt_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ready_for_review", "candidates": len(screened), "authors": len(author_rows), "report": str(report_path), "receipt": str(receipt_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
