"""F3a Review 挂 prose 复核测试（B 档）.

覆盖：
- recheck_against_prose 空正文 → []
- 对象层 issue 描述被正文兑现 → prose_confirmed=True + 证据片段
- 描述与正文不相关 → prose_confirmed=False、无 evidence
- 非 prose-recheckable 类型 → prose_confirmed=None（保持对象层原判）
- 混合列表按序输出全部条目
"""

from src.object_state import ReviewIssue
from src.workflow_action.review import recheck_against_prose


def _mk_issue(
    issue_id: str,
    issue_type: str,
    description: str,
    severity: str = "warning",
) -> ReviewIssue:
    return ReviewIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        severity=severity,
        location="pu_scene_014, 第三段",
        scope_of_impact="本 PlotUnit",
        violated_rule="伏笔兑现",
        description=description,
    )


def test_recheck_empty_prose_returns_empty():
    issues = [_mk_issue("i1", "abrupt_payoff", "旧信物未被回收")]
    assert recheck_against_prose(issues, "") == []
    assert recheck_against_prose(issues, "   \n ") == []


def test_recheck_confirm_issue_related_to_prose():
    """伏笔类 issue：正文讨论同一内容 → prose_confirmed=True + 证据."""
    prose = "他取出那只旧信物，在灯下看了许久，想起三年前的那次递刀。"
    issues = [_mk_issue("i1", "abrupt_payoff", "旧信物没有后续回收交代")]
    result = recheck_against_prose(issues, prose)
    assert len(result) == 1
    assert result[0]["prose_confirmed"] is True
    assert "信物" in result[0].get("evidence", "")


def test_recheck_unrelated_issue_not_confirmed():
    prose = "雨点顺着屋檐落成一条线，院子里一片寂静。"
    issues = [_mk_issue("i1", "abrupt_payoff", "传国玉玺下落成谜")]
    result = recheck_against_prose(issues, prose)
    assert result[0]["prose_confirmed"] is False
    assert "evidence" not in result[0]


def test_recheck_non_recheckable_type_stays_none():
    prose = "主角在客栈核对账本，发现数目对不上。"
    issues = [_mk_issue("i1", "fact_conflict", "账目金额矛盾")]
    result = recheck_against_prose(issues, prose)
    assert result[0]["prose_confirmed"] is None


def test_recheck_mixed_list_keeps_order_and_metadata():
    prose = "他想起那封信的来处，心里发沉。"
    issues = [
        _mk_issue("a", "abrupt_payoff", "那封信的来处未在正文交代"),
        _mk_issue("b", "timeline_error", "日期提前了一天"),
        _mk_issue("c", "promise_loss", "三日后再见的约定没了下文"),
    ]
    result = recheck_against_prose(issues, prose)
    assert [r["issue_id"] for r in result] == ["a", "b", "c"]
    # metadata 透传
    assert result[0]["issue_type"] == "abrupt_payoff"
    assert result[0]["severity"] == "warning"
    # 类型分类
    by_type = {r["issue_type"]: r["prose_confirmed"] for r in result}
    assert by_type["abrupt_payoff"] is True
    assert by_type["timeline_error"] is None
    assert by_type["promise_loss"] is False


def test_recheck_character_distortion_type():
    prose = "他垂着眼把文件推到桌对面，一句话也没有辩解。"
    issues = [_mk_issue("i1", "character_distortion", "主角垂着眼没有辩解，一反常态")]
    result = recheck_against_prose(issues, prose)
    assert result[0]["prose_confirmed"] is True
    assert "垂着眼" in result[0]["evidence"]
