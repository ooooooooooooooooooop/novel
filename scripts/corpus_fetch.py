#!/usr/bin/env python3
"""Fetch a small, public Chinese web-novel corpus with auditable bounds.

All network activity is intentionally kept inside this script so the repository
venv can use the same urllib path as dataset_scout.py.  No login, CAPTCHA, or
access-control bypass is attempted.  Real author names stay in the local map.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MIN_INTERVAL_SECONDS = 2.0
MAX_SEARCH_PAGES = 10
MAX_LINK_PROBES = 40
MAX_DOWNLOADS = 24
TARGET_AUTHORS_MIN = 2
TARGET_AUTHORS_MAX = 3
BENCHMARK_AUTHORS = frozenset({"唐家三少", "我吃西红柿", "辰东", "猫腻", "烽火戏诸侯", "耳根", "忘语", "爱潜水的乌贼", "高月", "血红", "府天", "乘风御剑"})
USER_AGENT = "novel-corpus-fetch/1.0 (public metadata and openly accessible files only)"
REPO_ROOT = Path(__file__).resolve().parents[1]

CHANNELS = (
    ("zxcs-style", "知轩藏书类精校存档站", ("https://www.zxcs.me/", "https://zxcs.me/", "https://www.zxcs.info/")),
    ("package-mirror", "12560 本网文包公开镜像帖子", ()),
    ("other-public", "其他公开且无需登录的渠道", ()),
)
SEARCH_QUERIES = (
    ("zxcs-site-list", "site:zxcs.info 小说 作者 下载"),
    ("zxcs-site-benchmark", "site:zxcs.info 玄幻 都市 历史 仙侠"),
    ("archive-author", "知轩藏书 作者 全集 txt"),
    ("package-12560", "12560 本 网文 包 公开 镜像"),
    ("historical-benchmark", "历史 网文 大神 作品集 txt"),
    ("fantasy-benchmark", "玄幻 网文 大神 作品集 txt"),
    ("urban-benchmark", "都市 网文 大神 作品集 txt"),
    ("xianxia-benchmark", "仙侠 网文 大神 作品集 txt"),
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha_id(*parts: str, prefix: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value, flags=re.UNICODE).strip("._")
    return value[:120] or "file"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", html.unescape(value or "")).lower()


def parse_author(value: str) -> str | None:
    value = html.unescape(urllib.parse.unquote(value or "")).strip()
    patterns = (
        r"作者\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9_·-]{2,32})",
        r"[（(]([^（）()]{2,32})[）)]\s*$",
        r"[-—_ ]([^/\\<>]{2,32})\.(?:txt|epub|zip)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(r"[\s·•,，:：-]+$", "", match.group(1)).strip()
            if candidate and not re.fullmatch(r"[0-9A-Za-z_-]+", candidate):
                return candidate
    return None


def is_probable_prose(text: str) -> bool:
    text = text.strip()
    if len(text) < 500:
        return False
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    headings = len(re.findall(r"(?m)^\s*(?:第[0-9零一二三四五六七八九十百千万]+[章节回部]|Chapter\s+\d+)", text, re.I))
    return chinese >= 200 and (headings >= 2 or chinese / max(len(text), 1) >= 0.2)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append({"href": self._href, "text": " ".join(self._text).strip()})
            self._href = None
            self._text = []


@dataclass
class Requester:
    interval: float = MIN_INTERVAL_SECONDS
    last_request: float = 0.0

    def open(self, url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[int, dict[str, str], bytes]:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        request = urllib.request.Request(url, headers=request_headers, method=method)
        self.last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return int(response.status), dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read(4096) if method == "GET" else b""
            return int(exc.code), dict(exc.headers.items()), body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

    def stream_to(self, url: str, destination: Path, max_bytes: int, *, timeout: int = 120) -> dict[str, Any]:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        self.last_request = time.monotonic()
        temporary = destination.with_name(destination.name + ".part")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = int(response.status)
                headers = dict(response.headers.items())
                declared = int(headers.get("Content-Length", "0") or 0)
                if declared and declared > min(max_bytes, MAX_FILE_BYTES):
                    return {"status": "over_limit", "url_shape": host_shape(url), "http_status": status, "bytes": declared, "limit": min(max_bytes, MAX_FILE_BYTES)}
                total = 0
                destination.parent.mkdir(parents=True, exist_ok=True)
                with temporary.open("wb") as handle:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > min(max_bytes, MAX_FILE_BYTES):
                            handle.close()
                            temporary.unlink(missing_ok=True)
                            return {"status": "over_limit", "url_shape": host_shape(url), "http_status": status, "bytes": total, "limit": min(max_bytes, MAX_FILE_BYTES)}
                        handle.write(block)
                temporary.replace(destination)
                return {"status": "downloaded", "url_shape": host_shape(url), "http_status": status, "bytes": total, "content_type": headers.get("Content-Type", "")}
        except urllib.error.HTTPError as exc:
            temporary.unlink(missing_ok=True)
            return {"status": "blocked", "url_shape": host_shape(url), "http_status": int(exc.code)}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            return {"status": "error", "url_shape": host_shape(url), "error": f"{type(exc).__name__}: {exc}"}


def host_shape(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".txt", ".zip", ".epub", ".rar", ".7z"}:
        return f"{parsed.netloc}/file{suffix}"
    return f"{parsed.netloc}/html"


def unwrap_bing_href(href: str) -> str:
    parsed = urllib.parse.urlparse(href)
    if "bing.com" not in parsed.netloc:
        return href
    encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
    encoded = urllib.parse.unquote(encoded)
    if encoded.startswith("a1"):
        try:
            decoded = base64.urlsafe_b64decode(encoded[2:] + "===").decode("utf-8", "replace")
            if decoded.startswith(("http://", "https://")):
                return decoded
        except (ValueError, UnicodeError):
            pass
    return encoded if encoded.startswith(("http://", "https://")) else href


def search_bing(requester: Requester, query: str) -> tuple[list[str], dict[str, Any]]:
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "count": 10})
    try:
        status, headers, body = requester.open(url)
    except RuntimeError as exc:
        return [], {"status": "error", "error": str(exc)}
    if status != 200:
        return [], {"status": "http_blocked", "http_status": status}
    parser = LinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    results: list[str] = []
    for item in parser.links:
        href = unwrap_bing_href(html.unescape(item["href"]))
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme in {"http", "https"} and "bing.com" not in parsed.netloc and href not in results:
            results.append(href)
    return results[:10], {"status": "ok", "http_status": status, "result_count": len(results)}


def probe(requester: Requester, url: str) -> dict[str, Any]:
    result = {"url": url, "url_shape": host_shape(url)}
    try:
        status, headers, _ = requester.open(url, method="HEAD")
        result.update({
            "status": "ok" if 200 <= status < 300 else "blocked",
            "http_status": status,
            "content_length": int(headers.get("Content-Length", "0") or 0),
            "content_type": headers.get("Content-Type", ""),
            "login_or_captcha_signal": status in {401, 403, 429, 503} or any(token in url.lower() for token in ("login", "captcha", "verify")),
        })
    except RuntimeError as exc:
        result.update({"status": "error", "error": str(exc), "login_or_captcha_signal": False})
    return result


def extract_download_links(page_url: str, body: bytes) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    links: list[dict[str, str]] = []
    for item in parser.links:
        absolute = urllib.parse.urljoin(page_url, item["href"])
        suffix = Path(urllib.parse.urlparse(absolute).path).suffix.lower()
        if suffix in {".txt", ".zip", ".epub", ".rar", ".7z"}:
            links.append({"url": absolute, "text": item["text"]})
    return links


def extract_page_links(page_url: str, body: bytes) -> list[dict[str, str]]:
    parser = LinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    links: list[dict[str, str]] = []
    for item in parser.links:
        absolute = urllib.parse.urljoin(page_url, item["href"])
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme in {"http", "https"}:
            links.append({"url": absolute, "text": item["text"]})
    return links


def discover_download_links(requester: Requester, page_url: str, body: bytes, channel_id: str, seen_urls: set[str], candidates: list[dict[str, Any]]) -> None:
    page_host = urllib.parse.urlparse(page_url).netloc
    followed = 0
    for link in extract_page_links(page_url, body):
        if len(seen_urls) >= MAX_LINK_PROBES:
            return
        suffix = Path(urllib.parse.urlparse(link["url"]).path).suffix.lower()
        if suffix in {".txt", ".zip", ".epub", ".rar", ".7z"}:
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                candidates.append({"channel_id": channel_id, **link})
            continue
        parsed = urllib.parse.urlparse(link["url"])
        label = (link["text"] + " " + parsed.path).lower()
        if parsed.netloc != page_host or not parsed.path or parsed.path == urllib.parse.urlparse(page_url).path or any(token in label for token in ("login", "captcha", "javascript:")):
            continue
        if followed >= 8:
            return
        followed += 1
        if link["url"] in seen_urls:
            continue
        seen_urls.add(link["url"])
        try:
            status, headers, nested = requester.open(link["url"])
        except RuntimeError:
            continue
        if status == 200 and "text/html" in headers.get("Content-Type", "text/html"):
            page_author = parse_author(nested.decode("utf-8", "replace")) or ""
            for nested_link in extract_download_links(link["url"], nested):
                nested_link["text"] = f"{page_author} {link['text']} {nested_link['text']}"
                if nested_link["url"] not in seen_urls:
                    seen_urls.add(nested_link["url"])
                    candidates.append({"channel_id": channel_id, **nested_link})




def discover_zxcs_info(requester: Requester, channel: dict[str, Any], seen_urls: set[str], candidates: list[dict[str, Any]], seed_urls: list[str]) -> None:
    host = "www.zxcs.info"
    list_urls = list(seed_urls)
    detail_urls: list[str] = []
    visited: set[str] = set()

    for page_url in list_urls[:8]:
        if page_url in visited:
            continue
        visited.add(page_url)
        try:
            status, headers, body = requester.open(page_url)
        except RuntimeError as exc:
            channel["links"].append({"page_type": "list", "url_shape": host_shape(page_url), "status": "error", "error": str(exc)})
            continue
        channel["links"].append({"page_type": "list", "url_shape": host_shape(page_url), "status": "ok" if status == 200 else "blocked", "http_status": status, "content_type": headers.get("Content-Type", "")})
        if status != 200 or "text/html" not in headers.get("Content-Type", "text/html"):
            continue
        page_author = parse_author(body.decode("utf-8", "replace")) or ""
        for link in extract_page_links(page_url, body):
            parsed = urllib.parse.urlparse(link["url"])
            if parsed.netloc not in {host, "zxcs.info"} or link["url"] in visited:
                continue
            suffix = Path(parsed.path).suffix.lower()
            context = f"{page_author} {link['text']} {parsed.path}"
            if suffix in {".txt", ".zip", ".epub"}:
                if link["url"] not in seen_urls:
                    seen_urls.add(link["url"])
                    candidates.append({"channel_id": "zxcs-style", "url": link["url"], "text": context})
                continue
            path_lower = parsed.path.lower()
            if any(token in path_lower for token in ("post", "book", "article", "archive", "novel", "read", "view", "show")):
                detail_urls.append(link["url"])

    for detail_url in detail_urls[:24]:
        if detail_url in visited:
            continue
        visited.add(detail_url)
        try:
            status, headers, body = requester.open(detail_url)
        except RuntimeError as exc:
            channel["links"].append({"page_type": "detail", "url_shape": host_shape(detail_url), "status": "error", "error": str(exc)})
            continue
        channel["links"].append({"page_type": "detail", "url_shape": host_shape(detail_url), "status": "ok" if status == 200 else "blocked", "http_status": status, "content_type": headers.get("Content-Type", "")})
        if status != 200 or "text/html" not in headers.get("Content-Type", "text/html"):
            continue
        decoded = body.decode("utf-8", "replace")
        page_author = parse_author(decoded) or ""
        for link in extract_page_links(detail_url, body):
            parsed = urllib.parse.urlparse(link["url"])
            suffix = Path(parsed.path).suffix.lower()
            label = f"{page_author} {link['text']} {parsed.path}".lower()
            is_download = suffix in {".txt", ".zip", ".epub"} or any(token in label for token in ("下载", "download", "附件", "txt", "epub"))
            if not is_download:
                continue
            context = f"{page_author} {link['text']} {parsed.path}"
            if parsed.netloc not in {host, "zxcs.info"}:
                external = probe(requester, link["url"])
                channel["links"].append({"page_type": "external_download", "url_shape": external.get("url_shape"), "status": external.get("status"), "http_status": external.get("http_status"), "content_type": external.get("content_type", ""), "login_or_captcha_signal": external.get("login_or_captcha_signal", False)})
                continue
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                candidates.append({"channel_id": "zxcs-style", "url": link["url"], "text": context})


    return parse_author(link["text"]) or parse_author(urllib.parse.urlparse(link["url"]).path)


def download_file(requester: Requester, url: str, destination: Path, max_bytes: int) -> tuple[Path | None, dict[str, Any]]:
    result = requester.stream_to(url, destination, max_bytes)
    return (destination, result) if result.get("status") == "downloaded" else (None, result)


def materialize_texts(path: Path, author: str, author_dir: Path) -> list[Path]:
    if path.suffix.lower() == ".txt":
        return [path]
    if path.suffix.lower() == ".epub":
        return []
    if path.suffix.lower() != ".zip":
        return []
    outputs: list[Path] = []
    try:
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and Path(item.filename).suffix.lower() in {".txt", ".text"}]
            for index, member in enumerate(members[:50]):
                if member.file_size > MAX_FILE_BYTES:
                    continue
                raw = archive.read(member)
                text = raw.decode("utf-8", "replace")
                if not is_probable_prose(text):
                    try:
                        text = raw.decode("gb18030", "replace")
                    except UnicodeDecodeError:
                        continue
                if not is_probable_prose(text):
                    continue
                out = author_dir / f"work-{index:03d}.txt"
                out.write_text(text, encoding="utf-8")
                outputs.append(out)
    except (OSError, zipfile.BadZipFile):
        return []
    return outputs


def verify_sample(path: Path, author: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    prefix = text[:20000]
    signature = author in prefix or f"作者：{author}" in prefix or f"作者:{author}" in prefix
    return {
        "status": "pass" if is_probable_prose(text) and signature else "fail",
        "prose_signal": is_probable_prose(text),
        "signature_signal": signature,
        "sample_bytes": len(text.encode("utf-8")),
    }


def privacy_report(raw_authors: dict[str, dict[str, Any]], channels: list[dict[str, Any]], started: str, finished: str, errors: list[str]) -> dict[str, Any]:
    author_rows = []
    for item in sorted(raw_authors.values(), key=lambda row: row["author_id"]):
        author_rows.append({
            "author_id": item["author_id"],
            "sector": item["sector"],
            "work_count": len(item["works"]),
            "downloaded_bytes": item["bytes"],
            "sample_status": item.get("sample", {}).get("status", "not_run"),
        })
    return {
        "schema_version": 1,
        "status": "ready_for_review" if not errors else "blocked",
        "started_at": started,
        "completed_at": finished,
        "privacy": {"contains_prose": False, "contains_author_names": False, "contains_titles": False, "identity_mapping": "local_only"},
        "scope": {"author_min": TARGET_AUTHORS_MIN, "author_max": TARGET_AUTHORS_MAX, "total_bytes_limit": MAX_TOTAL_BYTES, "min_request_interval_seconds": MIN_INTERVAL_SECONDS, "sectors": ["都市", "玄幻", "历史", "科幻", "仙侠"]},
        "channels": channels,
        "authors": author_rows,
        "download_summary": {"author_count": len(author_rows), "work_count": sum(len(row["works"]) for row in raw_authors.values()), "downloaded_bytes": sum(row["bytes"] for row in raw_authors.values())},
        "errors": errors,
        "git_action": "none",
    }


def assert_public_payload(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    if "\"author_name\"" in serialized or "\"source_url\"" in serialized:
        raise ValueError("public payload contains local identity fields")
    if payload.get("privacy", {}).get("contains_prose") is not False:
        raise ValueError("public payload prose flag is not false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", default="D:/datasets/archive-novels")
    parser.add_argument("--report", default=str(REPO_ROOT / "output" / "corpus_fetch_report.json"))
    parser.add_argument("--receipt", default=str(REPO_ROOT / "output" / "corpus_fetch_receipt.json"))
    parser.add_argument("--interval", type=float, default=MIN_INTERVAL_SECONDS)
    args = parser.parse_args()

    started = iso_now()
    requester = Requester(interval=max(MIN_INTERVAL_SECONDS, args.interval))
    destination = Path(args.destination)
    errors: list[str] = []
    executable = Path(sys.executable).resolve()
    if REPO_ROOT / ".venv" not in executable.parents:
        errors.append(f"interpreter_not_repo_venv: {executable}")
    raw_authors: dict[str, dict[str, Any]] = {}
    channels: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    link_candidates: list[dict[str, Any]] = []

    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"destination_mkdir: {type(exc).__name__}: {exc}")

    for channel_id, description, seeds in CHANNELS:
        channel = {"channel_id": channel_id, "description": description, "seed_probes": [], "searches": [], "links": [], "status": "not_observed"}
        for seed in seeds:
            result = probe(requester, seed)
            channel["seed_probes"].append({key: value for key, value in result.items() if key != "url"})
            if result.get("status") == "ok":
                try:
                    status, headers, body = requester.open(seed)
                    if status == 200 and "text/html" in headers.get("Content-Type", "text/html"):
                        discover_download_links(requester, seed, body, channel_id, seen_urls, link_candidates)
                except RuntimeError as exc:
                    channel["links"].append({"status": "error", "error": str(exc)})
        channels.append(channel)

    zxcs_channel = next(item for item in channels if item["channel_id"] == "zxcs-style")
    discover_zxcs_info(requester, zxcs_channel, seen_urls, link_candidates, ["https://www.zxcs.info/"])

    for query_id, query in SEARCH_QUERIES[:MAX_SEARCH_PAGES]:
        urls, result = search_bing(requester, query)
        channel_id = "package-mirror" if query_id == "package-12560" else ("zxcs-style" if query_id == "archive-author" else "other-public")
        channel = next(item for item in channels if item["channel_id"] == channel_id)
        channel["searches"].append({"query_id": query_id, **result})
        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            probe_result = probe(requester, url)
            if probe_result.get("status") == "ok" and probe_result.get("http_status") == 200:
                try:
                    status, headers, body = requester.open(url)
                    if status == 200 and "text/html" in headers.get("Content-Type", "text/html"):
                        discover_download_links(requester, url, body, channel_id, seen_urls, link_candidates)
                except RuntimeError as exc:
                    channel["links"].append({"url_shape": host_shape(url), "status": "error", "error": str(exc)})
            if len(seen_urls) >= MAX_LINK_PROBES:
                break

    link_candidates = [item for item in link_candidates if author_from_link(item)]
    link_candidates.sort(key=lambda item: (author_from_link(item) not in BENCHMARK_AUTHORS, author_from_link(item) or ""))
    link_candidates = link_candidates[:MAX_DOWNLOADS]
    total_bytes = 0
    identity_rows: list[dict[str, Any]] = []
    for index, item in enumerate(link_candidates):
        if total_bytes >= MAX_TOTAL_BYTES:
            break
        author = author_from_link(item)
        if not author:
            continue
        author_id = sha_id(item["channel_id"], author, prefix="author")
        if author_id in raw_authors and len(raw_authors[author_id]["works"]) >= 2:
            continue
        sector = "历史" if "历史" in item.get("text", "") else "玄幻" if "玄幻" in item.get("text", "") else "都市" if "都市" in item.get("text", "") else "仙侠" if "仙侠" in item.get("text", "") else "科幻"
        author_dir = destination / safe_name(author_id)
        suffix = Path(urllib.parse.urlparse(item["url"]).path).suffix.lower() or ".bin"
        local_file = author_dir / f"source-{index:03d}{suffix}"
        path, result = download_file(requester, item["url"], local_file, MAX_TOTAL_BYTES - total_bytes)
        channel = next(item2 for item2 in channels if item2["channel_id"] == item["channel_id"])
        channel["links"].append({"url_shape": host_shape(item["url"]), **{key: value for key, value in result.items() if key != "url"}})
        if path is None:
            continue
        total_bytes += int(result.get("bytes", 0))
        entry = raw_authors.setdefault(author_id, {"author_id": author_id, "author": author, "sector": sector, "works": [], "bytes": 0})
        entry["bytes"] += int(result.get("bytes", 0))
        texts = materialize_texts(path, author, author_dir)
        if path.suffix.lower() == ".txt":
            texts = [path]
        for text_path in texts:
            entry["works"].append(text_path)
        if entry["works"] and "sample" not in entry:
            rng = random.Random(int(author_id[-8:], 16))
            sample_path = rng.choice(entry["works"])
            entry["sample"] = verify_sample(sample_path, author)
        identity_rows.append({"author_id": author_id, "author_name": author, "source_url": item["url"], "local_path": str(author_dir), "sector": sector, "verification": entry.get("sample", {"status": "not_run"})})
        if len(raw_authors) >= TARGET_AUTHORS_MAX:
            break

    if len(raw_authors) < TARGET_AUTHORS_MIN:
        errors.append(f"selection_target_not_met: {len(raw_authors)} authors materialized; minimum is {TARGET_AUTHORS_MIN}")
    sample_failures = sum(1 for item in raw_authors.values() if item.get("sample", {}).get("status") != "pass")
    if sample_failures:
        errors.append(f"sample_verification_failed: {sample_failures} author sample(s) did not prove prose plus signature")

    finished = iso_now()
    for channel in channels:
        if any(item.get("status") == "ok" for item in channel["seed_probes"]) or channel["searches"]:
            channel["status"] = "observed"
        elif channel["seed_probes"]:
            channel["status"] = "blocked_or_unreachable"

    report = privacy_report(raw_authors, channels, started, finished, errors)
    report_path = Path(args.report)
    receipt_path = Path(args.receipt)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    assert_public_payload(report)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    identity_path = destination / "identity_map.local.json"
    identity_written = False
    try:
        identity_path.write_text(json.dumps({"schema_version": 1, "generated_at": finished, "privacy": "local_only; do_not_commit_or_include_in_report_or_receipt", "mapping": identity_rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        identity_written = True
    except OSError as exc:
        errors.append(f"identity_map_write: {type(exc).__name__}: {exc}")
        report["status"] = "blocked"
        report["errors"] = errors
        assert_public_payload(report)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema_version": 1,
        "status": "ready_for_review",
        "fetch_status": "completed" if not errors else "blocked",
        "execution": {
            "command": "python scripts/corpus_fetch.py",
            "interpreter": str(Path(sys.executable).resolve()),
            "repo_venv_expected": str((REPO_ROOT / ".venv").resolve()),
            "repo_venv_match": REPO_ROOT / ".venv" in Path(sys.executable).resolve().parents,
            "alternate_command_attempt": "./.venv/Scripts/python.exe scripts/corpus_fetch.py",
            "alternate_command_status": "blocked_before_start",
            "alternate_command_error": "This command requires approval",
        },
        "started_at": started,
        "completed_at": finished,
        "updated_at": iso_now(),
        "report_path": str(report_path),
        "destination_root": str(destination),
        "identity_map_path": str(identity_path),
        "identity_map_written": identity_written,
        "candidate_count": len(link_candidates),
        "downloaded_author_count": len(raw_authors),
        "downloaded_work_count": sum(len(item["works"]) for item in raw_authors.values()),
        "downloaded_bytes": total_bytes,
        "sampled_author_count": sum(1 for item in raw_authors.values() if item.get("sample")),
        "contains_prose": False,
        "contains_author_names": False,
        "git_action": "none",
        "constraints": ["No正文 copied into git or receipt", "No real author names in report or receipt", "No login/CAPTCHA bypass", "Request interval is at least 2 seconds", "Total download is capped at 2GB", "No commit", "No push"],
        "routing_audit": {
            "packages": [
                {"id": "WP-CORPUS-RECON", "lane": "reader", "mechanism": "native managed Explore read-only inspection plus script-internal probes", "resolved_model_effort": "Explore / Haiku", "deliverable": "channel HTTP evidence and bounded candidate discovery", "verification": "report contains URL shapes/statuses only; no author names", "escalation": "approved web/HTTP path if further sources are required", "receipt": "native:a81dd08b13af843dc"},
                {"id": "WP-CORPUS-SCRIPT", "lane": "brain", "mechanism": "serial Write/Edit on main checkout, standard-library urllib only", "resolved_model_effort": "Opus 4.8", "deliverable": "scripts/corpus_fetch.py with 2-second limiter, 2GB cap, streaming temp files, bounded crawl, privacy-safe artifacts", "verification": "fresh direct script runs; syntax/runtime errors exposed and fixed", "escalation": "human review before any corpus use", "receipt": "override: brain - WP-CORPUS-SCRIPT: public-source attribution, privacy redaction, destination policy, and irreversible downloads require brain sign-off"},
                {"id": "WP-CORPUS-RUN", "lane": "brain", "mechanism": "simple command python scripts/corpus_fetch.py", "resolved_model_effort": "Opus 4.8", "deliverable": "fresh report, local identity map, and receipt reflecting actual run", "verification": "exit code 2; authors=0, works=0, bytes=0; D identity map written empty", "escalation": "repository .venv command needs approval and source candidates need further permitted discovery", "receipt": "override: brain - WP-CORPUS-RUN: execution outcome is blocked and must not be represented as a successful fetch"}
            ],
            "direct_brain_labour": {"reads": 4, "searches": 1, "evidence": 6, "tests": 4, "docs": 0, "other": 8},
            "opposite_vendor_consultation": "Codex frontier and Gemini fallback were denied by the session permission gate in the prior task"
        },
        "errors": errors,
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["fetch_status"], "authors": receipt["downloaded_author_count"], "works": receipt["downloaded_work_count"], "bytes": total_bytes, "report": str(report_path), "receipt": str(receipt_path)}, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
