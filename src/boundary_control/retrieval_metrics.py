"""状态检索纯代码引擎 — 零依赖 TF-IDF/关键词.

档 1：以字符 bigram（中文）+ ASCII 词块为 term，TF-IDF 加权余弦。
档 2：预留接口签名不变，内部换 bge-small-zh 语义向量即可。

对齐 style_metrics.py：模块级预编译正则 + 纯函数，无 LLM、无依赖、可离线、可单测。
"""

import math
import re

from collections.abc import Sequence

# 连续汉字块（含扩展区基本中文）。中文无分词，切字符 2-gram。
_CJK_RE = re.compile(r"[一-鿿]+")
# 实体 ID / 词块（角色 c001、fact f_001、英文词）原样保留并 lower()。
_ASCII_RE = re.compile(r"[A-Za-z0-9_]+")

NGRAM_SIZE = 2
DEFAULT_TOP_K = 5
BOOST_WEIGHT = 2.0

# (doc_id, kind, search_text, display_text)  kind: "fact" | "foreshadow"
RetrievalDoc = tuple[str, str, str, str]


def _tokenize(text: str) -> list[str]:
    """把文本切成 term 列表：连续汉字块滑窗 2-gram，ASCII 词块原样 lower()."""
    tokens: list[str] = []
    for cjk in _CJK_RE.findall(text):
        if len(cjk) <= NGRAM_SIZE:
            tokens.append(cjk)
        else:
            tokens.extend(cjk[i : i + NGRAM_SIZE] for i in range(len(cjk) - NGRAM_SIZE + 1))
    for ascii_block in _ASCII_RE.findall(text):
        tokens.append(ascii_block.lower())
    return tokens


def _count_terms(tokens: Sequence[str]) -> dict[str, int]:
    """统计 term 出现次数."""
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _tf_weight(raw: int) -> float:
    """子线性 tf 权重."""
    return 1.0 + math.log(raw) if raw > 1 else 1.0


def _idf(doc_count: int, doc_freq: int) -> float:
    """平滑 idf."""
    return math.log((1 + doc_count) / (1 + doc_freq)) + 1


def retrieve(
    query_text: str,
    documents: Sequence[RetrievalDoc],
    top_k: int = DEFAULT_TOP_K,
    boost_ids: set[str] | None = None,
    boost_weight: float = BOOST_WEIGHT,
) -> list[tuple[str, float]]:
    """TF-IDF 加权余弦检索 top-k 文档. 返回 [(doc_id, score)]，得分降序、doc_id 升序（确定性）.

    空 query / 空语料 / 无共享 term → 返回 []（调用方据此降级为空注入）。
    """
    if not query_text.strip() or not documents:
        return []
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []
    query_tf = _count_terms(query_tokens)

    doc_tfs = [_count_terms(_tokenize(text)) for _, _, text, _ in documents]
    doc_count = len(documents)
    df: dict[str, int] = {}
    for tf in doc_tfs:
        for term in tf:
            df[term] = df.get(term, 0) + 1

    idf = {term: _idf(doc_count, freq) for term, freq in df.items()}
    q_norm = math.sqrt(
        sum(
            _tf_weight(query_tf[term]) * idf.get(term, 1.0) ** 2
            for term in query_tf
        )
    )
    if q_norm == 0:
        return []

    scored: list[tuple[str, float]] = []
    for (doc_id, _kind, _text, _display), tf in zip(documents, doc_tfs):
        common = set(query_tf) & set(tf)
        if not common:
            continue
        numerator = sum(
            _tf_weight(query_tf[term]) * _tf_weight(tf[term]) * idf[term] ** 2
            for term in common
        )
        d_norm = math.sqrt(
            sum(_tf_weight(tf[term]) * idf[term] ** 2 for term in tf)
        )
        if d_norm == 0:
            continue
        score = numerator / (q_norm * d_norm)
        if boost_ids and doc_id in boost_ids:
            score *= boost_weight
        scored.append((doc_id, score))

    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:top_k]


_KIND_LABELS = {"fact": "事实", "foreshadow": "伏笔"}


def render_retrieval_context(
    hits: Sequence[tuple[str, float]],
    docs: Sequence[RetrievalDoc],
) -> str:
    """把命中条目渲染成中文块（对齐 FactLedger.to_prompt_context 风格）."""
    if not hits:
        return ""
    by_id = {doc_id: (kind, display) for doc_id, kind, _text, display in docs}
    # 双层段头修复：内层头去掉括号标签，由消费方 continuation.py 独占外层
    # 【相关事实检索】段头（loader 只产正文）。
    lines = ["(top-k 与当前叙事状态相关)"]
    for doc_id, _score in hits:
        kind, display = by_id[doc_id]
        label = _KIND_LABELS.get(kind, kind)
        lines.append(f"- [{label}] {display} (id={doc_id})")
    return "\n".join(lines)
