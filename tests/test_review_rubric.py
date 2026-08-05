"""Tests for WebNovelBench 8 维本地 rubric — review_rubric.py.

验证：8 维结构、键完整性、映射引用合法性（ReviewIssueType / review.py 前缀）、
证据来源覆盖 7 张 web_fiction 表、JSON round-trip、offline 约束、诚实标注。
"""

import json
from pathlib import Path

from src.domain_layer.review_rubric import (
    REVIEW_RUBRIC,
    RUBRIC_SCHEMA_VERSION,
    export_rubric,
    render_rubric_json,
)
from src.object_state.reviewissue import ReviewIssueType

# review.py 实际发出的全部 issue_id 前缀（_hard_rules + _domain_rules 直读核对）
KNOWN_REVIEW_PREFIXES = {
    "iss_hard_overlap",
    "iss_hard_rel",
    "iss_hard_active_character",
    "iss_hard_plotunit_participant",
    "iss_hard_input_state_ref",
    "iss_hard_state_ref",
    "iss_hard_ineffective",
    "iss_hard_foreshadow",
    "iss_hard_time",
    "iss_hard_empty_fl",
    "iss_hard_empty_fg",
    "iss_hook",
    "iss_emotion",
    "iss_platform_hook",
    "iss_platform_patience",
    "iss_hook_eff",
    "iss_emotion_match",
    "iss_genind",
    "iss_genind2",
    "iss_genind3",
    "iss_layering",
    "iss_agency",
    "iss_info_channel",
    "iss_info_relay",
    "iss_info_scope",
}

# web_fiction.py 的 7 张领域表（evidence_sources 必须覆盖）
WEB_FICTION_TABLES = {
    "GENRE_FORMULAS",
    "HOOK_TAXONOMY",
    "EMOTIONAL_ARC_TEMPLATES",
    "NODE_EMOTION_MAP",
    "CRITICAL_HOOK_NODES",
    "GENRE_RULES",
    "PLATFORM_SNAPSHOTS",
}

VALID_STRENGTHS = {"strong", "moderate", "weak", "none"}


def test_eight_dimensions_exist():
    assert len(REVIEW_RUBRIC) == 8


def test_dimension_ids_unique_and_contiguous():
    ids = [dim["id"] for dim in REVIEW_RUBRIC]
    assert len(ids) == len(set(ids)), "id 必须唯一"
    assert ids == [f"wnb_{i:02d}" for i in range(1, 9)], "id 必须 wnb_01..wnb_08 连续"


def test_dimension_keys_complete():
    expected = {
        "id",
        "name_cn",
        "name_en",
        "description",
        "evaluation_focus",
        "mapped_issue_types",
        "mapped_rule_ids",
        "evidence_sources",
        "local_signal_strength",
        "notes",
    }
    for dim in REVIEW_RUBRIC:
        assert set(dim.keys()) == expected, dim["id"]


def test_signal_strength_valid():
    for dim in REVIEW_RUBRIC:
        assert dim["local_signal_strength"] in VALID_STRENGTHS, dim["id"]


def test_mapped_issue_types_in_literal():
    allowed = set(ReviewIssueType.__args__)
    for dim in REVIEW_RUBRIC:
        for issue_type in dim["mapped_issue_types"]:
            assert issue_type in allowed, f"{dim['id']} 映射了非法 issue_type: {issue_type}"


def test_mapped_rule_ids_in_review_prefixes():
    for dim in REVIEW_RUBRIC:
        for prefix in dim["mapped_rule_ids"]:
            assert any(
                prefix == known or prefix.startswith(known + "_")
                for known in KNOWN_REVIEW_PREFIXES
            ), f"{dim['id']} 映射了未知前缀: {prefix}"


def test_evidence_sources_cover_web_fiction_tables():
    joined = "\n".join(
        source
        for dim in REVIEW_RUBRIC
        for source in dim["evidence_sources"]
    )
    for table in WEB_FICTION_TABLES:
        assert table in joined, f"evidence_sources 未覆盖 web_fiction.py:{table}"


def test_json_round_trip():
    payload = json.loads(render_rubric_json())
    assert payload == export_rubric()
    assert len(payload["dimensions"]) == 8
    # schema 头字段齐全
    assert payload["schema_version"] == RUBRIC_SCHEMA_VERSION
    assert payload["benchmark"] == "WebNovelBench"
    assert payload["benchmark_reference"] == "arXiv:2505.14818"
    assert payload["source"] == "local-domain-rules"


def test_offline_no_network_keys():
    payload = export_rubric()
    assert payload["offline"] is True
    assert "provider" not in payload
    assert "api" not in payload
    assert "endpoint" not in payload
    # 渲染文本也不得含任何 http 引用
    rendered = render_rubric_json()
    assert "http" not in rendered.lower()


def test_wnb_02_sensory_detail_none_label():
    dim = next(d for d in REVIEW_RUBRIC if d["id"] == "wnb_02")
    assert dim["local_signal_strength"] == "none"
    assert "LLM-judge" in dim["notes"] or "无本地规则" in dim["notes"]
    assert dim["mapped_issue_types"] == []
    assert dim["mapped_rule_ids"] == []


def test_wnb_05_character_consistency_strong():
    dim = next(d for d in REVIEW_RUBRIC if d["id"] == "wnb_05")
    assert dim["local_signal_strength"] == "strong"
    assert "character_distortion" in dim["mapped_issue_types"]
    assert any("iss_hard_overlap" in p for p in dim["mapped_rule_ids"])


def test_wnb_08_covers_state_ref_and_foreshadow():
    dim = next(d for d in REVIEW_RUBRIC if d["id"] == "wnb_08")
    rule_ids = dim["mapped_rule_ids"]
    assert any("state_ref" in r for r in rule_ids)
    assert any("foreshadow" in r for r in rule_ids)
    assert "fact_conflict" in dim["mapped_issue_types"]
    assert "promise_loss" in dim["mapped_issue_types"]


def test_module_source_no_network_import():
    # 纯 stdlib 离线：模块源不得 import 任何网络库
    source = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "domain_layer"
        / "review_rubric.py"
    ).read_text(encoding="utf-8")
    for token in ("urllib", "requests", "socket", "import http", "aiohttp", "httpx"):
        assert token not in source, f"rubric 模块不得引用 {token}"
