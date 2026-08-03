"""time_audit — 时间审计引擎（FACTTRACK v2）.

`run_time_audit(objects, time_book=None) -> list[ReviewIssue]`：
  被 audit / rebuild / extend / `novel time --check` 四处调用，一处实现。

检测分级（零成本契约）：
  - time_book=None → 仅现有 3 项（死亡后活跃/过期持有/否定重叠），
    委托 ReconcileUnit.check_temporal_contradictions，行为与现状逐字节一致。
  - time_book 非空 → 追加：
      检测4 状态时间回退（anchors 单调性）
      检测5 先知逾期（timelines[].ends / 伏笔 expires_at）
      检测6 季节/历法违反（rules 驱动，warning 可关）
全部新增检测为 warning（非 blocking），review 可 pass。
"""

import re
from typing import Optional

from src.workflow_action.timebook import _cn_month_to_int, parse_date


# --- 季节推导（检测6 用） ----------------------------------------------------

# 农历月/节日 → 季节（北半球默认）
_LUNAR_SEASON: dict[str, str] = {
    "除夕": "冬", "春节": "冬", "冬至": "冬", "小寒": "冬", "大寒": "冬",
    "腊月": "冬", "冬月": "冬", "十一月": "冬", "十二月": "冬",
    "正月": "春", "元宵": "春", "立春": "春", "二月": "春", "三月": "春",
    "端午": "夏", "夏至": "夏", "七夕": "夏", "四月": "夏", "五月": "夏", "六月": "夏",
    "中秋": "秋", "重阳": "秋", "秋分": "秋", "七月": "秋", "八月": "秋", "九月": "秋",
    "十月": "冬",
}
_OPPOSITE_SEASONS = {("春", "秋"), ("秋", "春"), ("夏", "冬"), ("冬", "夏")}


def _solar_season(month: int) -> str:
    """北半球默认季节: 3-5 春, 6-8 夏, 9-11 秋, 12-2 冬."""
    if month in (3, 4, 5):
        return "春"
    if month in (6, 7, 8):
        return "夏"
    if month in (9, 10, 11):
        return "秋"
    return "冬"


def _lunar_season(lunar: Optional[str]) -> Optional[str]:
    """从农历字段推导季节; 无法推导返回 None."""
    if not lunar:
        return None
    for kw, season in _LUNAR_SEASON.items():
        if kw in lunar:
            return season
    return None


def _rule_covers_loc_month(tb, loc: str, month: int) -> bool:
    """软规则是否已声明该地点该月的季节（南半球覆盖）."""
    if not loc:
        return False
    for rule in tb.rules:
        if loc not in rule:
            continue
        m = re.search(
            r"(\d+|[一二三四五六七八九十]+)\s*月\s*(?:为|是)\s*(盛夏|酷暑|寒冬|严冬|暖冬|夏天|冬天)",
            rule,
        )
        if not m:
            continue
        decl = int(m.group(1)) if m.group(1).isdigit() else _cn_month_to_int(m.group(1))
        if decl == month:
            return True
    return False


def _detect_anchor_regression(tb):
    """检测4 状态时间回退: 后章锚点日期早于前章."""
    from src.object_state import ReviewIssue

    issues: list = []
    if not tb.anchors:
        return issues
    dated: list = []
    for a in tb.anchors:
        parsed = parse_date(a.date)
        m = re.search(r"(\d+)", a.chapter or "")
        if parsed is not None and m:
            dated.append((int(m.group(1)), parsed, a))
    dated.sort(key=lambda t: t[0])
    for (n1, d1, a1), (n2, d2, a2) in zip(dated, dated[1:]):
        if d2 < d1:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_time_regress_{a1.chapter}_{a2.chapter}",
                    issue_type="timeline_error",
                    severity="warning",
                    location=f"TimeBook anchors {a1.chapter} -> {a2.chapter}",
                    scope_of_impact="时间线一致性",
                    violated_rule="anchors 日期单调递增",
                    description=(
                        f"章节时间回退: {a1.chapter}({a1.date}) -> "
                        f"{a2.chapter}({a2.date})，后章日期早于前章"
                    ),
                )
            )
    return issues


def _detect_foreshadow_expiry(objects, tb):
    """检测5 先知逾期: 仍 active 的伏笔/时间线过了时效终点."""
    from src.object_state import ForeshadowGraph, ReviewIssue

    issues: list = []
    latest = tb.latest_anchor()
    if latest is None or not latest.date:
        return issues
    current = parse_date(latest.date)
    if current is None:
        return issues
    for graph in [o for o in objects if isinstance(o, ForeshadowGraph)]:
        for e in graph.entries:
            if e.current_status != "active" or not e.expires_at:
                continue
            expiry = parse_date(e.expires_at)
            if expiry is not None and current >= expiry:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_time_foreshadow_expired_{e.thread_id}",
                        issue_type="timeline_error",
                        severity="warning",
                        location=f"ForeshadowGraph {e.thread_id}",
                        scope_of_impact="承诺追踪",
                        violated_rule="active 伏笔不得越过时效终点",
                        description=(
                            f"伏笔 '{e.content}' 仍 active，但叙事时间 {latest.date} "
                            f"已到/超过时效终点 {e.expires_at}，先知前提失效"
                        ),
                    )
                )
    for tl in tb.timelines:
        if not tl.ends:
            continue
        ends = parse_date(tl.ends)
        if ends is not None and current >= ends:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_time_timeline_ended_{tl.id}",
                    issue_type="timeline_error",
                    severity="warning",
                    location=f"TimeBook timelines.{tl.id}",
                    scope_of_impact="时间线一致性",
                    violated_rule="叙事时间不得越过时间线时效边界",
                    description=(
                        f"时间线 '{tl.name or tl.id}' 时效终点 {tl.ends}，"
                        f"当前叙事时间 {latest.date} 已越过；先知/闪回前提失效"
                    ),
                )
            )
    return issues


def _detect_season_violation(tb):
    """检测6 季节/历法违反: 锚点自身阳历月与农历月季节相反（rules 覆盖除外）."""
    from src.object_state import ReviewIssue

    issues: list = []
    for a in tb.anchors:
        parsed = parse_date(a.date)
        if parsed is None:
            continue
        month = parsed[1]
        lunar_season = _lunar_season(a.lunar)
        if lunar_season is None:
            continue
        if _rule_covers_loc_month(tb, a.loc or "", month):
            continue
        solar_season = _solar_season(month)
        if (solar_season, lunar_season) in _OPPOSITE_SEASONS:
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_time_season_{a.chapter or 'anchor'}",
                    issue_type="timeline_error",
                    severity="warning",
                    location=f"TimeBook anchors {a.chapter or '?'}",
                    scope_of_impact="季节/历法一致性",
                    violated_rule="阳历月与农历月季节不得相反",
                    description=(
                        f"锚点 {a.chapter or '?'} date={a.date}(阳历"
                        f"{solar_season}) 与 lunar='{a.lunar}'(农历"
                        f"{lunar_season}) 季节相反，存在历法矛盾"
                    ),
                )
            )
    return issues


def run_time_audit(objects, time_book=None) -> list:
    """时间审计引擎（FACTTRACK v2）.

    Args:
        objects: 对象层（含 FactLedger / ForeshadowGraph，用于现有 3 项与先知检测）。
        time_book: TimeBook 先验；None → 仅现有 3 项检测（行为与现状一致）。

    Returns:
        ReviewIssue 列表。全部新增检测为 warning（非 blocking）。
    """
    from src.workflow_action.reconcile import ReconcileUnit

    issues: list = []
    # 现有 3 项（无条件跑，schema 无关）
    issues.extend(ReconcileUnit().check_temporal_contradictions(objects))
    if time_book is None:
        return issues
    issues.extend(_detect_anchor_regression(time_book))
    issues.extend(_detect_foreshadow_expiry(objects, time_book))
    issues.extend(_detect_season_violation(time_book))
    return issues


def build_timeline_report(
    objects,
    time_book,
    *,
    source_text_ref: str,
    extracted_anchors: Optional[list] = None,
) -> dict:
    """构建 timeline_report.json（一等产物，audit / `novel time --check` 共用）.

    - 无 TimeBook → 检测退化为现有 3 项（零成本契约）；extracted_anchors 仅作草稿展示。
    - 检测全部 warning（非 blocking），route 恒为 pass。
    """
    issues = run_time_audit(objects, time_book)
    latest = time_book.latest_anchor() if time_book is not None else None
    return {
        "schema_version": 1,
        "source_text_ref": source_text_ref,
        "time_book": time_book.model_dump() if time_book is not None else None,
        "extracted_anchors": (
            [a.model_dump() for a in extracted_anchors] if extracted_anchors else []
        ),
        "latest_anchor": latest.model_dump() if latest is not None else None,
        "detections_enabled": {
            "baseline_3": True,
            "anchor_regression": bool(time_book is not None and time_book.anchors),
            "foreshadow_expiry": bool(time_book is not None),
            "season_violation": bool(
                time_book is not None and time_book.rules
            ),
        },
        "issues": [i.model_dump(mode="json") for i in issues],
        "issue_count": len(issues),
        "blocking_count": sum(1 for i in issues if i.is_blocking()),
        "route": "block" if any(i.is_blocking() for i in issues) else "pass",
    }
