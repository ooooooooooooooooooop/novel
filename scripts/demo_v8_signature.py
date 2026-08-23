"""v8 双平面签名验证器演示脚本（研究性代理，非生产资格）。

演示目标：
1. 构造 2 题材 × 2 作者、每作者 3 个 work_slot 的确定性可学习事件集；
2. 调用 ``validate_decision_signature_v2``，展示 v8 双平面扩展：
   - backoff="none"（与 v2 旧行为回归锁定）
   - backoff="partial_pool" + operating_coverage（selective coverage 平面）
3. 打印 statistical_state / full_coverage_deployment_state / coverage /
   selective_risk / aurc / c_at_1 / f_half_u / backoff_events。

用法：``.venv\\Scripts\\python.exe scripts\\demo_v8_signature.py``
"""

from __future__ import annotations

from src.object_state.authorkernel import VALUE_VOCAB
from src.object_state.authormodel_v3 import DecisionEventV2
from src.workflow_action.authormodel_v3 import validate_decision_signature_v2

TOPICS = ("urban", "fantasy")
AUTHORS = {"urban": ("a_urban_1", "a_urban_2"), "fantasy": ("a_fant_1", "a_fant_2")}
STAGES = ("setup", "payoff")
ACTOR_ROLES = ("protagonist", "antagonist")
SITUATIONS = [
    # (power_gap, reversibility, threat, dependence, info_uncertainty, loyalty_conflict)
    ("high", "low", "high", "low", "low", "none"),
    ("high", "high", "low", "high", "low", "low"),
    ("low", "low", "high", "high", "high", "none"),
    ("low", "high", "low", "low", "high", "high"),
    ("high", "low", "low", "high", "high", "low"),
    ("low", "high", "high", "low", "low", "high"),
]
# 每作者确定性策略：situation_index -> 首选动作（跨作品稳定 → L1WO 可学习）
STRATEGIES: dict[str, list[str]] = {
    "a_urban_1": ["direct_confront", "withhold", "seek_ally", "defer", "direct_confront", "compromise"],
    "a_urban_2": ["defer", "compromise", "withhold", "seek_ally", "withhold", "defer"],
    "a_fant_1": ["sacrifice", "seek_ally", "direct_confront", "withhold", "compromise", "direct_confront"],
    "a_fant_2": ["withhold", "defer", "compromise", "direct_confront", "seek_ally", "sacrifice"],
}
ACTION_POOL = ["direct_confront", "defer", "seek_ally", "sacrifice", "withhold", "compromise"]


def build_events() -> list[DecisionEventV2]:
    events: list[DecisionEventV2] = []
    for topic in TOPICS:
        for author in AUTHORS[topic]:
            strategy = STRATEGIES[author]
            for slot in range(1, 4):  # 3 个 work_slot（满足 3 work_slot 门槛）
                for stage in STAGES:
                    for role in ACTOR_ROLES:
                        for situation_index, situation in enumerate(SITUATIONS):
                            preferred = strategy[situation_index]
                            # 候选 = 完整动作池：同题材其他作者的首选必然落入候选集，
                            # 使 hard negative（其他作者预测该事件选择）全部可评估。
                            candidates = list(ACTION_POOL)
                            # 候选列表稳定哈希轮换：selected 位置覆盖 1/2/3 非恒首位
                            rotated = candidates[slot % 3 :] + candidates[: slot % 3]
                            events.append(
                                DecisionEventV2(
                                    author_id=author,
                                    work_slot=f"{author}-w{slot}",
                                    stage=stage,
                                    topic_tag=topic,
                                    actor_role=role,
                                    power_gap=situation[0],
                                    reversibility=situation[1],
                                    threat=situation[2],
                                    dependence=situation[3],
                                    info_uncertainty=situation[4],
                                    loyalty_conflict=situation[5],
                                    candidates=rotated,
                                    selected=preferred,
                                    rejected=[action for action in rotated if action != preferred],
                                    cost_label="tangible",
                                    protected_value_key=VALUE_VOCAB[0],
                                    evidence_anchor=f"anchor-{author}-w{slot}-{stage}-{role}-{situation_index}",
                                    confidence=0.90,
                                )
                            )
    return events


def _fmt(result) -> str:
    lines = [
        f"  state                       = {result.state}",
        f"  statistical_state           = {result.statistical_state}",
        f"  full_coverage_deployment    = {result.full_coverage_deployment_state}",
        f"  coverage                    = {result.coverage}",
        f"  selective_risk              = {result.selective_risk}",
        f"  aurc                        = {result.aurc}",
        f"  c_at_1                      = {result.c_at_1}",
        f"  f_half_u                    = {result.f_half_u}",
        f"  backoff_used                = {result.backoff_used}",
        f"  backoff_events              = {result.backoff_events}",
        f"  operating_coverage          = {result.operating_coverage}",
        f"  author_accuracy             = {result.author_accuracy:.4f}",
        f"  hard_negative_accuracy      = {result.hard_negative_accuracy:.4f}",
        f"  author_advantage            = {result.author_advantage:.4f}",
        f"  confidence_interval         = {result.confidence_interval}",
        f"  permutation_p_value         = {result.permutation_p_value}",
        f"  evaluated_event_count       = {result.evaluated_event_count}",
        f"  fold_count                  = {result.fold_count}",
        f"  invalid_reasons             = {result.invalid_reasons}",
        f"  warnings                    = {result.warnings}",
    ]
    return "\n".join(lines)


def main() -> None:
    events = build_events()
    print(f"事件总数：{len(events)}（{len(AUTHORS['urban']) + len(AUTHORS['fantasy'])} 作者 × 3 work_slot × 12 情境）\n")

    print("== run 1: backoff='none'（v2 兼容语义回归锁定）==")
    result_none = validate_decision_signature_v2(events, backoff="none")
    print(_fmt(result_none))
    print()

    print("== run 2: backoff='partial_pool', operating_coverage=0.90（v8 selective 平面）==")
    result_pool = validate_decision_signature_v2(
        events, backoff="partial_pool", operating_coverage=0.90
    )
    print(_fmt(result_pool))
    print()

    print("== run 3: 非法 backoff 值（API 校验，应抛 ValueError）==")
    try:
        validate_decision_signature_v2(events, backoff="illegal")
        print("  未抛异常（意外）")
    except ValueError as exc:
        print(f"  ValueError: {exc}")
    print()

    print("== run 4: 空事件集（应 INVALID，数值不回落 0.5）==")
    result_empty = validate_decision_signature_v2([], backoff="none")
    print(
        f"  state={result_empty.state} author_accuracy={result_empty.author_accuracy} "
        f"invalid_reasons={result_empty.invalid_reasons}"
    )


if __name__ == "__main__":
    main()
