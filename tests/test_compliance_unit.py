"""Tests for ComplianceUnit — 合规扫描逻辑（prose 模式 + object 模式）."""

from src.workflow_action.compliance import ComplianceUnit, ComplianceHit

DIRTY_TEXT = """第一章 赌局

他走进地下赌场，一晚上赌博输光了全部家当。
庄家笑眯眯地看着他，让他再下注翻本。

第二章 变故

她脱下外套，露出里面的裸体。
房间里弥漫着令人不安的情欲气息。
"""

CLEAN_TEXT = """第一章 修炼

顾临蹲在藏经阁的地板缝边上，把一本缺了封皮的册子插回架。
他这双手在藏书阁待了六年。

第二章 代价

顾临翻开那本书，第一页只有一行字。
他蹲在灯下，把那行字读了三遍。
"""


def _scan(text, **kwargs):
    return ComplianceUnit().scan_prose(
        text,
        platform=kwargs.get("platform", "通用"),
        sensitive_on=kwargs.get("sensitive_on", True),
        custom_entries=kwargs.get("custom_entries"),
        source_text_ref=kwargs.get("source_text_ref", "input.txt"),
    )


def test_prose_scan_finds_hits_with_anchors():
    report = _scan(DIRTY_TEXT)
    assert report.hits
    # 命中带行号锚点 + 上下文片段
    for hit in report.hits:
        assert isinstance(hit, ComplianceHit)
        assert hit.line_number >= 1
        assert hit.snippet
        assert hit.category
    # 具体命中：赌博/赌场/庄家/下注/裸体/情欲
    words = {hit.word for hit in report.hits}
    assert {"赌博", "赌场", "裸体"} <= words


def test_prose_scan_severity_levels():
    report = _scan(DIRTY_TEXT)
    severities = {hit.severity for hit in report.hits}
    assert "high" in severities  # 裸体=high
    assert "medium" in severities  # 赌博/赌场/庄家/下注/情欲=medium


def test_sensitive_off_skips_lexicon():
    report = _scan(DIRTY_TEXT, sensitive_on=False)
    assert not report.hits  # 词库跳过
    assert report.sensitive_scan is False
    # 平台政策检查仍跑
    assert report.issues


def test_clean_text_no_hits():
    report = _scan(CLEAN_TEXT)
    assert not report.hits
    assert report.risk_level() == "clean"


def test_risk_level_mapping():
    report = _scan(DIRTY_TEXT)
    # 含 block 级 → critical；含 high → high
    assert report.risk_level() == "high"

    block_text = "他把毒品藏进箱子里。"
    report_block = _scan(block_text)
    assert report_block.risk_level() == "critical"

    clean = _scan(CLEAN_TEXT)
    assert clean.risk_level() == "clean"


def test_platform_policy_injected():
    report = _scan(DIRTY_TEXT, platform="番茄")
    assert report.platform == "番茄"
    assert report.platform_policy["description"]
    assert report.issues  # AI 直出禁令 issue


def test_unknown_platform_falls_back():
    report = _scan(DIRTY_TEXT, platform="不存在的平台")
    assert report.platform == "不存在的平台"  # 保留原始名
    assert report.platform_policy["description"]  # 但政策回退通用


def test_custom_lexicon_merged():
    custom = [{"word": "自定义测试词", "category": "涉政", "severity": "block", "note": "测试"}]
    report = _scan("正文里有一个自定义测试词。", custom_entries=custom)
    assert any(hit.word == "自定义测试词" for hit in report.hits)
    assert report.risk_level() == "critical"


def test_same_word_same_line_once():
    text = "他赌博，赌博，赌博。"
    report = _scan(text)
    # 同一行同一词只报一次
    gambling_hits = [h for h in report.hits if h.word == "赌博"]
    assert len(gambling_hits) == 1


def test_object_mode_platform_checks():
    # object 模式：对 PlotUnit 字段做平台政策检查（无正文场景降级）
    unit = ComplianceUnit()
    issues = unit.scan_objects(genre="都市", conflict="一个赌场老板的恩怨", platform="通用")
    assert issues  # conflict 命中红线关键词"赌"
    # 干净字段无 issue
    clean_issues = unit.scan_objects(genre="仙侠", conflict="突破瓶颈", platform="通用")
    assert not clean_issues


def test_report_to_dict_has_route_pass():
    report = _scan(CLEAN_TEXT)
    data = report.to_dict()
    assert data["route"] == "pass"  # 供 CLI list 解析
    assert "risk_level" in data
    assert "hits" in data
    assert "platform_policy" in data
