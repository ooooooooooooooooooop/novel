"""causal_defense 长程因果防线对抗测试（P1）.

目标：验证 5 类失败模式被确定性检测：
  1. 已完成事件被重写（抹掉已发生现实）→ blocking fact_conflict
  2. 已付代价失效（代价未传播/无解释恢复）→ warning missing_cost / blocking world_violation
  3. 人物成长或知识状态重置 → warning character_distortion
  4. 制度与群体后果未传播 → warning world_violation
  5. 已有选择未改变后续策略空间 → warning weak_progression

每类至少：违规注入 / 干净负控制 / 边界样本 / 顺序变化样本 / 幂等样本。
复用 ReviewIssueType 枚举，不扩枚举；全部确定性、零 LLM。
"""

from src.domain_layer.causal_defense import (
    detect_choice_no_future_impact,
    detect_erased_committed_event,
    detect_growth_reset,
    detect_group_consequence_unpropagated,
    detect_invalidated_cost,
    run_causal_defense,
)
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    PlotUnit,
    WorldModel,
)


def _pu(unit_id: str, *, goal="推进", conflict="冲突", released=None,
        consequences=None, summary=None, participants=None,
        input_ref="s_in", output_ref="s_out") -> PlotUnit:
    return PlotUnit(
        unit_id=unit_id,
        level="scene",
        goal=goal,
        conflict=conflict or "冲突",
        participants=participants or ["c001"],
        input_state_ref=input_ref,
        output_state_ref=output_ref,
        released_information=released or [],
        consequences=consequences or [],
        state_change_summary=summary,
    )


def _fact(fact_id: str, statement: str, *, fact_type="event", entities=None,
          confirmed=True) -> FactEntry:
    return FactEntry(
        fact_id=fact_id,
        statement=statement,
        fact_type=fact_type,
        involved_entities=entities or ["e001"],
        confirmed=confirmed,
    )


def _ledger(*entries: FactEntry) -> FactLedger:
    return FactLedger(entries=list(entries))


def _state(state_id: str, *, conflicts=(), goals=(), hidden=(), suspense=()) -> NarrativeState:
    return NarrativeState(
        state_id=state_id,
        current_time="第一章",
        current_location="廷根",
        current_situation="局势未定",
        active_conflicts=list(conflicts),
        current_goals=list(goals),
        hidden_information=list(hidden),
        active_suspense_items=list(suspense),
    )


# ---------------------------------------------------------------------------
# 1. 已完成事件被重写（抹掉已发生现实）
# ---------------------------------------------------------------------------

def test_erased_destroyed_location_is_blocking():
    objects = [
        _ledger(_fact("f_destroy", "古堡已被焚毁", fact_type="event")),
        _pu("pu_a", goal="探查古堡", conflict="寻找线索",
            released=["古堡竟完好如初，仿佛从未发生火灾"]),
    ]
    issues = detect_erased_committed_event(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "fact_conflict"
    assert issues[0].is_blocking()


def test_erased_clean_reference_to_history_is_not_blocking():
    # 负控制：草案只回忆历史（「他记得古堡被烧毁」），不含抹除词。
    objects = [
        _ledger(_fact("f_destroy2", "古堡已被焚毁", fact_type="event")),
        _pu("pu_b", goal="回忆往事", conflict="悼念",
            released=["他记得那座古堡当年被烧毁的惨状"]),
    ]
    assert detect_erased_committed_event(objects) == []


def test_erased_explicit_rebuild_with_cost_is_clean():
    # 负控制：显式重建事件（含代价），不是悄悄抹除。
    objects = [
        _ledger(_fact("f_destroy3", "古堡已被焚毁", fact_type="event")),
        _pu("pu_c", goal="重建古堡", conflict="筹措巨资",
            released=["他们筹集重金，历时三年重建了古堡"],
            consequences=["耗尽家财"]),
    ]
    assert detect_erased_committed_event(objects) == []


def test_erased_boundary_no_entity_match_is_clean():
    # 边界：抹除词与已终结事实的实体不一致 → 不触发。
    objects = [
        _ledger(_fact("f_destroy4", "北城已被焚毁", fact_type="event", entities=["北城"])),
        _pu("pu_d", goal="处理别事", conflict="",
            released=["西街的药铺完好如初"]),
    ]
    assert detect_erased_committed_event(objects) == []


def test_erased_order_independent_and_idempotent():
    objects_a = [
        _pu("pu_e", goal="返回", conflict="",
            released=["古堡完好如初，像没发生过火灾"]),
        _ledger(_fact("f_destroy5", "古堡已被焚毁", fact_type="event")),
    ]
    objects_b = [objects_a[1], objects_a[0]]
    ia = detect_erased_committed_event(objects_a)
    ib = detect_erased_committed_event(objects_b)
    assert [i.issue_id for i in ia] == [i.issue_id for i in ib]
    assert [i.issue_id for i in detect_erased_committed_event(objects_a)] == [
        i.issue_id for i in ia
    ]


# ---------------------------------------------------------------------------
# 2. 已付代价失效（代价未传播 / 无解释恢复）
# ---------------------------------------------------------------------------

def test_invalidated_cost_is_warning_without_world_mechanism():
    objects = [
        _ledger(_fact("f_cost", "张三失去一臂", fact_type="event")),
        _pu("pu_f", goal="重握刀柄", conflict="",
            released=["张三的断臂竟已恢复如初"]),
    ]
    issues = detect_invalidated_cost(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "missing_cost"
    assert issues[0].severity == "warning"
    assert not issues[0].is_blocking()


def test_invalidated_cost_upgrades_to_blocking_with_world_mechanism():
    world = WorldModel(
        consequence_logic=["禁术使用留下不可逆代价"],
        prohibitions=[],
    )
    objects = [
        world,
        _ledger(_fact("f_cost2", "李四透支修为", fact_type="event")),
        _pu("pu_g", goal="再战", conflict="",
            released=["李四的修为竟已重新拥有"]),
    ]
    issues = detect_invalidated_cost(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "world_violation"
    assert issues[0].is_blocking()


def test_invalidated_cost_clean_new_payment_is_clean():
    # 负控制：恢复伴随新的代价支付 → 合法。
    objects = [
        _ledger(_fact("f_cost3", "王五失去右腿", fact_type="event")),
        _pu("pu_h", goal="装义肢", conflict="",
            released=["王五装上义肢，重新行走"],
            consequences=["付出全部积蓄"]),
    ]
    assert detect_invalidated_cost(objects) == []


def test_invalidated_cost_boundary_no_recovery_marker_is_clean():
    objects = [
        _ledger(_fact("f_cost4", "赵六失去左眼", fact_type="event")),
        _pu("pu_i", goal="适应", conflict="",
            released=["赵六戴着单眼罩继续赶路"]),
    ]
    assert detect_invalidated_cost(objects) == []


# ---------------------------------------------------------------------------
# 3. 人物成长或知识状态重置
# ---------------------------------------------------------------------------

def test_growth_reset_is_warning():
    cm = CharacterModel(
        character_id="c001", name="主角", identity="流浪剑客",
        outer_goal="复仇", inner_need="和解", fear="重蹈覆辙", flaw="孤僻",
        strength="坚韧", stance="中立",
        change_trajectory=["从独行到愿意托付"],
        self_image="我已学会信任",
    )
    objects = [
        cm,
        _pu("pu_j", goal="面对旧友", conflict="",
            released=["他仿佛从未改变，又变回那个独来独往的人"]),
    ]
    issues = detect_growth_reset(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "character_distortion"
    assert issues[0].severity == "warning"


def test_growth_reset_clean_no_reset_marker_is_clean():
    cm = CharacterModel(
        character_id="c002", name="配角", identity="商人",
        outer_goal="盈利", inner_need="安稳", fear="破产", flaw="吝啬",
        strength="精明", stance="中立",
        change_trajectory=["从吝啬到愿意分利"],
    )
    objects = [
        cm,
        _pu("pu_k", goal="谈判", conflict="",
            released=["他主动提出与伙伴分利"]),
    ]
    assert detect_growth_reset(objects) == []


def test_growth_reset_boundary_other_character_is_clean():
    # 边界：重置语言涉及另一角色（不在 participants）→ 不触发。
    cm = CharacterModel(
        character_id="c003", name="甲", identity="书生",
        outer_goal="中举", inner_need="认可", fear="落榜", flaw="自卑",
        strength="勤奋", stance="中立",
        change_trajectory=["从自卑到自信"],
    )
    objects = [
        cm,
        _pu("pu_l", goal="旁观", conflict="", participants=["c999"],
            released=["那人又变回怯懦的样子"]),
    ]
    assert detect_growth_reset(objects) == []


# ---------------------------------------------------------------------------
# 4. 制度与群体后果未传播
# ---------------------------------------------------------------------------

def test_group_consequence_unpropagated_is_warning():
    objects = [
        _ledger(_fact("f_inst", "王城下达全面宵禁", fact_type="event", entities=["王城"])),
        _pu("pu_m", goal="夜行", conflict="",
            released=["主角照常深夜走在王城大街"]),
    ]
    issues = detect_group_consequence_unpropagated(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "world_violation"
    assert issues[0].severity == "warning"


def test_group_consequence_propagated_is_clean():
    # 负控制：后果已传播（策略/代价/反应）→ 不触发。
    objects = [
        _ledger(_fact("f_inst2", "王城下达全面宵禁", fact_type="event", entities=["王城"])),
        _pu("pu_n", goal="避巡夜", conflict="",
            released=["主角改走屋顶，避开巡夜兵丁"],
            consequences=["绕路消耗体力"]),
    ]
    assert detect_group_consequence_unpropagated(objects) == []


def test_group_consequence_boundary_no_entity_is_clean():
    objects = [
        _ledger(_fact("f_inst3", "东境开战", fact_type="event", entities=["东境"])),
        _pu("pu_o", goal="西市买米", conflict="",
            released=["西市粮价平稳"]),
    ]
    assert detect_group_consequence_unpropagated(objects) == []


# ---------------------------------------------------------------------------
# 5. 已有选择没有改变后续策略空间（质量信号）
# ---------------------------------------------------------------------------

def test_choice_no_future_impact_is_warning():
    objects = [
        _pu("pu_p", goal="决定投靠一方", conflict="选择阵营",
            released=["他最终决定投靠朝廷"]),
        _state("s_in", conflicts=("对峙",), goals=("自保",)),
        _state("s_out", conflicts=("对峙",), goals=("自保",)),
    ]
    issues = detect_choice_no_future_impact(objects)
    assert len(issues) == 1
    assert issues[0].issue_type == "weak_progression"
    assert issues[0].severity == "warning"


def test_choice_with_consequence_is_clean():
    # 负控制：选择有后果/状态变化 → 不触发。
    objects = [
        _pu("pu_q", goal="决定投靠一方", conflict="选择阵营",
            released=["他决定投靠朝廷"],
            consequences=["与旧主决裂，沦为通缉犯"],
            summary="阵营改变"),
        _state("s_in", conflicts=("对峙",), goals=("自保",)),
        _state("s_out", conflicts=("决裂",), goals=("逃亡",)),
    ]
    assert detect_choice_no_future_impact(objects) == []


def test_choice_boundary_not_a_choice_is_clean():
    objects = [
        _pu("pu_r", goal="路过城门", conflict="",
            released=["他交了过路费进城"]),
        _state("s_in"), _state("s_out"),
    ]
    assert detect_choice_no_future_impact(objects) == []


# ---------------------------------------------------------------------------
# 聚合：run_causal_defense 幂等 + 顺序无关
# ---------------------------------------------------------------------------

def test_run_causal_defense_idempotent_and_order_independent():
    objects = [
        _ledger(
            _fact("f_d", "古堡已被焚毁", fact_type="event"),
            _fact("f_c", "主角失去一臂", fact_type="event"),
        ),
        _pu("pu_s", goal="重访古堡", conflict="",
            released=["古堡完好如初，主角断臂也已恢复"]),
    ]
    a = run_causal_defense(objects)
    b = run_causal_defense(list(reversed(objects)))
    assert [i.issue_id for i in a] == [i.issue_id for i in b]
    assert [i.issue_id for i in run_causal_defense(objects)] == [
        i.issue_id for i in a
    ]
    # 事件抹除 blocking；代价失效在无世界机制时 warning
    assert any(i.is_blocking() for i in a)
    assert any(not i.is_blocking() for i in a)


def test_run_causal_defense_clean_objects_produce_no_issues():
    objects = [
        _ledger(_fact("f_ok", "主角到达王城", fact_type="event")),
        _pu("pu_t", goal="拜会", conflict="投帖",
            released=["他递上拜帖，等待接见"],
            consequences=["通报"]) ,
        _state("s_in"), _state("s_out"),
    ]
    assert run_causal_defense(objects) == []
