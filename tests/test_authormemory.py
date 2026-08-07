"""AuthorMemory tests — 作者性 5B/5C 受控注入 + 价值检索.

验证：Value-Mediated Retrieval 按价值冲突交检索（非语义相似度）；注入受
recency/counterexample priority/max 封顶控制（禁止 8：不无脑全注入）；内核
渲染空原则零成本；内核 sidecar 存/读；隐私（渲染不含作品内选择原文）。
"""

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    ChoiceLedgerEntry,
    RejectedRecord,
)
from src.workflow_action.authormemory import (
    infer_value_conflicts,
    kernel_summary,
    load_author_kernel,
    render_kernel_context,
    render_memory_context,
    retrieve_related_choices,
    save_author_kernel,
    select_memory_injections,
)


def _pu(cid: str) -> dict:
    return {
        "unit_id": f"pu_{cid}",
        "level": "scene",
        "goal": "推进",
        "participants": ["c001"],
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": ["后果"],
        "is_effective": True,
    }


def _choice(decision_id: str, tradeoff: str, conflicts: list[str]) -> ChoiceRecord:
    return ChoiceRecord(
        decision_id=decision_id,
        decision_timestamp="2026-08-07T12:00:00",
        plot_context="决策",
        state_ref="ns_in",
        candidates=[
            CandidateRecord(candidate_id="A", summary="A", plotunit=_pu("A"), new_state_ref="ns_out"),
            CandidateRecord(candidate_id="B", summary="B", plotunit=_pu("B"), new_state_ref="ns_out"),
        ],
        selected_candidate="B",
        rejected=[RejectedRecord(candidate_id="A", reason="x")],
        tradeoff=tradeoff,
        value_conflicts=conflicts,
    )


def _ledger_with(*choices: ChoiceRecord) -> ChoiceLedgerEntry:
    return ChoiceLedgerEntry(choices=list(choices))


def _kernel() -> AuthorKernel:
    return AuthorKernel(
        kernel_id="kernel_001",
        values=[
            AuthorPrinciple(
                principle_id="val_causality_001",
                category="value",
                vocab_key="character_causality_over_plot_convenience",
                description="角色因果优先",
                status="stable",
                supporting_choices=["d_001"],
                counterexamples=[],
                first_formed_at="2026-08-07T12:00:00",
            )
        ],
        prohibitions=[
            AuthorPrinciple(
                principle_id="pro_instant_001",
                category="prohibition",
                vocab_key="no_instant_forgiveness",
                description="不一次道歉修复",
                status="stable",
                supporting_choices=["d_001"],
                counterexamples=["d_099"],
                first_formed_at="2026-08-07T12:00:00",
                last_challenged="2026-08-07T13:00:00",
            )
        ],
    )


# ---- 5C：Value-Mediated Retrieval ----


def test_infer_value_conflicts_by_keywords():
    conflicts = infer_value_conflicts(
        "角色因果优先于剧情便利，放弃读者爽感换取人物一致性"
    )
    assert "character_causality_over_plot_convenience" in conflicts


def test_infer_returns_empty_for_neutral_text():
    assert infer_value_conflicts("主角穿过长街") == []


def test_retrieve_by_value_conflict_not_semantics():
    """表面语义不同但触及同一价值 → 应被检索到（§30 核心）."""
    ledger = _ledger_with(
        _choice("d_001", "放弃强迫对方马上回答，尊重其自主", ["autonomy_over_coercion"]),
        _choice("d_002", "角色因果优先", ["character_causality_over_plot_convenience"]),
    )
    related = retrieve_related_choices(ledger, ["autonomy_over_coercion"])
    assert [c.decision_id for c in related] == ["d_001"]


def test_retrieve_ranks_by_overlap_and_recency():
    ledger = _ledger_with(
        _choice("d_001", "x", ["autonomy_over_coercion"]),
        _choice("d_002", "x", ["autonomy_over_coercion", "no_instant_forgiveness"]),
        _choice("d_003", "x", ["autonomy_over_coercion"]),
    )
    related = retrieve_related_choices(ledger, ["autonomy_over_coercion", "no_instant_forgiveness"])
    # d_002 交集最多 → 第一；其余按 recency 倒序
    assert related[0].decision_id == "d_002"
    assert [c.decision_id for c in related[1:]] == ["d_003", "d_001"]


def test_retrieve_max_results_cap():
    ledger = _ledger_with(*[
        _choice(f"d_{i:03d}", "x", ["autonomy_over_coercion"]) for i in range(5)
    ])
    related = retrieve_related_choices(ledger, ["autonomy_over_coercion"], max_results=2)
    assert len(related) == 2


# ---- 5B：受控注入 ----


def test_select_injections_includes_related_and_challenges():
    ledger = _ledger_with(_choice("d_001", "x", ["no_instant_forgiveness"]))
    kernel = _kernel()
    selection = select_memory_injections(
        ledger, kernel, "角色是否该当场原谅对方的背叛"
    )
    assert selection["value_conflicts"]  # 有推断
    assert [c.decision_id for c in selection["related_choices"]] == ["d_001"]
    # 反例存在 → 被挑战原则呈现（counterexample priority）
    assert any(p.vocab_key == "no_instant_forgiveness" for p in selection["challenged_principles"])


def test_select_injections_no_ledger_no_kernel():
    selection = select_memory_injections(ChoiceLedgerEntry(), None, "中性语境")
    assert selection["related_choices"] == []
    assert selection["kernel"] is None
    assert selection["value_conflicts"] == []


def test_select_injections_caps_principles():
    ledger = _ledger_with(_choice("d_001", "x", ["autonomy_over_coercion"]))
    kernel = AuthorKernel(
        kernel_id="k",
        prohibitions=[
            AuthorPrinciple(
                principle_id=f"pro_{i}",
                category="prohibition",
                vocab_key="no_instant_forgiveness",
                description="d",
                supporting_choices=["d_001"],
                counterexamples=["d_099"],
                first_formed_at="t",
            )
            for i in range(8)
        ],
    )
    selection = select_memory_injections(
        ledger, kernel, "道歉与原谅", max_principles=3
    )
    assert len(selection["challenged_principles"]) == 3


# ---- 渲染与零成本 ----


def test_render_kernel_context_empty_is_zero():
    assert render_kernel_context(None) == ""
    assert render_kernel_context(AuthorKernel(kernel_id="k")) == ""
    # 只有 candidate 原则 → 不注入（未形成可消费结构）
    k = AuthorKernel(
        kernel_id="k",
        values=[AuthorPrinciple(
            principle_id="v1", category="value",
            vocab_key="autonomy_over_coercion", description="d",
            supporting_choices=["d_001"], counterexamples=[],
            first_formed_at="t", status="candidate",
        )],
    )
    assert render_kernel_context(k) == ""


def test_render_kernel_context_stable_principles():
    text = render_kernel_context(_kernel())
    assert "【作者选择结构】" in text
    assert "角色因果优先于剧情便利" in text  # 受限词汇表中性描述
    assert "不允许一次道歉修复长期创伤" in text
    # 不含作品内选择原文（隐私）
    assert "d_001" not in text


def test_render_memory_context_contains_tradeoff_not_plotunit():
    selection = {
        "related_choices": [_choice("d_001", "放弃爽感换取人物因果", ["character_causality_over_plot_convenience"])],
        "challenged_principles": [],
    }
    text = render_memory_context(selection)
    assert "【作者选择史】" in text
    assert "放弃爽感换取人物因果" in text
    # 不含 PlotUnit 全文（隐私 + 防过度锚定）
    assert "pu_A" not in text


def test_render_memory_context_empty_is_zero():
    assert render_memory_context({}) == ""


# ---- 内核 sidecar 存/读（隐私：作品工作区，非风格库） ----


def test_kernel_sidecar_roundtrip(tmp_path):
    kernel = _kernel()
    path = save_author_kernel(tmp_path, kernel)
    assert path.exists()
    loaded = load_author_kernel(tmp_path)
    assert loaded.kernel_id == "kernel_001"
    assert len(loaded.prohibitions) == 1


def test_load_missing_kernel_returns_none(tmp_path):
    assert load_author_kernel(tmp_path) is None


def test_kernel_summary(tmp_path):
    assert kernel_summary(None) == "未形成"
    assert kernel_summary(AuthorKernel(kernel_id="k")) == "未形成"
    summary = kernel_summary(_kernel())
    assert "原则 2 条" in summary
    assert "status=formed" in summary
