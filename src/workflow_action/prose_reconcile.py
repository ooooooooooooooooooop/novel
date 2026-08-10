"""ProseReconcile — 把 ProseEvidence 断言与上一可信状态双路核对.

Q1 核心原则的落地闸门：PlotUnit 是写作意图，正文才是最终事实；状态只能根据
通过审查的实际正文更新。本模块做两件事：

1. 硬一致性核对（blocking）：
   - 时间回退/季节跳跃（无显式相对时长标记、无闪回标记 → 回退）
   - 周期算术（循环/契约时间错乱，如 60 年甲子轮回在 11 年处被宣称到期）
   - 实体状态回退（trusted=found/home → 正文 missing/dead）
   - 道具身份变化（trusted=票根 → 正文从同位置拿出花瓣）
   - 元文本泄漏（上一章/本章/第N章进正文）
2. 窗口核对（跨章，需 prev_chapters）：
   - 相邻章开头复述（f06）
   - 重复顿悟句 ≥3 章（f07）
   - 纯氛围无状态变化（f08）

Issue 类型全部复用现有 ReviewIssueType，不扩枚举：
  timeline_error / fact_conflict / generative_indicia / redundancy / weak_progression。
合法时间跳跃（闪回、显式"三年后"）带标记即放行——这是本闸门的诚实边界。
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from src.object_state.reviewissue import ReviewIssue
from src.object_state.prose_evidence import ProseEvidenceItem, ProseEvidencePackage
from src.workflow_action.prose_evidence import (
    _CN_MONTHS,
    _MONTH_RE,
    _REL_DAY_RE,
    _REL_YEARS_RE,
    _STATUS_VERBS,
    _PULL_RE,
    _sentence_containing,
    ambient_only,
    conclusion_sentences,
    opening_signature,
)

# 周期/契约到期语言（用于「提前届满」检测）
_EXPIRY_RE = re.compile(r"(届满|到期|期满|将尽|临近结束|快要结束|尾声|开启在即|临近开启|就要开启|将至)")
# 年份推进标记：向后月份若带次年/跨年标记则合法
_YEAR_ADVANCE_RE = re.compile(r"(次年|来年|翌年|第二年|转过|过了年|跨年|新年|下一年)")
# 顿悟核心：取「明白」之后的核心断言（忽然/终于 等标记归一）
_CONC_CORE_RE = re.compile(r"明白(.+)")

# --------------------------------------------------------------------------
# 可信状态快照
# --------------------------------------------------------------------------

_SEASON_ORDER = {"春": 1, "夏": 2, "秋": 3, "冬": 4}


def _season_of_month(month: int) -> str:
    if month <= 3:
        return "春"
    if month <= 6:
        return "夏"
    if month <= 9:
        return "秋"
    return "冬"


def _cn_number_to_int(s: str) -> Optional[int]:
    """中文数字转 int（仅支持年数用到的常见形式）. """
    if not s:
        return None
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if s == "多":
        return None
    if s in digits:
        return digits[s]
    if s in ("十", "廿", "卅"):
        return {"十": 10, "廿": 20, "卅": 30}[s]
    if s.startswith("十") and len(s) == 2:
        return 10 + digits.get(s[1], 0)
    if len(s) == 2 and s[0] in digits and s[1] == "十":
        return digits[s[0]] * 10
    if len(s) == 3 and s[0] in digits and s[1] == "十" and s[2] in digits:
        return digits[s[0]] * 10 + digits[s[2]]
    return None


@dataclass
class PropSnapshot:
    """道具身份快照：identity=当前身份标签, location=所在位置标签（可空）. """
    prop_id: str
    identity: str
    location: Optional[str] = None


@dataclass
class CycleAnchor:
    """周期锚点：cycle_length_years=循环/契约周期, current_elapsed_years=当前已过. """
    cycle_label: str
    cycle_length_years: int
    current_elapsed_years: int


@dataclass
class TrustedSnapshot:
    """上一可信状态的扁平快照（来自 FactLedger/CharacterModel 的适配视图）.

    由 fixtures 直接构造，或经 build_trusted_snapshot() 从真实对象推导。
    """
    entities: dict[str, list[str]] = field(default_factory=dict)  # entity_id -> 标签
    entity_status: dict[str, str] = field(default_factory=dict)   # entity_id -> found/missing/dead/home/left/...
    props: dict[str, PropSnapshot] = field(default_factory=dict)  # prop_id -> 快照
    current_month: Optional[int] = None                            # 上一可信月份
    current_season: Optional[str] = None                           # 上一可信季节
    cycle: Optional[CycleAnchor] = None                            # 周期锚（时间算术用）
    fact_statements: list[str] = field(default_factory=list)       # 上下文参考


def _month_from_anchor_date(anchor) -> Optional[int]:
    """从 TimeAnchor.date(ISO YYYY-MM-DD) 取月份；无日期/无法解析则 None. """
    if anchor is None:
        return None
    date = getattr(anchor, "date", None)
    if not date:
        return None
    parts = date.split("-")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    month = int(parts[1])
    return month if 1 <= month <= 12 else None


def build_trusted_snapshot(
    fact_ledger=None, character_model=None, labels=None, time_book=None
) -> TrustedSnapshot:
    """从真实 FactLedger/CharacterModel 对象推导快照（尽力而为）.

    只做无歧义提取：
    - 实体注册表来自 labels（entity_id -> 标签）；反向标签表用于道具/位置识别。
    - FactLedger 陈述含状态动词（找到/失踪/死亡…）→ 该句 involved_entities 得状态。
    - FactLedger 陈述形如「票根 夹在 诗集里」→ 首标签实体得 prop 身份 + 位置。
    - TimeBook 最新锚点日期（ISO）→ current_month / current_season。
    CharacterModel 的当前状态字段若含可映射状态也并入（找不到则空）。
    推导不到的内容保持空——空即不核对，与本模块「无法断言就不断言」一致。
    """
    snap = TrustedSnapshot()
    if time_book is not None:
        anchor = getattr(time_book, "latest_anchor", lambda: None)()
        month = _month_from_anchor_date(anchor)
        if month is not None:
            snap.current_month = month
            snap.current_season = _season_of_month(month)
    rev: dict[str, str] = {}
    for eid, labs in (labels or {}).items():
        snap.entities[eid] = list(labs)
        for lab in labs:
            rev[lab] = eid
    if fact_ledger is not None:
        for e in getattr(fact_ledger, "entries", []):
            stmt = getattr(e, "statement", "")
            if not stmt:
                continue
            snap.fact_statements.append(stmt)
            ents = list(getattr(e, "involved_entities", []) or [])
            for verb, status in _STATUS_VERBS.items():
                if verb in stmt:
                    for eid in ents:
                        snap.entity_status[eid] = status
            # 道具位置标签：如 "票根 夹在 诗集里" -> prop=票根(eid), location=诗集
            tokens = re.split(r"[ ，。、]+", stmt)
            for i, tok in enumerate(tokens):
                if tok in rev and i + 1 < len(tokens) and tokens[i + 1] in ("夹在", "位于", "放在"):
                    raw_loc = tokens[i + 2] if i + 2 < len(tokens) else None
                    loc = raw_loc
                    if raw_loc:
                        for label in rev:
                            if raw_loc.startswith(label):
                                loc = label
                                break
                    snap.props[rev[tok]] = PropSnapshot(prop_id=rev[tok], identity=tok, location=loc)
    return snap


# --------------------------------------------------------------------------
# 单条核对
# --------------------------------------------------------------------------

def _check_time_regression(
    draft_text: str,
    items: list[ProseEvidenceItem],
    trusted: TrustedSnapshot,
) -> list[ReviewIssue]:
    """时间回退/季节跳跃：回退 或 季节跳 ≥3 且无年份推进标记 → blocking.

    合法例外：闪回标记（flashback_marked）放行；向后月份带「次年/来年/跨年」等
    年份推进标记放行（新年一月正常回落）。一月→九月（跳 2 段）合法向前不阻断。
    """
    issues: list[ReviewIssue] = []
    if trusted.current_month is None:
        return issues
    for it in items:
        if it.kind != "time":
            continue
        if it.flashback_marked:
            continue
        m = _MONTH_RE.search(it.evidence)
        if not m or m.group(1) not in _CN_MONTHS:
            continue
        month = _CN_MONTHS[m.group(1)]
        sent = _sentence_containing(draft_text, draft_text.find(it.evidence))
        year_advance = bool(_YEAR_ADVANCE_RE.search(sent))
        duration_marker = bool(_REL_YEARS_RE.search(sent)) or bool(_REL_DAY_RE.search(sent))
        backward = month < trusted.current_month and not year_advance
        leap = abs(_SEASON_ORDER[_season_of_month(month)] - _SEASON_ORDER[_season_of_month(trusted.current_month)])
        leap_cross = leap >= 3 and not year_advance and not duration_marker
        if not (backward or leap_cross):
            continue
        reason = "回退" if backward else "跨整年跳跃"
        issues.append(
            ReviewIssue(
                issue_id=f"iss_q1_time_{it.item_id}",
                issue_type="timeline_error",
                severity="blocking",
                location=f"正文 {it.location}『{it.evidence}』",
                scope_of_impact="跨章时间一致性",
                violated_rule="连续叙事时间必须单调推进或带显式时长/年份标记",
                description=(
                    f"上一可信状态为 {trusted.current_month} 月；正文断言 "
                    f"{it.claim}——{reason}且无显式时长/年份/闪回标记"
                ),
                suggested_fix="补相对时长标记（如『三个月后』『次年』）或明确为闪回并加回忆标记",
            )
        )
    return issues


def _check_cycle_arithmetic(
    draft_text: str,
    items: list[ProseEvidenceItem],
    trusted: TrustedSnapshot,
) -> list[ReviewIssue]:
    """周期算术：循环内契约时间错乱.

    双臂检测：
      A. 提前届满 —— 正文出现周期锚定时长 n（n < 周期 L），却带「届满/到期/开启在即」
         等契约到期语言 → blocking。
      B. 整周期已过 —— 正文声称 n ≥ L，而可信状态仍处周期内（elapsed < L）→ blocking。
    """
    issues: list[ReviewIssue] = []
    cyc = trusted.cycle
    if cyc is None:
        return issues
    for it in items:
        if it.kind != "time":
            continue
        m = _REL_YEARS_RE.search(it.evidence)
        if not m:
            continue
        n = _cn_number_to_int(m.group(1))
        if n is None:
            continue
        # 提前届满：时长项所在句子未必带届满语言（可能在下一句），扫整个草稿更稳
        premature = (
            n < cyc.cycle_length_years
            and _EXPIRY_RE.search(draft_text)
            and cyc.current_elapsed_years < cyc.cycle_length_years
        )
        overrun = n >= cyc.cycle_length_years and cyc.current_elapsed_years < cyc.cycle_length_years
        if not (premature or overrun):
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_q1_cycle_{it.item_id}",
                issue_type="timeline_error",
                severity="blocking",
                location=f"正文 {it.location}『{it.evidence}』",
                scope_of_impact="时间算术/周期一致",
                violated_rule="周期内契约不得在周期外时间点宣称到期",
                description=(
                    f"可信状态: {cyc.cycle_label} 周期共 {cyc.cycle_length_years} 年，"
                    f"当前已过 {cyc.current_elapsed_years} 年；正文断言 {it.claim} "
                    f"（{n} 年）"
                    + ("并带『届满』语言——周期未满即宣称到期"
                       if premature else "——整周期已过，契约不应此时才开启/结束")
                ),
                suggested_fix="把时长改为周期内合理数值，或去掉与周期冲突的到期语言",
            )
        )
    return issues


def _check_entity_status_regression(
    items: list[ProseEvidenceItem],
    trusted: TrustedSnapshot,
) -> list[ReviewIssue]:
    """实体状态回退：trusted=found/home → 正文 missing/dead → blocking. """
    issues: list[ReviewIssue] = []
    for it in items:
        if it.kind != "entity_status":
            continue
        # 从 claim 中识别实体 id 与状态
        m = None
        for eid in trusted.entity_status:
            if f"{eid}(" in it.claim or f"实体 {eid}" in it.claim:
                m = eid
                break
        if m is None:
            # 无注册实体 id 也可用标签兜底
            for eid, labels in trusted.entities.items():
                if any(label in it.claim for label in labels):
                    m = eid
                    break
        if m is None:
            continue
        prev = trusted.entity_status.get(m)
        if prev in ("found", "home", "rescued", "trapped") and any(
            w in it.claim for w in ("missing", "dead")
        ):
            issues.append(
                ReviewIssue(
                    issue_id=f"iss_q1_status_{it.item_id}",
                    issue_type="fact_conflict",
                    severity="blocking",
                    location=f"正文 {it.location}『{it.evidence}』",
                    scope_of_impact="实体状态一致性",
                    violated_rule="状态只能根据正文演进，不可未加事件地回退",
                    description=(
                        f"上一可信状态 {m} 为 {prev}，正文断言 {it.claim} "
                        f"（{it.evidence}），状态回退无过渡事件"
                    ),
                    suggested_fix="若人物确实消失/死亡，需补足导致该状态的事件与因果",
                )
            )
    return issues


def _check_prop_identity(
    items: list[ProseEvidenceItem],
    draft_text: str,
    trusted: TrustedSnapshot,
) -> list[ReviewIssue]:
    """道具身份：从可信道具所在位置拿出非该道具之物 → blocking. """
    issues: list[ReviewIssue] = []
    if not trusted.props:
        return issues
    for m in _PULL_RE.finditer(draft_text):
        pulled = m.group(2)
        sent = _sentence_containing(draft_text, m.start())
        if not sent:
            continue
        for p in trusted.props.values():
            if p.location and p.location in sent:
                if p.identity and p.identity not in pulled:
                    issues.append(
                        ReviewIssue(
                            issue_id=f"iss_q1_prop_{p.prop_id}",
                            issue_type="fact_conflict",
                            severity="blocking",
                            location=f"正文『{m.group(0)}』",
                            scope_of_impact="道具身份一致性",
                            violated_rule="道具身份不得凭空变化",
                            description=(
                                f"可信状态: 道具 {p.prop_id}({p.identity}) 位于 "
                                f"{p.location}；正文从同一位置拿出『{pulled}』"
                                f"——道具身份变了且无转换事件"
                            ),
                            suggested_fix="保持票根等身份，或补『变成/换作』转换并写因果",
                        )
                    )
    return issues


def _check_meta_text(items: list[ProseEvidenceItem]) -> list[ReviewIssue]:
    """元文本泄漏：上一章/本章/第N章 等进正文 → blocking. """
    issues: list[ReviewIssue] = []
    for it in items:
        if it.kind != "meta_text":
            continue
        issues.append(
            ReviewIssue(
                issue_id=f"iss_q1_meta_{it.item_id}",
                issue_type="generative_indicia",
                severity="blocking",
                location=f"正文 {it.location}『{it.evidence}』",
                scope_of_impact="生成痕迹/读者信任",
                violated_rule="生成与编辑过程文字不得进入正文",
                description=f"元文本泄漏: {it.claim}",
                suggested_fix="删除该过程性文字，改用叙事性表达",
            )
        )
    return issues


def _check_opening_repetition(
    draft_text: str, prev_chapters: list[str]
) -> list[ReviewIssue]:
    """相邻章开头复述：draft 开头签名 == 上一章开头签名 → blocking. """
    issues: list[ReviewIssue] = []
    if not prev_chapters:
        return issues
    draft_sig = opening_signature(draft_text)
    if not draft_sig:
        return issues
    prev_sig = opening_signature(prev_chapters[-1])
    if prev_sig and draft_sig == prev_sig:
        issues.append(
            ReviewIssue(
                issue_id="iss_q1_opening",
                issue_type="redundancy",
                severity="blocking",
                location="正文 开头",
                scope_of_impact="跨章进展感知",
                violated_rule="相邻章不得重复相同开头",
                description=(
                    f"本章开头『{draft_sig[:24]}…』与上一章完全复述——读者会感到"
                    f"时间没推进"
                ),
                suggested_fix="改写出新的开场情境或从上一个场景的落点续写",
            )
        )
    return issues


def _conclusion_core(normalized: str) -> str:
    """顿悟核心：取「明白」之后的核心断言，去标点/空白.

    忽然明白 vs 终于明白 归一为同一核心，供跨章重复顿悟检测。
    """
    m = _CONC_CORE_RE.search(normalized)
    core = m.group(1) if m else normalized
    return re.sub(r"[\s，。！？!?、；：]+", "", core)


def _check_repeated_conclusion(
    draft_text: str, prev_chapters: list[str], window: int = 3
) -> list[ReviewIssue]:
    """重复顿悟：同一条顿悟核心在最近 window 章内出现 ≥ window-1 次 → blocking. """
    issues: list[ReviewIssue] = []
    if not prev_chapters:
        return issues
    draft_conc = [_conclusion_core(c) for c in conclusion_sentences(draft_text)]
    if not draft_conc:
        return issues
    recent = prev_chapters[-window + 1:]  # 与本章合计 window 章
    for core in draft_conc:
        count = 1
        for ch in recent:
            if core in [_conclusion_core(c) for c in conclusion_sentences(ch)]:
                count += 1
        if count >= window:
            issues.append(
                ReviewIssue(
                    issue_id="iss_q1_repeat_conc",
                    issue_type="redundancy",
                    severity="blocking",
                    location="正文 中段",
                    scope_of_impact="顿悟/情感推进",
                    violated_rule="同一顿悟不得在多章重复表述",
                    description=(
                        f"顿悟核心『{core[:24]}…』在最近 {count}/{window} 章重复出现——"
                        f"顿悟应是一次性的认知跃迁"
                    ),
                    suggested_fix="保留一次，其余改为行为/后果落地，或让角色真正行动",
                )
            )
            break
    return issues


def _has_progression_signal(items: list[ProseEvidenceItem]) -> bool:
    """证据包里是否存在推进信号（时间/事件/选择/道具/状态/元文本）.

    纯氛围章（f08）不应有任何推进信号；f01（拈出花瓣）/ f05（回家）分别有
    prop_identity / meta_text 信号，不属于「无状态变化」。
    """
    return any(
        i.kind in ("time", "state_change", "choice", "prop_identity", "entity_status", "meta_text")
        for i in items
    )


def _check_no_state_change(
    draft_text: str, items: list[ProseEvidenceItem]
) -> list[ReviewIssue]:
    """纯氛围无状态变化：无事件/选择/顿悟/对白/时间/道具信号 → blocking. """
    if not ambient_only(draft_text) or _has_progression_signal(items):
        return []
    return [
        ReviewIssue(
            issue_id="iss_q1_no_change",
            issue_type="weak_progression",
            severity="blocking",
            location="正文 全章",
            scope_of_impact="叙事推进",
            violated_rule="每章必须推进至少一项状态（事件/选择/新事实/关系/承诺）",
            description=(
                "本章为纯氛围/位移（坐/看/换手/走回），无实质性事件、无选择、"
                "无顿悟、无对白——叙事未推进"
            ),
            suggested_fix="补一个真正发生的事件/发现/对话，让状态产生可核对的变化",
        )
    ]


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def reconcile_prose_evidence(
    draft_text: str,
    package: ProseEvidencePackage,
    *,
    prev_chapters: Optional[list[str]] = None,
    trusted: Optional[TrustedSnapshot] = None,
    chapter_ref: str = "",
) -> list[ReviewIssue]:
    """双路核对：硬一致性（单章） + 窗口（跨章）.

    Args:
        draft_text: 待提交草稿正文。
        package: extract_prose_evidence() 的产出（含证据锚点）。
        prev_chapters: 上一可信状态之前的最近章节正文（相邻章差分）。
        trusted: 上一可信状态快照；缺省空——空即不核对实体/时间/道具/周期。
        chapter_ref: 当前章标识，用于 issue 位置说明。

    Returns:
        blocking ReviewIssue 列表（无问题则为空列表）。
    """
    issues: list[ReviewIssue] = []
    items = package.items

    if trusted is not None:
        issues.extend(_check_time_regression(draft_text, items, trusted))
        issues.extend(_check_cycle_arithmetic(draft_text, items, trusted))
        issues.extend(_check_entity_status_regression(items, trusted))
        issues.extend(_check_prop_identity(items, draft_text, trusted))
    issues.extend(_check_meta_text(items))
    issues.extend(_check_no_state_change(draft_text, items))

    if prev_chapters:
        issues.extend(_check_opening_repetition(draft_text, prev_chapters))
        issues.extend(_check_repeated_conclusion(draft_text, prev_chapters))

    # 统一位置前缀，方便审阅
    if chapter_ref:
        for i in issues:
            i.location = f"{chapter_ref} {i.location}"
    return issues
