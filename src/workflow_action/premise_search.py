"""A1 T4 — needs_premise 自动搜索：候选生成 prompt / 严格解析 / 确定性验证 / 帧投影.

流程：结构完成但仍有未兑现承诺（viability=needs_premise）时，一次 provider 调用
生成一批 PremiseCandidate；每个候选经 ``validate_premise_candidate`` 确定性验证
（义务必须命中活跃承诺 + 投影新非终止帧后重新进入 viability 必须回到 continue）；
至少一个通过 → 采用并投影新 active 帧，随后以新帧驱动下一章规划；
全部失败且预算耗尽 → ``premise_exhausted`` 终态（无 [WAITING]、无人工路径）。

生成 prompt 只要求候选内容；验证全部是纯代码，Provider 无法伪造通过。
"""

from __future__ import annotations

import json
from typing import Iterable

from src.object_state.premise_candidate import PremiseCandidate
from src.object_state.foreshadowgraph import ForeshadowEntry
from src.workflow_action.continuation_viability import analyze_continuation_viability
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.json_repair import parse_json


def build_premise_search_prompt(
    *,
    state_context: str,
    workspec_context: str,
    frame_context: dict | None,
    open_promises: Iterable[tuple[str, str]],
    contract_context: str = "",
    required_premise: str = "",
    count: int,
) -> str:
    """生成一批前提候选的 prompt（role=generation）。"""
    promises_lines = "\n".join(
        f"- {thread_id}: {content}" for thread_id, content in open_promises
    )
    premise_section = (
        f"\n【所需前提】\n{required_premise}\n" if required_premise else ""
    )
    contract_section = f"\n【读者契约】\n{contract_context}" if contract_context else ""
    return f"""你正在维护一部连载小说。当前结构已完成，但仍有未兑现的叙事承诺，
需要你提出新的阶段前提，把故事推进下去。这是纯创作决策，不涉及任何流程审批。

【当前状态】
{state_context}

【当前帧（已完成结构）】
{json.dumps(frame_context or {}, ensure_ascii=False, indent=2)}

【未兑现承诺（活跃线索）】
{promises_lines}
{premise_section}
{contract_section}

【作品约束】
{workspec_context}

【前提要求】
1. 新前提必须能推进至少一条上列未兑现承诺（obligations_to_old_promises 必须引用
   对应线索的 thread_id 或其内容）。
2. 必须引入新的外部冲突与新的阶段目标，且不得重新打开已闭合的情感弧
   （boundary_to_closed_arc 说明边界）。
3. 必须声明可产生的新状态变化（new_state_change），否则视为原地打转。
4. 必须满足读者契约（reader_contract_legal=true），并给出理由。
5. 生成 {count} 个互不相同的候选。

【输出格式】
严格输出 JSON（只输出 JSON，不要 markdown）：
{{
  "candidates": [
    {{
      "candidate_id": "premise-001",
      "new_external_conflict": "新外部冲突",
      "new_phase_goal": "新阶段目标",
      "boundary_to_closed_arc": "与已闭合情感弧的边界",
      "obligations_to_old_promises": ["thread_id_或_承诺内容", "..."],
      "new_state_change": "可产生的新状态变化",
      "reader_contract_legal": true,
      "reader_contract_reason": "为何满足读者契约"
    }}
  ]
}}
"""


def parse_premise_candidates(response: str) -> list[PremiseCandidate]:
    """严格解析前提候选；多余字段/缺失字段/形状错误一律拒绝（不宽容）。"""
    data = parse_json(response)
    if not isinstance(data, dict) or "candidates" not in data:
        raise ValueError("premise search response must be an object with candidates")
    candidates = data["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("premise search candidates must be a non-empty list")
    required = {
        "candidate_id",
        "new_external_conflict",
        "new_phase_goal",
        "boundary_to_closed_arc",
        "obligations_to_old_promises",
        "new_state_change",
        "reader_contract_legal",
        "reader_contract_reason",
    }
    parsed: list[PremiseCandidate] = []
    seen_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"premise candidate #{index} must be an object")
        extra = sorted(set(candidate) - required)
        if extra:
            raise ValueError(
                f"premise candidate #{index} has unexpected field(s): {', '.join(extra)}"
            )
        missing = sorted(required - set(candidate))
        if missing:
            raise ValueError(
                f"premise candidate #{index} missing field(s): {', '.join(missing)}"
            )
        obligations = candidate["obligations_to_old_promises"]
        if not isinstance(obligations, list) or not obligations:
            raise ValueError(f"premise candidate #{index} obligations must be a non-empty list")
        candidate_id = candidate["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError(f"premise candidate #{index} blank candidate_id")
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate premise candidate_id: {candidate_id}")
        seen_ids.add(candidate_id)
        parsed.append(
            PremiseCandidate(
                candidate_id=candidate_id,
                new_external_conflict=str(candidate["new_external_conflict"]),
                new_phase_goal=str(candidate["new_phase_goal"]),
                boundary_to_closed_arc=str(candidate["boundary_to_closed_arc"]),
                obligations_to_old_promises=tuple(str(o) for o in obligations),
                new_state_change=str(candidate["new_state_change"]),
                reader_contract_legal=bool(candidate["reader_contract_legal"]),
                reader_contract_reason=str(candidate["reader_contract_reason"]),
            )
        )
    return parsed


def match_open_promise_threads(
    obligations: Iterable[str], open_threads: Iterable[ForeshadowEntry]
) -> list[str]:
    """把义务映射到活跃承诺的 thread_id（thread_id 精确 或 内容互含）。"""
    open_list = list(open_threads)
    matched: list[str] = []
    for obligation in obligations:
        for thread in open_list:
            if obligation == thread.thread_id:
                matched.append(thread.thread_id)
                break
            if thread.content and (obligation in thread.content or thread.content in obligation):
                matched.append(thread.thread_id)
                break
    return matched


def project_premise_frames(
    candidate: PremiseCandidate,
    frames: list[dict],
    *,
    next_chapter_number: int,
    matched_thread_ids: Iterable[str] = (),
) -> list[dict]:
    """把候选投影成一条新的 active 帧链（book → arc → chapter → scene）。

    新 arc 用候选的阶段目标作 purpose、命中义务作 active_thread_ids、非终止节点
    ``rising_action`` 作 scene formula——投影后 get_cursor 指向新 scene，
    viability 回到 continue。旧帧除 book 外全部降为 planned，保证帧校验
    （每级唯一 active + cursor 链）通过。
    """
    projected = [dict(frame) for frame in frames]
    book = next((frame for frame in projected if frame["level"] == "book"), None)
    if book is None:
        raise ValueError("project_premise_frames requires an existing book frame")
    book_id: str = book["frame_id"]
    for frame in projected:
        if frame["level"] != "book" and frame["status"] == "active":
            frame["status"] = "planned"

    arc_number = _next_index(projected, "arc", "arc")
    chapter_number_internal = _next_index(projected, "chapter", "chapter")
    scene_number = _next_index(projected, "scene", "scene")
    arc_id = f"arc_{arc_number:03d}"
    chapter_id = f"chapter_{chapter_number_internal:03d}"
    scene_id = f"scene_{scene_number:03d}"
    arc_order = _next_order(projected, "arc")

    thread_ids = [thread_id for thread_id in matched_thread_ids]
    projected.append(
        {
            "frame_id": arc_id,
            "level": "arc",
            "title": "New phase",
            "purpose": candidate.new_phase_goal,
            "position": "full",
            "status": "active",
            "parent_id": book_id,
            "order_index": arc_order,
            "active_thread_ids": thread_ids,
        }
    )
    projected.append(
        {
            "frame_id": chapter_id,
            "level": "chapter",
            "title": f"Chapter {next_chapter_number}",
            "purpose": "Premise-driven chapter progression",
            "position": "full",
            "status": "active",
            "parent_id": arc_id,
            "order_index": 0,
        }
    )
    projected.append(
        {
            "frame_id": scene_id,
            "level": "scene",
            "title": "Premise scene",
            "purpose": candidate.new_external_conflict,
            "position": "flexible",
            "status": "active",
            "parent_id": chapter_id,
            "order_index": 0,
            "formula_node": "rising_action",
            "target_plotunit_ids": [],
            "active_thread_ids": [],
        }
    )
    return projected


def validate_premise_candidate(
    candidate: PremiseCandidate,
    *,
    foreshadows,
    frame_context: dict | None,
    workspec,
    contract,
    frames: list[dict],
    next_chapter_number: int,
    recent_chapter_count: int = 0,
) -> tuple[bool, str]:
    """确定性验证：候选能否合法地把故事推进到 continue。

    通过 = 内容非空 + 读者契约合法 + 义务命中 ≥1 条活跃承诺 + 投影新帧后
    ``analyze_continuation_viability`` 回到 continue。
    """
    checks: list[str] = []
    if not candidate.new_external_conflict or not candidate.new_phase_goal:
        checks.append("冲突/阶段目标为空")
    if not candidate.boundary_to_closed_arc:
        checks.append("未声明与已闭合弧的边界")
    if candidate.new_external_conflict == candidate.new_phase_goal:
        checks.append("外部冲突与阶段目标重复")
    if not candidate.reader_contract_legal:
        checks.append("不满足读者契约")
    if not candidate.reader_contract_reason:
        checks.append("读者契约理由为空")
    if checks:
        return False, "；".join(checks)

    open_threads = foreshadows.get_active() if foreshadows is not None else []
    if not open_threads:
        return False, "无可兑现的活跃承诺——应走 stop 而非新前提"
    matched = match_open_promise_threads(
        candidate.obligations_to_old_promises, open_threads
    )
    if not matched:
        return (
            False,
            "义务未命中任何活跃承诺（thread_id 或内容）",
        )

    try:
        projected = project_premise_frames(
            candidate,
            frames,
            next_chapter_number=next_chapter_number,
            matched_thread_ids=matched,
        )
    except ValueError as exc:
        return False, f"帧投影失败: {exc}"
    frame_unit = NarrativeFrameUnit()
    issues = frame_unit.validate_frame_state(projected)
    blocking = [issue for issue in issues if issue["severity"] == "blocking"]
    if blocking:
        return False, "投影帧校验失败: " + "; ".join(
            f"{issue['issue_type']}: {issue['description']}" for issue in blocking
        )
    cursor = frame_unit.get_cursor(projected)
    projected_context = frame_unit.build_continue_context(projected, cursor)
    viability = analyze_continuation_viability(
        narrative_state=None,
        foreshadows=foreshadows,
        frame_context=projected_context,
        workspec=workspec,
        contract=contract,
        recent_chapter_count=recent_chapter_count,
    )
    if viability.verdict != "continue":
        return (
            False,
            f"投影后 viability={viability.verdict}（非 continue），候选不能推进故事",
        )
    return True, ""


def _next_index(frames: list[dict], level: str, prefix: str) -> int:
    values: list[int] = []
    for frame in frames:
        if frame.get("level") != level:
            continue
        frame_id = frame.get("frame_id", "")
        if frame_id.startswith(prefix + "_"):
            suffix = frame_id[len(prefix) + 1:]
            if suffix.isdigit():
                values.append(int(suffix))
    return (max(values) + 1) if values else 1


def _next_order(frames: list[dict], level: str) -> int:
    values = [
        frame.get("order_index", 0)
        for frame in frames
        if frame.get("level") == level and isinstance(frame.get("order_index"), int)
    ]
    return (max(values) + 1) if values else 0


__all__ = [
    "build_premise_search_prompt",
    "match_open_promise_threads",
    "parse_premise_candidates",
    "validate_premise_candidate",
    "project_premise_frames",
]
