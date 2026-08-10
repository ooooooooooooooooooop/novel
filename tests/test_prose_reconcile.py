"""Phase 1 门禁：ProseEvidence 提取 + ProseReconcile 双路核对必须阻断 8 类夹具.

**翻转约定**（见 test_q1_phase0_baseline.py 文件头）：Phase 0 证明现有门禁错误
放行这些夹具；Phase 1 实现新门禁后，本文件断言「必须阻断」成为回归基线。

每个夹具断言其专属门禁的 issue_type 命中（比单纯断言非空更强——证明是正确
的门禁挡住了它，而不是别的原因）：

  f01 道具身份变化      -> fact_conflict（可信票根在诗集，正文从诗集拈出花瓣）
  f02 实体状态回退      -> fact_conflict（可信 found，正文 missing 无事件）
  f03 时间回退          -> timeline_error（一月 -> 十二月，无时长/年份/闪回标记）
  f04 周期算术          -> timeline_error（60 年周期，11 年处即宣称届满）
  f05 元文本泄漏        -> generative_indicia（上一章/本章 进正文）
  f06 相邻章开头复述    -> redundancy（开头签名与上章相同）
  f07 重复顿悟 ≥3 章    -> redundancy（同一顿悟核心跨 3 章）
  f08 纯氛围无变化      -> weak_progression（无事件/选择/顿悟/对白/时间信号）
"""

import pytest

from src.object_state.prose_evidence import ProseEvidencePackage
from src.workflow_action.prose_evidence import extract_prose_evidence
from src.workflow_action.prose_reconcile import (
    CycleAnchor,
    PropSnapshot,
    TrustedSnapshot,
    reconcile_prose_evidence,
)
from tests.test_q1_phase0_baseline import FIXTURES

# fixture_id -> (TrustedSnapshot, 专属门禁期望的 blocking issue_type)
TRUSTED = {
    "f01_ticket_to_petal": (
        TrustedSnapshot(
            entities={"c001": ["方宇"], "obj_ticket": ["票根"]},
            entity_status={"c001": "active"},
            props={"obj_ticket": PropSnapshot(prop_id="obj_ticket", identity="票根", location="诗集")},
        ),
        "fact_conflict",
    ),
    "f02_found_to_missing": (
        TrustedSnapshot(
            entities={"c002": ["李文"], "c003": ["陈叔"]},
            entity_status={"c002": "found", "c003": "active"},
        ),
        "fact_conflict",
    ),
    "f03_january_to_december": (
        TrustedSnapshot(
            entities={"c001": ["方宇"]},
            entity_status={},
            current_month=1,
        ),
        "timeline_error",
    ),
    "f04_cycle_60yr_expires_11yr": (
        TrustedSnapshot(
            entities={"org_sect": ["长老"]},
            entity_status={},
            cycle=CycleAnchor(cycle_label="甲子", cycle_length_years=60, current_elapsed_years=11),
        ),
        "timeline_error",
    ),
    "f05_metatext_leak": (
        None,
        "generative_indicia",
    ),
    "f06_same_opening": (
        None,
        "redundancy",
    ),
    "f07_epiphany_repeated_3ch": (
        None,
        "redundancy",
    ),
    "f08_no_state_change": (
        TrustedSnapshot(
            entities={"c006": ["林生"]},
            entity_status={"c006": "active"},
        ),
        "weak_progression",
    ),
}


def _prev_chapters(fixture) -> list[str]:
    """上一可信章节正文（有序，最后一项是最接近草稿的一章）. """
    prev = [fixture["prev_text"]]
    if "prev_prev_text" in fixture:
        prev = [fixture["prev_prev_text"], fixture["prev_text"]]
    return prev


def _entities_of(trusted: TrustedSnapshot) -> dict[str, list[str]]:
    if trusted is None:
        return {}
    return trusted.entities


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["fixture_id"])
def test_phase1_prose_reconcile_must_block(fixture):
    """Phase 1 门禁：新门禁必须阻断全部 8 类夹具，且命中的是正确的 issue_type. """
    trusted, expected_type = TRUSTED[fixture["fixture_id"]]
    draft_text = fixture["draft_text"]
    prev_chapters = _prev_chapters(fixture)

    pkg = extract_prose_evidence(draft_text, entities=_entities_of(trusted))
    issues = reconcile_prose_evidence(
        draft_text, pkg, prev_chapters=prev_chapters, trusted=trusted,
        chapter_ref="draft",
    )
    blocking = [i for i in issues if i.is_blocking()]

    assert blocking, (
        f"夹具 {fixture['fixture_id']} 未被新门禁阻断！"
        f"\n夹具意图: {fixture['desc']}"
        f"\n应被 {fixture['q1_gate']} 拦截"
    )
    assert any(i.issue_type == expected_type for i in blocking), (
        f"夹具 {fixture['fixture_id']} 被阻断但命中的 issue_type 不对："
        f"{[i.issue_type for i in blocking]}（期望 {expected_type}）"
    )


def test_phase1_legit_forward_time_not_blocked():
    """合法向前推进不误伤：一月 -> 九月（季节跳 2 段）、带『三个月后』标记的跨季. """
    legit = "九月里，稻子黄了。田埂上有人赶着牛走过，孩子跟在后面拾穗。"
    pkg = extract_prose_evidence(legit)
    issues = reconcile_prose_evidence(
        legit, pkg,
        trusted=TrustedSnapshot(current_month=1),
    )
    assert not any(i.is_blocking() for i in issues), issues

    legit2 = "三个月后已是寒冬，河面结冰，货船都停了。"
    pkg2 = extract_prose_evidence(legit2)
    issues2 = reconcile_prose_evidence(
        legit2, pkg2,
        trusted=TrustedSnapshot(current_month=9),
    )
    assert not any(i.is_blocking() for i in issues2), issues2


def test_phase1_flashback_time_not_blocked():
    """闪回标记放行：时间跳跃带显式回忆标记不算回退. """
    flashback = "他想起那年十二月，也是这样的寒夜。他裹紧被子，没有睡实。"
    pkg = extract_prose_evidence(flashback)
    issues = reconcile_prose_evidence(
        flashback, pkg,
        trusted=TrustedSnapshot(current_month=1),
    )
    assert not any(i.is_blocking() for i in issues), issues


def test_phase1_clean_chapter_not_blocked():
    """正常推进章（事件 + 时间 + 对白）不触发任何阻断. """
    draft = "五月，她把那封信交到老陈手里，说：这是账房的凭证。老陈接过来，压在柜里。"
    pkg = extract_prose_evidence(
        draft,
        entities={"c001": ["她"], "c002": ["老陈"], "obj_letter": ["信"]},
    )
    issues = reconcile_prose_evidence(
        draft, pkg,
        prev_chapters=["三月里，她翻出旧账本，一笔一笔核对。"],
        trusted=TrustedSnapshot(
            entities={"c001": ["她"], "c002": ["老陈"]},
            entity_status={"c001": "active", "c002": "active"},
            current_month=3,
        ),
    )
    assert not any(i.is_blocking() for i in issues), issues


def test_phase1_package_is_prose_evidence_package():
    """类型契约：reconcile 消费的确实是 ProseEvidencePackage. """
    pkg = extract_prose_evidence("次日，她离开码头。")
    assert isinstance(pkg, ProseEvidencePackage)


def test_build_trusted_snapshot_from_fact_ledger():
    """对接真实对象：build_trusted_snapshot 从 FactLedger 推导实体状态与道具身份. """
    from src.object_state import FactEntry, FactLedger
    from src.workflow_action.prose_reconcile import build_trusted_snapshot

    ledger = FactLedger(entries=[
        FactEntry(
            fact_id="f_ticket",
            statement="票根 夹在 诗集里",
            fact_type="relation",
            involved_entities=["obj_ticket", "obj_book", "c001"],
            confirmed=True,
            timestamp="第一章",
        ),
        FactEntry(
            fact_id="f_found",
            statement="李文 已找到 在码头",
            fact_type="relation",
            involved_entities=["c002", "loc_dock"],
            confirmed=True,
            timestamp="第一章",
        ),
    ])
    snap = build_trusted_snapshot(
        fact_ledger=ledger,
        labels={
            "obj_ticket": ["票根"], "obj_book": ["诗集"], "c001": ["方宇"],
            "c002": ["李文"], "loc_dock": ["码头"],
        },
    )
    # 道具身份 + 位置
    assert snap.props["obj_ticket"].identity == "票根"
    assert snap.props["obj_ticket"].location == "诗集"
    # 实体状态（已找到）
    assert snap.entity_status.get("c002") == "found"
    # 实体注册表
    assert snap.entities["obj_ticket"] == ["票根"]


def test_build_trusted_snapshot_end_to_end_blocks_f01():
    """端到端：build_trusted_snapshot(真实 FactLedger) -> extract -> reconcile 阻断 f01. """
    from src.object_state import FactEntry, FactLedger
    from src.workflow_action.prose_reconcile import build_trusted_snapshot

    fixture = next(f for f in FIXTURES if f["fixture_id"] == "f01_ticket_to_petal")
    ledger = fixture["objects"]()[0]  # FactLedger（票根 夹在 诗集里）
    snap = build_trusted_snapshot(
        fact_ledger=ledger,
        labels={"obj_ticket": ["票根"], "obj_book": ["诗集"], "c001": ["方宇"]},
    )
    pkg = extract_prose_evidence(fixture["draft_text"], entities=snap.entities)
    issues = reconcile_prose_evidence(
        fixture["draft_text"], pkg, prev_chapters=[fixture["prev_text"]], trusted=snap,
    )
    blocking = [i for i in issues if i.is_blocking()]
    assert any(i.issue_type == "fact_conflict" for i in blocking), blocking


def test_build_trusted_snapshot_derives_time_from_timebook():
    """对接 TimeBook：从最新锚点日期推导当前月份（f03 一月场景）. """
    import importlib
    from src.workflow_action.prose_reconcile import build_trusted_snapshot

    TimeBook = importlib.import_module("src.object_state.timebook").TimeBook
    TimeAnchor = importlib.import_module("src.object_state.timebook").TimeAnchor
    tb = TimeBook(
        schema_version=1,
        anchors=[TimeAnchor(chapter="第1章", date="2026-01-15")],
    )
    snap = build_trusted_snapshot(time_book=tb)
    assert snap.current_month == 1
    assert snap.current_season == "春"


def test_build_trusted_snapshot_timebook_blocks_f03():
    """端到端：TimeBook(一月) 推导的时间快照 -> reconcile 阻断 f03 十二月回退. """
    import importlib
    from src.workflow_action.prose_reconcile import build_trusted_snapshot

    TimeBook = importlib.import_module("src.object_state.timebook").TimeBook
    TimeAnchor = importlib.import_module("src.object_state.timebook").TimeAnchor
    fixture = next(f for f in FIXTURES if f["fixture_id"] == "f03_january_to_december")
    tb = TimeBook(
        schema_version=1,
        anchors=[TimeAnchor(chapter="第1章", date="2026-01-15")],
    )
    snap = build_trusted_snapshot(time_book=tb)
    pkg = extract_prose_evidence(fixture["draft_text"], entities={})
    issues = reconcile_prose_evidence(
        fixture["draft_text"], pkg, prev_chapters=[fixture["prev_text"]], trusted=snap,
    )
    blocking = [i for i in issues if i.is_blocking()]
    assert any(i.issue_type == "timeline_error" for i in blocking), blocking
