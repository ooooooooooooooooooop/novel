"""A1 T6 — 帕累托前沿 + 匿名 A/B 换位选择（design §7；tasks.md T6）。

T6.2/T6.3：对帕累托前沿候选执行匿名 A/B 与 B/A 成对比较——评审 prompt 只含两段
无标识正文（候选甲/候选乙），**不含**候选 id / 预承诺 id / 计划标签 / 版本号 /
正文哈希 / 生成模型身份（reward hacking 与同模型自偏好的隔离面）。每对同时跑
A/B 与 B/A 两轮换位；两轮命名同一正文 → 位置一致（position-consistent）。

T6.4：``pareto_frontier`` 做软轴帕累托前沿——候选 X 支配 Y ⟺ 所有软轴 X≥Y 且
至少一轴 X>Y；非支配候选构成前沿。硬轴违例已在前一阶段淘汰，不能进入前沿。

T6.5：``selection_tournament`` 淘汰赛——逐对比较（每对 A/B + B/A），胜者前进；
位置不一致时执行判别轮（至多 ``max_rounds``），仍不一致即该对双方淘汰；
无法收敛到唯一稳定胜者 → 返回 None → 运行层 quality_exhausted（不转人工）。
"""

from __future__ import annotations

import json
from typing import Callable, NamedTuple

# 匿名换位评审的严格输出：preferred ∈ {A, B, no_difference}。
PairPreference = str  # "A" | "B" | "no_difference"


class PairTournamentResult(NamedTuple):
    """淘汰赛结果：稳定胜者 + 逐对记录 + 位置一致率."""

    winner: str | None
    pairs: list[dict]
    position_consistency_rate: float


def pareto_frontier(
    candidate_ids: list[str],
    axis_scores: dict[str, dict[str, int]],
) -> list[str]:
    """软轴帕累托前沿：返回非支配候选（输入顺序，确定性）.

    X 支配 Y ⟺ 对每个轴 score_X ≥ score_Y 且至少一个轴 score_X > score_Y。
    缺失轴按 0 计；空分数 → 无支配，全部入选。
    """
    ids = list(candidate_ids)
    frontier: list[str] = []
    for index, candidate in enumerate(ids):
        dominated = False
        for other in ids:
            if other == candidate:
                continue
            if _dominates(axis_scores.get(other, {}), axis_scores.get(candidate, {})):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return frontier


def _dominates(a: dict[str, int], b: dict[str, int]) -> bool:
    axes = set(a) | set(b)
    strictly_better = False
    for axis in axes:
        if a.get(axis, 0) < b.get(axis, 0):
            return False
        if a.get(axis, 0) > b.get(axis, 0):
            strictly_better = True
    return strictly_better


def build_anonymous_pair_prompt(
    prose_a: str,
    prose_b: str,
    *,
    role: str = "reader_judge",
    reader_contract_context: str = "",
) -> str:
    """匿名 A/B 换位评审 prompt：只含两段无标识正文与评审要求.

    上下文隔离（T5.6/T6.6）：绝不写入候选 id / 预承诺 id / 计划标签 / 版本号 /
    正文哈希 / 生成参数 / 生成模型身份——评审无法通过任何旁证识别候选来迎合
    （reward hacking 隔离），也无法按「自己生成的更熟悉」自偏好（同模型自偏好）。
    """
    role_guide = {
        "fact_judge": "你负责【事实】轴：正文与可信事实的一致性、确定性是否站得住。",
        "character_judge": "你负责【人物】轴：角色行为是否符合其驱动力与连续性。",
        "reader_judge": "你负责【读者体验】轴：推进、阅读摩擦、契约、语言辨识度、建设性歧义。",
    }.get(role, "你负责综合判断两段正文的质量。")
    contract_section = (
        f"\n【读者契约】\n{reader_contract_context}" if reader_contract_context else ""
    )
    return f"""【匿名换位评审】
你是一位匿名换位评审。下面两段正文来自同一个剧情点的两版候选，
请忽略任何与你无关的细节，只比较**正文本身**在 {role_guide}上的优劣。

【候选甲（匿名）】
{prose_a}

【候选乙（匿名）】
{prose_b}{contract_section}

【评审要求】
1. 只比较两段正文的内容质量，不要猜它们的来源、作者或生成方式。
2. 若一段明确更好，返回它；若各有长短难以取舍，返回 no_difference。
3. 必须给出简短 rationale。

【输出格式】严格 JSON：
{{
  "preferred": "A",
  "rationale": "…"
}}

注意：preferred 只能是 "A"（候选甲）或 "B"（候选乙）或 "no_difference"。
"""


def parse_anonymous_pair_response(response: str, pair_id: str) -> PairPreference:
    """严格解析换位评审响应 → "A" / "B" / "no_difference".

    Raises:
        ValueError: 非 JSON / 非对象 / 多余字段 / 缺 preferred / preferred 非法
            / rationale 空白 —— 运行层记为 schema 错误 → execution_failed。
    """
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError(f"pair {pair_id}: response must be a JSON object")
    required = {"preferred", "rationale"}
    missing = sorted(required - set(data))
    extra = sorted(set(data) - required)
    if missing or extra:
        raise ValueError(
            f"pair {pair_id}: missing field(s) {missing} and/or extra field(s) {extra}"
        )
    preferred = data["preferred"]
    if preferred not in ("A", "B", "no_difference"):
        raise ValueError(f"pair {pair_id}: invalid preferred value {preferred!r}")
    rationale = data["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError(f"pair {pair_id}: rationale must be non-blank")
    return preferred


def resolve_pair(
    pref_ab: PairPreference,
    pref_ba: PairPreference,
    candidate_x: str,
    candidate_y: str,
) -> tuple[str | None, bool, str]:
    """对同一对正文的两轮换位判断求位置一致性.

    - A/B 轮：候选甲=x、候选乙=y。
    - B/A 轮：候选甲=y、候选乙=x（同对正文，顺序互换）。

    位置一致 ⟺ 两轮命名同一正文为胜者（且都不是 no_difference）。

    Returns:
        (winner_candidate | None, position_consistent, disagreement)
    """
    winner_ab = (
        candidate_x if pref_ab == "A" else candidate_y if pref_ab == "B" else None
    )
    winner_ba = (
        candidate_y if pref_ba == "A" else candidate_x if pref_ba == "B" else None
    )
    disagreement = f"A/B→{pref_ab}, B/A→{pref_ba}"
    if winner_ab is not None and winner_ab == winner_ba:
        return winner_ab, True, disagreement
    return None, False, disagreement


def selection_tournament(
    frontier: list[str],
    judge_pair: Callable[[str, str], tuple[PairPreference, PairPreference]],
    *,
    max_rounds: int,
) -> PairTournamentResult:
    """淘汰赛：逐对 A/B+B/A，胜者前进；位置不一致执行判别轮；仍不一致该对淘汰.

    Args:
        frontier: 帕累托前沿候选 id（顺序确定）。
        judge_pair: (x, y) → (pref_ab, pref_ba)，由运行层以匿名 prompt 驱动两次
            provider 调用（A/B 与 B/A）。
        max_rounds: 判别轮上限（策略冻结）。

    Returns:
        winner（唯一幸存者，无则 None）+ 逐对记录 + 位置一致率。
    """
    pool = list(frontier)
    pair_records: list[dict] = []
    pair_number = 0
    while len(pool) >= 2:
        pair_number += 1
        x, y = pool[0], pool[1]
        pref_ab, pref_ba = judge_pair(x, y)
        winner, consistent, disagreement = resolve_pair(pref_ab, pref_ba, x, y)
        rounds = 1
        while not consistent and rounds < max_rounds:
            rounds += 1
            pref_ab, pref_ba = judge_pair(x, y)
            winner, consistent, disagreement = resolve_pair(pref_ab, pref_ba, x, y)
        pair_records.append(
            {
                "pair_id": f"pair_{pair_number:04d}",
                "candidates": [x, y],
                "pref_ab": pref_ab,
                "pref_ba": pref_ba,
                "winner": winner,
                "position_consistent": consistent,
                "discriminator_rounds": rounds,
                "disagreement": disagreement,
            }
        )
        if not consistent:
            # 仍不稳定 → 该对双方淘汰（无稳定胜者可由该对产生）。
            pool = pool[2:]
            continue
        pool = [winner, *pool[2:]]
    rate = (
        sum(1 for record in pair_records if record["position_consistent"])
        / len(pair_records)
        if pair_records
        else 1.0
    )
    winner = pool[0] if len(pool) == 1 else None
    return PairTournamentResult(winner=winner, pairs=pair_records, position_consistency_rate=rate)
