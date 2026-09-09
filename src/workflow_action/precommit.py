"""冻结规划预承诺，并检索正文中的词语线索（零模型调用）。

词语命中无法证明事件已经发生，未命中也不能证明正文没有意译表达。
因此本模块只生成 advisory/inconclusive 线索，不把近似匹配变成事实判断。
runner 必须通过 fact_judge 对全部 evidence_obligations 的带锚点核对后才能选稿。
快照版覆盖语义状态差分和新增事实，并绑定完整提交载荷；覆盖检查仍不是语义真值证明。
"""

from __future__ import annotations

import hashlib
import json
import re

from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.object_state.judge_claim import JudgeClaim, ProseAnchor
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.plan_search import compact_text
from src.workflow_action.preference_review import _locate_excerpt

_ANCHOR_OPENING_CHARS = 160

# 内容词匹配（意译容忍）：去掉高频功能字后，测条目子句的内容字符在正文中的保序
# 覆盖率。正文以自然语序重述条目内容时（如「评估价低于基准两成」→「低于同区域
# 近三年成交均价约两成」），内容字符（名词/动词/修饰词）的保序覆盖仍高；条目内容
# 完全缺失时覆盖趋近于零。这是 doc 47 §3.3「从正文重建状态能否得到计划声称的变化」
# 的确定性近似——不是固定句式搜索，也不是把短语交给 LLM 判定。
_CONTENT_STOP = frozenset(
    "的了着在是有被把让它我你他她我们你们她们咱们自己"
    "这那也还就才都和与或但而于其从对向又以及"
    "因为所以虽然但是为了不是过没并没已还要会能可正在"
    "吗呢吧啊哦嗯却则便仍尤其并且况且就算哪怕"
)
_CLAUSE_SPLIT_RE = re.compile(r"[，。；：、,.!?;:！？…—～\s「」『』“”‘’()（）【】《》]+")
# 子句命中阈值：内容字符二元组（词结构）在正文**同一局部窗口**内的去重命中数。
# 二元组要求局部邻接——意译保留词结构（「举报信…评估价偏低」→ 举报/报信/评估/偏低
# 等词对仍在），而散落的通用字（人名 + 说/动/作 各自出现）无法拼出 4 个不同词对。
# 窗口要求把「正文证据」限定为局部成簇：真实落地时条目的词对出现在同一场景段
# （≤400 字符）内；不同段落偶发共现（同一题材的常用词散落全章）构不成证据。
_CLAUSE_BIGRAM_MIN = 0.35
_CLAUSE_BIGRAM_HITS_MIN = 4
_EVIDENCE_WINDOW_CHARS = 400

def canonical_candidate_payload(plotunit: PlotUnit, new_state: NarrativeState, new_facts: list) -> str:
    """Bind all fields the selected plan can submit; preserve list order."""
    if not isinstance(new_facts, list):
        raise ValueError("new_facts must be a list")
    return json.dumps({"plotunit": plotunit.model_dump(mode="json"),
                       "new_state": new_state.model_dump(mode="json"), "new_facts": new_facts},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_evaluator_precommit(
    *,
    precommit_id: str,
    plotunit: PlotUnit,
    input_state: NarrativeState,
    new_state: NarrativeState,
    trusted_state_hash: str,
    new_facts: list | None = None,
) -> EvaluatorPrecommit:
    """只读正文前输入，生成不可修改的评审预承诺.

    input_state/new_state 均为结构对象（计划层），trusted_state_hash 为可信状态
    （facts ledger + 上一 NarrativeState）哈希——证明预承诺冻结于正文前的可信状态，
    正文完成后无法改写（模型无正文字段 + extra=forbid）。
    """
    payload = canonical_candidate_payload(plotunit, new_state, new_facts if new_facts is not None else [])
    return EvaluatorPrecommit(
        precommit_id=precommit_id,
        plotunit_id=plotunit.unit_id,
        input_state_id=input_state.state_id,
        output_state_id=new_state.state_id,
        expected_output_location=new_state.current_location or "",
        expected_output_situation=new_state.current_situation or "",
        expected_released_information=tuple(plotunit.released_information or []),
        expected_consequences=tuple(plotunit.consequences or []),
        effective=bool(plotunit.is_effective),
        trusted_state_hash=trusted_state_hash,
        input_state_json=json.dumps(input_state.model_dump(mode="json"), ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":")),
        candidate_payload_json=payload,
        candidate_payload_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def _content_chars(text: str) -> str:
    """去高频功能字后的内容字符（仅 CJK，不含标点/空白/数字）。"""
    return "".join(
        ch for ch in text if "一" <= ch <= "鿿" and ch not in _CONTENT_STOP
    )


def _content_bigrams(text: str) -> set[str]:
    """内容字符的相邻二元组集合（词结构的最小单元，意译稳定）。"""
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _windowed_clause_hits(ci: str, prose: str) -> int:
    """子句内容二元组在正文任一局部窗口内的去重命中数（正文证据的局部成簇度量）.

    对每个子句内容二元组收集其在正文中的所有命中位置；滑动窗口统计任一
    ``_EVIDENCE_WINDOW_CHARS`` 区间内最多能同时命中的**不同**二元组数。
    """
    clause_bigrams = _content_bigrams(ci)
    positions: list[tuple[int, str]] = []
    for bigram in clause_bigrams:
        start = 0
        while True:
            index = prose.find(bigram, start)
            if index < 0:
                break
            positions.append((index, bigram))
            start = index + 1
    if not positions:
        return 0
    positions.sort()
    best = 0
    for i in range(len(positions)):
        distinct: set[str] = set()
        for j in range(i, len(positions)):
            if positions[j][0] - positions[i][0] >= _EVIDENCE_WINDOW_CHARS:
                break
            distinct.add(positions[j][1])
        best = max(best, len(distinct))
    return best


def _clause_content_match(clause: str, prose: str) -> tuple[bool, str]:
    """子句内容二元组是否在正文某局部窗口内成批出现；返回 (命中, 子句内容字符)。"""
    ci = _content_chars(compact_text(clause))
    if len(ci) < _CLAUSE_BIGRAM_HITS_MIN + 1:  # 至少要能形成 4 个二元组
        return False, ci
    clause_bigrams = _content_bigrams(ci)
    hits = _windowed_clause_hits(ci, prose)
    return (
        hits >= _CLAUSE_BIGRAM_HITS_MIN
        and hits / len(clause_bigrams) >= _CLAUSE_BIGRAM_MIN
    ), ci


def _locate_content_anchor(prose: str, ci: str) -> int:
    """在原始正文中定位子句内容字符首次成词出现的位置（锚点必须是真实正文区间）。"""
    for k in range(len(ci) - 1):
        index = prose.find(ci[k:k + 2])
        if index >= 0:
            return index
    index = prose.find(ci[0]) if ci else -1
    return index if index >= 0 else 0


def falsify_blocking(code_claims: list[JudgeClaim]) -> bool:
    """保留旧记录的数量聚合接口，不作为当前正文语义核验。

    现有词语检索只产生 advisory/inconclusive，因此走此接口不会自行确认或拒绝
    候选。当前候选准入由逐项 fact_judge 覆盖与既有硬冲突门禁决定。
    旧格式中 blocking/violated 数量不少于 satisfied 时返回 True，仅用于兼容。
    """
    missing = 0
    found = 0
    effective = False
    for claim in code_claims:
        if claim.axis != "plotunit_expected_change":
            continue
        if claim.verdict == "violated":
            missing += 1
            if claim.severity == "blocking":
                effective = True
        elif claim.verdict == "satisfied":
            found += 1
    if not effective or missing == 0:
        return False
    return missing >= found


def _find_item(prose: str, item: str) -> int:
    """检索可能相关的词语位置（不是语义支持证明），找不到返回 -1.

    三级确定性匹配：
    1. 原始逐字子串；
    2. 压缩（去空白标点）整串子串；
    3. 意译容忍：条目任一分句的内容二元组在正文**同一局部窗口**内成批出现
       （去重命中 ≥4 且 包含率 ≥0.35）。
    4. 整条目合并判定（兜底）：正文可能把条目各分句内容分散在相邻句子
       （代词回指/改写式意译/跨句表达），把条目全部子句的内容二元组合并成
       一个词簇，在正文任一局部窗口内成批出现（命中 ≥4 且 覆盖 ≥0.35）
       仅定位可能相关的片段；命中不解决否定、模态、信念或实体归属。
    未命中也不证明缺失，意译可能完全不保留词对。所有结果均待语义评审。
    """
    if not item:
        return -1
    index = prose.find(item)
    if index >= 0:
        return index
    located = _locate_excerpt(prose, item, allow_fuzzy=False, min_length=1)
    if located is not None:
        return located[0]  # 原始字符坐标，不能把压缩字符串坐标当原文坐标。
    for clause in _CLAUSE_SPLIT_RE.split(item):
        matched, ci = _clause_content_match(clause, prose)
        if matched:
            return _locate_content_anchor(prose, ci)
    # 第四级：整条目合并判定（各子句二元组并集局部成簇）。
    # 合并判定是兜底：正文把条目各分句内容分散在相邻句子时，单子句窗口命中
    # 阈值偏高（4+bigrams×35%ratio），合并后整体词簇用更低阈值（3+bigrams×25%ratio），
    # 因为合并信号已经比单子句弱，且正文确以词结构在同一场景段重述了条目整体语义。
    merged: list[str] = []
    for clause in _CLAUSE_SPLIT_RE.split(item):
        ci = _content_chars(compact_text(clause))
        if len(ci) >= 2:
            merged.append(ci)
    if merged:
        merged_text = "".join(merged)
        merged_bigrams = _content_bigrams(merged_text)
        if len(merged_bigrams) >= 3:
            hits = _windowed_clause_hits(merged_text, prose)
            if hits >= 3 and hits / len(merged_bigrams) >= 0.25:
                return _locate_content_anchor(prose, merged_text)
    return -1


def _opening_anchor(prose: str, chapter_ref: str) -> ProseAnchor:
    end = min(len(prose), _ANCHOR_OPENING_CHARS)
    return ProseAnchor(
        chapter_ref=chapter_ref,
        position="start",
        excerpt=prose[0:end],
        char_start=0,
        char_end=end,
    )


def _found_anchor(prose: str, chapter_ref: str, index: int, length: int) -> ProseAnchor:
    end = min(len(prose), index + length)
    if index >= end:
        return _opening_anchor(prose, chapter_ref)
    return ProseAnchor(
        chapter_ref=chapter_ref,
        position="middle",
        excerpt=prose[index:end],
        char_start=index,
        char_end=end,
    )


def evidence_obligations(precommit: EvaluatorPrecommit) -> dict[str, str]:
    """从正文前预承诺派生稳定条目 ID；不读取正文、不拆散复合断言的语义。"""
    items = {
        "evidence_location": precommit.expected_output_location,
        "evidence_situation": precommit.expected_output_situation,
    }
    for label, values in (
        ("released", precommit.expected_released_information),
        ("consequence", precommit.expected_consequences),
    ):
        items.update({f"evidence_{label}_{i:03d}": v for i, v in enumerate(values, 1)})
    if precommit.candidate_payload_json:
        previous = json.loads(precommit.input_state_json)
        payload = json.loads(precommit.candidate_payload_json)
        state = payload["new_state"]
        # Unchanged trusted context need not be narrated again. IDs and reference scope
        # remain structurally checked and included in the complete payload binding.
        for key, field in (("evidence_location", "current_location"),
                           ("evidence_situation", "current_situation")):
            if state.get(field) == previous.get(field):
                items.pop(key, None)
        structural = {"state_id", "linked_open_threads", "current_facts_in_scope"}
        for field, value in state.items():
            if field in structural | {"current_location", "current_situation"}:
                continue
            if value != previous.get(field):
                items[f"evidence_state_{field}"] = json.dumps(
                    {"field": field, "before": previous.get(field), "after": value},
                    ensure_ascii=False, sort_keys=True)
        for index, fact in enumerate(payload["new_facts"], 1):
            items[f"evidence_fact_{index:03d}"] = json.dumps(fact, ensure_ascii=False, sort_keys=True)
    return {key: value for key, value in items.items() if value.strip()}


def validate_commit_evidence(precommit: EvaluatorPrecommit, *, plotunit: PlotUnit,
                             new_state: NarrativeState, new_facts: list,
                             prose: str, reviewed_prose_sha256: str,
                             claims: list[JudgeClaim]) -> None:
    """Last check before commit-side mutations; no model calls or file writes."""
    if not precommit.candidate_payload_json:
        raise ValueError("legacy precommit has no complete candidate binding")
    if canonical_candidate_payload(plotunit, new_state, new_facts) != precommit.candidate_payload_json:
        raise ValueError("commit candidate differs from reviewed precommit")
    if hashlib.sha256(prose.encode("utf-8")).hexdigest() != reviewed_prose_sha256:
        raise ValueError("commit prose differs from reviewed candidate")
    if unresolved_evidence(precommit, claims):
        raise ValueError("commit candidate has unresolved evidence")
    for claim in claims:
        for anchor in claim.anchors:
            if prose[anchor.char_start:anchor.char_end] != anchor.excerpt:
                raise ValueError("commit evidence anchor no longer matches prose")


def unresolved_evidence(
    precommit: EvaluatorPrecommit, claims: list[JudgeClaim]
) -> dict[str, str]:
    """完整覆盖才可选稿：缺项、重复、错归属或不确定均不能当作已核实。

    这里只核验评审覆盖契约，不能验证模型的语义结论本身是否正确。
    锚点真实性由 parse_judge_claims 先核验，调用方不得传入未解析的模型响应。
    """
    unresolved = {}
    for key in evidence_obligations(precommit):
        matches = [c for c in claims if c.claim_id == key]
        if not matches:
            unresolved[key] = "missing"
        elif len(matches) != 1:
            unresolved[key] = "duplicate"
        else:
            claim = matches[0]
            if (claim.precommit_id != precommit.precommit_id
                    or claim.generator_source != "fact_judge"
                    or claim.axis != "fact_conflict"):
                unresolved[key] = "wrong_binding"
            elif claim.verdict != "satisfied":
                unresolved[key] = claim.verdict
    return unresolved


def falsify_prose_against_precommit(
    precommit: EvaluatorPrecommit, prose: str, chapter_ref: str
) -> list[JudgeClaim]:
    """兼容旧入口名；返回词语线索，全部为 advisory/inconclusive。

    未匹配的 opening anchor 仅定位被检查文本，不是缺失或冲突的证据。
    此结果不能单独授权选稿；runner 随后的逐项 fact_judge 覆盖门禁负责拦截。
    """
    if not prose.strip():
        raise ValueError("cannot locate evidence in empty prose")
    claims = []
    for key, item in evidence_obligations(precommit).items():
        found_at = _find_item(prose, item)
        anchor = (_found_anchor(prose, chapter_ref, found_at, len(item))
                  if found_at >= 0 else _opening_anchor(prose, chapter_ref))
        hint = "找到可能相关的词语线索" if found_at >= 0 else "未找到词语线索；仍可能存在意译"
        claims.append(JudgeClaim(
            claim_id="code_hint_" + key,
            precommit_id=precommit.precommit_id,
            axis="prose_actual_change" if key in ("evidence_location", "evidence_situation")
                 else "plotunit_expected_change",
            verdict="inconclusive", severity="advisory", anchors=(anchor,),
            rationale=f"{hint}。不能据此确认或否认断言；待逐项事实评审：{item}",
            generator_source="code",
        ))
    return claims
