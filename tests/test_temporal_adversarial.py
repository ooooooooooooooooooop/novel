"""时间一致性门禁对抗性注入测试（Track A 替代验收证据）.

目标：向 FactLedger 注入**已知违例**，验证确定性门禁
``ReconcileUnit.check_temporal_contradictions``（对齐 FACTTRACK）按冻结口径检出：
  1. 死亡后仍活跃 → blocking timeline_error
  2. 过期事实仍被持有 → warning timeline_error
  3. 时间感知否定（X vs 未X/不X/没X，区间重叠）→ blocking timeline_error
  4. 干净台账 → 零误报
  5. 未过期持有 → 不触发（负控制）

这些是 state-first 的一致性验收证据：不依赖 LLM 评审，可复现、可注入、可证伪。
"""

from src.object_state.factledger import FactEntry, FactLedger, ValidityInterval
from src.workflow_action.reconcile import ReconcileUnit


def _ledger(*entries: FactEntry) -> list:
    return [FactLedger(entries=list(entries))]


def _issues(objects: list) -> list:
    return ReconcileUnit().check_temporal_contradictions(objects)


def _timeline(issue) -> bool:
    return issue.issue_type == "timeline_error"


# ---------------------------------------------------------------------------
# 1. 死亡后仍活跃（注入违例，必须 blocking 检出）
# ---------------------------------------------------------------------------

def test_inject_death_then_active_is_blocking():
    objects = _ledger(
        FactEntry(
            fact_id="f_death", statement="张三死亡", fact_type="event",
            involved_entities=["张三"],
            validity_interval=ValidityInterval(valid_from="第三章", valid_until="第五章"),
        ),
        FactEntry(
            fact_id="f_alive", statement="张三仍在行动", fact_type="relation",
            involved_entities=["张三"],
            validity_interval=ValidityInterval(valid_from="第六章"),
        ),
    )
    issues = _issues(objects)
    assert len(issues) == 1
    assert _timeline(issues[0])
    assert issues[0].severity == "blocking"
    assert "死亡" in issues[0].description and "活跃" in issues[0].description


def test_inject_active_before_death_is_clean():
    # 死亡在前、活跃在后才违例；活跃早于死亡不触发（负控制）。
    objects = _ledger(
        FactEntry(
            fact_id="f_alive0", statement="张三在行动", fact_type="relation",
            involved_entities=["张三"],
            validity_interval=ValidityInterval(valid_from="第一章"),
        ),
        FactEntry(
            fact_id="f_death0", statement="张三死亡", fact_type="event",
            involved_entities=["张三"],
            validity_interval=ValidityInterval(valid_from="第三章", valid_until="第五章"),
        ),
    )
    assert _issues(objects) == []


# ---------------------------------------------------------------------------
# 2. 过期事实仍被持有（注入违例，必须 warning 检出）
# ---------------------------------------------------------------------------

def test_inject_expired_holding_is_warning():
    objects = _ledger(
        FactEntry(
            fact_id="f_exp", statement="令牌归c001所有", fact_type="rule",
            involved_entities=["c001"],
            validity_interval=ValidityInterval(valid_from="第一章", valid_until="第五章"),
        ),
        FactEntry(
            fact_id="f_hold", statement="c001 仍持有令牌", fact_type="relation",
            involved_entities=["c001"],
            validity_interval=ValidityInterval(valid_from="第六章"),
        ),
    )
    issues = _issues(objects)
    assert len(issues) == 1
    assert _timeline(issues[0])
    assert issues[0].severity == "warning"
    assert "过期" in issues[0].description


def test_inject_holding_not_expired_is_clean():
    # valid_until=None（始终有效）→ 不触发过期持有（负控制）。
    objects = _ledger(
        FactEntry(
            fact_id="f_always", statement="令牌归c003所有", fact_type="rule",
            involved_entities=["c003"],
            validity_interval=ValidityInterval(valid_from="第一章"),
        ),
        FactEntry(
            fact_id="f_hold3", statement="c003 持有令牌", fact_type="relation",
            involved_entities=["c003"],
        ),
    )
    assert _issues(objects) == []


# ---------------------------------------------------------------------------
# 3. 时间感知否定（注入违例，必须 blocking 检出）
# ---------------------------------------------------------------------------

def test_inject_temporal_negation_overlap_is_blocking():
    objects = _ledger(
        FactEntry(
            fact_id="f_pos", statement="刀在甲手中", fact_type="event",
            involved_entities=["甲", "刀"],
            validity_interval=ValidityInterval(valid_from="第一章", valid_until="第三章"),
        ),
        FactEntry(
            fact_id="f_neg", statement="刀不在甲手中", fact_type="event",
            involved_entities=["甲", "刀"],
            validity_interval=ValidityInterval(valid_from="第二章", valid_until="第三章"),
        ),
    )
    issues = _issues(objects)
    assert len(issues) == 1
    assert _timeline(issues[0])
    assert issues[0].severity == "blocking"
    assert "互相矛盾" in issues[0].description


def test_inject_non_overlapping_negation_is_clean():
    # 否定事实区间严格不相交 → 不冲突（负控制：甲先得刀、后失刀是正常时序）。
    objects = _ledger(
        FactEntry(
            fact_id="f_pos0", statement="刀在甲手中", fact_type="event",
            involved_entities=["甲", "刀"],
            validity_interval=ValidityInterval(valid_from="第一章", valid_until="第一章"),
        ),
        FactEntry(
            fact_id="f_neg0", statement="刀不在甲手中", fact_type="event",
            involved_entities=["甲", "刀"],
            validity_interval=ValidityInterval(valid_from="第三章", valid_until="第三章"),
        ),
    )
    assert _issues(objects) == []


# ---------------------------------------------------------------------------
# 4. 干净台账 → 零误报
# ---------------------------------------------------------------------------

def test_clean_ledger_no_false_positives():
    objects = _ledger(
        FactEntry(
            fact_id="f1", statement="李四出发", fact_type="event",
            involved_entities=["李四"],
            validity_interval=ValidityInterval(valid_from="第一章", valid_until="第二章"),
        ),
        FactEntry(
            fact_id="f2", statement="李四抵达", fact_type="event",
            involved_entities=["李四"],
            validity_interval=ValidityInterval(valid_from="第三章"),
        ),
        FactEntry(
            fact_id="f3", statement="令牌归c002所有", fact_type="rule",
            involved_entities=["c002"],
        ),
    )
    assert _issues(objects) == []
