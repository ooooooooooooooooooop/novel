"""State V2 production closed loop — 最小接入层.

把此前仅由 research probe 调用的选择/维护链接入 production continuation：
pre-state → candidate_pool → narrative_selector → suppressor →
context_firewall/ChapterPacket → (writer) → accepted prose →
state_maintainer 确定性更新 → state_validation → committed post-state。

纪律（doc 73126）：
- legacy 路径默认不变；state_v2 是显式 mode。
- state delta 只能来自 accepted prose 的 PlotUnit/NarrativeState（计划不是事实）。
- seed 必须逐条带 provenance 来源（正文/Rebuild/committed orchestration/事实库），
  不允许未来大纲、期望答案、作者隐藏计划、未写入正文的 intended delta。
- 任一失败 fail closed，不静默 fallback 到 legacy。
- 零新增模型调用：维护只用 update_from_plotunit 确定性层；LLM 质性维护契约不启用。
"""

import hashlib
import json
from pathlib import Path
from typing import Optional

from src.object_state.statemodel import StateModel
from src.workflow_action.candidate_pool import build_candidate_pool
from src.workflow_action.context_firewall import ChapterPacket, build_chapter_packet
from src.workflow_action.narrative_selector import select_candidates, suppress_overreach
from src.workflow_action.state_maintainer import update_from_plotunit
from src.workflow_action import state_validation

STATE_V2_STATE_FILE = "state_v2_model.json"
STATE_V2_TRACE_FILE = "state_v2_trace.json"

ALLOWED_SEED_SOURCES = frozenset({
    "prose",                    # 已有正文/history
    "rebuild",                  # 当前 Rebuild 结果
    "committed_orchestration",  # 当前 committed orchestration state
    "fact_ledger",              # 明确已有的作品事实库
})


class StateV2Error(ValueError):
    """state_v2 模式下的启动/提交失败（fail closed，不回退 legacy）."""


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state(workspace_dir: Path) -> Optional[StateModel]:
    """读取工作区已提交的 State V2 post-state；不存在返回 None."""
    p = Path(workspace_dir) / STATE_V2_STATE_FILE
    if not p.exists():
        return None
    return StateModel.model_validate(json.loads(p.read_text(encoding="utf-8")))


def save_state(workspace_dir: Path, sm: StateModel) -> Path:
    p = Path(workspace_dir) / STATE_V2_STATE_FILE
    p.write_text(sm.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return p


def _seed_entries(sm: StateModel) -> dict[str, str]:
    """seed 里所有需 provenance 的条目：thread_id / fact / knowledge / intent / strategic entity."""
    out = {}
    for t in sm.threads:
        out[f"thread:{t.thread_id}"] = t.label
    for f in sm.facts:
        out[f"fact:{f[:40]}"] = f
    for k in sm.knowledge:
        out[f"knowledge:{k.holder}:{k.fact_ref[:30]}"] = k.fact_ref
    for i in sm.intents:
        out[f"intent:{i.entity}"] = i.intent
    for s in sm.strategic:
        out[f"strategic:{s.entity}"] = s.entity
    for o in sm.offscreen:
        out[f"offscreen:{o.entity}"] = o.entity
    return out


def validate_seed_doc(doc: dict) -> StateModel:
    """校验 state_v2 seed 文档并返回 StateModel.

    要求：{"state_model": {...}, "provenance_map": {"<entry_key>": {"source": ..., "ref": ...}}}
    每个 entry 必须在 provenance_map 里有记录，source ∈ ALLOWED_SEED_SOURCES，ref 非空。
    """
    if not isinstance(doc, dict) or "state_model" not in doc or "provenance_map" not in doc:
        raise StateV2Error("seed must contain 'state_model' and 'provenance_map'")
    try:
        sm = StateModel.model_validate(doc["state_model"])
    except Exception as exc:
        raise StateV2Error(f"seed state_model invalid: {exc}") from exc
    pmap = doc["provenance_map"]
    if not isinstance(pmap, dict):
        raise StateV2Error("provenance_map must be an object")
    missing, bad = [], []
    for key in _seed_entries(sm):
        entry = pmap.get(key)
        if not entry:
            missing.append(key)
            continue
        if entry.get("source") not in ALLOWED_SEED_SOURCES or not str(entry.get("ref") or "").strip():
            bad.append(key)
    if missing:
        raise StateV2Error(f"seed entries missing provenance: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    if bad:
        raise StateV2Error(f"seed provenance source/ref illegal: {bad[:5]}{'...' if len(bad) > 5 else ''}")
    return sm


def run_selection(
    sm: StateModel,
    chapter_number: int,
    *,
    work_preferences: Optional[list[str]] = None,
    reader_knowledge: Optional[set[str]] = None,
    max_selected: Optional[int] = None,
) -> tuple[ChapterPacket, dict]:
    """candidate_pool → selector → suppressor → chapter packet；返回 (packet, trace)."""
    pool = build_candidate_pool(sm, reader_knowledge=reader_knowledge)
    selection = suppress_overreach(select_candidates(pool, sm, work_preferences, max_selected=max_selected))
    packet = build_chapter_packet(selection, chapter=chapter_number)
    trace = {
        "candidate_ids": [c.candidate_id for c in pool.candidates],
        "excluded_alive": list(pool.excluded_alive),
        "selected_ids": selection.ids("selected"),
        "background_ids": selection.ids("background"),
        "dormant_ids": selection.ids("dormant"),
        "suppressed": {c.candidate_id: c.non_entry_impact for c in selection.rejected},
        "chapter_packet_sha256": sha_text(packet.render()),
    }
    return packet, trace


def _anchor_grounded(anchor: str, prose_text: str, chapter_number: int) -> bool:
    """evidence_anchor 是否能定位到最终 accepted prose（确定性、可重算）.

    规则：空白规范化后 anchor 是 prose 的子串；或 anchor 显式引用本章
    （"chapter_<n>" / "第<n>章"）。否则拒绝。
    """
    norm_anchor = "".join(str(anchor or "").split())
    if not norm_anchor:
        return False
    norm_prose = "".join((prose_text or "").split())
    if norm_anchor in norm_prose:
        return True
    return str(anchor).strip() in (f"chapter_{chapter_number}", f"第{chapter_number}章")


def commit_post_state(
    sm: StateModel,
    plotunit,
    new_state,
    chapter_number: int,
    prose_text: str,
    thread_transitions: list | None = None,
) -> tuple[StateModel, dict]:
    """accepted prose 之后的确定性状态更新 + 验证；返回 (post_state, trace_additions).

    evidence grounding：transition 的 evidence_anchor 必须能定位到 accepted
    prose，否则跳过（declared but not grounded ≠ closed）。
    factual lifecycle transition 由 post-prose Review 阶段声明（唯一能逐字
    引用最终正文的阶段），经本函数 grounding 后才进入 writeback。
    """
    before = sm.model_dump_json()
    closed_before = {t.thread_id for t in sm.threads if t.lifecycle.value == "closed"}
    ids_before = {t.thread_id for t in sm.threads}

    # grounding pre-filter：只让 evidence 落地的 transition 进入 update
    declared_tr = list(thread_transitions or [])
    grounded, skipped_reasons = [], {}
    for i, tr in enumerate(declared_tr):
        tid = tr.thread_id if hasattr(tr, "thread_id") else tr.get("thread_id")
        anchor = tr.evidence_anchor if hasattr(tr, "evidence_anchor") else tr.get("evidence_anchor", "")
        if _anchor_grounded(anchor, prose_text, chapter_number):
            grounded.append(tr)
        else:
            skipped_reasons[f"decl#{i}:{tid or 'OPEN'}"] = "evidence_not_grounded"

    sm = update_from_plotunit(sm, plotunit, new_state, chapter_number,
                              thread_transitions=grounded)
    released = list(getattr(plotunit, "released_information", None) or [])
    validation = {
        "strategy_horizon": state_validation.strategy_horizon_score(sm),
        "offscreen_survival": state_validation.offscreen_survival_check(sm),
        "world_background": state_validation.world_background_check(sm),
    }
    thread_keywords = {t.label: [t.label] for t in sm.threads if t.label}
    if thread_keywords:
        validation["silence_discipline"] = state_validation.silence_discipline(prose_text or "", thread_keywords)
    transitions = declared_tr
    closed_now = [t.thread_id for t in sm.threads
                  if t.lifecycle.value == "closed" and t.thread_id not in closed_before]
    opened_now = [t.thread_id for t in sm.threads if t.thread_id not in ids_before]
    declared = [
        {"action": (tr.action if hasattr(tr, "action") else tr.get("action", "CLOSE")),
         "thread_id": (tr.thread_id if hasattr(tr, "thread_id") else tr.get("thread_id")),
         "thread_label": (tr.thread_label if hasattr(tr, "thread_label")
                          else tr.get("thread_label", ""))}
        for tr in transitions]
    additions = {
        "proposed_state_delta": {
            "released_information": released,
            "new_state_ref": getattr(new_state, "state_id", None),
        },
        "thread_transitions": {
            "declared": declared,
            "evidence_verified": [
                d for i, d in enumerate(declared)
                if not any(k.startswith(f"decl#{i}:") for k in skipped_reasons)],
            "opened_now": opened_now,
            "closed_now": closed_now,
            "skipped": [
                d["thread_id"] or d["thread_label"]
                for i, d in enumerate(declared)
                if (any(k.startswith(f"decl#{i}:") for k in skipped_reasons)
                    or (d["action"] == "CLOSE" and d["thread_id"] not in closed_now))],
            "skipped_reason": {**skipped_reasons,
                               **{d["thread_id"]: "thread_missing_or_already_closed"
                                  for d in declared
                                  if d["action"] == "CLOSE"
                                  and d["thread_id"]
                                  and d["thread_id"] not in closed_now
                                  and not any(k.endswith(":" + d["thread_id"])
                                              for k in skipped_reasons)}},
        },
        "validation": validation,
        "pivot_actions": [],
        "post_state_changed": sm.model_dump_json() != before,
    }
    return sm, additions


def append_trace(workspace_dir: Path, record: dict) -> Path:
    """向 state_v2_trace.json 追加一条 per-chapter 结构化 trace."""
    p = Path(workspace_dir) / STATE_V2_TRACE_FILE
    entries = []
    if p.exists():
        entries = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise StateV2Error(f"{STATE_V2_TRACE_FILE} corrupted: not a list")
    entries.append(record)
    p.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
