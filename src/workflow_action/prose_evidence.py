"""ProseEvidence 提取器 — 从待提交正文提取可核对的事实/状态断言.

代码级、确定性提取（零 LLM），把「正文说了什么」固化为 ProseEvidencePackage。
设计边界：
- 只提取无歧义的结构化信号（时间、实体状态、道具身份、元文本、选择、事件）；
- 每条断言带原文证据锚点；无证据不输出；
- 实体/道具身份核对依赖调用方提供 entities 注册表（entity_id -> 标签）；
  无注册表则相应类别静默为空（无法核对就不断言）。

覆盖 Phase 0 夹具对应的失败类：
  时间回退 / 周期算术 / 实体状态回退 / 道具身份变化 / 元文本泄漏。
重复顿悟与开头复述在 reconcile 阶段用 prev_chapters 计算（本模块提供辅助函数）。
"""

import hashlib
import re
from typing import Optional

from src.object_state.prose_evidence import ProseEvidenceItem, ProseEvidencePackage

# --------------------------------------------------------------------------
# 正则与词表
# --------------------------------------------------------------------------

_CN_MONTHS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
    "九": 9, "十": 10, "十一": 11, "十二": 12, "腊": 12,
}
_MONTH_RE = re.compile(r"(一|二|三|四|五|六|七|八|九|十|十一|十二|腊)月")

# 粗分季节（1-3 春 / 4-6 夏 / 7-9 秋 / 10-12 冬）
_SEASON_WORDS = {
    "开冻": "春", "回暖": "春", "抽芽": "春", "春": "春", "风筝": "春",
    "夏": "夏", "酷暑": "夏", "蝉": "夏",
    "秋": "秋", "落叶": "秋", "枯叶": "秋", "雁": "秋",
    "冬": "冬", "寒风": "冬", "结冰": "冬", "炉子": "冬", "雪": "冬",
}

# 相对时间：N年（十一年/六十年/一年后/多年过去）、次日/第二天 等
_REL_YEARS_RE = re.compile(r"(十[一二三四五六七八九]|廿|卅|二十|三十|四十|五十|六|七|八|九|多|[一二三四五六七八九十]+)(年)?(过去|之后|后|前|之期)")
_REL_DAY_RE = re.compile(r"(次日|第二天|隔天|翌日|当天|第三天|三天后|一周后|一月后|翌年|来年|明年|去年)")
_FLASHBACK_RE = re.compile(r"(回忆|想起|那年|回到从前|从前|当年|闪回|往昔|昔日|记得那时|依稀|回想)")

# 元文本泄漏（生成/编辑过程文字进正文）
_META_TEXT_RE = re.compile(r"(上一章|本章|下一章|第[0-9一二三四五六七八九十]+章|第[0-9一二三四五六七八九十]+回|章末|上回|前文|结尾处|下文|开头处)")
# 章节标题（行首的「第N章」「第N回」是合法标题行，非元文本泄漏——CLAUDE.md
# 章节正文保留标题行「第一章 开端」）
_CHAPTER_TITLE_RE = re.compile(r"^第[0-9一二三四五六七八九十]+[章回]")
# 「下文」后接章回体叙事习语 = 正常叙事（下文再表/下文自有分晓/下文如何/下文详见），
# 不是生成/编辑过程文字。匹配从「下文」结束位置开始的叙事后缀。
_NARRATIVE_AFTER_DOWN_WEN_RE = re.compile(
    r"(再表|自有分晓|自有交代|自有分解|详见|如何|怎么|会发生|且听|自见分晓|自有下文|见分晓)"
)

# 实体状态动词 -> 规范化状态
_STATUS_VERBS = {
    "不见了": "missing", "失踪": "missing", "消失": "missing", "重新不见了": "missing",
    "死亡": "dead", "死了": "dead", "陨落": "dead", "身亡": "dead",
    "被找到": "found", "已找到": "found", "找到了": "found", "归来": "found",
    "回家": "home", "已到家": "home", "离开": "left", "走了": "left",
    "被困": "trapped", "被救": "rescued",
}

# 道具身份变化 / 持有转移
_PROP_TRANSFORM_RE = re.compile(r"(变成|化为|变作|成了|其实是|原来是|竟然是)([^\s，。！？]{1,6})")
_PULL_RE = re.compile(r"(拈出|拿出|取出|抽出|掏出|翻出|找到|夹出)([^\s，。！？]{1,6})(?:物|片|张|本|封信|照片|花瓣|票|纸|壳|盒)?")

# 选择 / 决定
_CHOICE_RE = re.compile(r"(决定|选择|拿定主意|下定决心|打定主意|打定主意要|决定不|决定要|执意|铁了心)(要|去|做|不|留下|离开|答应|拒绝|干|买|卖|走|等|出手|投)?")
_CONSEQUENCE_RE = re.compile(r"(结果|于是|只得|只好|此后|自此|从那天起|这一晚之后)")

# 实质性事件动词（区别于 坐/看/换手/走回 等氛围/位移动词）
_SUBSTANTIVE_EVENT_RE = re.compile(
    r"(决定|选择|找到|发现|拿到|失去|被告知|承认|坦白|说出|开口|答应|拒绝|赶来|拦住|抵达|出发|交易|签|买下|卖出|告诉|得知|揭开|查清|证实|赎回|托付|托|寄出|收到|交还|带走|闯入|绑架|劫走|被抓|逃跑|逃走|宣布|继任|落网|供出)"
)
_AMBIENT_VERB_RE = re.compile(r"(坐着|坐下|站着|站起|起身|抬头|低头|闭上|睁开|看|望|听|想|发呆|叹气|掸|喝水|沏茶|换到|换回|走回|回到|走|出门|打伞|抽|夹|放回|合上|推开|推开窗|倒了一杯|坐了很久)")

# 顿悟/结论句
_CONCLUSION_RE = re.compile(r"(终于明白|忽然明白|才明白|他明白|她明白|恍然大悟|明白过来|意识到|恍然)")

_SENT_SPLIT_RE = re.compile(r"[。！？!?]")


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text)]
    return [p for p in parts if p]


def opening_signature(text: str, n_sentences: int = 2) -> str:
    """开头签名：前 n 句拼合（用于相邻章开头复述检测）. """
    return "".join(split_sentences(text)[:n_sentences])


def conclusion_sentences(text: str) -> list[str]:
    """顿悟句：含顿悟标记的句子，归一化（去空白/标点）. """
    out = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？!?":
            s = buf.strip()
            if _CONCLUSION_RE.search(s):
                norm = re.sub(r"\s+", "", s)
                out.append(norm)
            buf = ""
    if buf.strip() and _CONCLUSION_RE.search(buf.strip()):
        out.append(re.sub(r"\s+", "", buf.strip()))
    return out


def _loc(text: str, pos: int) -> str:
    total = max(1, len(text))
    if pos < total / 5:
        return "开头"
    if pos > total * 4 / 5:
        return "结尾"
    return "中段"


def _sentence_containing(text: str, pos: int) -> str:
    """返回包含 pos 的句子片段. """
    start = text.rfind("。", 0, pos) + 1
    end = text.find("。", pos)
    if end == -1:
        end = len(text)
    return text[start:end]


# --------------------------------------------------------------------------
# 提取
# --------------------------------------------------------------------------

def _extract_time(text: str, seq: int) -> list[ProseEvidenceItem]:
    items: list[ProseEvidenceItem] = []
    for m in _MONTH_RE.finditer(text):
        fb = bool(_FLASHBACK_RE.search(_sentence_containing(text, m.start())))
        month = _CN_MONTHS[m.group(1)]
        items.append(
            ProseEvidenceItem.new(
                seq, "time", f"时间断言: {m.group(0)}（月份 {month}）",
                m.group(0), location=_loc(text, m.start()), flashback_marked=fb,
            )
        )
        seq += 1
    for w, season in _SEASON_WORDS.items():
        for m in re.finditer(w, text):
            fb = bool(_FLASHBACK_RE.search(_sentence_containing(text, m.start())))
            items.append(
                ProseEvidenceItem.new(
                    seq, "time", f"时间断言: {m.group(0)}（季节 {season}）",
                    m.group(0), location=_loc(text, m.start()), flashback_marked=fb,
                )
            )
            seq += 1
    for m in _REL_YEARS_RE.finditer(text):
        fb = bool(_FLASHBACK_RE.search(_sentence_containing(text, m.start())))
        items.append(
            ProseEvidenceItem.new(
                seq, "time", f"时间断言: 相对时长 {m.group(0)}",
                m.group(0), location=_loc(text, m.start()), flashback_marked=fb,
            )
        )
        seq += 1
    for m in _REL_DAY_RE.finditer(text):
        fb = bool(_FLASHBACK_RE.search(_sentence_containing(text, m.start())))
        items.append(
            ProseEvidenceItem.new(
                seq, "time", f"时间断言: {m.group(0)}",
                m.group(0), location=_loc(text, m.start()), flashback_marked=fb,
            )
        )
        seq += 1
    return items


def _extract_entity_status(
    text: str, entities: dict[str, list[str]], seq: int
) -> list[ProseEvidenceItem]:
    items: list[ProseEvidenceItem] = []
    for eid, labels in entities.items():
        for label in labels:
            for m in re.finditer(re.escape(label), text):
                sent = _sentence_containing(text, m.start())
                for verb, status in _STATUS_VERBS.items():
                    if verb in sent:
                        items.append(
                            ProseEvidenceItem.new(
                                seq, "entity_status",
                                f"实体 {eid}({label}) 状态: {status}",
                                verb,  # 证据锚点为原文真实子串
                                location=_loc(text, m.start()),
                            )
                        )
                        seq += 1
                        break
                # 无主语消失信号：句中"人不见了"且本句出现该实体标签
                if ("不见了" in sent or "失踪" in sent or "消失" in sent) and (
                    "人不见了" in sent or "人不见了。" in sent
                ):
                    items.append(
                        ProseEvidenceItem.new(
                            seq, "entity_status",
                            f"实体 {eid}({label}) 状态: missing（无主语消失句）",
                            "人不见了",  # 证据锚点为原文真实子串
                            location=_loc(text, m.start()),
                        )
                    )
                    seq += 1
    return items


def _extract_prop_identity(
    text: str, entities: dict[str, list[str]], seq: int
) -> list[ProseEvidenceItem]:
    items: list[ProseEvidenceItem] = []
    for m in _PULL_RE.finditer(text):
        obj = m.group(2)
        sent = _sentence_containing(text, m.start())
        items.append(
            ProseEvidenceItem.new(
                seq, "prop_identity",
                f"道具被拿出/翻出: {obj}（句: {sent[:20]}…）",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    for m in _PROP_TRANSFORM_RE.finditer(text):
        obj = m.group(2)
        items.append(
            ProseEvidenceItem.new(
                seq, "prop_identity",
                f"道具身份变化: 变为 {obj}",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    return items


def _extract_meta_text(text: str, seq: int) -> list[ProseEvidenceItem]:
    items: list[ProseEvidenceItem] = []
    for m in _META_TEXT_RE.finditer(text):
        # 行首的「第N章」「第N回」是章节标题（合法正文），不是元文本泄漏；
        # 句中「第N章末」「上一章末」「本章」等过程标记仍按泄漏处理。
        if m.start() == 0 or (m.start() > 0 and text[m.start() - 1] == "\n"):
            if _CHAPTER_TITLE_RE.match(text[m.start():]):
                continue
        # 「下文」在章回体中是标准叙事习语（下文再表/下文自有分晓/下文如何），
        # 不是生成/编辑过程文字，跳过误杀。
        if m.group(0) == "下文" and _NARRATIVE_AFTER_DOWN_WEN_RE.match(text, m.end()):
            continue
        items.append(
            ProseEvidenceItem.new(
                seq, "meta_text",
                f"元文本泄漏: {m.group(0)}（生成/编辑过程文字进入正文）",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    return items


def _extract_choice_consequence(text: str, seq: int) -> list[ProseEvidenceItem]:
    items: list[ProseEvidenceItem] = []
    for m in _CHOICE_RE.finditer(text):
        items.append(
            ProseEvidenceItem.new(
                seq, "choice",
                f"作出的选择: {m.group(0)}",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    for m in _CONSEQUENCE_RE.finditer(text):
        items.append(
            ProseEvidenceItem.new(
                seq, "consequence",
                f"可见后果标记: {m.group(0)}",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    return items


def _extract_state_change(text: str, seq: int) -> list[ProseEvidenceItem]:
    """实质性事件检测：存在 决定/发现/被告知/交易 等事件动词即状态变化信号.

    仅氛围/位移（坐/看/换手/走回）不产生 state_change —— f08 据此判定无状态变化。
    """
    items: list[ProseEvidenceItem] = []
    for m in _SUBSTANTIVE_EVENT_RE.finditer(text):
        items.append(
            ProseEvidenceItem.new(
                seq, "state_change",
                f"实质性事件: {m.group(0)}",
                m.group(0), location=_loc(text, m.start()),
            )
        )
        seq += 1
    return items


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

def extract_prose_evidence(
    text: str,
    *,
    package_id: str = "pe",
    chapter_ref: str = "",
    entities: Optional[dict[str, list[str]]] = None,
) -> ProseEvidencePackage:
    """从正文提取证据包.

    Args:
        text: 待提交正文（草稿）。
        entities: 实体注册表 {entity_id: [标签...]}，用于实体状态/道具身份核对；
            缺省不核对这两类（无法断言）。
    """
    seq = 0
    items: list[ProseEvidenceItem] = []
    for collector in (
        _extract_time,
        _extract_meta_text,
        _extract_choice_consequence,
        _extract_state_change,
    ):
        collected = collector(text, seq)
        items.extend(collected)
        seq += len(collected)

    if entities:
        items.extend(_extract_entity_status(text, entities, seq))
        seq += sum(1 for _ in items)  # 保守推进 seq（后续不再依赖具体序号）
        items.extend(_extract_prop_identity(text, entities, seq))

    return ProseEvidencePackage(
        package_id=package_id,
        chapter_ref=chapter_ref,
        source_text_hash=_sha(text),
        items=items,
    )


def ambient_only(text: str) -> bool:
    """正文是否仅氛围/位移（无实质性事件、无选择、无顿悟、无对白）. """
    if _SUBSTANTIVE_EVENT_RE.search(text):
        return False
    if _CHOICE_RE.search(text):
        return False
    if conclusion_sentences(text):
        return False
    # 有对白（引号内文本）不算无状态变化
    if re.search(r"[“\"『「]", text):
        return False
    return True
