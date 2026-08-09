"""State Model 测试三件套：Strategy Horizon / 非主角线程 / 世界后台."""
from src.object_state.statemodel import (
    OffScreenProcess,
    Provenance,
    StateModel,
    StrategicPosition,
)
from src.workflow_action.state_validation import (
    build_survival_probe,
    offscreen_survival_check,
    strategy_horizon_score,
    world_background_check,
)


def test_strategy_horizon_multi():
    """战略站位同时有 waiting + pending_payoffs + triggers = 多时域（掌控感来源）."""
    sm = StateModel(
        strategic=[
            StrategicPosition(
                entity="周正", waiting_for=["商业地皮批复"], pending_payoffs=["产业链整合"],
                triggers=["批复下达"], positioning=["已留后手"],
            )
        ]
    )
    score = strategy_horizon_score(sm)
    assert score["multi_horizon"] == 1
    assert score["solve_now_only"] == 0
    assert score["horizon_span"] >= 3  # 覆盖未来兑现


def test_strategy_horizon_solve_now():
    """只有当前判断、无等待/兑现 = 短视（遇事解决特征）."""
    sm = StateModel(
        strategic=[StrategicPosition(entity="周正", judgment=["此事必须马上处理"])]
    )
    score = strategy_horizon_score(sm)
    assert score["solve_now_only"] == 1
    assert score["multi_horizon"] == 0


def test_offscreen_survival():
    """离场 30 章：有状态、有事件、非被动等待 → 存活."""
    off = build_survival_probe("某同学", intents=["毕业就业"], elapsed_chapters=30)
    sm = StateModel(offscreen=[off])
    check = offscreen_survival_check(sm, elapsed_chapters=30)
    assert check["survived"] == 1
    assert check["waiting_passive"] == 0


def test_offscreen_passive_fails():
    """失败信号：离场实体「等待主角重新出现」= 冻结."""
    sm = StateModel(
        offscreen=[
            OffScreenProcess(entity="某配角", background_state="", next_most_likely="等待主角回来")
        ]
    )
    check = offscreen_survival_check(sm, elapsed_chapters=30)
    assert check["survived"] == 0
    assert check["waiting_passive"] == 1  # 检测到被动等待


def test_world_background_independent():
    """组织类离场实体有独立动力学（非冻结）."""
    sm = StateModel(
        offscreen=[
            build_survival_probe("某公司", intents=["市场扩张"], elapsed_chapters=35),
            OffScreenProcess(entity="某配角", background_state="", next_most_likely="等待"),
        ]
    )
    check = world_background_check(sm)
    assert check["total_org"] == 1  # 只统计组织类
    assert check["independent"] == 1  # 公司有独立动力学


def test_build_survival_probe_simulated():
    off = build_survival_probe("某同学", intents=["恋爱"], elapsed_chapters=50)
    assert off.provenance == Provenance.SIMULATED  # 后台推演不升级为 CANON
    assert "性格/处境已有可见变化" in off.background_state  # 50章必有变化
