"""ReviewUnit — 审查工作流（对象层一致性审查编排器）.

职责边界（重构解耦）：
- 硬规则 `_hard_rules`：校验对象层契约（state_ref 存在性/角色 ID 一致性/
  事实时间冲突/Foreshadow 引用）——属核心1 一致性审查的编排职责，保留本处。
- 领域弱信号：已拆分到 src/domain_layer/review_signals.py（每类失败类型一个
  detect_* 检测器），`_domain_rules` 只做循环调用汇总。
- prompt 渲染 / 路由解析 / 正文级复核：保留本处。

数据表（触发词/失败类型字典/四层分类）在 src/domain_layer/
review_signal_knowledge.py；FAILURE_TYPE_LEXICON 在此 re-export
（测试与 prompt 渲染依赖 `from src.workflow_action.review import FAILURE_TYPE_LEXICON`）。
"""

import json
import re
from collections import defaultdict

from src.object_state.narrativestate import INFORMATION_LAYER_GUIDANCE
from src.boundary_control.review_input import validate_review_input
from src.domain_layer.review_signal_knowledge import FAILURE_TYPE_LEXICON
from src.domain_layer.review_signals import (
    run_all_signal_detectors,
)
from src.domain_layer.info_warrant_knowledge import (
    INFO_GAP_FORMS,
)
from src.domain_layer.info_warrant_rules import build_info_warrant_guidance
from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    ReviewIssue,
    ReviewReminder,
    WorkSpec,
    WorldModel,
)

_DIALOGUE_QUOTE_RE = re.compile(r"[“\"「『]([^”\"」』]{4,200})[”\"」』]")
_DIALOGUE_FUNC_CHARS = frozenset(
    "的一了是我不在人们有来他这上着个地到大说就去子得也和还要以于但在你"
    "它她我们们你那吗呢吧啊嘛啦哦呀么什怎为最会能可都没把被让从向与及或"
    "很更再又还只并而因如所其此每各该些多谁怎哪乃已竟即若便岂"
)


def _dialogue_theme_recurrence(prose_text: str) -> list[str]:
    """机械检测：对白中逐字/近逐字重复表述信号（dialogue_loop_stasis 候选）。

    提取引号内对白轮次，找 ≥4 字且跨越 ≥2 个不同轮次重现的表述片段
    （同一承诺/条件/风险被原样再说一遍）；仅作审查模型的注意信号，
    不直接判定。返回候选重复表述（按覆盖轮次与长度排序）。
    """
    turns = _DIALOGUE_QUOTE_RE.findall(prose_text or "")
    if len(turns) < 6:
        return []
    positions: dict[str, set[int]] = {}
    for ti, turn in enumerate(turns):
        seen: set[str] = set()
        for n in range(4, 11):
            for i in range(len(turn) - n + 1):
                gram = turn[i:i + n]
                if sum(c not in _DIALOGUE_FUNC_CHARS for c in gram) >= 3:
                    seen.add(gram)
        for gram in seen:
            positions.setdefault(gram, set()).add(ti)
    hits = [(g, len(s)) for g, s in positions.items() if len(s) >= 2]
    hits = [(g, c) for g, c in hits
            if not any(h != g and g in h for h, c2 in hits if c2 >= 2)]
    hits = sorted(hits, key=lambda x: (-x[1], -len(x[0])))
    # 归并同族命中：保留覆盖轮次最多的代表
    picked: list[str] = []
    for gram, _ in hits:
        if any(gram in p or p in gram for p in picked):
            continue
        picked.append(gram)
        if len(picked) >= 4:
            break
    return picked


_DIALOGUE_REFUSAL_MARK_RE = re.compile(
    r"(已经|刚才|之前就|早就).{0,8}(说过|讲过|提过|回答)|"
    r"(说过|讲过|问过)了|不再重复|不会.{0,4}因为.{0,6}改变|"
    r"规矩不变|规则不变|答案不变"
)

# 显性复读仪式：『复述一遍』『记住没』式确认仪式把重确认变成读者
# 可见的机械流程；与 ≥2 个重述轮叠加时构成车轱辘堆叠（H01 证据：
# 各命题仅重述一次但配复读仪式，盲评仍判损伤；E06 无仪式不重）。
_DIALOGUE_READBACK_RITUAL_RE = re.compile(
    r"复述一遍|重复一遍|再说一遍|记住了[吗没？?]|背一遍"
)


def dialogue_turns_numbered(prose_text: str) -> list[str]:
    """提取引号内对白轮次（≥2 字），供仲裁按编号引用。"""
    return re.findall(r'[“"]([^”"]{2,})[”"]', prose_text or "")


# --- DFD V1：细节功能密度机械候选层（只产候选，不直接定罪） ---
_DIALOGUE_SPAN_RE = re.compile(r"[“\"「『]([^”\"」』]*)[”\"」』]")


def narrative_spans_numbered(
    prose_text: str, keep_dialogue: bool = False
) -> list[str]:
    """叙述句段编号：按段落切分，剥掉引号对白内容，供仲裁按 [n] 引用。

    细节功能的判定单元是叙述句段（装修清单是段落级现象），不是对白轮。
    keep_dialogue=True 时保留引号内对白——留白核验（dim8a）等对白
    本身可作证据/说破载体的判定需要看见对白内容。
    """
    spans = []
    for para in (prose_text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        if not keep_dialogue:
            para = _DIALOGUE_SPAN_RE.sub("「…」", para)  # 对白占位，保留叙述外壳
        spans.append(para)
    return spans


# 静态陈设/存在动词：枚举式描写的典型谓语（有/摆/挂/立/铺…）。
# 「有」前有否定字（没有/无有/未有）不算陈设——否定排比是修辞不是清单。
_INVENTORY_STATIC_VERB_RE = re.compile(
    r"(?:(?<!没)(?<!无)(?<!未)有|摆着|放着|挂着|立着|堆着|铺着|贴着|"
    r"悬着|竖着|插着|镶着|散落|弥漫|散发|"
    r"是.{0,6}(?:一[张片个块间排道点]|几[张片个块间排道点]|"
    r"[粗细低矮高大深浅薄厚长短方圆新旧明暗冷暖]))"
)
# 否定排比防护：句内 ≥2 处「没有/无/不再」即整句判修辞性列举，不产候选
_NEGATION_LITANY_RE = re.compile(r"(?:没有|无有|不再有|再也没有|并不|并非)")
# 顿号枚举：≥2 个顿号串起 ≥3 个并列名词项
_INVENTORY_ENUM_RE = re.compile(
    r"[^。！？；：，\s「」“”\"]{1,10}、[^。！？；：，\s「」“”\"]{1,10}"
    r"(?:、[^。！？；：，\s「」“”\"]{1,10})+"
)
# 人物动作信号（仅物理位移/操作动作）：观察取景动词（环顾/看/望/听）
# 恰恰引出清单，不算；排除与静态陈设冲突的字（放/点/倒/压/铺/贴）。
_ACTION_SIGNAL_RE = re.compile(
    r"(?:走|跑|冲|扑|跃|抓|握|挥|砸|踢|推|拉|按|拧|掀|翻|躲|闪|爬|跪|蹲|"
    r"扔|掷|拔|抽|刺|劈|砍|烧|敲|踏|踩|坐|站|靠|躺|趴|俯|仰|"
    r"伸手|开口|出声|喊|叫|挤|撕|扯|拖|拽|抱|背|扛|提|端|灌|吞|咽|咬|舔|吻)"
)


_SENTENCE_SPLIT_RE = re.compile(r"[。！？；\n]")


def _narrative_proposition_recurrence(prose_text: str) -> list[str]:
    """机械检测：叙述句段中命题级逐字重现信号（repetition coverage 入口）。

    与 _dialogue_theme_recurrence 同构但作用于叙述句段：≥4 字内容片段
    跨越 ≥2 个不同叙述句段重现即候选（同一计划/条件/安排被复述）。
    只产仲裁触发信号，不判定。D02 证据：ds 未点火时路线陈述在引号内外
    混合复述 4 次，整体漏过仲裁——本信号提供确定性入口。

    返回候选重现片段（按覆盖句段数与长度排序，≤4 条）。
    """
    spans = narrative_spans_numbered(prose_text)
    if len(spans) < 4:
        return []
    positions: dict[str, set[int]] = {}
    for si, span in enumerate(spans):
        seen: set[str] = set()
        for n in range(4, 11):
            for i in range(len(span) - n + 1):
                gram = span[i:i + n]
                if sum(c not in _DIALOGUE_FUNC_CHARS for c in gram) >= 3:
                    seen.add(gram)
        for gram in seen:
            positions.setdefault(gram, set()).add(si)
    hits = [(g, len(s)) for g, s in positions.items() if len(s) >= 2]
    hits = [(g, c) for g, c in hits
            if not any(h != g and g in h for h, c2 in hits if c2 >= 2)]
    hits = sorted(hits, key=lambda x: (-x[1], -len(x[0])))
    picked: list[str] = []
    for gram, _ in hits:
        if any(gram in p or p in gram for p in picked):
            continue
        picked.append(gram)
        if len(picked) >= 4:
            break
    return picked


# --- dim6a：语义节奏/事件链无状态迁移 机械候选层（只产候选不阻断） ---
# 裁决冻结：机械层高召回产候选（连续≥3 动作小句 / 位移链 / 程序链 /
# 高动作密度+低结果密度），narrative_state_delta 由仲裁层判定。
# 纯空间坐标改变不自动算 state delta。

_CLAUSE_SPLIT_RE = re.compile(r"[，、。！？；：]")
_DISPLACEMENT_VERB_RE = re.compile(
    r"(?:走|跑|进|出|上|下|回|到|来|去|穿|跨|爬|钻|拐|绕|"
    r"推开门|拉开|推开|迈进|踏入|走下|走上|走进|走出|回到|赶到|"
    r"坐|站|蹲|靠|躺|趴|停|开|关)")
_PROCEDURAL_VERB_RE = re.compile(
    r"(?:拿|取|放|倒|灌|切|拆|装|拧|掀|翻|递|接|按|点|铺|摆|"
    r"系|解|扣|刷|洗|擦|烧|煮|泡|折|卷|抽|插|拔|塞|压|盖|"
    r"烫|注|等|握|端|托|捧|掏|摸|揭|绑|缝|剪|扫|抹|涂|抬|扶|撑)")


def _event_chain_candidates(prose_text: str) -> list[dict]:
    """机械检测：连续事件链候选（语义节奏惰性探针）。

    规则（只召回不判定）：
    - 连续 ≥3 个含动作/位移/程序动词的小句成链
    - 链按叙述句段定位；同一 span 可有多链
    - 对白引号内容已剥除（narrative_spans_numbered）
    返回 [{"span", "excerpt", "chain_len", "kind"}]；
    kind ∈ displacement / procedural / generic。
    """
    spans = narrative_spans_numbered(prose_text)
    cands: list[dict] = []
    for i, span in enumerate(spans, 1):
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(span)
                   if c.strip()]
        run: list[str] = []
        # PC-DIALOGUE-COLLAPSE-01 冻结边界：shown dialogue 发言轮不属于
        # 本机制可压缩节点（其冗余归对白机制）。确定性打标：段内嵌
        # 「…」发言占位，或段尾冒号直接引出下一段发言轮。
        next_span = spans[i] if i < len(spans) else ""
        dialogue_bound = ("「…」" in span) or (
            span.rstrip().endswith(("：", ":"))
            and next_span.strip() == "「…」")
        def _flush():
            if len(run) >= 3:
                kinds = set()
                for cl in run:
                    if _DISPLACEMENT_VERB_RE.search(cl):
                        kinds.add("displacement")
                    if _PROCEDURAL_VERB_RE.search(cl):
                        kinds.add("procedural")
                    if _ACTION_SIGNAL_RE.search(cl):
                        kinds.add("action")
                kind = ("displacement" if kinds == {"displacement"}
                        else "procedural" if "procedural" in kinds
                        and "displacement" not in kinds
                        else "generic")
                excerpt = "，".join(run)
                cands.append({"span": i, "excerpt": excerpt[:80],
                              "chain_len": len(run), "kind": kind,
                              "dialogue_bound": dialogue_bound})
        for cl in clauses:
            if (_ACTION_SIGNAL_RE.search(cl)
                    or _DISPLACEMENT_VERB_RE.search(cl)
                    or _PROCEDURAL_VERB_RE.search(cl)):
                run.append(cl)
            else:
                _flush()
                run = []
        _flush()
    return cands


# --- MN V1：比喻必要性机械候选层（只产候选，不直接定罪） ---
# V1 范围声明（裁决冻结）：只收明喻/显式类比构式——带比较标记的
# figurative comparison。不收无标记暗喻/动词隐喻/转喻/词汇化隐喻。
# detection coverage = explicit figurative comparison only。
_METAPHOR_SIMILE_RE = re.compile(
    r"(?:像|如|仿佛|好似|宛如|犹如|如同|好比|恰似|似是)"
    r"[^。！？；，\n]{1,24}?"
    r"(?:一样|一般|似的|那般|那样|般地|一样地)"
)
# 弱构式：本体/喻体间只靠前缀标记无尾部呼应（「心像被针扎了一下」
# 「如刀锋的目光」）。冒烟证据：单靠前缀集 {犹如/如同/宛如/仿佛} 漏检
# 「像X+谓词」构式。字面比较/认知用法（像他这样的人/他像睡着了）会
# 混入候选——由仲裁 is_figurative 字段过滤，不在机械层裁决。
_METAPHOR_PREFIX_ONLY_RE = re.compile(
    r"(?:犹如|如同|宛如|仿佛|好似|恰似|像|如)"
    r"(?!果|此|何|今|下|上|前|后|常|实|期|意|数|约|样|话|素|章)"
    r"[^。！？；，\n]{1,18}?(?=[，。！？；\n]|$)"
)


def _metaphor_candidates(prose_text: str) -> list[dict]:
    """机械检测：显式比喻/类比候选（明喻标记构式）。

    规则（只产候选，供窄仲裁判定必要性）：
    - 强构式：标记词 + 喻体 + 呼应尾（像X一样/仿佛Y似的）
    - 弱构式：仅前缀标记的显性类比（犹如X）
    - 同一 span 内多处命中逐项列出
    返回 [{"span": 段号, "excerpt": 候选构式截断, "marker": 标记词,
           "vehicle": 喻体片段}]。
    """
    cands: list[dict] = []
    for i, span in enumerate(narrative_spans_numbered(prose_text), 1):
        for m in _METAPHOR_SIMILE_RE.finditer(span):
            seg = m.group(0)
            marker = re.match(r"(?:像|如|仿佛|好似|宛如|犹如|如同|好比|恰似|似是)",
                              seg).group(0)
            cands.append({"span": i, "excerpt": seg[:60],
                          "marker": marker,
                          "vehicle": seg[len(marker):][:30]})
        covered = [m.span() for m in _METAPHOR_SIMILE_RE.finditer(span)]
        for m in _METAPHOR_PREFIX_ONLY_RE.finditer(span):
            if any(s <= m.start() < e for s, e in covered):
                continue
            seg = m.group(0)
            marker = re.match(
                r"(?:犹如|如同|宛如|仿佛|好似|恰似|像|如|似是)",
                seg).group(0)
            cands.append({"span": i, "excerpt": seg[:60],
                          "marker": marker,
                          "vehicle": seg[len(marker):][:30]})
    return cands


def _detail_inventory_candidates(prose_text: str) -> list[dict]:
    """机械检测：枚举式细节堆叠候选（decorative_inventory 候选信号）。

    规则（只产候选，供窄仲裁判定功能归属）：
    - 句级判定：一句内含顿号枚举（≥3 并列名词项）或 ≥3 个静态陈设
      谓语，且该句无物理动作信号（观察取景动词除外——它恰恰引出清单）；
    - 段落级返回：含 ≥1 个候选句的段落记一个候选。
    返回 [{"span": 段号, "excerpt": 截断候选句, "items": 命中项数}]。
    """
    cands: list[dict] = []
    for i, span in enumerate(narrative_spans_numbered(prose_text), 1):
        hit_sentences = []
        for sent in _SENTENCE_SPLIT_RE.split(span):
            sent = sent.strip()
            if len(sent) < 8:
                continue
            if len(_NEGATION_LITANY_RE.findall(sent)) >= 2:
                continue
            enum_hits = _INVENTORY_ENUM_RE.findall(sent)
            enum_items = sum(h.count("、") + 1 for h in enum_hits)
            static_hits = len(_INVENTORY_STATIC_VERB_RE.findall(sent))
            if not (enum_items >= 3 or static_hits >= 3):
                continue
            stripped = _INVENTORY_STATIC_VERB_RE.sub("", sent)
            if _ACTION_SIGNAL_RE.search(stripped):
                continue
            hit_sentences.append((sent, max(enum_items, static_hits)))
        if hit_sentences:
            best = max(hit_sentences, key=lambda x: x[1])
            cands.append({
                "span": i,
                "excerpt": best[0][:60],
                "items": best[1],
            })
    return cands


def build_detail_adjudication_prompt(
        prose_text: str, candidates: list[dict],
        contract_context: str = "") -> str:
    """细节功能窄仲裁 prompt：对机械候选段抽事实，不判严重度。

    事实抽取项（供确定性裁决）：
    - 每个候选段：枚举项数、逐项功能归属、是否共享 collective function、
      删除损失；
    - detail_contract 在场时：计划承重细节是否写入正文并产生声明效应。
    """
    spans = narrative_spans_numbered(prose_text)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- 第{c['span']}段（{c['items']}项）: 「{c['excerpt']}」"
        for c in candidates)
    contract_block = (
        "\n【细节功能契约】（作者侧计划，供对照，不向读者公开）\n"
        + contract_context) if contract_context else ""
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号，机械检测"
        "标记了若干枚举式细节堆叠候选段。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【枚举候选段】\n" + cand_lines + "\n"
        + contract_block + "\n\n"
        "【功能分类】环境细节的合法功能：ORIENTATION（帮读者定位空间/"
        "位置）、ACTION_CONSTRAINT（限制或使能角色行动：距离/掩体/工具/"
        "出口）、SENSORY（使场景真实可感的感官锚点）、RELATIONAL（承载"
        "人物关系/地位/历史）、ATMOSPHERE（投射情绪/张力）。注意：功能"
        "必须在当前句段产生真实读者效应才成立——「用了颜色」不算完成"
        "感官功能，「写了阴暗形容词」不算完成氛围；多处细节可共享一个"
        "collective function（如空间建立镜头共享定位+行动约束），但"
        "该共享功能必须可在当前行动或后文兑现，不接受声明式自证。\n\n"
        "【抽取项】\n"
        "1. clusters：对每个候选段输出 {"
        "\"span\":段号,\"item_count\":枚举项数,"
        "\"functional_items\":能指出具体读者效应的项数,"
        "\"shared_function\":\"共同的collective function或null\","
        "\"function_realized\":共享/逐项功能是否真实兑现 true|false,"
        "\"expression_integrated\":功能是否以有效叙述形态落地（细节融入"
        "动作/感知/判断流），而非物件被声明存在/装修清单式插入 true|false,"
        "\"deletion_loss\":整段删除后读者是否失去定位/行动/感官/关系/"
        "氛围中任一能力 true|false}\n"
        "   注意 function_realized 与 expression_integrated 是两个独立事实："
        "细节可能确实传达了方位/规则信息（realized）但以清单式写法落地"
        "（not integrated）——两者不得混淆记分。\n"
        "2. contract_check：若有【细节功能契约】，对每个计划承重细节输出 "
        "{\"planned\":\"细节描述\",\"written\":是否写入正文,"
        "\"effect_delivered\":是否产生声明效应,"
        "\"expression_integrated\":是否以附着于动作/感知/判断的形态落地"
        "而非声明式/罗列式插入 true|false,"
        "\"deletion_loss\":若删去该细节，是否失去其声明的定位/动作约束/"
        "感官/关系/氛围功能之一 true|false}；无契约则输出 []\n"
        "3. stale_reuse：已建立细节的再现是否新增状态/作用/意义——列出"
        "仅为证明其持续存在而重复出现、无新增功能的细节及所在段号"
        "（如道具反复摆动但无新信息）；无则输出 []\n"
        "4. overload：环境细节密度是否稀释当前读者任务（关键交锋中被"
        "无关环境描写打断/淹没）true|false\n"
        "5. evidence：每个判定的一段原文证据\n\n"
        "【输出 JSON】{\"clusters\":[..],\"contract_check\":[..],"
        "\"stale_reuse\":[{\"detail\":\"..\",\"span\":n}],"
        "\"overload\":true|false,\"evidence\":\"..\"} 只输出 JSON。"
    )


def parse_detail_adjudication(response: str) -> dict:
    """解析细节仲裁响应中的 JSON 事实对象。"""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}


_DETAIL_ADJ_BOOL_KEYS = ("overload",)


def merge_detail_adjudication_runs(runs: list[dict]) -> dict:
    """多次细节仲裁投票合并：布尔多数决，clusters 按 span 对齐取多数事实。"""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    out: dict = {"overload": sum(
        1 for r in runs if r.get("overload")) > len(runs) / 2}
    # clusters 按 span 对齐：每个 span 取多数票的 function_realized /
    # deletion_loss，item_count/functional_items 取中位数
    by_span: dict[int, list[dict]] = {}
    for r in runs:
        for c in r.get("clusters") or []:
            s = c.get("span")
            if isinstance(s, int):
                by_span.setdefault(s, []).append(c)
    merged_clusters = []
    for s, cs in sorted(by_span.items()):
        n = len(cs)
        realized_votes = sum(1 for c in cs if c.get("function_realized"))
        integ_votes = sum(1 for c in cs if c.get("expression_integrated"))
        loss_votes = sum(1 for c in cs if c.get("deletion_loss"))
        merged_clusters.append({
            "span": s,
            "item_count": sorted(
                int(c.get("item_count") or 0) for c in cs)[n // 2],
            "functional_items": sorted(
                int(c.get("functional_items") or 0) for c in cs)[n // 2],
            "shared_function": next(
                (c.get("shared_function") for c in cs
                 if c.get("shared_function")), None),
            "function_realized": realized_votes > n / 2,
            "expression_integrated": integ_votes > n / 2,
            "deletion_loss": loss_votes > n / 2,
            "votes": n,
        })
    out["clusters"] = merged_clusters
    # contract_check 按 planned 对齐取多数
    by_planned: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("contract_check") or []:
            p = (c.get("planned") or "")[:30]
            if p:
                by_planned.setdefault(p, []).append(c)
    out["contract_check"] = [{
        "planned": p,
        "written": sum(1 for c in cs if c.get("written")) > len(cs) / 2,
        "effect_delivered": sum(
            1 for c in cs if c.get("effect_delivered")) > len(cs) / 2,
        "expression_integrated": sum(
            1 for c in cs if c.get("expression_integrated")) > len(cs) / 2,
        "deletion_loss": (
            sum(1 for c in cs if c.get("deletion_loss")) > len(cs) / 2
            if any("deletion_loss" in c for c in cs) else None),
    } for p, cs in by_planned.items()]
    # stale_reuse：召回偏置（≥1 票即采纳——机械复用漏检代价高于误报，
    # 误报只产 warning）
    stale: list[dict] = []
    for r in runs:
        for s in r.get("stale_reuse") or []:
            if isinstance(s, dict) and s.get("detail"):
                stale.append({"detail": s["detail"][:40],
                              "span": s.get("span")})
    out["stale_reuse"] = stale[:4]
    out["evidence"] = next(
        (r.get("evidence") for r in runs if r.get("evidence")), "")
    return out


def detail_function_verdict(facts: dict) -> str:
    """确定性严重度裁决（DFD V1.1：功能与表达分层）。

    返回 issue_type 或 "none"/warning 级类型。
    - 成簇候选段（≥3 枚举项）无真实功能且无删除损失
      → decorative_inventory blocking
    - 成簇/契约细节功能成立但 expression_integrated=false（清单式落地，
      「物件被声明存在」）→ functional_but_detached blocking
      （D06 证据：计划细节正确仍被 3/4 判读作清单腔——功能与表达是
      两个独立事实，rewrite 只改承载方式不重选细节）
    - 部分承重/未达簇阈值/契约计划细节漏写/已建立细节无新增复用
      → functionless_detail warning
    - 密度过载 → detail_overload warning
    """
    clusters = facts.get("clusters") or []
    verdicts: list[str] = []
    detached = False
    for c in clusters:
        realized = c.get("function_realized")
        integrated = c.get("expression_integrated")
        loss = c.get("deletion_loss")
        items = int(c.get("item_count") or 0)
        fitems = int(c.get("functional_items") or 0)
        if realized:
            if integrated is False:
                detached = True
            continue
        # 成簇无功能：≥3 项枚举 + 功能占比 ≤1/4 + 无删除损失
        # （POS_INV 证据：6 项清单被记 1 项沾边仍本质是清单）
        if items >= 3 and fitems * 4 <= items and not loss:
            verdicts.append("decorative_inventory")
        else:
            verdicts.append("functionless_detail")
    deletable = 0
    for cc in (facts.get("contract_check") or []):
        delivered = cc.get("effect_delivered")
        if cc.get("written") is False or delivered is False:
            verdicts.append("functionless_detail")
        elif delivered:
            if cc.get("expression_integrated") is False:
                detached = True
            # 声明承重但删除无损（D06 证据：登记本+告示被盲评一致
            # 旗标「删除后无损失的清单腔」，而逐项附着判定被放过）——
            # 删除检验是读者侧的功能兑现代理，delivered 声明被其否决
            if cc.get("deletion_loss") is False:
                deletable += 1
    if deletable >= 2:
        verdicts.append("decorative_inventory")
    elif deletable == 1:
        verdicts.append("functionless_detail")
    if "decorative_inventory" in verdicts:
        return "decorative_inventory"
    if detached:
        return "functional_but_detached"
    if verdicts or facts.get("stale_reuse"):
        return "functionless_detail"
    if facts.get("overload"):
        return "detail_overload"
    return "none"


def build_dialogue_adjudication_prompt(
        prose_text: str, terms: list[str] | None = None) -> str:
    """对白重复候选的窄仲裁 prompt（V1.8：逐字 + 转述双通道）。

    只抽取事实、不判严重度：是否对已确认命题逐字/换措辞重述、
    重述是否有文本可见的功能豁免、是否存在压力消散结构。
    terms 为逐字 n-gram 机械候选线索（可为空，此时仲裁检查全对白
    是否存在任何被重复声明的已确认命题）。
    严重度由 dialogue_echo_verdict() 确定性裁决。
    """
    turns = dialogue_turns_numbered(prose_text)
    numbered = "\n".join(f"[{i}] {q}" for i, q in enumerate(turns, 1))
    nspans = narrative_spans_numbered(prose_text)
    nnumbered = "\n".join(f"[N{i}] {s}" for i, s in enumerate(nspans, 1))
    hint = ("【重现表述】\n" + "\n".join(f"- {t}" for t in terms) + "\n\n"
            if terms else
            "机械检测未找到逐字重现表述——请检查是否存在同一已确认命题"
            "被换措辞反复声明的轮次。\n\n")
    return (
        "你只回答一个窄问题。下面小说正文中可能存在对白重复声明同一"
        "社会命题的缺陷。\n\n"
        + hint +
        "【对白轮次（已编号）】\n" + numbered + "\n\n"
        "【叙述段落（已编号，对白内容以「…」占位）】\n" + nnumbered + "\n\n"
        "【判定】\n"
        "1. acknowledged：是否存在一个社会命题（承诺/条件/边界/风险/限制/"
        "资格标准）已在前面轮次被完整陈述并成文（对方同意与否不限，"
        "只需已明确摆上台面获得实质回应）。\n"
        "2. echo_turns：确认之后，哪些对白轮次再次以逐字/高度近似措辞重述"
        "同一命题的关键表述（列出轮次序号，从1计）。只要该命题的核心承诺/"
        "条件/边界以近乎相同措辞被再说一遍即算，不要求整轮逐字。"
        "关键：若一次重提附加了新的条件、限定、交换物、威胁或资格标准，"
        "视为新 move，不算复读。\n"
        "2b. paraphrase_echo_turns：确认之后，哪些轮次以【不同措辞】再次"
        "声明同一已确认命题的社会内容（换说法、换角度、换句式但承诺/"
        "条件/边界/风险本身不变——如『期满再谈』『以后再谈聘用』『保持"
        "现有身份直到合同结束』属同一命题）。同样排除带新条件的重提。\n"
        "2c. restatements：对 echo_turns 与 paraphrase_echo_turns 中的每一轮，"
        "给出它重述的命题最早由哪一轮陈述（输出 [{\"turn\":重述轮,\"of\":"
        "最早陈述轮}]）。重述不同命题的轮次会有不同的 of 锚点——"
        "不要为了让数字整齐而把不同命题合并。\n"
        "排除（两类共通）：为回应对方新提出的【未获得过实质回应的】问题/"
        "异议而作的应答轮次（被动应答不是自愿复述）；但若对方是在重提一个"
        "已获实质回应的旧问题（无新信息角度），则该问与答整体都计入——"
        "旧问题重开本身就是复述缺陷。也排除提出新要求或施压的轮次。\n"
        "3. 逐字功能豁免（逐项独立判 true/false，仅当文本可见对应证据时记 true）：\n"
        "   a. formal_readback：正式逐字宣读/read-back、法律/程序要求原文确认、"
        "      引用对方原话纠错或对质、誓言仪式等形式要求。"
        "      『双方各自重申立场以便记录』不算——若改用『按刚才的条件记下』"
        "      等指代即可保持最终状态不变，记 false。\n"
        "   b. new_audience：换了新受众必须完整重传。\n"
        "   c. directive_transform：把已确认条件转化为后续行动或文件的"
        "      具体指令，且该轮存在明确的指令对象与行动要求"
        "      （让某人去做/去写/去执行）；仅复述谈判立场或声明条款"
        "      会算进合同，不算指令转化。\n"
        "   d. refusal_relitigation：存在『一方重开已获实质回应的旧问题、"
        "      另一方明确拒绝重新展开并以重申条款顶回』的结构，"
        "      且文本可见显式顶回标记（如『我已经说过』『不再重复』"
        "      『规则不变』式拒绝）；若应答方把已答内容再次完整展开"
        "      陈述一遍，不算顶回，整组仍按复述缺陷处理。\n"
        "   e. pressure_shift：有意复读施压且第二次确实改变了局面。\n\n"
        "4. pressure_dissipation：是否存在『一方提出的问题或施加的压力，"
        "被另一方以沉默/转移话题/不置可否/无代价回避等方式使压力消散"
        "且持续≥2轮』的结构。注意：形式上『有回应』不等于实质回应——"
        "转移、拖延、不承诺的软回绝都算压力消散。仅当文本可见该结构时"
        "记 true。\n"
        "5. unanswered_reasks：若 acknowledged=false，检查是否存在对同一"
        "问题以近似措辞反复追问、且对方始终以沉默/转移/不答应回避实质回应"
        "的轮次（列出追问轮次序号）。这是压力消散签名，不是复述。\n"
        "6. objective_done：重复轮次开始时，本场主要交涉目标（谈成/拒绝/"
        "达成记录/建立边界等）是否已经完成；仍在拉锯、未定局记 false。\n"
        "7. narrative_repeats：【叙述段落】中是否存在同命题复述——某叙述段"
        "（含内心独白/计划回顾/情绪重述/场景重描）把已在前文完整确立的"
        "计划/事实/情绪状态原样或换措辞再陈述一遍且零新增信息（D02/D05"
        "证据：『先回城取物再出海』后文又以『短暂回到贝克兰德取回物品，"
        "然后出海寻找美人鱼』重述同一计划；『答案被留到明天』式情绪判断"
        "三段连说）。输出 [{\"span\":叙述段号,\"of\":最早陈述同一命题的"
        "叙述段号或对白轮号}]——跨段落锚定同一命题的各段用相同 of，"
        "不同命题不要合并锚点；段中新增条件/行动/对手信息不算复述；"
        "首次陈述本身不算复述，只列重述段。\n\n"
        "【输出 JSON】{\"acknowledged\":true|false,\"echo_turns\":[n..],"
        "\"paraphrase_echo_turns\":[n..],"
        "\"restatements\":[{\"turn\":n,\"of\":m}],"
        "\"narrative_repeats\":[{\"span\":n,\"of\":m}],"
        "\"formal_readback\":true|false,\"new_audience\":true|false,"
        "\"directive_transform\":true|false,\"refusal_relitigation\":true|false,"
        "\"pressure_shift\":true|false,\"pressure_dissipation\":true|false,"
        "\"unanswered_reasks\":[n..],\"objective_done\":true|false,"
        "\"evidence\":\"<=60字\"} 只输出 JSON。"
    )


def parse_dialogue_adjudication(response: str) -> dict:
    """解析仲裁响应中的 JSON 事实对象。"""
    m = re.search(r"\{.*\}", response or "", re.S)
    return json.loads(m.group(0)) if m else {}


_DIALOGUE_ADJ_BOOL_KEYS = (
    "acknowledged", "formal_readback", "new_audience",
    "directive_transform", "refusal_relitigation",
    "pressure_shift", "pressure_dissipation", "objective_done",
)


def merge_adjudication_runs(runs: list[dict]) -> dict:
    """多次仲裁结果投票合并：布尔多数决，轮次字段按 ≥半数运行命中保留。"""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    out: dict = {}
    for key in _DIALOGUE_ADJ_BOOL_KEYS:
        vals = [bool(r.get(key)) for r in runs]
        if key == "pressure_dissipation":
            # 召回偏置：该结构漏检代价高于误检，任一运行检出即采纳
            #（其余豁免字段维持多数决——误放代价不对称）。
            out[key] = any(vals)
        else:
            out[key] = vals.count(True) > len(vals) / 2
    need = len(runs) / 2.0
    out["echo_turns"] = sorted(
        {t for t in
         (x for r in runs for x in (r.get("echo_turns") or []))
         if sum(t in (r.get("echo_turns") or []) for r in runs) > need})
    out["unanswered_reasks"] = sorted(
        {t for t in
         (x for r in runs for x in (r.get("unanswered_reasks") or []))
         if sum(t in (r.get("unanswered_reasks") or [])
                for r in runs) > need})
    out["paraphrase_echo_turns"] = sorted(
        {t for t in
         (x for r in runs for x in (r.get("paraphrase_echo_turns") or []))
         if sum(t in (r.get("paraphrase_echo_turns") or [])
                for r in runs) > need})
    edges = set()
    for r in runs:
        for e in (r.get("restatements") or []):
            if isinstance(e, dict):
                t, o = e.get("turn"), e.get("of")
                if isinstance(t, int) and isinstance(o, int):
                    edges.add((t, o))
    out["restatements"] = sorted(
        [list(e) for e in edges
         if sum(e in {
             (x.get("turn"), x.get("of"))
             for x in (r.get("restatements") or []) if isinstance(x, dict)}
             for r in runs) > need])
    # narrative_repeats：叙述段级同命题复述——按 span 多数决保留，
    # 锚点取命中票众数；同锚聚簇（叙述段号与对白轮号共享锚点语义：
    # 指向同一最早命题陈述即同簇）
    nr_votes: dict[int, list] = {}
    for r in runs:
        for e in (r.get("narrative_repeats") or []):
            if isinstance(e, dict) and isinstance(e.get("span"), int):
                nr_votes.setdefault(e["span"], []).append(e.get("of"))
    nr = []
    for s, ofs in nr_votes.items():
        if len(ofs) > need:
            anchors = [o for o in ofs if isinstance(o, int)]
            nr.append({"span": s,
                       "of": max(set(anchors), key=anchors.count)
                       if anchors else None})
    out["narrative_repeats"] = sorted(nr, key=lambda e: e["span"])
    nr_edges = [(e["span"], e["of"]) for e in nr
                if isinstance(e.get("of"), int)]
    nr_counts = _repeat_cluster_counts([e["span"] for e in nr], nr_edges)
    out["narrative_repeat_max"] = max(nr_counts.values()) if nr_counts else 0
    return out


def _repeat_cluster_counts(repeats, edges):
    """按 restatements 锚点把重述轮聚到同一命题族，返回各簇重述轮数。

    并查集：边 (turn, of) 把重述轮并入其命题锚点所在集合；无锚点的
    重述轮自成单轮簇。损伤本质是『同一命题被反复确认』，跨命题各
    收尾一次不算车轱辘（E06 证据）。
    """
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int):
        parent[find(a)] = find(b)

    for e in edges:
        if isinstance(e, (list, tuple)) and len(e) == 2:
            t, o = e
            if isinstance(t, int) and isinstance(o, int):
                union(t, o)
    counts: dict[int, int] = {}
    for t in repeats:
        root = find(t)
        counts[root] = counts.get(root, 0) + 1
    return counts


def dialogue_echo_verdict(facts: dict, prose_text: str) -> str:
    """确定性严重度裁决（V1.9：逐字/转述双通道 + 同命题聚簇）。

    返回 issue_type 或 "none"/"no_turn_delta"。
    - pressure_dissipation / unanswered_reasks≥2 → no_response_pressure
    - 同命题簇内逐字重述 ≥3 轮 + 无豁免 → formal_echo_after_ack
    - 同命题簇内重复总轮（逐字+转述）≥3 + 无豁免 → objective_done ?
      excessive_redundant_tail : dialogue_loop_stasis
    - 最大簇 = 2 → no_turn_delta（warning 级，不阻断）
    豁免：formal_readback / new_audience / refusal_relitigation /
    pressure_shift。directive_transform 仅记录不否决（F06 证据：模型
    对『条款算进合同』误读率高，该功能由 new_audience 覆盖）。
    无 restatements 锚点时回退为全体重述轮同一簇（V1.8 行为）。
    """
    if facts.get("pressure_dissipation"):
        return "no_response_pressure"
    # 叙述层同命题复述（D02/D05 回归证据：计划/情绪在叙述段被原样重述，
    # 对白轮次信号无从覆盖）——同锚复述段 ≥2 即阻断，注入 redundancy
    if (facts.get("narrative_repeat_max") or 0) >= 2:
        return "redundancy"
    if not facts.get("acknowledged"):
        if len(facts.get("unanswered_reasks") or []) >= 2:
            return "no_response_pressure"
        return "none"
    echos = facts.get("echo_turns") or []
    paras = facts.get("paraphrase_echo_turns") or []
    repeats = sorted(set(echos) | set(paras))
    if len(repeats) < 2:
        return "none"
    edges = [e for e in (facts.get("restatements") or [])
             if isinstance(e, (list, tuple)) and len(e) == 2]
    if edges:
        rep_counts = _repeat_cluster_counts(repeats, edges)
        echo_counts = _repeat_cluster_counts(echos, edges)
        max_rep = max(rep_counts.values())
        max_echo = max(echo_counts.values()) if echo_counts else 0
    else:
        max_rep, max_echo = len(repeats), len(echos)
    refusal = facts.get("refusal_relitigation")
    if not refusal:
        # 机械兜底：重复簇内/邻位存在显式顶回标记 → 顶回结构成立
        qs = dialogue_turns_numbered(prose_text)
        for t in repeats:
            for j in (t - 1, t, t + 1):
                if 1 <= j <= len(qs) and _DIALOGUE_REFUSAL_MARK_RE.search(
                        qs[j - 1]):
                    refusal = True
                    break
            if refusal:
                break
    if refusal or any(facts.get(k) for k in (
            "formal_readback", "new_audience", "pressure_shift")):
        return "none"
    if max_echo >= 3:
        return "formal_echo_after_ack"
    if max_rep >= 3:
        return ("excessive_redundant_tail" if facts.get("objective_done")
                else "dialogue_loop_stasis")
    if _DIALOGUE_READBACK_RITUAL_RE.search(prose_text or ""):
        return ("excessive_redundant_tail" if facts.get("objective_done")
                else "dialogue_loop_stasis")
    return "no_turn_delta"


_DIALOGUE_LOOP_ISSUE_TYPES = frozenset({
    "dialogue_loop_stasis", "excessive_redundant_tail",
    "formal_echo_after_ack", "no_response_pressure",
})
_DIALOGUE_ADJUDICATED_TYPES = frozenset({
    "dialogue_loop_stasis", "excessive_redundant_tail",
    "formal_echo_after_ack",
})


def apply_dialogue_adjudication(
        issues: list, verdict: str,
        facts: dict | None = None,
        prose_text: str = "") -> tuple[list, object]:
    """把仲裁裁决应用回 issue 集合。

    - loop 族 blocking（loop_stasis/excessive_tail/formal_echo）若裁决为
      none/no_turn_delta → 从集合剔除；
    - 裁决为 blocking 类型且集合无 loop 族 blocking → 注入合成 issue；
    - no_response_pressure 不被 echo 仲裁否决（签名路由独立成立）。

    注入合成 issue 时携带仲裁事实中的重述轮定位（轮次+锚点+引文摘录），
    使 rewrite 能精确压缩被判定的轮次而不是凭猜测（H08 证据：仅有
    verdict 名的 issue 导致三方接力复述残留）。

    返回 (new_issues, synthetic_issue_or_None)。
    """
    issues = list(issues)
    if verdict in ("none", "no_turn_delta"):
        issues = [i for i in issues
                  if getattr(i, "issue_type", "")
                  not in _DIALOGUE_ADJUDICATED_TYPES]
        return issues, None
    blocking_loop = [i for i in issues
                     if getattr(i, "issue_type", "")
                     in _DIALOGUE_ADJUDICATED_TYPES
                     and getattr(i, "severity", "") in ("blocking", "critical")]
    if blocking_loop:
        return issues, None
    if verdict == "redundancy":
        # 叙述层同命题复述注入（lexicon redundancy 默认 warning，
        # 此处条件阻断——同锚复述段≥2）
        existing = [i for i in issues
                    if getattr(i, "issue_type", "") == "redundancy"
                    and getattr(i, "severity", "")
                    in ("blocking", "critical")]
        if existing:
            return issues, None
        desc = "narrative adjudicator verdict=redundancy"
        if facts:
            nspans = narrative_spans_numbered(prose_text)
            parts = []
            for e in (facts.get("narrative_repeats") or [])[:6]:
                s = e.get("span")
                if isinstance(s, int) and 1 <= s <= len(nspans):
                    parts.append(
                        f"第N{s}段(复述锚{e.get('of')}): "
                        f"「{nspans[s-1][:40]}」")
            if parts:
                desc += " | 需压缩叙述段: " + "；".join(parts)
        syn = ReviewIssue(
            issue_id="narr_adj_1", issue_type="redundancy",
            severity="blocking",
            location="叙述同命题复述段", scope_of_impact="场景节奏与在场感",
            violated_rule="重复控制",
            description=desc)
        issues.append(syn)
        return issues, syn
    if verdict in _DIALOGUE_LOOP_ISSUE_TYPES:
        desc = "dialogue adjudicator verdict=" + verdict
        if facts:
            parts = []
            rs = facts.get("restatements") or []
            # merge 输出为 [turn, of] 列表对；容忍 dict 形以兼容旧事实文件
            def _rs_pair(r):
                if isinstance(r, dict):
                    return r.get("turn"), r.get("of")
                if isinstance(r, (list, tuple)) and len(r) == 2:
                    return r[0], r[1]
                return None, None
            if rs:
                parts.append("重述轮→锚轮: " + "; ".join(
                    f"{t}→{o}" for t, o in
                    (_rs_pair(r) for r in rs)
                    if isinstance(t, int) and isinstance(o, int)))
            else:
                rep = sorted(set(
                    list(facts.get("echo_turns") or [])
                    + list(facts.get("paraphrase_echo_turns") or [])))
                if rep:
                    parts.append("重述轮: " + ",".join(map(str, rep)))
            turns = dialogue_turns_numbered(prose_text)
            if turns and parts:
                snips = []
                for r in rs[:6]:
                    t, _ = _rs_pair(r)
                    if isinstance(t, int) and 1 <= t <= len(turns):
                        snips.append(f"第{t}轮「{turns[t-1][:30]}」")
                if snips:
                    parts.append("需压缩轮原文: " + "；".join(snips))
            if parts:
                desc += " | " + " | ".join(parts)
        syn = ReviewIssue(
            issue_id="dlg_adj_1", issue_type=verdict, severity="blocking",
            location="对白重复轮次", scope_of_impact="本场交锋",
            violated_rule="对白作为社会行动",
            description=desc)
        issues.append(syn)
        return issues, syn
    return issues, None


_DETAIL_ADJUDICATED_TYPES = frozenset({
    "decorative_inventory", "functionless_detail", "detail_overload",
    "functional_but_detached",
})
_DETAIL_BLOCKING_TYPES = frozenset({
    "decorative_inventory", "functional_but_detached",
})


def apply_detail_adjudication(
        issues: list, verdict: str,
        facts: dict | None = None,
        prose_text: str = "") -> tuple[list, object]:
    """把细节仲裁裁决应用回 issue 集合。

    - 裁决 none/warning 级 → 剔除 detail 族 blocking（仲裁覆核权）；
    - decorative_inventory 且集合无 detail blocking → 注入合成 issue
      （携带候选段定位+枚举摘录，供 rewrite 精确压缩）；
    - functionless_detail/detail_overload 为 warning 级，不注入 blocking。

    返回 (new_issues, synthetic_issue_or_None)。
    """
    issues = list(issues)
    if verdict not in _DETAIL_BLOCKING_TYPES:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _DETAIL_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical"))]
        return issues, None
    existing = [i for i in issues
                if getattr(i, "issue_type", "") in _DETAIL_ADJUDICATED_TYPES
                and getattr(i, "severity", "")
                in ("blocking", "high", "critical")]
    if existing:
        return issues, None
    desc = "detail adjudicator verdict=" + verdict
    if facts:
        spans = narrative_spans_numbered(prose_text)
        parts = []
        for c in (facts.get("clusters") or [])[:6]:
            s = c.get("span")
            if isinstance(s, int) and 1 <= s <= len(spans):
                tag = ("清单式落地"
                       if c.get("function_realized")
                       else f"承重{c.get('functional_items')}项")
                parts.append(
                    f"第{s}段（{c.get('item_count')}项，{tag}）: "
                    f"「{spans[s-1][:40]}」")
        for cc in (facts.get("contract_check") or [])[:4]:
            if (cc.get("effect_delivered")
                    and cc.get("expression_integrated") is False):
                parts.append(
                    f"契约细节「{cc.get('planned','')[:30]}」"
                    "功能成立但表达为声明/罗列式插入")
            elif (cc.get("effect_delivered")
                    and cc.get("deletion_loss") is False):
                parts.append(
                    f"契约细节「{cc.get('planned','')[:30]}」"
                    "声明承重但删除无损——须改写为影响当前状态/行动")
        if parts:
            desc += " | 需处理: " + "；".join(parts)
    syn = ReviewIssue(
        issue_id="dfd_adj_1", issue_type=verdict, severity="blocking",
        location="枚举式细节堆叠段", scope_of_impact="本场景在场感",
        violated_rule="细节功能密度",
        description=desc)
    issues.append(syn)
    return issues, syn


# --- MN V1：比喻必要性窄仲裁（事实抽取 → 确定性裁决） ---
# 裁决冻结要点：
# - function 只是描述（比喻在做什么），不拥有保留否决权；
#   function_realized ≠ necessity_established。
# - literal_adequacy gate：adjudicator 必须先产出最强直述替换并验证其
#   合格（防「写个烂直述证明比喻必要」）；不合格 → NOT_EVALUABLE，
#   不等于「比喻必要」。
# - viewpoint/continuity 需要可观察证据（认知立场 delta / 前文意象
#   antecedent span），不接受「更有感觉/气质一致」式声明。

def build_metaphor_adjudication_prompt(
        prose_text: str, candidates: list[dict]) -> str:
    """比喻必要性窄仲裁 prompt：对机械候选抽事实，不判严重度。

    事实抽取项（供确定性裁决）：
    - 每处候选：primary/secondary function（各至多 1 个，不许堆标签）、
      最强直述替换、literal adequacy 五查、substitution_loss；
    - 仅当替换合格才判 substitution_loss；不合格标记 not_evaluable。
    """
    spans = narrative_spans_numbered(prose_text)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- 第{c['span']}段: 「{c['excerpt']}」（标记 {c['marker']}）"
        for c in candidates)
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号，机械检测"
        "标记了若干显式比喻/类比候选。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【比喻候选】\n" + cand_lines + "\n\n"
        "【功能分类】（每处候选至多 1 个 primary + 1 个 secondary，"
        "功能必须指出具体读者效应才可记，不许堆标签凑「功能多」）\n"
        "compression 压缩复杂关系为单个意象 | concretization 抽象转可感知 | "
        "relational_map 映射结构关系 | viewpoint 暴露人物认知/立场"
        "（需指出比直述多出的具体认知立场变化：感知框架/认知姿态/评价框架/"
        "聚焦点之一；「更有画面/更有感觉/更朦胧/更有氛围」不算） | "
        "affective_load 改变情绪强度 | continuity 承接前文已建立意象"
        "（需指出 echo_target_span=前文采象所在段号 + 关系 callback/"
        "transformed_echo/motif_progression；气质一致不算）\n\n"
        "【抽取项】对每个候选输出：\n"
        "{\"span\":段号,\"excerpt\":\"候选原文片段\","
        "\"is_figurative\":true|false——候选是否为比喻性类比；字面比较"
        "（像他这样的人/和以前一样）或认知性用法（他像睡着了/仿佛在"
        "想事情）标 false，其余字段可填 null,"
        "\"primary_function\":\"六类之一或null\","
        "\"secondary_function\":\"六类之一或null\","
        "\"function_evidence\":\"该功能的具体读者效应（一句话，无则null）\","
        "\"viewpoint_delta\":\"若为viewpoint：比直述多出的认知立场变化，否则null\","
        "\"echo_target_span\":若为continuity：前文意象所在段号，否则null,"
        "\"literal_replacement\":\"最强等价直述替换稿（保留事实与对象，"
        "不偷换为另一个比喻，不擅自加信息）\","
        "\"literal_adequacy\":{\"proposition_preserved\":true|false,"
        "\"referent_preserved\":true|false,\"no_new_fact\":true|false,"
        "\"no_new_figure\":true|false,\"contextual_fit\":true|false},"
        "\"substitution_loss\":\"三态 token：literal_adequacy 任一不合格"
        "→ not_evaluable；全过且替换无实质损失 → none；全过且有实质损失"
        "→ meaningful\","
        "\"loss_evidence\":\"若 meaningful：损失的具体能力一句话"
        "（压缩/映射/立场/情绪/意象承接；「不够生动/没文采」不算），"
        "否则 null\"}\n\n"
        "【输出 JSON】{\"candidates\":[..]} 只输出 JSON。"
    )


def parse_metaphor_adjudication(response: str) -> dict:
    """解析比喻仲裁响应中的 JSON 事实对象。"""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def merge_metaphor_adjudication_runs(runs: list[dict]) -> dict:
    """多次比喻仲裁投票合并：按 span+excerpt 前缀对齐取多数事实。"""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    by_key: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("candidates") or []:
            key = f"{c.get('span')}:{(c.get('excerpt') or '')[:12]}"
            by_key.setdefault(key, []).append(c)
    merged = []
    for key, cs in by_key.items():
        n = len(cs)
        # literal adequacy 五查逐条多数决；全过才 PASS
        la_keys = ("proposition_preserved", "referent_preserved",
                   "no_new_fact", "no_new_figure", "contextual_fit")
        la = {k: (sum(1 for x in cs
                      if isinstance(x.get("literal_adequacy"), dict)
                      and x["literal_adequacy"].get(k)) > n / 2)
              for k in la_keys}
        sl_votes = []
        for c in cs:
            v = c.get("substitution_loss")
            # 模型可能回描述性文本而非 token——描述串≠none/not_evaluable
            # 即视为 meaningful 主张（具体损失声明），None 才算未评估
            if v in ("none", "not_evaluable", "meaningful"):
                sl_votes.append(v)
            elif v:
                sl_votes.append("meaningful")
            else:
                sl_votes.append("not_evaluable")
        merged.append({
            "span": cs[0].get("span"),
            "excerpt": cs[0].get("excerpt"),
            "is_figurative": sum(
                1 for c in cs if c.get("is_figurative") is not False) > n / 2,
            "primary_function": next(
                (c.get("primary_function") for c in cs
                 if c.get("primary_function")), None),
            "secondary_function": next(
                (c.get("secondary_function") for c in cs
                 if c.get("secondary_function")), None),
            "literal_replacement": next(
                (c.get("literal_replacement") for c in cs
                 if c.get("literal_replacement")), ""),
            "literal_adequacy": la,
            "adequacy_pass": all(la.values()) if la else False,
            "substitution_loss": (
                "none" if sum(1 for v in sl_votes if v == "none") > n / 2
                else ("meaningful" if sum(
                    1 for v in sl_votes if v == "meaningful") > n / 2
                    else "not_evaluable")),
            "loss_evidence": next(
                (c.get("loss_evidence") for c in cs
                 if c.get("loss_evidence")), None),
            "votes": n,
        })
    return {"candidates": merged}


def metaphor_necessity_verdict(facts: dict) -> str:
    """确定性裁决（MN V1）：function 无否决权，necessity 由替换损失决定。

    - 任一候选：literal_adequacy 全过 且 substitution_loss=none
      → gratuitous_metaphor blocking（替换无损 = 不必要比喻）
    - 全部候选 adequacy 不合格（not_evaluable 居多）→ none
      （不判必要，只不干预——烂直述不证明比喻必要）
    - substitution_loss=meaningful → keep，不计入
    """
    for c in facts.get("candidates") or []:
        if (c.get("is_figurative", True)
                and c.get("adequacy_pass")
                and c.get("substitution_loss") == "none"):
            return "gratuitous_metaphor"
    return "none"


_METAPHOR_ADJUDICATED_TYPES = frozenset({"gratuitous_metaphor"})
_METAPHOR_BLOCKING_TYPES = frozenset({"gratuitous_metaphor"})


def apply_metaphor_adjudication(
        issues: list, verdict: str,
        facts: dict | None = None,
        prose_text: str = "") -> tuple[list, object]:
    """把比喻仲裁裁决应用回 issue 集合。

    - 裁决 none → 剔除 metaphor 族 blocking（仲裁覆核权）；
    - gratuitous_metaphor → 注入合成 issue（携带段定位+直述替换稿，
      供 rewrite 精确替换）。
    返回 (new_issues, synthetic_issue_or_None)。
    """
    issues = list(issues)
    if verdict not in _METAPHOR_BLOCKING_TYPES:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _METAPHOR_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical"))]
        return issues, None
    existing = [i for i in issues
                if getattr(i, "issue_type", "") in _METAPHOR_ADJUDICATED_TYPES
                and getattr(i, "severity", "")
                in ("blocking", "high", "critical")]
    if existing:
        return issues, None
    desc = "metaphor adjudicator verdict=" + verdict
    if facts:
        parts = []
        for c in (facts.get("candidates") or []):
            if (c.get("is_figurative", True)
                    and c.get("adequacy_pass")
                    and c.get("substitution_loss") == "none"):
                parts.append(
                    f"第{c.get('span')}段「{(c.get('excerpt') or '')[:40]}」"
                    f"→ 替换为直述「{(c.get('literal_replacement') or '')[:50]}」")
        if parts:
            desc += " | 需处理: " + "；".join(parts[:4])
    syn = ReviewIssue(
        issue_id="mn_adj_1", issue_type=verdict, severity="blocking",
        location="显式比喻候选段", scope_of_impact="表达经济性",
        violated_rule="比喻必要性",
        description=desc)
    issues.append(syn)
    return issues, syn


# --- dim6a：语义节奏/事件链无状态迁移 窄仲裁（事实抽取 → 确定性裁决） ---
# 裁决冻结：
# - blocking 须同时满足：event_chain=true AND state_delta=false AND
#   chain_function=false AND compression_loss=none_or_trivial
# - narrative_state_delta 八轴：goal/intention/decision | knowledge/belief |
#   relationship/power | constraint/affordance | risk/stakes |
#   resource/possession/status | physical_condition | causal_commitment/
#   outcome。纯空间坐标改变不自动算 delta。
# - NO_STATE_DELTA ≠ 自动缺陷：链条承担 suspense/timing/ritual/
#   characterization/spatial_causality/sensory_buildup/comic_dramatic_timing
#   即 KEEP。
# - intervention 只有 COMPRESS_EVENT_CHAIN / SURFACE_EXISTING_STATE_DELTA；
#   禁止现场发明状态后果（delta 须已存在于下游 prose/计划/契约）。

def build_pacing_adjudication_prompt(
        prose_text: str, candidates: list[dict]) -> str:
    """语义节奏窄仲裁 prompt：对事件链候选抽事实，不判严重度。"""
    spans = narrative_spans_numbered(prose_text)
    numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(spans, 1))
    cand_lines = "\n".join(
        f"- 第{c['span']}段({c['kind']}链,{c['chain_len']}小句): "
        f"「{c['excerpt']}」"
        + ("【dialogue_bound：包裹/引出 shown dialogue 发言轮，"
           "本机制不可压缩，仅需回报 event_chain 字段】"
           if c.get("dialogue_bound") else "")
        for c in candidates)
    return (
        "你只抽取事实，不判严重度。下面小说正文按叙述句段编号，机械检测"
        "标记了若干连续事件链候选（动作/位移/程序小句连发）。\n\n"
        "【编号叙述句段】\n" + numbered + "\n\n"
        "【事件链候选】\n" + cand_lines + "\n\n"
        "【narrative_state_delta 八轴】（链走完后发生实际变化的轴；"
        "纯空间坐标改变不自动算）\n"
        "goal/intention/decision | knowledge/belief | relationship/power | "
        "constraint/affordance | risk/stakes | resource/possession/status | "
        "physical_condition | causal_commitment/outcome\n\n"
        "【抽取项】对每个候选输出：\n"
        "{\"span\":段号,\"excerpt\":\"候选原文片段\","
        "\"event_chain\":true|false——确为连续事件链（误报标false）,"
        "\"state_delta\":{\"changed\":true|false,"
        "\"axes\":[\"实际变化的轴名列表，无则空\"]},"
        "\"chain_function\":{\"present\":true|false,"
        "\"kind\":\"suspense_timing|ritual|characterization|"
        "spatial_causality|sensory_buildup|comic_dramatic_timing 之一或null\","
        "\"evidence\":\"该功能的具体读者效应一句话，无则null\"},"
        "\"compression\":\"把此链压缩到「最小充分步骤」——保留最终结果与"
        "链的功能，只删并中间死步骤（如七步位移→「他径直走进电报局」），"
        "不是整链删除。合法压缩只允许在同一自然段内删并步骤：不得跨段落/"
        "空行边界合并（段界本身是节拍结构），不得把对白发言轮转成叙述摘要"
        "（shown dialogue 不可压，其冗余归对白机制）："
        "none_or_trivial=在上述边界内压缩后读者几乎无损失 | "
        "meaningful=压缩会损失具体内容，或实质压缩必须越界才可能"
        "（说明损失什么） | not_evaluable=无法判断\","
        "\"compression_evidence\":\"meaningful 时损失什么一句话，否则null\","
        "\"existing_delta_downstream\":\"下游正文是否已有可前置/并接的"
        "状态变化事实（供 SURFACE_EXISTING_STATE_DELTA）：段号或null\"}\n\n"
        "注意：chain_function 必须挂在链条步骤本身（步骤的慢/繁琐/程式感"
        "在做功），链之后发生的事重要不算链的功能——「因为后面有回报所以"
        "前面的接近链有悬念价值」不成立，除非接近过程的长度本身被用来"
        "蓄压（如有明确证据再标 present）。\n\n"
        "【输出 JSON】{\"candidates\":[..]} 只输出 JSON。"
    )


def parse_pacing_adjudication(response: str) -> dict:
    """解析节奏仲裁响应中的 JSON 事实对象。"""
    m = re.search(r"\{.*\}", response or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def merge_pacing_adjudication_runs(runs: list[dict]) -> dict:
    """多次节奏仲裁投票合并：按 span+excerpt 前缀对齐取多数事实。"""
    runs = [r for r in runs if r]
    if not runs:
        return {}
    by_key: dict[str, list[dict]] = {}
    for r in runs:
        for c in r.get("candidates") or []:
            key = f"{c.get('span')}:{(c.get('excerpt') or '')[:12]}"
            by_key.setdefault(key, []).append(c)
    merged = []
    for key, cs in by_key.items():
        n = len(cs)

        def _mj(getter):
            return sum(1 for c in cs if getter(c)) > n / 2

        sd_changed = _mj(lambda c: isinstance(c.get("state_delta"), dict)
                         and c["state_delta"].get("changed"))
        sd_axes = sorted({a for c in cs
                          if isinstance(c.get("state_delta"), dict)
                          for a in (c["state_delta"].get("axes") or [])})
        cf_present = _mj(lambda c: isinstance(c.get("chain_function"), dict)
                         and c["chain_function"].get("present"))
        cf_kind = next(
            (c["chain_function"].get("kind") for c in cs
             if isinstance(c.get("chain_function"), dict)
             and c["chain_function"].get("present")
             and c["chain_function"].get("kind")), None)
        comp_votes = [c.get("compression") for c in cs]
        merged.append({
            "span": cs[0].get("span"),
            "excerpt": cs[0].get("excerpt"),
            "event_chain": _mj(lambda c: c.get("event_chain") is not False),
            "state_delta_changed": sd_changed,
            "state_delta_axes": sd_axes,
            "chain_function_present": cf_present,
            "chain_function_kind": cf_kind,
            "compression": (
                "none_or_trivial" if sum(
                    1 for v in comp_votes if v == "none_or_trivial") > n / 2
                else ("meaningful" if sum(
                    1 for v in comp_votes if v == "meaningful") > n / 2
                    else "not_evaluable")),
            "compression_evidence": next(
                (c.get("compression_evidence") for c in cs
                 if c.get("compression_evidence")), None),
            "existing_delta_downstream": next(
                (c.get("existing_delta_downstream") for c in cs
                 if c.get("existing_delta_downstream")), None),
            "votes": n,
        })
    return {"candidates": merged}


def pacing_verdict(facts: dict) -> str:
    """确定性裁决（dim6a）：四条件同时满足才 blocking。

    event_chain=true AND state_delta=false AND chain_function=false
    AND compression=none_or_trivial → event_chain_without_state_delta
    """
    bound_spans = set(facts.get("dialogue_bound_spans") or [])
    for c in facts.get("candidates") or []:
        if c.get("span") in bound_spans:
            continue  # PC-DIALOGUE-COLLAPSE-01：归对白机制，本机制不处理
        if (c.get("event_chain")
                and not c.get("state_delta_changed")
                and not c.get("chain_function_present")
                and c.get("compression") == "none_or_trivial"):
            return "event_chain_without_state_delta"
    return "none"


_PACING_ADJUDICATED_TYPES = frozenset({"event_chain_without_state_delta"})
_PACING_BLOCKING_TYPES = frozenset({"event_chain_without_state_delta"})


def pacing_rewrite_boundary_violations(
        original: str, revised: str) -> list[str]:
    """PC-BEAT-COLLAPSE-01 / PC-DIALOGUE-COLLAPSE-01 确定性后验.

    pacing 重写只允许段内压缩：非空段落数不得减少（跨段/空行合并 =
    beat 边界违例），引号行数不得减少（shown dialogue → told = 越界）。
    返回违例代码列表；空表=合规。仅应在 blocking 集为纯 pacing 类型
    时调用——混合集中对白轮合并可能合法减少引号行，机械代理无法归因。
    """
    def _paras(t: str) -> list[str]:
        return [p for p in re.split(r"\n+", t) if p.strip()]

    def _quote_lines(t: str) -> int:
        return sum(1 for p in _paras(t)
                   if p.strip().startswith(("“", "「", "『")))

    violations: list[str] = []
    if len(_paras(revised)) < len(_paras(original)):
        violations.append("beat_boundary_merge")
    if _quote_lines(revised) < _quote_lines(original):
        violations.append("dialogue_shown_to_told")
    return violations


def apply_pacing_adjudication(
        issues: list, verdict: str,
        facts: dict | None = None,
        prose_text: str = "") -> tuple[list, object]:
    """把节奏仲裁裁决应用回 issue 集合（同 MN 模式）。"""
    issues = list(issues)
    if verdict not in _PACING_BLOCKING_TYPES:
        issues = [i for i in issues
                  if not (getattr(i, "issue_type", "")
                          in _PACING_ADJUDICATED_TYPES
                          and getattr(i, "severity", "")
                          in ("blocking", "high", "critical"))]
        return issues, None
    existing = [i for i in issues
                if getattr(i, "issue_type", "") in _PACING_ADJUDICATED_TYPES
                and getattr(i, "severity", "")
                in ("blocking", "high", "critical")]
    if existing:
        return issues, None
    desc = "pacing adjudicator verdict=" + verdict
    if facts:
        parts = []
        bound_spans = set(facts.get("dialogue_bound_spans") or [])
        for c in (facts.get("candidates") or []):
            if c.get("span") in bound_spans:
                continue  # PC-DIALOGUE-COLLAPSE-01
            if (c.get("event_chain")
                    and not c.get("state_delta_changed")
                    and not c.get("chain_function_present")
                    and c.get("compression") == "none_or_trivial"):
                seg = f"第{c.get('span')}段「{(c.get('excerpt') or '')[:40]}」"
                if c.get("existing_delta_downstream"):
                    seg += (f"（下游第{c['existing_delta_downstream']}段"
                            f"已有可前置的状态变化）")
                parts.append(seg)
        if parts:
            desc += " | 需处理: " + "；".join(parts[:4])
    syn = ReviewIssue(
        issue_id="pc_adj_1", issue_type=verdict, severity="blocking",
        location="事件链候选段", scope_of_impact="语义节奏",
        violated_rule="推进=有意义状态变化率",
        description=desc)
    issues.append(syn)
    return issues, syn


def _failure_type_lexicon_text() -> str:
    """渲染【失败类型字典】段（LLM 对齐 issue_type 词汇用）。"""
    lines = ["【失败类型字典】"]
    for issue_type, severity, blocking in FAILURE_TYPE_LEXICON:
        lines.append(f"- {issue_type}（默认 {severity}，{blocking}）")
    return "\n".join(lines)


def _info_warrant_guidance_text() -> str:
    """渲染【信息凭证约束】段（09_information_warrant_rules 审查 prompt 注入）.

    覆盖通道谱系 + 聚焦三分 + 四条凭证约束 + 信息差距形态（合法/非法 4+4）。
    """
    sections = [build_info_warrant_guidance()]
    gap_lines = ["【信息差距形态】"]
    for gap in INFO_GAP_FORMS:
        kind = "合法" if gap["kind"] == "legal" else "非法"
        gap_lines.append(
            f"- [{kind}] {gap['name']}（{gap['relation']}）: {gap['driver']}"
            f" — 检测: {gap['detection']}"
        )
    sections.append("\n".join(gap_lines))
    return "\n\n".join(sections)


def _text_related(text: str, content: str, min_bigrams: int = 2) -> bool:
    """弱相关判定：两段文本共享 ≥ min_bigrams 个字符 2-gram 即视为相关.

    用于 abrupt_payoff 判定"释放信息是否与活跃伏笔有铺垫交集"。
    要求 ≥2 个共享 bigram 是为了过滤'的/是/一'等高频虚字造成的过敏。
    """
    if not text or not content:
        return False
    gt = set(zip(text, text[1:]))
    gc = set(zip(content, content[1:]))
    return len(gt & gc) >= min_bigrams


def _pu_info_text(pu: PlotUnit) -> str:
    """拼接 PlotUnit 的信息承载字段，供 iss_info_* 弱信号检测."""
    return " ".join(
        filter(
            None,
            [pu.goal, pu.conflict]
            + list(pu.released_information)
            + [pu.hook or "", pu.emotional_shift or ""]
            + list(pu.consequences),
        )
    )


_FORESHADOW_STOPWORDS = frozenset(
    (
        "的", "了", "是", "说", "在", "有", "和", "与", "就", "都", "也",
        "不", "没", "会", "要", "能", "把", "被", "让", "那", "这",
        "他", "她", "你", "我", "们", "一个", "什么", "怎么", "为什么",
        "它", "上", "下", "里", "时", "后", "前", "再", "又", "还", "只",
    )
)


def _foreshadow_keywords(content: str, max_keywords: int = 4) -> list[str]:
    """从伏笔内容提取核心关键词（2-6 字中文片段，排除停用词），供内容级引用匹配."""
    segments = re.findall(r"[一-鿿]{2,}", content or "")
    keywords: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        for length in range(6, 1, -1):
            for i in range(len(seg) - length + 1):
                word = seg[i : i + length]
                if word in seen:
                    continue
                if any(stop in word for stop in _FORESHADOW_STOPWORDS):
                    continue
                seen.add(word)
                keywords.append(word)
    return keywords[:max_keywords]


def _foreshadow_referenced(
    entry,
    plotunit_ids: set[str],
    pu_texts: list[str],
) -> bool:
    """判断 active 伏笔是否被任一 PlotUnit 引用.

    优先看显式 linked_plotunits；否则做内容级匹配——任一 PlotUnit 的信息文本
    包含伏笔内容的核心关键词即视为被引用（避免只看 id 链接导致漏判）。
    """
    linked = set(entry.linked_plotunits or [])
    if linked.intersection(plotunit_ids):
        return True
    keywords = _foreshadow_keywords(entry.content)
    if not keywords:
        return False
    return any(any(kw in text for kw in keywords) for text in pu_texts)


# F3a：可做正文级复核的 issue 类型（对象层弱信号、正文层可兑现）。
_PROSE_RECHECK_TYPES = frozenset(
    ("abrupt_payoff", "promise_loss", "missing_consequence", "character_distortion")
)


def _prose_evidence(desc: str, prose_text: str, window: int = 20) -> str:
    """在正文中定位与 issue 描述共享 2-gram 的首次命中点，取邻窗作证据片段."""
    desc_bigrams = set(zip(desc, desc[1:]))
    for pos in range(len(prose_text) - 1):
        if (prose_text[pos], prose_text[pos + 1]) in desc_bigrams:
            start = max(0, pos - window // 2)
            end = min(len(prose_text), pos + window)
            return prose_text[start:end]
    return ""


def recheck_against_prose(issues, prose_text: str, evidence_chars: int = 40) -> list[dict]:
    """正文级复核（F3a）：对对象层 issue 做 prose 兑现检查，返回标注（不改 route）.

    对象层 Review 在成文前运行，部分 issue（伏笔/承诺/后果/角色）可能在成文
    正文中已被自然兑现——这些是"对象层弱信号、正文层已解决"的噪声。本函数对
    prose-recheckable 类型 issue 判定其描述与正文的相关性（字符 2-gram ≥2）：

    - 相关 → prose_confirmed=True，附命中片段证据（evidence）；
    - 不相关 → prose_confirmed=False；
    - 其余类型 → prose_confirmed=None（不适用，保持对象层原判）。

    返回值仅用于展示/注释，不修改 issue、不改 route。
    """
    if not prose_text or not prose_text.strip():
        return []
    results: list[dict] = []
    for issue in issues:
        entry: dict = {
            "issue_id": issue.issue_id,
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "location": issue.location,
        }
        if issue.issue_type not in _PROSE_RECHECK_TYPES:
            entry["prose_confirmed"] = None
            results.append(entry)
            continue
        confirmed = _text_related(issue.description, prose_text)
        entry["prose_confirmed"] = confirmed
        if confirmed:
            entry["evidence"] = _prose_evidence(
                issue.description, prose_text
            )[:evidence_chars]
        results.append(entry)
    return results


class ReviewUnit:
    """审查重建结果或推进结果."""

    VALID_ROUTES = {"pass", "rewrite", "block"}
    _FULL_CONTEXT_PREFIXES = ("extend", "compose", "a1-post-prose")

    validate_input = staticmethod(validate_review_input)

    def build_prompt(
        self,
        objects: list,
        context: str = "audit",
        prose_text: str | None = None,
        transition_contract: str = "",
    ) -> str:
        """生成审查 prompt.

        Args:
            objects: 待审查对象层。
            context: 审查上下文标签（audit/extend/compose/…-rereview）。
            prose_text: 可选正文文本。非空时注入【本章正文】段并激活正文层
                审查维度（方向文档第五节的 7 维正文审查）。None/空串时不注入，
                prompt 与旧版逐字节相同（零成本契约，回归测试锁死）。
        """
        # Full-chain callers must provide the objects their references name.
        # Audit may intentionally diagnose an incomplete reconstruction; its
        # hard-rule output remains available rather than hiding those defects.
        if context.startswith(self._FULL_CONTEXT_PREFIXES):
            self.validate_input(objects)
        hard_issues = self._hard_rules(objects)
        domain_issues = self._domain_rules(objects)
        return self._build_prompt(
            objects, hard_issues, domain_issues, context, prose_text,
            transition_contract,
        )

    def parse_response(
        self,
        response: str,
        foreshadows: list | None = None,
        character_models: list | None = None,
    ) -> tuple[list[ReviewIssue], list[ReviewReminder], str]:
        """解析 LLM 审查响应.

        Args:
            response: LLM 返回的 JSON 文本。
            foreshadows: 可选 ForeshadowGraph 列表；响应含 foreshadow_updates 时，
                就地更新对应线程状态（正文已兑现的承诺在此落为 resolved，消除
                后续 promise_loss 重复误报）。
            character_models: 可选 CharacterModel 列表；响应含
                character_knowledge_updates 时，就地同步角色已知信息（移除已过期
                的『不知道X』断言，消除信息凭证重复误报）。

        Returns:
            (ReviewIssue 列表, ReviewReminder 列表, 路由推荐)
        """
        from src.workflow_action.preference_review import _parse_json

        data = _parse_json(response)
        required_fields = ("issues", "reminders", "route")
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(
                f"Review response missing required field(s): {', '.join(missing)}"
            )
        allowed_fields = required_fields + (
            "foreshadow_updates",
            "character_knowledge_updates",
            "character_pressure_updates",
            "misinformation_updates",
            "thread_transitions",
        )
        extra = sorted(set(data) - set(allowed_fields))
        if extra:
            raise ValueError(
                f"Review response has unexpected field(s): {', '.join(extra)}"
            )
        if not isinstance(data["issues"], list):
            raise ValueError("Review response field issues must be a list")
        if not isinstance(data["reminders"], list):
            raise ValueError("Review response field reminders must be a list")
        issues = [ReviewIssue(**i) for i in data["issues"]]
        reminders = [ReviewReminder(**r) for r in data["reminders"]]
        route = data["route"]
        if route not in self.VALID_ROUTES:
            raise ValueError(f"Invalid review route: {route}")
        if foreshadows:
            updates = data.get("foreshadow_updates") or []
            if not isinstance(updates, list):
                raise ValueError("Review response field foreshadow_updates must be a list")
            self._apply_foreshadow_updates(foreshadows, updates)
        if character_models:
            updates = data.get("character_knowledge_updates") or []
            if not isinstance(updates, list):
                raise ValueError(
                    "Review response field character_knowledge_updates must be a list"
                )
            self._apply_knowledge_updates(character_models, updates)
            updates = data.get("character_pressure_updates") or []
            if not isinstance(updates, list):
                raise ValueError(
                    "Review response field character_pressure_updates must be a list"
                )
            self._apply_pressure_updates(character_models, updates)
            updates = data.get("misinformation_updates") or []
            if not isinstance(updates, list):
                raise ValueError(
                    "Review response field misinformation_updates must be a list"
                )
            self._apply_misinformation_updates(character_models, updates)
        return issues, reminders, route

    @staticmethod
    def extract_transitions(response: str) -> list:
        """提取 review 响应中可选的 thread_transitions（State V2 lifecycle 契约）.

        factual transition 的合法声明点在 post-prose 阶段——只有看过最终
        正文的阶段才能逐字引用 evidence_anchor。Continue/PlotUnit 不再承载。
        返回 ThreadTransition 列表；无字段/空列表返回 []；非法条目抛错
        （属契约失败，可走同 prompt rematerialization）。
        """
        from src.object_state.plotunit import ThreadTransition
        from src.workflow_action.preference_review import _parse_json

        data = _parse_json(response)
        raw = data.get("thread_transitions") or []
        if not isinstance(raw, list):
            raise ValueError("Review response field thread_transitions must be a list")
        return [ThreadTransition(**t) for t in raw]

    @staticmethod
    def _apply_foreshadow_updates(foreshadows: list, updates: list) -> None:
        """把 review 声明的线程状态更新落到 ForeshadowGraph（unknown id 静默跳过）."""
        for item in updates:
            if not isinstance(item, dict):
                continue
            thread_id = item.get("thread_id")
            status = item.get("status")
            if not isinstance(thread_id, str) or not thread_id.strip():
                continue
            if not isinstance(status, str) or not status.strip():
                continue
            for fg in foreshadows:
                fg.set_status(thread_id.strip(), status.strip())

    @staticmethod
    def _apply_knowledge_updates(character_models: list, updates: list) -> None:
        """把 review 声明的角色已知信息更新落到 CharacterModel（unknown id 静默跳过）."""
        by_id = {cm.character_id: cm for cm in character_models}
        for item in updates:
            if not isinstance(item, dict):
                continue
            character_id = item.get("character_id")
            if not isinstance(character_id, str) or character_id.strip() not in by_id:
                continue
            cm = by_id[character_id.strip()]
            learn = item.get("learn")
            drop_unknown = item.get("drop_unknown")
            if isinstance(learn, list) and learn:
                cm.reconcile_knowledge(learn=learn)
            if isinstance(drop_unknown, list) and drop_unknown:
                cm.reconcile_knowledge(drop_unknown=drop_unknown)

    @staticmethod
    def _apply_pressure_updates(character_models: list, updates: list) -> None:
        """把 review 声明的『已解决压力』从 current_pressure 移除（unknown id 静默跳过）."""
        by_id = {cm.character_id: cm for cm in character_models}
        for item in updates:
            if not isinstance(item, dict):
                continue
            character_id = item.get("character_id")
            resolve = item.get("resolve")
            if not isinstance(character_id, str) or character_id.strip() not in by_id:
                continue
            if not isinstance(resolve, list) or not resolve:
                continue
            by_id[character_id.strip()].resolve_pressures(resolve)

    @staticmethod
    def _apply_misinformation_updates(character_models: list, updates: list) -> None:
        """把 review 声明的『错误信念被击穿/修正』落到 CharacterModel（unknown id 静默跳过）.

        misinformation 是 belief state，与 knowledge truth 分离：disproven 只移除
        已被证伪且角色不再持有的断言，不追加到 knowledge_state；corrected 用
        [{from, to}] 替换为修正后的信念（如『被抛弃』→『明白是被迫离开，仍有怨』）。
        """
        by_id = {cm.character_id: cm for cm in character_models}
        for item in updates:
            if not isinstance(item, dict):
                continue
            character_id = item.get("character_id")
            if not isinstance(character_id, str) or character_id.strip() not in by_id:
                continue
            cm = by_id[character_id.strip()]
            disproven = item.get("disproven")
            corrected = item.get("corrected")
            if isinstance(disproven, list) and disproven:
                cm.reconcile_misinformation(disproven=disproven)
            if isinstance(corrected, list) and corrected:
                cm.reconcile_misinformation(corrected=corrected)

    def resolve_route(self, issues: list[ReviewIssue], route: str) -> str:
        """Resolve final route after code and LLM issues are merged."""
        has_blocking = any(issue.is_blocking() for issue in issues)
        if has_blocking and route == "pass":
            return "rewrite"
        if not has_blocking and route == "rewrite":
            return "pass"
        return route

    def _hard_rules(self, objects: list) -> list[ReviewIssue]:
        """代码层面硬规则检查，返回正式 ReviewIssue."""
        issues: list[ReviewIssue] = []
        char_models = [o for o in objects if isinstance(o, CharacterModel)]
        fact_ledgers = [o for o in objects if isinstance(o, FactLedger)]
        foreshadows = [o for o in objects if isinstance(o, ForeshadowGraph)]

        # 规则1: CharacterModel knowledge 和 misinformation 不应重叠
        for cm in char_models:
            overlap = set(cm.knowledge_state) & set(cm.misinformation)
            if overlap:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_overlap_{cm.character_id}",
                        issue_type="character_distortion",
                        severity="blocking",
                        location=f"CharacterModel {cm.character_id}",
                        scope_of_impact="角色认知一致性",
                        violated_rule="knowledge_state 与 misinformation 互斥",
                        description=f"角色 '{cm.name}' 的 knowledge 与 misinformation 重叠: {overlap}",
                    )
                )

        # 规则2: FactLedger 空检查
        for fl in fact_ledgers:
            if not fl.entries:
                issues.append(
                    ReviewIssue(
                        issue_id="iss_hard_empty_fl",
                        issue_type="fact_conflict",
                        severity="warning",
                        location="FactLedger",
                        scope_of_impact="全局事实基础",
                        violated_rule="FactLedger 不得为空",
                        description="FactLedger 为空 — 未建立任何 hard facts",
                    )
                )

        # 规则3: ForeshadowGraph 空检查
        for fg in foreshadows:
            if not fg.entries:
                issues.append(
                    ReviewIssue(
                        issue_id="iss_hard_empty_fg",
                        issue_type="promise_loss",
                        severity="warning",
                        location="ForeshadowGraph",
                        scope_of_impact="承诺追踪",
                        violated_rule="ForeshadowGraph 不得为空",
                        description="ForeshadowGraph 为空 — 无伏笔/承诺被追踪",
                    )
                )

        # 规则4: 角色ID一致性
        char_ids = {cm.character_id for cm in char_models}
        for cm in char_models:
            for rel_id in cm.relations:
                if rel_id not in char_ids:
                    issues.append(
                        ReviewIssue(
                            issue_id=f"iss_hard_rel_{cm.character_id}",
                            issue_type="character_distortion",
                            severity="blocking",
                            location=f"CharacterModel {cm.character_id}",
                            scope_of_impact="角色关系网络",
                            violated_rule="relations 必须指向已知角色",
                            description=f"角色 '{cm.name}' 关联了未知 ID: {rel_id}",
                        )
                    )

        narrative_states = [o for o in objects if isinstance(o, NarrativeState)]
        if char_ids:
            for ns in narrative_states:
                for character_id in ns.active_characters:
                    if character_id not in char_ids:
                        issues.append(
                            ReviewIssue(
                                issue_id=(
                                    f"iss_hard_active_character_"
                                    f"{ns.state_id}_{character_id}"
                                ),
                                issue_type="character_distortion",
                                severity="blocking",
                                location=f"NarrativeState {ns.state_id}",
                                scope_of_impact="active character references",
                                violated_rule=(
                                    "NarrativeState.active_characters must reference "
                                    "known CharacterModel.character_id"
                                ),
                                description=(
                                    f"NarrativeState '{ns.state_id}' references unknown "
                                    f"active character ID: {character_id}"
                                ),
                            )
                        )

        # 规则5: PlotUnit 的 output_state_ref 必须指向存在的 NarrativeState
        plotunits = [o for o in objects if isinstance(o, PlotUnit)]
        state_ids = {ns.state_id for ns in narrative_states}

        for pu in plotunits:
            if pu.input_state_ref and pu.input_state_ref not in state_ids:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_input_state_ref_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="state transition chain",
                        violated_rule=(
                            "PlotUnit.input_state_ref must reference an existing "
                            "NarrativeState.state_id"
                        ),
                        description=(
                            f"PlotUnit '{pu.unit_id}' input_state_ref "
                            f"'{pu.input_state_ref}' does not exist in current "
                            "NarrativeState objects"
                        ),
                    )
                )
            if pu.output_state_ref and pu.output_state_ref not in state_ids:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_state_ref_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="状态链连续性",
                        violated_rule="PlotUnit.output_state_ref 必须指向存在的 NarrativeState",
                        description=(
                            f"PlotUnit '{pu.unit_id}' 的 output_state_ref "
                            f"'{pu.output_state_ref}' 不存在于当前 NarrativeState 列表"
                        ),
                    )
                )
            if not pu.is_effective:
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_ineffective_{pu.unit_id}",
                        issue_type="weak_progression",
                        severity="blocking",
                        location=f"PlotUnit {pu.unit_id}",
                        scope_of_impact="推进有效性",
                        violated_rule="PlotUnit 必须导致有意义状态变化",
                        description=(
                            f"PlotUnit '{pu.unit_id}' 未被标记为有效推进；"
                            "不能作为通过结果继续流转"
                        ),
                    )
                )
            if char_ids:
                for character_id in pu.participants:
                    if character_id not in char_ids:
                        issues.append(
                            ReviewIssue(
                                issue_id=(
                                    f"iss_hard_plotunit_participant_"
                                    f"{pu.unit_id}_{character_id}"
                                ),
                                issue_type="character_distortion",
                                severity="blocking",
                                location=f"PlotUnit {pu.unit_id}",
                                scope_of_impact="PlotUnit participant references",
                                violated_rule=(
                                    "PlotUnit.participants must reference known "
                                    "CharacterModel.character_id"
                                ),
                                description=(
                                    f"PlotUnit '{pu.unit_id}' references unknown "
                                    f"participant ID: {character_id}"
                                ),
                            )
                        )

        # 规则6: active 状态的 ForeshadowEntry 必须至少被一个 PlotUnit 引用
        # （显式 linked_plotunits id，或任一 PlotUnit 信息文本提及伏笔核心内容）
        plotunit_ids = {pu.unit_id for pu in plotunits}
        pu_texts = [_pu_info_text(pu) for pu in plotunits]

        for fg in foreshadows:
            for entry in fg.get_active():
                if _foreshadow_referenced(entry, plotunit_ids, pu_texts):
                    continue
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_foreshadow_{entry.thread_id}",
                        issue_type="promise_loss",
                        severity="warning",
                        location=f"ForeshadowGraph {entry.thread_id}",
                        scope_of_impact="承诺追踪",
                        violated_rule="active 伏笔必须有 PlotUnit 引用",
                        description=(
                            f"伏笔 '{entry.content}' (setup: {entry.setup_point}) "
                            "处于 active 状态，但未被任何 PlotUnit 显式引用或推进"
                        ),
                        suggested_fix="在后续 PlotUnit 中回收此伏笔，或标记为 abandoned",
                        )
                    )

        # 规则7: 同一实体在同一时间点不应有矛盾事件
        time_facts = defaultdict(list)
        for fl in fact_ledgers:
            for entry in fl.entries:
                if entry.fact_type == "time_order" and entry.timestamp:
                    entities_key = (
                        tuple(sorted(entry.involved_entities))
                        if entry.involved_entities
                        else ("__none__",)
                    )
                    key = (entry.timestamp, entities_key)
                    time_facts[key].append(entry)

        for (timestamp, entities), entries in time_facts.items():
            if len(entries) > 1:
                statements = [e.statement for e in entries]
                issues.append(
                    ReviewIssue(
                        issue_id=f"iss_hard_time_{timestamp}_{'_'.join(entities)}",
                        issue_type="fact_conflict",
                        severity="warning",
                        location="FactLedger",
                        scope_of_impact="时间线一致性",
                        violated_rule="同一实体在同一时间点不应有多条 time_order 事实",
                        description=(
                            f"时间点 '{timestamp}'，实体 {list(entities)} 有 "
                            f"{len(entries)} 条 time_order 事实: {statements}"
                        ),
                    )
                )

        return issues

    def _domain_rules(self, objects: list) -> list[ReviewIssue]:
        """领域层规则检查，返回正式 ReviewIssue.

        弱信号检测已拆分到 src/domain_layer/review_signals.py（每类失败类型
        一个 detect_* 检测器，按注册表顺序汇总）。本方法只做编排——调用
        run_all_signal_detectors 汇总，issue 列表逐条与解耦前一致（零回归契约）。
        """
        return run_all_signal_detectors(objects)


    def _build_prompt(
        self,
        objects: list,
        hard_issues: list[ReviewIssue],
        domain_issues: list[ReviewIssue],
        context: str,
        prose_text: str | None = None,
        transition_contract: str = "",
    ) -> str:
        """生成审查 prompt."""
        obj_ctx = []
        for obj in objects:
            if hasattr(obj, "to_prompt_context"):
                obj_ctx.append(obj.to_prompt_context())

        hard_section = ""
        if hard_issues:
            hard_section = "\n【代码硬规则已发现问题】\n" + "\n".join(
                f"- [{issue.severity}] {issue.issue_type}: {issue.description}"
                for issue in hard_issues
            )

        domain_section = ""
        if domain_issues:
            domain_section = "\n【领域规则已发现问题】\n" + "\n".join(
                f"- [{issue.severity}] {issue.issue_type}: {issue.description}"
                for issue in domain_issues
            )

        # B 档：失败类型字典（08_failure_types §10 默认严重度 + §11 阻断倾向）
        lexicon_section = "\n" + _failure_type_lexicon_text()

        # D 档：信息凭证指导（09_information_warrant_rules 审查 prompt 注入）
        warrant_section = "\n" + _info_warrant_guidance_text()

        # 对白审查块：仅当对象层存在 DialogueStrategy 时注入（ds=None
        # 负控场景不得接受对白专项审查/改写处理）。
        dlg_section = ""
        has_dlg_strategy = any(
            getattr(o, "dialogue_strategy", None) for o in objects)
        if has_dlg_strategy:
            dlg_section = (
                "- 对白作为社会行动（独立 family，issue_type 见下）：先判本场"
                "是否真的存在社会博弈（寒暄/交代/无争议确认不报），存在则依次判："
                "①社会/信息约束存在时人物是否为让读者明白而说破不能直说的事？"
                "unearned_directness；"
                "②对话结束时角色是否根本没通过言语行动推进其目的？"
                "objective_unpursued；"
                "③关键回合是否只有信息交换，没有试探/拒绝/承诺/施压/交换等"
                "社会动作？flat_tactic；"
                "④上一关键动作已改变局面，下一方却像没听见继续自己台词，"
                "或以无后果的沉默/回避/张嘴又停/避而不答让必须回应的压力"
                "凭空消失，或多轮只在重复确认同一限制而无新增 delta？"
                "no_response_pressure（含 pressure dissipation by withhold "
                "与 stalling-stasis；关键压力消散或关键问题被拖延吞掉时"
                "为 blocking，且必须报此类型、不得归入 weak_progression。"
                "典型签名一：问询/交涉场景中对方连续以停顿、转移、不答应对"
                "关键问题，至场终仍无任何实质回应或局面变化。"
                "典型签名二：循环停滞——同一已确立命题（同一边界/条件/风险/"
                "限制）在多轮中被反复声明。判据不是『有没有新 delta』，而是"
                "边际贡献/可压缩性：对该命题第二次及之后的每一轮，逐一问——"
                "若把这轮删除或并入上一轮，最终的 information/commitment/"
                "leverage/status/action-space/角色关系状态是否会损失任何新"
                "变化？若只会损失措辞更明确、同义复述或再次确认，该轮属"
                "LOW_MARGINAL_DELTA（无足够边际贡献）。判定句：如果这轮对白"
                "能合并进上一轮，而最终社会状态不变，它就没有足够的边际贡献。"
                "然后按确认功能是否耗尽分三级：允许一次有功能的确认——"
                "若主要 interaction objective 尚未完成，低边际重复轮次持续"
                "占据交锋并延迟下一社会行动/场景动作，按 dialogue_loop_stasis"
                " blocking 报告；若 objective 已完成且后续轮次承担一次有效"
                "确认/正式化/责任接受/社会性收束，按 no_turn_delta warning"
                "报告；若 objective 已完成且同一命题已获实质确认之后仍继续"
                "换措辞重复确认同一社会状态（删除这些轮次不损失信息/承诺/"
                "杠杆/地位/行动空间，也不损失独立的礼貌/关系功能），按"
                " excessive_redundant_tail blocking 报告（必须写明：已确立"
                "的命题是什么、确认在哪一轮已耗尽功能、哪几轮在确认完成后"
                "继续重复）；另查形式性复述：命题已获实质确认后，是否以逐字/"
                "高度近似措辞再次整段重说，且该逐字形式并无文本可见的功能"
                "必需（豁免：正式宣读/程序或记录要求原文确认/引用原话纠错"
                "对质/仪式誓言/有意复读施压且第二次确实改变局面/换新受众"
                "必须完整重传）？成立则按 formal_echo_after_ack blocking"
                "报告——『双方各自重申立场以便记录』不自动豁免，须指明为何"
                "微功能非靠整段原话再说不行；"
                "⑦反向哨兵：人人绕说/该问不问/为神秘牺牲清晰度？"
                "subtext_overengineering——V1 仅 warning，不阻断；"
                "⑤潜台词已由对白反应建立，旁白又翻译『他其实是在……』？"
                "subtext_glossed；"
                "⑥整段交锋结束后信息/承诺/杠杆/地位/行动空间一个都没变？"
                "no_turn_delta——V1 仅 warning，不阻断\n"
            )
            if prose_text and prose_text.strip():
                terms = _dialogue_theme_recurrence(prose_text)
                if terms:
                    dlg_section += (
                        "【机械检测信号 LOOP_CANDIDATE】表述 "
                        + "、".join(f"『{t}』" for t in terms)
                        + " 在 ≥2 个对白轮次中逐字/近逐字重现——这是循环停滞"
                        "候选，不直接定罪。请对照边际贡献判定序：定位承载这些"
                        "表述的轮次，对其中第二次及之后的每一轮，问『删除或"
                        "并入上一轮后最终社会状态是否损失新变化』；损失则为"
                        "有效轮次不报，不损失则按确认功能耗尽度分级"
                        "（objective 未完成且占据交锋→dialogue_loop_stasis"
                        " blocking；objective 完成且属一次有效收束→"
                        "no_turn_delta warning；objective 完成且确认已耗尽后"
                        "继续重复确认→excessive_redundant_tail blocking）。"
                        "另查：这些重复是否为对已确认命题的逐字/近逐字整段"
                        "重说且无逐字功能证据→formal_echo_after_ack blocking。\n"
                    )

        # DFD V1：细节功能审查块——detail_contract 在场（对照计划兑现）
        # 或机械候选命中（枚举堆叠待判功能）时注入。候选只提示注意，不定罪。
        dfd_section = ""
        if prose_text and prose_text.strip():
            has_detail_contract = any(
                getattr(o, "detail_contract", None) for o in objects)
            inv_cands = _detail_inventory_candidates(prose_text)
            if has_detail_contract or inv_cands:
                dfd_section = (
                    "- 细节功能（issue_type 见下）：环境/细节不是装饰——每处"
                    "环境细节须让读者获得定位、行动约束、感官在场、关系信号"
                    "或氛围积累中至少一项真实效应（realized effect："
                    "「用了颜色」不等于完成感官功能，功能标签不得自证）。"
                    "依次判：①连续枚举多个物体/空间项而均不产生上述效应、"
                    "删掉整段读者无损失？成簇则 decorative_inventory blocking"
                    "（须写明哪些段、枚举了什么、为何均不承重）；"
                    "②单个细节删掉读者无损失但未成簇？functionless_detail"
                    " warning；③细节密度稀释当前读者任务（关键交锋中被"
                    "无关环境描写打断/淹没）？detail_overload warning；"
                    "④共享功能豁免：多处细节可共同兑现一个 collective "
                    "function（如空间建立镜头共享定位+行动约束）——但须在"
                    "当前行动或后文可兑现，不接受「这是氛围」式声明自证；"
                    "⑤若本单元带 detail_contract：对照计划承重细节是否真"
                    "写入正文并产生声明的效应——漏写或写了不兑现按"
                    " functionless_detail/decorative_inventory 处理\n"
                )
                if inv_cands:
                    dfd_section += (
                        "【机械检测信号 INVENTORY_CANDIDATE】以下叙述段含"
                        "枚举式细节堆叠，是 decorative_inventory 候选，"
                        "不直接定罪："
                        + "；".join(
                            f"第{c['span']}段「{c['excerpt'][:40]}」"
                            for c in inv_cands[:6])
                        + "。请逐段问：这些枚举项是否共享一个可在当前行动/"
                        "后文兑现的功能？或逐一项能否指出它给读者的效应？"
                        "都不能则成簇无功能→blocking。\n"
                    )

        # 正文层审查：prose_text 非空时注入【本章正文】+ 7 维正文审查维度。
        # 零成本契约：None/空串时不注入，prompt 与旧版逐字节相同。
        prose_section = ""
        if prose_text and prose_text.strip():
            prose_section = (
                "\n\n【本章正文】\n" + prose_text
                + "\n\n【正文层审查维度】（对照【本章正文】逐条判定）\n"
                "- 兑现：PlotUnit 的 goal / conflict / consequences / released_information"
                " 是否在正文中真实落地，而非仅被提及、绕过或写成另一件事\n"
                "- 人物忠实：正文对白 / 心理 / 动作是否让角色变成另一个人"
                "（与 CharacterModel 的身份 / 目标 / 恐惧 / 关系 / 当前压力 / 历史冲突不符）\n"
                "- 情绪落地：情绪是否由动作 / 物品 / 空间 / 对话 / 停顿产生，"
                "而非被直接声明（『他很悲伤』）；是否过度自我总结（『那一刻他明白了』）\n"
                "- 解读空间：象征 / 情绪是否被过度解释；场景已能表达却补一段说明；"
                "是否允许 unresolved 保持 unresolved\n"
                "- 场景在场：是否有具体行动 / 物体 / 声音 / 触感 / 空间关系 / 人物微动作，"
                "让场景真实发生\n"
                "- 对白：去掉人名后能否区分角色；是否所有人都说同一套腔调；"
                "是否大量对白只是解释剧情；是否有关系差异与潜文本\n"
                "- AI 味：句式过度整齐 / 情感总被总结 / 相同转折结构 / 章末模板化 /"
                " 同章内语句或对白逐字重复 / 每场戏都完整起承转合\n"
                "- 认知劳动分配（issue_type=reader_cognitive_allocation）："
                "必须主动枚举，不能只靠印象——先扫描本章每个『交锋/动作/对白/细节』"
                "之后紧跟的段落或长句，逐一判定它是不是解释尾巴："
                "动作/对白/细节已足以让读者得出判断，正文却又翻译其含义、"
                "讲解刚演完的博弈/策略（TACTICAL_GLOSS）、总结人物动机或信条"
                "（MOTIVE_GLOSS）、用比喻/评价重述已实现的效果（EFFECT_RESTATEMENT）、"
                "复述前文已演示的原则（ECHO）、或把本可悬着的暧昧直接判明"
                "（AMBIGUITY_FORECLOSURE）。"
                "判据（Necessary Contribution）：删掉这段解释后，事实、因果、"
                "人物选择与可理解性是否都不损失？是则为过满（OVER_EXPLAINED）。"
                "反向也必查（UNDER_EVIDENCED）：正文是否要求读者完成一个重要推断，"
                "却缺至少一个现有文本无法合理补出的必要前提——"
                "『我没一眼看懂』不算，必须指出 target inference / missing premise / "
                "为什么现有 evidence 不能提供它，否则不得报告；"
                "认知本身改变人物下一步选择、不可见信息、规则关键因果属贡献非 NONE，"
                "不属过满。报告的 issue 在 description 中标注方向（OVER_EXPLAINED/"
                "UNDER_EVIDENCED）、贡献类别：NEW_FACT / "
                "INACCESSIBLE_INTERNAL_STATE / RULE_CRITICAL_CAUSE / "
                "DECISION_CHANGING_REALIZATION / NONE，"
                "以及违反类型：ECHO / MOTIVE_GLOSS / TACTICAL_GLOSS / "
                "EFFECT_RESTATEMENT / AMBIGUITY_FORECLOSURE / MISSING_PREMISE\n"
                "- 人物选择显形（独立 family，issue_type 见下）：按固定顺序判定，"
                "先问本场是否真的需要诊断性选择——过渡/执行/信息接收/气氛场景"
                "不需要则为合法无发现（NO_DIAGNOSTIC_CHOICE_NEEDED，不报）；"
                "需要时依次判："
                "①是否至少两个真实可行选项？否则 fake_alternative；"
                "②是否存在可感知取舍/代价？否则 cost_free_choice；"
                "③决定权是否真属人物（非强迫/巧合/他人代决）？否则 agency_outsourced；"
                "④最终是否经行为/对白/不行动落地（讨论半天没动作=未落地）？"
                "否则 choice_not_enacted；"
                "⑤落地后旁白是否又解释性格答案（『这说明他……』）？"
                "是则 trait_gloss_after_choice；"
                "⑥行为逻辑成立但换成任何正常主角都一样（缺角色特异性）？"
                "generic_protagonist_choice——V1 仅 warning，不阻断\n"
                + dlg_section
                + dfd_section
                + "\n对每个对象层 issue，对照【本章正文】判定：已被正文自然兑现则降级或撤销，"
                "被正文坐实则升级；正文层独有问题以新增 issue 形式报告。"
                "正文层新增 issue 的 location 必须直接复制【本章正文】中的一段连续原文，"
                "不得写『第一段』『全章』『正文』等位置标签；该原文将被系统逐字核验。"
                "信息层放置单独核对：正文明确揭示 hidden_information 的内容，"
                "说明读者已经知道，不能因内容兑现就撤销字段放置问题。"
                "旁白或内心活动不自动使其他角色知情；未描写不能单独证明秘密为真。"
            )

        # State V2 lifecycle 契约：仅在 post-prose Review 阶段声明 factual
        # transition（此刻才看得见最终正文，anchor 才可能逐字落地）。
        # 零成本：transition_contract 为空时 prompt 字节不变。
        transitions_field = ""
        transitions_note = ""
        if transition_contract:
            transitions_field = (
                ',\n  "thread_transitions": [\n    {\n'
                '      "action": "OPEN",\n'
                '      "thread_label": "正文明确形成的新义务/后果压力",\n'
                '      "thread_type": "承诺线",\n'
                '      "evidence_anchor": "正文原句逐字片段"\n'
                "    },\n    {\n"
                '      "action": "CLOSE",\n'
                '      "thread_id": "既有线程ID",\n'
                '      "closure_kind": "fulfilled",\n'
                '      "evidence_anchor": "正文原句逐字片段"\n'
                "    }\n  ]"
            )
            transitions_note = (
                "\n\n" + transition_contract
            )

        object_summary = "\n---\n".join(obj_ctx)

        return f"""你是一位叙事审查专家。请对以下叙事对象层进行审查。
【审查上下文】{context}
{hard_section}{domain_section}

【对象层摘要】
{object_summary}
{prose_section}

【审查维度】
{INFORMATION_LAYER_GUIDANCE}
1. 事实一致性: FactLedger 条目是否自洽? 是否有矛盾?
2. 角色一致性: CharacterModel 行为逻辑是否自洽? 目标/恐惧/缺陷是否驱动决策?
3. 世界合法性: WorldModel 规则是否被尊重? 是否有无代价的违规行为?
4. 承诺追踪: ForeshadowGraph 是否活跃? 是否有承诺被遗忘?
5. 状态有效性: NarrativeState 是否可运行? 时间/地点/冲突是否清晰?
{lexicon_section}

{warrant_section}

【Track 1 约束】
- 只审查硬事实, 不审查推断
- 不要把 working-state pressure 当成 fact violation

【Track 3 约束】
- 检查 CharacterModel 是否只存结论
- 检查 knowledge_state 是否混入支撑证据

【输出格式】严格输出 JSON:
{{
  "issues": [
    {{
      "issue_id": "iss_001",
      "issue_type": "fact_conflict",
      "severity": "warning",
      "location": "FactLedger",
      "scope_of_impact": "后续所有依赖该事实的推断",
      "violated_rule": "事实一致性",
      "description": "描述",
      "suggested_fix": "可选"
    }}
  ],
  "reminders": [
    {{
      "reminder_id": "rem_001",
      "family": "promise_followup_needed",
      "trigger_condition": "3个PlotUnit内未回收",
      "window": "plotunit_count=2",
      "escalation_issue_type": "missing_consequence",
      "early_escalation_condition": "same thread reminder repeats",
      "closure_condition": "promise is advanced, narrowed, or delayed with cost",
      "priority": "medium"
    }}
  ],
  "route": "pass",
  "foreshadow_updates": [
    {{
      "thread_id": "th_002",
      "status": "resolved",
      "note": "该伏笔在正文已兑现/回收，从活跃承诺中移除"
    }}
  ],
  "character_knowledge_updates": [
    {{
      "character_id": "c001",
      "learn": ["苏观使找了十二年"],
      "drop_unknown": ["不知道苏观使找了十二年"]
    }}
  ],
  "character_pressure_updates": [
    {{
      "character_id": "c001",
      "resolve": ["处决文书今日到期"]
    }}
  ],
  "misinformation_updates": [
    {{
      "character_id": "c001",
      "disproven": ["一度怀疑自己看见旧字只是眼花（后自我纠正）"],
      "corrected": [{{"from": "旧错误信念", "to": "修正后的信念"}}]
    }}
  ]{transitions_field}
}}

字段约束（与解析契约一致，必须遵守）：
- route 仅可取 pass | rewrite | block 之一（不要写 revise/review/continue 等值）；
- severity 仅可取 critical | blocking | warning | low 之一；
- reminders[].family 仅可取 missing_consequence | missing_cost |
  relationship_bridge_needed | promise_followup_needed | knowledge_check_needed 之一；
- reminders[] 仅允许字段：reminder_id / family / trigger_condition / window /
  escalation_issue_type / early_escalation_condition / closure_condition /
  priority / status / source_review，不得添加其他字段；
- reminders[].status 仅可取 active | resolved | escalated 之一（默认 active，
  不要自造 monitoring/open/other 等值）；
- reminders[].escalation_issue_type 必须属于该 family 允许的升级类型：
  missing_consequence→missing_consequence；missing_cost→missing_cost；
  relationship_bridge_needed→relationship_jump|motivation_gap；
  promise_followup_needed→promise_loss|missing_consequence；
  knowledge_check_needed→information_leak。

如无问题，返回空 issues 和 "pass" 路由。
foreshadow_updates 可选：仅当某 active 伏笔在本章（含其后果/正文）已被兑现或
明确推进时列出，status 取 active/resolved/abandoned/transformed/open/delayed/
false_path 之一；仍开放的承诺不要列入（保持 active）。
character_knowledge_updates 可选：仅当某角色在本章得知了新信息（情节揭示给了他），
把对应的『不知道X』断言从 drop_unknown 移除、把新得知的信息加入 learn；角色仍
不知道的不要列入。
character_pressure_updates 可选：仅当某角色在本章的某条当前压力已被解决/不再
成立（如目标达成、威胁解除），把它列进 resolve 从 current_pressure 移除；仍成立
的压力不要列入。
misinformation_updates 可选：仅当某角色的一条错误信念在本章被事实击穿（证据已
给出、角色已不再持有该信念）时，把它列进 disproven 移除；若信念被修正为另一种
形态（如『被抛弃』→『明白是被迫离开但仍有怨』），用 corrected 的 [{{from, to}}]
替换。注意：错误信念是 belief state，与 knowledge truth 分离——事实被证明不等于
人物心理上已经接受，只移除确实不再持有的断言，不要因为『事实被证伪』就把信念
从 misinformation 抹掉。仍成立的错误信念不要列入。{transitions_note}"""

    def is_pass(self, issues: list[ReviewIssue]) -> bool:
        """判断是否通过（无阻断性问题）."""
        return not any(issue.is_blocking() for issue in issues)
