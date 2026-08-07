"""AuthorMemory — 作者长期记忆的受控注入与价值检索（作者性第五阶段 §28-30）.

四级记忆（§28）：
    Level 1 Episodic Memory    具体发生过什么        Event
    Level 2 Narrative/Char State 当前故事/人物状态    State
    Level 3 Choice Memory      过去做过什么创作选择    Choice → ChoiceLedger
    Level 4 Author Memory      选择历史压缩的长期价值  Repeated Choices → AuthorKernel

受控注入（§29，禁止 8）：不要把所有历史无脑注入 Prompt——会造成 Memory
Anchoring + Self-Imitation（系统越来越只会重复过去的自己）。由
memory relevance + value relevance + recency + counterexample priority
共同控制注入。

Value-Mediated Retrieval（§30）：检索不能只用语义相似度。先推断当前决策触及
哪些 Value Conflict，再按价值检索 Choice History——而不是 Current Text →
Semantic Similarity → Top-K。例：「是否该强迫别人马上回答」和「按钮是否该
连弹三次确认」表面语义完全不同，深层都是 autonomy/coercion。
"""

import json
from pathlib import Path
from typing import Optional

from src.object_state.authorkernel import (
    VALUE_VOCAB,
    VALUE_VOCAB_DESCRIPTIONS,
    VALUE_VOCAB_KEYWORDS,
    AuthorKernel,
    AuthorPrinciple,
)
from src.object_state.choicerecord import ChoiceLedgerEntry, ChoiceRecord


def infer_value_conflicts(
    *texts: str,
    category: Optional[str] = None,
) -> list[str]:
    """从决策/理由文本推断触及的价值冲突（受限词汇表键，确定性启发式代理）.

    非 LLM：对每段文本做 VALUE_VOCAB_KEYWORDS 关键词命中计数，取命中率最高的
    词汇键。这是 5C 的离线代理——真正运行时可换 LLM 推断，协议不变。

    Args:
        texts: 决策上下文/候选摘要/tradeoff 等文本。
        category: 可选类别限定（如 'value' 只返回 value 类词汇键）。
    """
    hits: dict[str, int] = {}
    for key, keywords in VALUE_VOCAB_KEYWORDS.items():
        count = 0
        for text in texts:
            for kw in keywords:
                if kw in (text or ""):
                    count += 1
        if count > 0:
            hits[key] = count
    if not hits:
        return []
    ranked = sorted(hits, key=lambda k: (-hits[k], k))
    return ranked


def retrieve_related_choices(
    ledger: ChoiceLedgerEntry,
    value_conflicts: list[str],
    *,
    max_results: int = 3,
) -> list[ChoiceRecord]:
    """Value-Mediated Retrieval（§30）——按价值冲突交检索选择史.

    不是语义相似度：只要求 choice.value_conflicts 与当前推断的价值冲突有交集。
    交集越多越相关；交集相同则按 recency（写入顺序倒序）。
    """
    wanted = set(value_conflicts)
    scored: list[tuple[int, int, ChoiceRecord]] = []  # (overlap, index, record)
    for index, choice in enumerate(ledger.choices):
        overlap = len(wanted & set(choice.value_conflicts))
        if overlap > 0:
            scored.append((overlap, index, choice))
    scored.sort(key=lambda t: (-t[0], -t[1]))  # 交集多优先，同交集最近优先
    return [record for _, _, record in scored[:max_results]]


def _recency_score(index: int, total: int) -> float:
    """0-1 最近优先（index=0 最旧）."""
    if total <= 1:
        return 1.0
    return (index + 1) / total


def select_memory_injections(
    ledger: ChoiceLedgerEntry,
    kernel: Optional[AuthorKernel],
    decision_context: str,
    *,
    max_choices: int = 3,
    max_principles: int = 5,
) -> dict:
    """受控注入选择（§29/§30，禁止 8）.

    组合信号：value relevance（推断的价值冲突交集）+ recency + counterexample
    priority（挑战现存原则的反例选择优先呈现，防 Self-Imitation）。输出受
    max_choices / max_principles 封顶，绝不无脑全注入。

    Returns:
        {
          "value_conflicts": [...],
          "related_choices": [ChoiceRecord...],
          "challenged_principles": [AuthorPrinciple...],
          "kernel": AuthorKernel | None,
        }
    """
    conflicts = infer_value_conflicts(decision_context)
    related = retrieve_related_choices(ledger, conflicts, max_results=max_choices)

    challenged: list[AuthorPrinciple] = []
    if kernel is not None:
        for principle in kernel.all_principles():
            if principle.counterexamples:
                # 反例本身携带挑战：值得在注入里优先呈现，避免只强化一致选择
                challenged.append(principle)
        # 封顶 + 按挑战新鲜度（last_challenged 倒序）优先
        challenged.sort(
            key=lambda p: (p.last_challenged or p.first_formed_at),
            reverse=True,
        )
        challenged = challenged[:max_principles]

    return {
        "value_conflicts": conflicts,
        "related_choices": related,
        "challenged_principles": challenged,
        "kernel": kernel,
    }


def render_kernel_context(kernel: Optional[AuthorKernel]) -> str:
    """渲染【作者选择结构】块（§25 六部）——空原则不渲染（零成本）.

    只输出中性方法论语义（VALUE_VOCAB_DESCRIPTIONS），不输出作品内 supporting
    choices 的原始文本（隐私 + 防过度锚定）。
    """
    if kernel is None or not kernel.all_principles():
        return ""
    lines: list[str] = ["【作者选择结构】"]
    stable = [p for p in kernel.all_principles() if p.status in ("stable", "weak")]
    if not stable:
        return ""  # 只有 candidate 原则时不注入（未形成可消费的长期结构）
    for p in stable:
        label = VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)
        marker = {
            "value": "价值",
            "prohibition": "禁忌",
            "commitment": "承诺",
            "tension": "张力",
            "attention_bias": "注意偏置",
            "interpretive_bias": "解释偏置",
        }.get(p.category, p.category)
        lines.append(f"- [{marker}] {label}")
    return "\n".join(lines)


def render_memory_context(selection: dict) -> str:
    """渲染【作者选择史】块（Level 3+4 注入）——受控注入结果，空则零成本.

    只渲染 related_choices 的 tradeoff（中性化：不含候选 plotunit 全文），
    以及被挑战原则——让模型看见「过去拒绝过什么、放弃什么换取什么」。
    """
    parts: list[str] = []
    choices = selection.get("related_choices") or []
    if choices:
        lines = ["【作者选择史】"]
        for c in choices:
            conflicts = "/".join(c.value_conflicts) or "—"
            lines.append(
                f"- 选择 {c.selected_candidate}（触及 {conflicts}）：{c.tradeoff}"
            )
        parts.append("\n".join(lines))
    challenged = selection.get("challenged_principles") or []
    if challenged:
        lines = ["【作者正被挑战的原则】"]
        for p in challenged:
            label = VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)
            lines.append(f"- {label}（反例 {len(p.counterexamples)} 条，状态 {p.status}）")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def save_author_kernel(output_dir: Path, kernel: AuthorKernel) -> Path:
    """保存内核到作品工作区 sidecar（隐私：含作品语境，不入风格库）."""
    path = Path(output_dir) / "author_kernel.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kernel.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_author_kernel(output_dir: Path) -> Optional[AuthorKernel]:
    """读内核；缺失返回 None（主流程 no-op）."""
    path = Path(output_dir) / "author_kernel.json"
    if not path.exists():
        return None
    return AuthorKernel.model_validate_json(path.read_text(encoding="utf-8"))


def kernel_summary(kernel: Optional[AuthorKernel]) -> str:
    """内核一句话概要（报告/CLI 用；空内核返回 '未形成'）."""
    if kernel is None or not kernel.all_principles():
        return "未形成"
    counts = {
        cat: len(kernel.principles_by_category(cat))
        for cat in (
            "value",
            "prohibition",
            "commitment",
            "tension",
            "attention_bias",
            "interpretive_bias",
        )
    }
    return f"原则 {sum(counts.values())} 条（值{counts['value']}/禁{counts['prohibition']}/" \
           f"承{counts['commitment']}/张{counts['tension']}/注{counts['attention_bias']}/" \
           f"释{counts['interpretive_bias']}）status={kernel.status}"
