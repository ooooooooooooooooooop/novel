"""状态检索工作流 — 以当前 NarrativeState 检索 FactLedger/ForeshadowGraph top-k 并渲染注入文本.

对齐 style.py 的 load_style_context：静默降级 loader，空 query / 空语料 / 全零分返回 ""。
检索层是 spec/先验消费：只读现有状态对象字段，不进入状态机、不进 serialization.py。
"""

from pathlib import Path

from src.boundary_control.retrieval_metrics import (
    DEFAULT_TOP_K,
    BOOST_WEIGHT,
    RetrievalDoc,
    render_retrieval_context,
    retrieve,
)
from src.object_state import FactLedger, ForeshadowGraph, NarrativeState


def textualize_narrative_state(state: NarrativeState) -> str:
    """把当前叙事状态渲染成检索 query 文本.

    排除 state_id / current_time（无检索价值）与 public_information（与事实账本冗余）。
    """
    parts = [
        state.current_situation,
        state.current_location,
        state.primary_goal or "",
        state.emotional_temperature or "",
        *state.active_characters,
        *state.active_conflicts,
        *state.current_goals,
        *state.active_suspense_items,
        *state.hidden_information,
    ]
    return " ".join(part for part in parts if part)


def textualize_fact(entry) -> str:
    """FactEntry → 检索文本（statement + 类型 + 涉及实体）."""
    return f"{entry.statement} {entry.fact_type} {' '.join(entry.involved_entities)}"


def textualize_foreshadow(entry) -> str:
    """ForeshadowEntry → 检索文本（内容 + 埋设点 + 预期回收 + 关联角色）."""
    return (
        f"{entry.content} {entry.setup_point} {entry.expected_payoff} "
        f"{' '.join(entry.linked_characters)}"
    )


class RetrievalUnit:
    """以当前状态为 query 从事实/伏笔语料检索 top-k 并渲染注入文本."""

    def __init__(self, top_k: int = DEFAULT_TOP_K) -> None:
        self.top_k = top_k

    def build_retrieval_context(
        self,
        state: NarrativeState,
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
    ) -> str:
        """检索并渲染注入文本. 空 query / 空语料 / 全零分 → 返回 ""（字节不变降级）."""
        docs = self._build_documents(facts, foreshadows, state)
        if not docs:
            return ""
        query_text = textualize_narrative_state(state)
        if not query_text.strip():
            return ""
        boost_ids = set(state.current_facts_in_scope)
        hits = retrieve(
            query_text,
            docs,
            top_k=self.top_k,
            boost_ids=boost_ids,
            boost_weight=BOOST_WEIGHT,
        )
        if not hits:
            return ""
        return render_retrieval_context(hits, docs)

    def _build_documents(
        self,
        facts: FactLedger,
        foreshadows: ForeshadowGraph,
        state: NarrativeState,
    ) -> list[RetrievalDoc]:
        """构建检索语料.

        - 事实源：已确认（confirmed）的全量 FactEntry（未确认是推断，不应作为先验注入）。
        - 伏笔源：仅 state.linked_open_threads 关联且 active 的条目
          （未关联的活跃伏笔已在 prompt 的【活跃承诺/伏笔】块全量注入，检索层不重复）。
        - 每条文档 = (doc_id, kind, search_text, display_text)：
          检索用富文本（statement + 类型 + 实体），展示用纯 statement/content。
        """
        docs: list[RetrievalDoc] = []
        for entry in facts.entries:
            if entry.confirmed:
                docs.append(
                    (
                        entry.fact_id,
                        "fact",
                        textualize_fact(entry),
                        entry.statement,
                    )
                )
        linked = set(state.linked_open_threads)
        for entry in foreshadows.entries:
            if entry.thread_id in linked and entry.current_status == "active":
                docs.append(
                    (
                        entry.thread_id,
                        "foreshadow",
                        textualize_foreshadow(entry),
                        entry.content,
                    )
                )
        return docs


def load_retrieval_context(
    output_dir: Path,
    state: NarrativeState,
    facts: FactLedger,
    foreshadows: ForeshadowGraph,
    top_k: int = DEFAULT_TOP_K,
) -> str:
    """状态检索 loader — 静默降级：空 query / 空语料 / 全零分返回 "".

    output_dir 保留以对齐 load_style_context 签名（档 1 未用；档 2 语义索引 / 开关持久化时使用）。
    """
    return RetrievalUnit(top_k=top_k).build_retrieval_context(state, facts, foreshadows)
