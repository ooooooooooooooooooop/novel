"""网文领域层 — 信息凭证一致性知识表.

规则知识，非事实，非推断。结构与 style_knowledge.py 对齐：
TypedDict 纯数据表 + 供 info_warrant_rules.py 消费。

回答"某个角色凭什么知道某信息"（epistemic warrant），与
docs/03_rules/05_information_release_rules.md（信息释放=分配）正交互补：
- 05 管"该不该知道"（分配）
- 09 管"凭什么知道"（凭证：通道/时效/来源）

内容来源：
- 网文叙事研究：Genette 聚焦理论（零/内/外）、有限视角 POV 常识
- Hitchcock 信息差机制（悬念=读者>角色；神秘=角色>读者）
- Knox 侦探公平游戏规则（读者知情权）
- 本项目真实事故复盘（续写正文信息越权：未亲历却获知细节）
"""

from typing import TypedDict


class InfoChannel(TypedDict):
    name: str  # 通道名
    definition: str  # 定义
    detail_capacity: str  # 能产出的细节级
    reliability: str  # 可靠度
    detection: str  # 检测要点（该通道能/不能产出什么）


class FocalizationType(TypedDict):
    name: str  # 聚焦名
    definition: str  # 定义
    narrator_relation: str  # 叙述者与角色的知识相对关系
    legality: str  # 合法使用方式


class WarrantConstraint(TypedDict):
    rule_id: str  # P1...P4
    name: str  # 约束名
    definition: str  # 公理表述
    instruction: str  # 写作指引
    misuse: str  # 误用警示/非法示例
    detection: str  # 对象层检测要点


class InfoGapForm(TypedDict):
    name: str  # 形态名
    kind: str  # legal | illegal
    relation: str  # 相对关系（角色 vs 读者）
    driver: str  # 驱动情绪
    detection: str  # 检测要点


# --- 信息通道谱系 ---

INFO_CHANNELS: list[InfoChannel] = [
    {
        "name": "亲历感知",
        "definition": "亲眼/亲耳/亲身接触，直接感知对象或事件",
        "detail_capacity": "最高：外观、神态、情绪、内部状态、现场过程",
        "reliability": "高",
        "detection": "唯一能产出外观/神态/情绪等亲历型细节的通道；亲历细节必须能回溯到某亲历者",
    },
    {
        "name": "转述",
        "definition": "他人告知（电话/捎话/汇报/线人/传闻），非直接接触",
        "detail_capacity": "中：转述的内容；不可含转述者未亲历的细节",
        "reliability": "中：会失真、漏报、被刻意误导",
        "detection": "转述通道产出的细节粒度不得超过转述者本人的亲历上限；转述须标注来源",
    },
    {
        "name": "书面文件",
        "definition": "文件/账本/材料/信函/密档",
        "detail_capacity": "具体：数字/名单/交易过程/往来记录",
        "reliability": "视来源与时效",
        "detection": "产出精确数字/名单时须有文件或档案作为通道",
    },
    {
        "name": "公开信息",
        "definition": "公告/新闻/公示/公开会议",
        "detail_capacity": "泛化：公开层面的事实",
        "reliability": "中",
        "detection": "公开信息只能产出公开层面内容，不能产出内部密谋",
    },
    {
        "name": "推断",
        "definition": "由已知前提推出结论",
        "detail_capacity": "结论性：判断、猜测、预案",
        "reliability": "视前提可靠性",
        "detection": "推断须有前提；无前提的'想明白了'是叙述泄漏",
    },
    {
        "name": "记忆",
        "definition": "旧知/前世记忆/档案回忆",
        "detail_capacity": "历史性：过往事实、人物旧闻",
        "reliability": "视年代与来源",
        "detection": "历史细节可经记忆通道；但记忆不能产出当下状态（那是时效问题）",
    },
]

# --- 聚焦三分（Genette） ---

FOCALIZATION_TYPES: list[FocalizationType] = [
    {
        "name": "零聚焦（全知）",
        "definition": "叙述者知道得比任何角色都多，自由穿越角色内心",
        "narrator_relation": "叙述者 > 所有角色",
        "legality": "任意信息可直述，但切换须有标记，否则读者迷失锚点",
    },
    {
        "name": "内聚焦（有限）",
        "definition": "叙述被限制在单一角色感知/记忆/推断/被告知范围内",
        "narrator_relation": "叙述者 = 聚焦角色",
        "legality": "直述不得超过聚焦角色当刻知识域；本项目正文采用（以主角为锚）",
    },
    {
        "name": "外聚焦（客观）",
        "definition": "叙述只录外部可观察的行为与对白，不进入任何角色内心",
        "narrator_relation": "叙述者 < 角色",
        "legality": "只产出可观察行为；用于窥局/留白场景",
    },
]

# --- 四条凭证约束（P1-P4） ---

WARRANT_CONSTRAINTS: list[WarrantConstraint] = [
    {
        "rule_id": "P1",
        "name": "亲历凭证（通道匹配）",
        "definition": "亲历型细节（外观/神态/情绪/内部状态）只能由'亲历感知'通道供给",
        "instruction": "要写亲历细节，先保证有人亲眼/亲耳到过场；转述只能写转述内容",
        "misuse": "转述通道产出亲历细节，且无亲历前提——例：'具体在哪儿还没摸实……人瘦得脱了相'",
        "detection": "同单元共现'亲历细节词'与'未知/未接触否定词' → 提示通道冲突可能",
    },
    {
        "rule_id": "P2",
        "name": "时效凭证（信息不过期）",
        "definition": "角色知道的是'截止某时刻'的信息；旧消息被当当下状态使用 = 凭证过期",
        "instruction": "跨多日剧情中转述消息须带时间锚，或显式让状态更新",
        "misuse": "相隔多日的信息被写成同时状态，且无时间锚区分",
        "detection": "转述消息无时间锚，且与前序状态间隔过长 → 提示时效风险",
    },
    {
        "rule_id": "P3",
        "name": "渠道凭证（无通道则不知）",
        "definition": "每条'知道'都要能回溯到一条通道；无通道 → 不知",
        "instruction": "角色突然掌握需密档/现场/告知才能得到的信息时，补一条合法通道",
        "misuse": "角色无任何观察/告知/推断依据，突然准确说出只有密档才有的内容",
        "detection": "PlotUnit 产出高密细节但对象层无通道引入标记 → 提示叙述泄漏",
    },
    {
        "rule_id": "P4",
        "name": "容量凭证（知识域匹配身份）",
        "definition": "角色知识域与其身份匹配；同一角色对同一信息的知情状态不得翻转",
        "instruction": "前文断言'不知道 X'，后文若产出依赖 X 的细节，须先引入新通道",
        "misuse": "前文'不知道X'，后文直接产出依赖 X 的细节且无新通道",
        "detection": "knowledge_state 含'未知 X'断言，但 PlotUnit 产出依赖 X 的细节 → 提示知识域翻转",
    },
]

# --- 信息差距形态（合法 vs 非法） ---

INFO_GAP_FORMS: list[InfoGapForm] = [
    {
        "name": "神秘",
        "kind": "legal",
        "relation": "角色 > 读者",
        "driver": "好奇（驱动追读）",
        "detection": "章末钩子：扣住'角色已知、读者未知'的关键信息",
    },
    {
        "name": "悬念",
        "kind": "legal",
        "relation": "读者 > 角色",
        "driver": "恐惧/紧张（Hitchcock 桌下炸弹）",
        "detection": "告知读者危险，角色无知",
    },
    {
        "name": "同步共知",
        "kind": "legal",
        "relation": "读者 = 角色",
        "driver": "共情/代入",
        "detection": "常规推进",
    },
    {
        "name": "聚焦切换",
        "kind": "legal",
        "relation": "全知 > 角色（临时）",
        "driver": "全局感（权谋布局）",
        "detection": "必须标注切换点，否则读者迷失锚点",
    },
    {
        "name": "通道越界",
        "kind": "illegal",
        "relation": "角色知识 > 其通道供给",
        "driver": "—",
        "detection": "对应 P1/P3：细节粒度超通道上限",
    },
    {
        "name": "叙述泄漏",
        "kind": "illegal",
        "relation": "叙述直述聚焦角色不可能知道的信息",
        "driver": "—",
        "detection": "对应 P3：无通道引入标记的高密直述",
    },
    {
        "name": "时效过期",
        "kind": "illegal",
        "relation": "旧信息当新状态",
        "driver": "—",
        "detection": "对应 P2：无时间锚的旧消息",
    },
    {
        "name": "知识域翻转",
        "kind": "illegal",
        "relation": "同一角色前后知情状态矛盾",
        "driver": "—",
        "detection": "对应 P4：'未知X'断言 vs 依赖X的产出",
    },
]

# --- 检测 marker 词集（iss_info_* 弱信号用） ---

# 亲历型细节触发词：这类词标记"细节粒度需要亲历前提"。
# 只收"描述他人外观/神态/身体状态"的词（亲历才能写），
# 不收"看着/听见/闻到"等动作感官词（太宽，'远远看着'会误报）。
FIRSTHAND_DETAIL_MARKERS: frozenset[str] = frozenset({
    # 外观/神态/身体细节（亲历才能写）
    "瘦了", "脸色", "眼神", "眼眶", "神态", "气色", "表情", "皮包骨", "脱了相",
    # 强亲历标记
    "亲眼", "亲耳", "亲口", "当场", "面前", "眼睁睁", "亲眼所见",
})

# 未知/未接触否定词：这类词标记"该角色（或其代理）未到现场/未掌握"。
UNKNOWN_NEGATION_MARKERS: frozenset[str] = frozenset({
    "没摸实", "摸不清", "没掌握", "无从", "未及", "打听不到", "下落不明",
    "没到现场", "远在", "隔着", "没接触", "不清楚", "没听说", "不知道", "不知",
})

# 转述通道标记：这类词标记"该信息经转述流入，非亲历"。
RELAY_MARKERS: frozenset[str] = frozenset({
    "转告", "捎话", "带话", "电话", "来电", "来信", "汇报", "上报",
    "听说", "传闻", "听人说", "底下人说", "线人", "传话",
})
