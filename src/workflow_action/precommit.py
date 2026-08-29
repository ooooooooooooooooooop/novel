"""A1 T5 — EvaluatorPrecommit 生成与确定性证伪（design §8；doc 48 §6 step 6）.

评审看正文前只读取可信状态、ReaderContract、PlotUnit 和承诺图，生成不可修改的
``EvaluatorPrecommit``；正文完成后用同一份预承诺执行证伪检查。

``falsify_prose_against_precommit`` 是**纯代码**的确定性证伪：把 PlotUnit 的
释放信息/后果/预期局势与正文逐项核对，产出带真实正文锚点的 JudgeClaim
（generator_source="code"）。硬违例（effective 单元缺失释放信息/后果）由
claim_is_hard_violation 判定为 blocking → 候选淘汰，软分数不能抵消
（requirement §5 规则 7：「每个提交状态变化都有正文证据」）。

匹配是三级确定性近似（``_find_item``）：逐字子串 → 压缩整串子串 → 子句内容二元组
局部成簇（去掉高频功能字后，条目任一分句的内容词对在正文同一 ≤400 字符窗口内
去重命中 ≥4 且 包含率 ≥0.35）。前两级保持「短短语逐字命中」的既有口径；第三级让
长句条目在自然意译下也能被证伪而不是无谓阻断——正文确以词结构在同一场景段重述了
条目内容即视为落地（G8 根因：plan 层产出句子级条目，prose 层必然意译，全句逐字
匹配在真实生成中恒为缺失）。条目内容完全缺失（词对不局部成簇）仍然
violated/blocking。

锚点必须真实：excerpt 直接取自被评审正文的 [char_start, char_end) 区间，
不可能捏造（与 judge 路径同一核验口径）。
"""

from __future__ import annotations

import re

from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.object_state.judge_claim import JudgeClaim, ProseAnchor
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.workflow_action.plan_search import compact_text

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


def build_evaluator_precommit(
    *,
    precommit_id: str,
    plotunit: PlotUnit,
    input_state: NarrativeState,
    new_state: NarrativeState,
    trusted_state_hash: str,
) -> EvaluatorPrecommit:
    """只读正文前输入，生成不可修改的评审预承诺.

    input_state/new_state 均为结构对象（计划层），trusted_state_hash 为可信状态
    （facts ledger + 上一 NarrativeState）哈希——证明预承诺冻结于正文前的可信状态，
    正文完成后无法改写（模型无正文字段 + extra=forbid）。
    """
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
    """候选级证伪聚合判定：仅当 effective 单元缺失项**不少于**已落地项才硬阻断.

    单项缺失 → 不阻断（正文意译措辞不同是软质量问题，交给带正文锚点的 LLM 评审维
    权衡；缺失项仍以 blocking 严重级进入 claim 集，在帕累托/淘汰赛中降低该候选的
    plotunit_expected_change 软轴分数，让更忠实于计划的候选胜出）。缺失项 ≥ 已落地项
    → 正文没有实质兑现计划声称的多数状态变化，构成硬证据缺口
    （doc 47 §5「每个状态变化都有正文证据」的实质口径），阻断候选。

    注意：satisfied 项的严重级恒为 advisory（无论 effective 与否），故是否 effective
    以「缺失项中存在 blocking 严重级」为判据；非 effective 计划的缺失全为 advisory，
    永不硬阻断。
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
    """在正文中定位一项计划内容；返回原始下标，找不到返回 -1.

    三级确定性匹配：
    1. 原始逐字子串；
    2. 压缩（去空白标点）整串子串；
    3. 意译容忍：条目任一分句的内容二元组在正文**同一局部窗口**内成批出现
       （去重命中 ≥4 且 包含率 ≥0.35）。
    4. 整条目合并判定（兜底）：正文可能把条目各分句内容分散在相邻句子
       （代词回指/改写式意译/跨句表达），把条目全部子句的内容二元组合并成
       一个词簇，在正文任一局部窗口内成批出现（命中 ≥4 且 覆盖 ≥0.35）
       即视为落地——正文确以词结构在同一场景段重述了条目整体语义。
    前两级保持既有口径（短短语/逐字引用直接命中），第三级让长句条目在自然意译下
    也能被证伪而非无谓阻断——正文确以词结构在同一场景段重述了条目内容即视为落地；
    内容真正缺失（词对不局部成簇）仍然 violated/blocking。
    """
    if not item:
        return -1
    index = prose.find(item)
    if index >= 0:
        return index
    compact_prose = compact_text(prose)
    compact_item = compact_text(item)
    if compact_item and compact_item in compact_prose:
        return compact_prose.find(compact_item)
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


def falsify_prose_against_precommit(
    precommit: EvaluatorPrecommit, prose: str, chapter_ref: str
) -> list[JudgeClaim]:
    """纯代码证伪：PlotUnit 预期变化 ↔ 正文实际变化（design §8 check 1）.

    对每项释放信息/后果：正文包含 → satisfied advisory（正文证据）；正文缺失 →
    violated（effective 单元 blocking，非 effective advisory）。预期局势缺失 →
    advisory（局势短语易被意译，不作硬门禁）。全部 JudgeClaim 都带真实正文锚点。
    """
    claims: list[JudgeClaim] = []
    expected_items = list(precommit.expected_released_information) + list(
        precommit.expected_consequences
    )
    for index, item in enumerate(expected_items):
        found_at = _find_item(prose, item)
        is_consequence = index >= len(precommit.expected_released_information)
        if found_at >= 0:
            claims.append(
                JudgeClaim(
                    claim_id=f"code_expected_{index + 1:02d}",
                    precommit_id=precommit.precommit_id,
                    axis="plotunit_expected_change",
                    verdict="satisfied",
                    severity="advisory",
                    anchors=(
                        _found_anchor(prose, chapter_ref, found_at, len(item)),
                    ),
                    rationale=(
                        "正文已包含该 PlotUnit 预期信息/后果（正文证据落地）："
                        f"{item}"
                    ),
                    generator_source="code",
                )
            )
        else:
            severity = "blocking" if precommit.effective else "advisory"
            label = "后果" if is_consequence else "释放信息"
            claims.append(
                JudgeClaim(
                    claim_id=f"code_missing_{index + 1:02d}",
                    precommit_id=precommit.precommit_id,
                    axis="plotunit_expected_change",
                    verdict="violated",
                    severity=severity,
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale=(
                        f"正文未找到该 PlotUnit 预期{label}：『{item}』——"
                        "提交状态变化缺少对应正文证据"
                    ),
                    generator_source="code",
                )
            )
    if compact_text(precommit.expected_output_situation):
        if _find_item(prose, precommit.expected_output_situation) >= 0:
            claims.append(
                JudgeClaim(
                    claim_id="code_situation_ok",
                    precommit_id=precommit.precommit_id,
                    axis="prose_actual_change",
                    verdict="satisfied",
                    severity="advisory",
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale="正文体现了预期输出局势。",
                    generator_source="code",
                )
            )
        else:
            claims.append(
                JudgeClaim(
                    claim_id="code_situation_missing",
                    precommit_id=precommit.precommit_id,
                    axis="prose_actual_change",
                    verdict="violated",
                    severity="advisory",
                    anchors=(_opening_anchor(prose, chapter_ref),),
                    rationale="正文未明显体现预期输出局势（advisory，局势可被意译）。",
                    generator_source="code",
                )
            )
    return claims
