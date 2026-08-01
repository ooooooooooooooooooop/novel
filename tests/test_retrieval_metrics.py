"""Tests for the retrieval engine — zero-dependency TF-IDF/keyword scoring."""

from src.boundary_control.retrieval_metrics import (
    _count_terms,
    _tf_weight,
    _tokenize,
    render_retrieval_context,
    retrieve,
)


def test_tokenize_short_cjk_is_single_term():
    assert _tokenize("令牌") == ["令牌"]


def test_tokenize_long_cjk_bigrams():
    assert _tokenize("藏经阁") == ["藏经", "经阁"]


def test_tokenize_ascii_lowered():
    assert _tokenize("C001") == ["c001"]
    assert _tokenize("f_001") == ["f_001"]


def test_tokenize_mixed_cjk_and_ascii():
    tokens = _tokenize("顾临在藏经阁 c001")
    assert "顾临" in tokens
    assert "藏经" in tokens
    assert "经阁" in tokens
    assert "c001" in tokens


def test_tokenize_empty():
    assert _tokenize("") == []
    assert _tokenize("!!!   ") == []


def test_tokenize_punctuation_dropped():
    tokens = _tokenize("令牌，归c001所有。")
    assert "令牌" in tokens
    assert "c001" in tokens
    assert all("，" not in t and "。" not in t for t in tokens)


def test_count_terms():
    counts = _count_terms(["a", "b", "a", "a"])
    assert counts == {"a": 3, "b": 1}


def test_tf_weight_sublinear():
    assert _tf_weight(1) == 1.0
    assert _tf_weight(3) < 3.0
    assert _tf_weight(4) > _tf_weight(3)


def test_retrieve_rank_by_relevance():
    docs = [
        ("f_001", "fact", "古书藏于藏经阁密室", "古书藏于藏经阁密室"),
        ("f_002", "fact", "顾临在祠堂烧香", "顾临在祠堂烧香"),
        ("f_003", "fact", "令牌归宗门所有", "令牌归宗门所有"),
    ]
    hits = retrieve("藏经阁古书", docs, top_k=3)
    # 完全相关（藏经阁+古书）排第一；无共享 term 的不出现
    assert hits[0][0] == "f_001"
    assert len(hits) == 1


def test_retrieve_top_k_limits():
    docs = [
        ("f_001", "fact", "藏经阁藏古书", "藏经阁藏古书"),
        ("f_002", "fact", "藏经阁有暗门", "藏经阁有暗门"),
        ("f_003", "fact", "藏经阁禁地", "藏经阁禁地"),
    ]
    hits = retrieve("藏经阁", docs, top_k=2)
    assert len(hits) == 2
    # 三个 doc 都含藏经阁 term，top_k=2 截断为 2 条
    assert all(doc_id in {"f_001", "f_002", "f_003"} for doc_id, _ in hits)
    # 确定性：同输入两次结果一致
    hits2 = retrieve("藏经阁", docs, top_k=2)
    assert hits == hits2


def test_retrieve_empty_query_returns_empty():
    docs = [("f_001", "fact", "藏经阁藏古书", "藏经阁藏古书")]
    assert retrieve("", docs) == []
    assert retrieve("   ", docs) == []


def test_retrieve_empty_docs_returns_empty():
    assert retrieve("藏经阁", []) == []


def test_retrieve_no_common_term_returns_empty():
    docs = [("f_001", "fact", "祠堂烧香", "祠堂烧香")]
    assert retrieve("藏经阁古书", docs) == []


def test_retrieve_boost_applies():
    docs = [
        ("f_001", "fact", "令牌归宗门所有", "令牌归宗门所有"),
        ("f_002", "fact", "藏经阁藏古书", "藏经阁藏古书"),
    ]
    hits = retrieve("藏经阁", docs, top_k=2, boost_ids={"f_001"})
    # f_001 无共享 term，不出现；验证 boost 不改 empty 过滤
    assert all(doc_id != "f_001" for doc_id, _ in hits)


def test_retrieve_boost_raises_ranked_doc():
    docs = [
        ("f_001", "fact", "藏经阁密道", "藏经阁密道"),
        ("f_002", "fact", "藏经阁古书", "藏经阁古书"),
    ]
    base = retrieve("藏经阁", docs, top_k=2)
    boosted = retrieve("藏经阁", docs, top_k=2, boost_ids={"f_002"})
    base_ids = [doc_id for doc_id, _ in base]
    boosted_ids = [doc_id for doc_id, _ in boosted]
    # 两者都含 f_002（共享 term），boost 后 f_002 仍应在 top-k 且不劣于 base
    assert "f_002" in base_ids
    assert "f_002" in boosted_ids
    assert boosted_ids.index("f_002") <= base_ids.index("f_002")


def test_retrieve_deterministic_tie_break():
    docs = [
        ("f_a", "fact", "藏经阁", "藏经阁"),
        ("f_b", "fact", "藏经阁", "藏经阁"),
    ]
    hits1 = retrieve("藏经阁", docs, top_k=2)
    hits2 = retrieve("藏经阁", docs, top_k=2)
    assert hits1 == hits2
    assert hits1[0][0] == "f_a"


def test_render_retrieval_context_empty_hits():
    assert render_retrieval_context([], [("f_001", "fact", "藏经阁", "藏经阁")]) == ""


def test_render_retrieval_context_lines():
    docs = [
        ("f_001", "fact", "古书藏于藏经阁密室", "古书藏于藏经阁密室"),
        ("t_002", "foreshadow", "主角身世之谜", "主角身世之谜"),
    ]
    text = render_retrieval_context([("f_001", 0.9), ("t_002", 0.5)], docs)
    assert "【相关事实检索】" in text
    assert "- [事实] 古书藏于藏经阁密室 (id=f_001)" in text
    assert "- [伏笔] 主角身世之谜 (id=t_002)" in text
