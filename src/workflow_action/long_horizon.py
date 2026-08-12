"""LongHorizonUnit — 长程摘要重建与对账（design §9 / T7.1–T7.2）.

在 1/3/5/10/20/30 章检查点，从**真实已提交正文**重建结构/人物/承诺摘要，并与滚动
摘要对账；旧摘要不能无限自我继承——每次检查点后滚动摘要以正文重建为准刷新，未在
正文落地的开放承诺成为漂移证据（可被门禁阻断）。

- `summarize_prose`：纯代码确定性重建（角色标签提及 / 开放承诺引用 / 结构节点）；
- `build_rolling_from_plan`：从计划/状态线索构造滚动摘要（系统信念）；
- `detect_drift`：滚动信念 vs 正文现实的差距（承诺轴打分、人物轴记录）；
- `evaluate_long_horizon_checkpoint`：单检查点判定（pass / block）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.object_state.longhorizon import (
    LongHorizonCheckpoint,
    ProseSummary,
    RollingLongHorizonSummary,
)

DEFAULT_DRIFT_THRESHOLD = 0.5
"""承诺漂移默认阈值：开放承诺中 >50% 在全文从未被提及 → block（可被门禁参数覆盖）."""

_ROLLING_SUMMARY_FILE = "gates/rolling_summary.json"


def _iter_occurrences(corpus: str, needle: str) -> int:
    return corpus.count(needle)


def summarize_prose(
    chapters: Iterable[str],
    labels: dict[str, list[str]] | None = None,
    promise_tokens: dict[str, str] | None = None,
    structural_nodes: list[str] | None = None,
) -> ProseSummary:
    """从正文重建摘要：统计注册角色/开放承诺的提及次数 + 结构节点序列（零 LLM）."""
    corpus = "\n".join(chapters or [])
    character_mentions: dict[str, int] = {}
    for label, tokens in (labels or {}).items():
        count = sum(_iter_occurrences(corpus, t) for t in tokens if t)
        if count > 0:
            character_mentions[label] = count
    promise_mentions: dict[str, int] = {}
    for thread_id, ref_text in (promise_tokens or {}).items():
        if not ref_text:
            continue
        count = _iter_occurrences(corpus, ref_text)
        if count > 0:
            promise_mentions[thread_id] = count
    return ProseSummary(
        chapter_count=len(list(chapters or [])),
        character_mentions=character_mentions,
        promise_mentions=promise_mentions,
        structural_nodes=list(structural_nodes or []),
    )


def build_rolling_from_plan(
    open_promises: dict[str, str],
    active_characters: Iterable[str] | None = None,
    structural_node: str = "",
) -> RollingLongHorizonSummary:
    """从计划/状态线索构造滚动摘要（系统信念，可能与正文现实不符）.

    - open_promises: {thread_id: reference_text}（ForeshadowGraph 开放承诺）；
    - active_characters: 计划输出状态中的活跃角色 id；
    - structural_node: 当前结构节点标签（如 opening/rising_action）。
    信念以 0 计数占位，检查点对账时与正文提及对照。
    """
    promise_mentions = {tid: 0 for tid in open_promises}
    character_mentions = {cid: 0 for cid in (active_characters or [])}
    return RollingLongHorizonSummary(
        last_checkpoint=0,
        summary=ProseSummary(
            chapter_count=0,
            character_mentions=character_mentions,
            promise_mentions=promise_mentions,
            structural_nodes=[structural_node] if structural_node else [],
        ),
    )


def detect_drift(
    rebuilt: ProseSummary,
    rolling: RollingLongHorizonSummary,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> dict:
    """滚动信念 vs 正文现实：承诺轴打分，人物轴记录为证据.

    - stale_promises: 滚动认为开放、但全文提及次数为 0 的承诺；
    - stale_characters: 滚动认为活跃、但全文提及次数为 0 的角色（证据，不参与打分）；
    - drift_score: stale_promises / max(1, 滚动承诺数)；
    - blocking: drift_score > drift_threshold。
    """
    belief_promises = rolling.summary.promise_mentions
    belief_characters = rolling.summary.character_mentions
    stale_promises = sorted(
        tid for tid in belief_promises if rebuilt.promise_mentions.get(tid, 0) == 0
    )
    stale_characters = sorted(
        cid for cid in belief_characters if rebuilt.character_mentions.get(cid, 0) == 0
    )
    drift_score = len(stale_promises) / max(1, len(belief_promises))
    return {
        "drift_score": round(drift_score, 4),
        "stale_promises": stale_promises,
        "stale_characters": stale_characters,
        "blocking": drift_score > drift_threshold,
    }


def reconcile(
    rolling: RollingLongHorizonSummary,
    rebuilt: ProseSummary,
    checkpoint: int,
    *,
    open_promises: dict[str, str] | None = None,
    active_characters: Iterable[str] | None = None,
) -> RollingLongHorizonSummary:
    """以正文重建为准刷新滚动摘要，叠加此刻仍开放的承诺（落地提及数或 0 占位）.

    旧摘要不能无限自我继承：滚动摘要只追踪「此刻仍开放的承诺」，已关闭的承诺
    （open_promises 之外）自然消失，不被继承。
    """
    merged_promises: dict[str, int] = {
        tid: rebuilt.promise_mentions.get(tid, 0) for tid in (open_promises or {})
    }
    merged_chars = dict(rebuilt.character_mentions)
    for cid in (active_characters or []):
        merged_chars.setdefault(cid, 0)
    return RollingLongHorizonSummary(
        last_checkpoint=checkpoint,
        summary=ProseSummary(
            chapter_count=rebuilt.chapter_count,
            character_mentions=merged_chars,
            promise_mentions=merged_promises,
            structural_nodes=rebuilt.structural_nodes,
        ),
    )


def evaluate_long_horizon_checkpoint(
    checkpoint: int,
    chapters: Iterable[str],
    rolling: RollingLongHorizonSummary | None,
    *,
    labels: dict[str, list[str]] | None = None,
    promise_tokens: dict[str, str] | None = None,
    structural_nodes: list[str] | None = None,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
) -> LongHorizonCheckpoint:
    """单检查点长程对账：正文重建 → 与滚动摘要对账 → pass/block."""
    rebuilt = summarize_prose(
        chapters, labels=labels, promise_tokens=promise_tokens,
        structural_nodes=structural_nodes,
    )
    if rolling is None:
        return LongHorizonCheckpoint(
            checkpoint=checkpoint,
            route="pass",
            drift_score=0.0,
            drift_threshold=drift_threshold,
            stale_promises=[],
            stale_characters=[],
            rebuilt_chapter_count=rebuilt.chapter_count,
            rolling_chapter_count=0,
            reason="first checkpoint; no rolling baseline yet",
        )
    drift = detect_drift(rebuilt, rolling, drift_threshold)
    if drift["blocking"]:
        return LongHorizonCheckpoint(
            checkpoint=checkpoint,
            route="block",
            drift_score=drift["drift_score"],
            drift_threshold=drift_threshold,
            stale_promises=drift["stale_promises"],
            stale_characters=drift["stale_characters"],
            rebuilt_chapter_count=rebuilt.chapter_count,
            rolling_chapter_count=rolling.summary.chapter_count,
            reason=(
                f"long-horizon drift at checkpoint {checkpoint}: open promises "
                f"never grounded in prose: {drift['stale_promises']} "
                f"(drift_score={drift['drift_score']} > {drift_threshold})"
            ),
        )
    return LongHorizonCheckpoint(
        checkpoint=checkpoint,
        route="pass",
        drift_score=drift["drift_score"],
        drift_threshold=drift_threshold,
        stale_promises=drift["stale_promises"],
        stale_characters=drift["stale_characters"],
        rebuilt_chapter_count=rebuilt.chapter_count,
        rolling_chapter_count=rolling.summary.chapter_count,
        reason=(
            f"checkpoint {checkpoint} reconciled: prose-rebuilt summary "
            f"({rebuilt.chapter_count} chapters) matches rolling belief"
        ),
    )


def load_rolling_summary(run_dir: Path) -> RollingLongHorizonSummary | None:
    """从 run 目录载入持久化滚动摘要；缺失返回 None（首个检查点）."""
    path = Path(run_dir) / _ROLLING_SUMMARY_FILE
    if not path.is_file():
        return None
    return RollingLongHorizonSummary.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def save_rolling_summary(run_dir: Path, rolling: RollingLongHorizonSummary) -> Path:
    """持久化滚动摘要到 run 目录 gates/rolling_summary.json."""
    path = Path(run_dir) / _ROLLING_SUMMARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        rolling.model_dump_json(indent=2), encoding="utf-8"
    )
    return path
