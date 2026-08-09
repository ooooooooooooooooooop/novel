"""State 三指标测试：Selection Precision / Silence Discipline / Off-screen Survival.

这三个指标取代"关键词 8/8"作为 State 阶段的质量核心：
- 关键词只作工程诊断，不作质量证明。
"""
from src.object_state.statemodel import (
    CompressionLevel,
    OffScreenProcess,
    StateModel,
    ThreadState,
)
from src.workflow_action.state_validation import (
    offscreen_survival,
    selection_precision,
    silence_discipline,
)

THREADS = {
    "经销商大会": ["经销商大会"],
    "恒通机芯": ["恒通"],
    "劲达竞争": ["劲达"],
    "官场": ["陆平"],
    "家庭": ["夏晴"],
    "战略": ["超级VCD"],
}


def test_selection_precision_measures_cramming():
    real = "经销商大会召开，陆平到场，劲达受邀。"
    gen = "经销商大会召开，陆平到场，劲达受邀，夏晴在家，超级VCD发布。"
    res = selection_precision(gen, real, THREADS)
    # gen 用 5 条，真实 3 条 → precision 3/5，塞入 2 条
    assert res["gen_used"] == 5
    assert res["real_used"] == 3
    assert res["precision"] == 3 / 5
    assert res["crammed"] == ["家庭", "战略"]  # 塞入真实章没有的


def test_silence_discipline_detects_checklist():
    # 全用 6/6 = 清单化信号
    gen_all = "经销商大会 恒通 劲达 陆平 夏晴 超级VCD 都提到"
    res = silence_discipline(gen_all, THREADS)
    assert res["usage_ratio"] == 1.0
    assert res["checklist_like"] is True

    # 只用 2/6 = 有克制（自然子集）
    gen_sub = "经销商大会，恒通谈判。"
    res2 = silence_discipline(gen_sub, THREADS)
    assert res2["used"] == 2
    assert res2["checklist_like"] is False
    assert "官场" in res2["restrained"]  # 被忍住


def test_offscreen_survival_not_forgotten():
    # 状态里有 6 线程；正文只写 2 条 → 其余 4 条应仍活跃
    sm = StateModel(
        threads=[
            ThreadState(thread_id=f"t{i}", thread_type="线", label=name,
                        compression=CompressionLevel.ACTIVE)
            for i, name in enumerate(THREADS)
        ]
    )
    gen = "经销商大会，恒通谈判。"
    res = offscreen_survival(sm, gen, THREADS)
    assert res["restrained"]  # 有被忍住的线程
    assert res["survived_in_state"]  # 都在 state 里活着（ACTIVE）
    assert res["forgotten"] == []  # 没被遗忘
    assert res["survival_rate"] == 1.0


def test_offscreen_survival_catches_forgetting():
    # 正文用了某线程，但 state 里它已不在活跃线程（被遗忘）
    sm = StateModel(
        threads=[ThreadState(thread_id="t1", thread_type="线", label="经销商大会",
                             compression=CompressionLevel.ARCHIVED)]
    )
    gen = "劲达竞争线。"
    res = offscreen_survival(sm, gen, THREADS)
    # 被忍住的 5 条里，除了经销商大会归档，其余未建模 → 记为 forgotten
    assert res["survival_rate"] < 1.0 or res["forgotten"]
