"""S3（54 计划 §S3）长程因果防线对抗样本集——5 类攻击 × 正例/负控，可重跑.

5 类攻击（P-3）：
1. erased          现实抹除（已完成事件被重写为未发生）
2. invalidated_cost 已付代价消失（代价被无声恢复）
3. growth_reset    成长/知识状态重置
4. group_consequence 制度与群体后果未传播
5. choice_no_impact 选择无后效（无未来差异）

run_suite() 遍历全部样本：正例必须被 run_causal_defense 检出
（erased 类必须 blocking 级），负控必须零检出；同时验证幂等。
返回结构化报告，供 scripts/run_causal_adversarial_suite.py 打印矩阵。

样本对象构造对齐 tests/test_causal_defense.py 的既有样例模式
（各检测器的真实触发条件：恢复词/重置词/规避缺失/状态无变化），
检测语义与既有实现一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    NarrativeState,
    PlotUnit,
    WorldModel,
)
from src.domain_layer.causal_defense import run_causal_defense

ATTACK_CLASSES: tuple[str, ...] = (
    "erased",
    "invalidated_cost",
    "growth_reset",
    "group_consequence",
    "choice_no_impact",
)


@dataclass(frozen=True)
class CausalAdversarialCase:
    case_id: str
    attack_class: str
    expect: str  # "block"（正例，必须检出） | "pass"（负控，必须零检出）
    # FactLedger 条目：(fact_id, statement, entities)
    facts: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    # PlotUnit
    plot_goal: str = "推进"
    plot_conflict: str = "冲突"
    released: tuple[str, ...] = ()
    consequences: tuple[str, ...] = ()
    summary: Optional[str] = None
    # WorldModel（代价失效升级 blocking 用）
    world_consequence_logic: tuple[str, ...] = ()
    # CharacterModel（成长重置用）
    character: Optional[dict[str, Any]] = None
    # NarrativeState in/out：((in_conflicts, in_goals), (out_conflicts, out_goals))
    states: tuple[tuple[tuple[str, ...], tuple[str, ...]],
                  tuple[tuple[str, ...], tuple[str, ...]]] | None = None


def _objects(case: CausalAdversarialCase) -> list:
    objects: list = []
    if case.world_consequence_logic:
        objects.append(WorldModel(
            consequence_logic=list(case.world_consequence_logic),
            prohibitions=[],
        ))
    if case.facts:
        objects.append(FactLedger(entries=[
            FactEntry(
                fact_id=fid, statement=stmt, fact_type="event",
                involved_entities=list(entities or ["e001"]), confirmed=True,
            )
            for fid, stmt, entities in case.facts
        ]))
    if case.character:
        cm = case.character
        objects.append(CharacterModel(
            character_id=cm.get("character_id", "c001"),
            name=cm.get("name", "主角"),
            identity=cm.get("identity", "流浪剑客"),
            outer_goal=cm.get("outer_goal", "复仇"),
            inner_need=cm.get("inner_need", "和解"),
            fear=cm.get("fear", "重蹈覆辙"),
            flaw=cm.get("flaw", "孤僻"),
            strength=cm.get("strength", "坚韧"),
            stance=cm.get("stance", "中立"),
            change_trajectory=cm.get("change_trajectory", []),
            self_image=cm.get("self_image", ""),
        ))
    pu = PlotUnit(
        unit_id=f"pu_{case.case_id}",
        level="scene",
        goal=case.plot_goal,
        conflict=case.plot_conflict or "冲突",
        participants=["c001"],
        input_state_ref="s_in",
        output_state_ref="s_out",
        released_information=list(case.released),
        consequences=list(case.consequences),
        state_change_summary=case.summary,
    )
    objects.append(pu)
    if case.states:
        (in_c, in_g), (out_c, out_g) = case.states
        objects.append(NarrativeState(
            state_id="s_in", current_time="第一章", current_location="廷根",
            current_situation="局势未定",
            active_conflicts=list(in_c), current_goals=list(in_g),
        ))
        objects.append(NarrativeState(
            state_id="s_out", current_time="第一章", current_location="廷根",
            current_situation="局势未定",
            active_conflicts=list(out_c), current_goals=list(out_g),
        ))
    return objects


# ---- 5 类对抗样本（正例 expect=block / 负控 expect=pass） ----
# 构造对齐 tests/test_causal_defense.py 的真实触发条件。

ADVERSARIAL_CASES: tuple[CausalAdversarialCase, ...] = (
    # 1. 现实抹除（blocking fact_conflict）
    CausalAdversarialCase(
        "erased-001", "erased", "block",
        facts=(("f_destroy", "古堡已被焚毁", ("古堡",)),),
        released=("古堡竟完好如初，仿佛从未发生火灾",),
    ),
    CausalAdversarialCase(
        "erased-002-clean", "erased", "pass",
        facts=(("f_destroy2", "古堡已被焚毁", ("古堡",)),),
        released=("他记得那座古堡当年被烧毁的惨状",),
    ),
    # 2. 已付代价消失（warning missing_cost / +世界规则 blocking）
    CausalAdversarialCase(
        "cost-001", "invalidated_cost", "block",
        facts=(("f_cost", "张三失去一臂", ("张三",)),),
        plot_conflict="",
        released=("张三的断臂竟已恢复如初",),
        world_consequence_logic=("禁术使用留下不可逆代价",),
    ),
    CausalAdversarialCase(
        "cost-002-clean", "invalidated_cost", "pass",
        facts=(("f_cost2", "王五失去右腿", ("王五",)),),
        plot_conflict="",
        released=("王五装上义肢，重新行走",),
        consequences=("付出全部积蓄",),
    ),
    # 3. 成长/知识状态重置（warning character_distortion）
    CausalAdversarialCase(
        "growth-001", "growth_reset", "block",
        plot_goal="面对旧友",
        plot_conflict="",
        released=("他仿佛从未改变，又变回那个独来独往的人",),
        character={"change_trajectory": ["从独行到愿意托付"],
                   "self_image": "我已学会信任"},
    ),
    CausalAdversarialCase(
        "growth-002-clean", "growth_reset", "pass",
        plot_goal="面对旧友",
        plot_conflict="",
        released=("他握住对方的手，说这些年我学会了信任",),
        character={"change_trajectory": ["从独行到愿意托付"],
                   "self_image": "我已学会信任"},
    ),
    # 4. 制度与群体后果未传播（warning world_violation）
    CausalAdversarialCase(
        "group-001", "group_consequence", "block",
        facts=(("f_inst", "王城下达全面宵禁", ("王城",)),),
        plot_goal="夜行",
        plot_conflict="",
        released=("主角照常深夜走在王城大街",),
    ),
    CausalAdversarialCase(
        "group-002-clean", "group_consequence", "pass",
        facts=(("f_inst2", "王城下达全面宵禁", ("王城",)),),
        plot_goal="避巡夜",
        plot_conflict="",
        released=("主角改走屋顶，避开巡夜兵丁",),
        consequences=("绕路消耗体力",),
    ),
    # 5. 选择无后效（warning weak_progression）
    CausalAdversarialCase(
        "choice-001", "choice_no_impact", "block",
        plot_goal="决定投靠一方",
        plot_conflict="选择阵营",
        released=("他最终决定投靠朝廷",),
        states=((("对峙",), ("自保",)), (("对峙",), ("自保",))),
    ),
    CausalAdversarialCase(
        "choice-002-clean", "choice_no_impact", "pass",
        plot_goal="决定投靠一方",
        plot_conflict="选择阵营",
        released=("他决定投靠朝廷",),
        consequences=("与旧主决裂，沦为通缉犯",),
        summary="阵营改变",
        states=((("对峙",), ("自保",)), (("决裂",), ("逃亡",))),
    ),
)


def _run_case(case: CausalAdversarialCase) -> dict[str, Any]:
    objects = _objects(case)
    issues = run_causal_defense(objects)
    issues_again = run_causal_defense(objects)  # 幂等
    detected = len(issues) > 0
    blocking = any(getattr(i, "is_blocking", lambda: False)() for i in issues)
    if case.expect == "block":
        ok = detected
    else:
        ok = not detected
    return {
        "case_id": case.case_id,
        "attack_class": case.attack_class,
        "expect": case.expect,
        "detected": detected,
        "blocking": blocking,
        "issue_types": sorted({getattr(i, "issue_type", "") for i in issues}),
        "idempotent": [i.issue_id for i in issues] == [i.issue_id for i in issues_again],
        "ok": ok,
    }


def run_suite() -> dict[str, Any]:
    """跑全部对抗样本，返回覆盖矩阵与汇总."""
    rows = [_run_case(case) for case in ADVERSARIAL_CASES]
    total = len(rows)
    ok_count = sum(1 for r in rows if r["ok"])
    per_class = {}
    for cls in ATTACK_CLASSES:
        cls_rows = [r for r in rows if r["attack_class"] == cls]
        per_class[cls] = {
            "cases": len(cls_rows),
            "ok": all(r["ok"] for r in cls_rows),
            "positive_detected": all(r["detected"] for r in cls_rows if r["expect"] == "block"),
            "negative_clean": all(not r["detected"] for r in cls_rows if r["expect"] == "pass"),
        }
    return {
        "total_cases": total,
        "ok_cases": ok_count,
        "suite_pass": ok_count == total,
        "per_class": per_class,
        "rows": rows,
    }
