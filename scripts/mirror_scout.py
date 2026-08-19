#!/usr/bin/env python3
"""Scout public mirrors for the deleted 12560-webnovel package."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from corpus_fetch import LinkParser, Requester, unwrap_bing_href

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
REPORT_PATH = OUTPUT_DIR / "mirror_scout_report.json"
RECEIPT_PATH = OUTPUT_DIR / "mirror_scout_receipt.json"
USER_AGENT = "novel-mirror-scout/1.0 (public link availability research)"
QUERIES = (
    "12560本网文 百度网盘",
    "novel_json_tokens512",
    "网文 指令数据 21.7M",
    "webnovel_cn 网盘",
    "小说语料 12560 提取码",
)
ALIVE_MARKERS = ("请输入提取码", "提取码", "访问码", "分享密码", "取件码", "密码：", "密码:")
DEAD_MARKERS = (
    "链接不存在",
    "你来晚了",
    "已被取消",
    "文件不存在",
    "分享已失效",
    "分享已取消",
)
BING_URL = "https://www.bing.com/search?"


def iso_now() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def search_bing_with_evidence(requester: Requester, query: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    search_url = BING_URL + urllib.parse.urlencode({"q": query, "count": 10})
    try:
        status, headers, body = requester.open(search_url, headers={"User-Agent": USER_AGENT})
    except RuntimeError as exc:
        return [], {"query": query, "url": search_url, "status": "error", "error": str(exc)}
    if status != 200:
        return [], {"query": query, "url": search_url, "status": "http_blocked", "http_status": status}
    parser = LinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.links:
        href = unwrap_bing_href(html.unescape(item["href"]))
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme not in {"http", "https"} or "bing.com" in parsed.netloc or href in seen:
            continue
        seen.add(href)
        results.append({"url": href, "result_text": item["text"][:240]})
    return results[:10], {
        "query": query,
        "url": search_url,
        "status": "ok",
        "http_status": status,
        "content_type": headers.get("Content-Type", ""),
        "result_count": len(results[:10]),
    }


def marker_evidence(text: str, markers: tuple[str, ...]) -> dict[str, str] | None:
    normalized = html.unescape(text)
    for marker in markers:
        match = re.search(re.escape(marker), normalized, flags=re.IGNORECASE)
        if match:
            start = max(0, match.start() - 80)
            end = min(len(normalized), match.end() + 120)
            return {"marker": match.group(0), "excerpt": re.sub(r"\s+", " ", normalized[start:end]).strip()}
    return None


def probe_candidate(requester: Requester, candidate: dict[str, Any]) -> dict[str, Any]:
    url = candidate["url"]
    result = {
        "url": url,
        "queries": candidate["queries"],
        "source_pages": candidate["source_pages"],
        "search_result_texts": candidate["search_result_texts"],
    }
    try:
        status, headers, body = requester.open(url, headers={"User-Agent": USER_AGENT})
    except RuntimeError as exc:
        result.update({"status": "error", "error": str(exc), "http_status": None})
        return result
    text = body.decode("utf-8", "replace")
    alive = marker_evidence(text, ALIVE_MARKERS)
    dead = marker_evidence(text, DEAD_MARKERS)
    result.update({
        "http_status": status,
        "content_type": headers.get("Content-Type", ""),
        "content_length": len(body),
    })
    if status == 200 and alive:
        result.update({"status": "alive", "evidence": alive})
    elif dead:
        result.update({"status": "dead", "evidence": dead})
    elif status != 200:
        result.update({"status": "blocked", "evidence": {"marker": None, "excerpt": ""}})
    else:
        result.update({"status": "unknown", "evidence": {"marker": None, "excerpt": ""}})
    return result


def main() -> int:
    started_at = iso_now()
    requester = Requester(interval=2.0)
    searches: list[dict[str, Any]] = []
    candidates_by_url: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        results, evidence = search_bing_with_evidence(requester, query)
        searches.append(evidence)
        source_page = evidence.get("url", "")
        for item in results:
            candidate = candidates_by_url.setdefault(item["url"], {
                "url": item["url"],
                "queries": [],
                "source_pages": [],
                "search_result_texts": [],
            })
            if query not in candidate["queries"]:
                candidate["queries"].append(query)
            if source_page and source_page not in candidate["source_pages"]:
                candidate["source_pages"].append(source_page)
            if item["result_text"] and item["result_text"] not in candidate["search_result_texts"]:
                candidate["search_result_texts"].append(item["result_text"])

    probes = [probe_candidate(requester, candidate) for candidate in candidates_by_url.values()]
    alive = [probe for probe in probes if probe.get("status") == "alive"]
    dead = [probe for probe in probes if probe.get("status") == "dead"]
    completed_at = iso_now()
    report = {
        "schema_version": 1,
        "status": "ready_for_review" if alive else "blocked",
        "started_at": started_at,
        "completed_at": completed_at,
        "package": {
            "name": "12560-webnovel-instruction-data",
            "known_deleted_url": "https://pan.baidu.com/s/1TorBMbrqxrn6odRF0PJBVw",
            "known_extract_code": "jlh3",
            "telegram_source": "https://t.me/+JbovpBG6-gBiNDI1",
        },
        "search": {
            "engine": "Bing",
            "queries": list(QUERIES),
            "searches": searches,
            "unique_candidate_count": len(candidates_by_url),
        },
        "probes": probes,
        "summary": {
            "alive_count": len(alive),
            "dead_count": len(dead),
            "unknown_count": sum(probe.get("status") == "unknown" for probe in probes),
            "blocked_count": sum(probe.get("status") == "blocked" for probe in probes),
            "error_count": sum(probe.get("status") == "error" for probe in probes),
            "alive_candidates": alive,
        },
        "method": {
            "network_client": "urllib.request only",
            "request_interval_seconds": 2.0,
            "alive_rule": "HTTP 200 and body contains an extract-code/password marker",
            "dead_rule": "body contains a deleted/cancelled/expired marker",
            "unmatched_200_rule": "unknown; never reported as alive",
        },
        "privacy": {
            "contains_prose": False,
            "contains_author_names": False,
            "body_evidence_limited_to_marker_excerpt": True,
        },
    }
    receipt = {
        "schema_version": 1,
        "status": "ready_for_review",
        "result_status": report["status"],
        "started_at": started_at,
        "completed_at": completed_at,
        "updated_at": completed_at,
        "report_path": "output/mirror_scout_report.json",
        "receipt_path": "output/mirror_scout_receipt.json",
        "command": "python scripts/mirror_scout.py",
        "network_client": "urllib.request only",
        "candidate_count": len(candidates_by_url),
        "alive_count": len(alive),
        "dead_count": len(dead),
        "search_query_count": len(QUERIES),
        "evidence": "Each probe records the actual HTTP status and exact marker text when matched; no unmatched 200 response is called alive.",
        "ready_for_review": True,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates": len(candidates_by_url), "alive": len(alive), "dead": len(dead)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
