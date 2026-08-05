"""网文风格领域层 — 风格知识规则表.

规则知识，非事实，非推断。结构与 web_fiction.py 对齐：
TypedDict 纯数据表 + 供 style_rules.py 消费。

内容来源：
- 《示例小说丙》人工润色沉淀的量化清单（写作技巧总结.md）
- 网文写作风格研究（tone 特征 / genre 惯例 / AI 味标记 / 作家文风锚点）
"""

from typing import TypedDict


class ToneTraitEntry(TypedDict):
    trait: str  # "情绪呈现"
    instruction: str  # 具体写作指引


class AiFlavorMarker(TypedDict):
    rule_id: str
    category: str  # weak_adverb | metaphor_repeat | explanatory_voice | shell | parallel | emotion | dialogue_tag | dash_colon
    description: str
    measure_unit: str  # per_1000_chars | absolute | count
    threshold: float
    severity: str  # warning | low
    instructions: list[str]


# --- 叙事调性 → 具体写作特征 ---

TONE_STYLE_TRAITS: dict[str, list[ToneTraitEntry]] = {
    "克制": [
        {"trait": "情绪呈现", "instruction": "情绪靠身体反应（冷汗/攥拳/瞳孔一缩），不用'他感到/他恐惧'" },
        {"trait": "节奏", "instruction": "叙述默认 20-30 字长句；情绪爆点用独立短句" },
        {"trait": "留白", "instruction": "顿悟用矛盾呈现（'可他从不记得来过'）而非'他忽然明白'" },
        {"trait": "物象", "instruction": "一个物象开头出现、结局变化/回归（闭环物象）" },
        {"trait": "对话", "instruction": "对白极简，多是一问一答或沉默，形成紧张场域" },
    ],
    "热血": [
        {"trait": "动词密度", "instruction": "强势动词替换温吞表达，'她生气'→'她捏碎了玻璃杯'" },
        {"trait": "短句爆破", "instruction": "三五个字短句连续扫射；超过三个逗号的长句立即拆解" },
        {"trait": "五感", "instruction": "每个战斗场景至少 2 种非视觉感官（听觉/触觉/嗅觉）" },
        {"trait": "少写情绪多写结果", "instruction": "不写'他气得发抖'，写'指节捏得发白，一字一顿从牙缝挤出来'" },
        {"trait": "用静写强", "instruction": "强者压迫感用安静呈现：'他只抬了一眼。全场瞬间死寂。'" },
    ],
    "暗黑": [
        {"trait": "代价具象化", "instruction": "代价落到可数物件（名字/脸/旧发带），不写抽象痛苦" },
        {"trait": "零度叙事", "instruction": "以近乎冷酷的平静叙述极端事件，不做道德审判，禁感叹号抒情" },
        {"trait": "感官剥夺", "instruction": "否定性描写剥夺常规联想：'整个世界没有一个植物'" },
        {"trait": "反温情", "instruction": "禁写无代价的温情桥段，温情需被解构" },
    ],
    "冷峻": [
        {"trait": "电报体", "instruction": "极少修饰语，删掉不承载信息的副词（很/非常/相当）" },
        {"trait": "事实呈现", "instruction": "以事实代替评论，叙述句不出现价值判断词" },
        {"trait": "细节暗示", "instruction": "关键信息用动作/景物/对话暗示，绝不点破" },
        {"trait": "结构晶体化", "instruction": "舍弃枝蔓直奔核心冲突，截取一个时间段/时间点" },
    ],
    "幽默诙谐": [
        {"trait": "反差比喻", "instruction": "比喻第二半翻转预期：'他的笑容温暖得像冬天的太阳——主要功能是照明，不负责供暖'" },
        {"trait": "嘴替旁白", "instruction": "叙事声音机智犀利，内心 OS 外化调侃" },
        {"trait": "对话密集", "instruction": "对白必须有趣且承担塑造人物/推动剧情/制造冲突之一" },
        {"trait": "预期反差", "instruction": "正经开头+离谱结尾；一本正经地干蠢事" },
        {"trait": "分寸感", "instruction": "能戳小痛点，不能戳伤口；先逗一下再递上温暖" },
    ],
    "文艺细腻": [
        {"trait": "白描为本", "instruction": "用动词+名词打天下，'她很美'→'她笑的时候，右边嘴角会先往上翘半分'" },
        {"trait": "细节越小力量越大", "instruction": "微观视角：'他数清了对面墙砖的裂缝，37条'" },
        {"trait": "道具记忆", "instruction": "物品承载人物故事与温度，'笔帽内侧刻着歪扭的勇字'" },
        {"trait": "感官留白", "instruction": "一个感官细节+留白，让读者自行代入" },
        {"trait": "语言极简", "instruction": "淡味/浓情白描二选一，底层都不靠形容词" },
    ],
    "爽文快节奏": [
        {"trait": "节奏单元固化", "instruction": "每章一个小结果，每3章一个中高潮（压→转→爽），委屈不过3章" },
        {"trait": "对话优先", "instruction": "能用对话交代的绝不靠旁白；大段叙述是爽文大忌" },
        {"trait": "压得越狠打脸越爽", "instruction": "先让主角被极度贬低，读者知真相剧中人不知，再当众爆发" },
        {"trait": "断章留钩", "instruction": "每章结尾断在悬念最高点、情节转折前" },
        {"trait": "配角衬托", "instruction": "高手称赞比路人惊叹更暗爽；配角震惊/嫉妒/折服烘托主角" },
    ],
}

# --- Genre → 写作风格惯例 ---

GENRE_STYLE_GUIDANCE: dict[str, list[str]] = {
    "仙侠": [
        "古典白话痕迹，近金庸而非现代修真口语；人物言行恪守古典范式",
        "境界术语有典籍依据（练气/筑基/金丹），功法命名贴合内丹学，不造玄奥无凭的新词",
        "景物白描承载天人感应修行逻辑，不写无意义的散文化文字",
        "诗化对白沿《红楼梦》浅白畅快，招式渲染点到为止，忌每招喊术语名",
        "突破要写出生理/神识/法力变化的'过程实录'，让读者可感可信",
    ],
    "玄幻": [
        "世界观像冰山只露一角，设定打碎穿插在剧情/对话/旁白中，开篇绝不上设定集",
        "力量体系层级数量服务篇幅，境界名具象化（淬体境=强化肉身）",
        "代入感靠具象化：'一拳破天'优于'九天十地禁咒'",
        "战斗拒绝数值对轰，用环境杀、规则战、情感暴击",
        "节奏三层：单章钩子、小阶段高潮、大阶段升级；'不是换地图，是换规则'",
    ],
    "都市": [
        "设定和描写越真实越好，对话和神态描写需求高，景物描写要求低",
        "以情爱/生活为核心，用偶遇、误解、冲突结构故事",
        "口语化、生活化比喻",
        "城市孤独感是常驻情绪基座",
    ],
    "科幻": [
        "核心能力是脑洞力：构建逻辑自洽的新世界，尊重科学结论合理设想",
        "软科幻重哲学/心理学/社会学，硬科幻以物理化学生物为基础",
        "用设定驱动思考而非纯炫技；点子+逻辑链优于辞藻",
        "世界观细节要经得起反推，战力/科技等级自洽优先",
    ],
    "悬疑": [
        "总悬念贯穿始终逐步揭开，悬念用科学/逻辑解释",
        "线索公平：真线索与红鲱鱼均匀分布，真线索尽量基于常识",
        "伏笔双关：表面一层意思、暗藏另一层含义；所有伏笔必须回收",
        "心跳式节奏：平时匀速、关键时刻短句硬切",
        "视角限制制造悬念：第一人称有限视角是工具",
        "反转必须'预料之外、情理之中'；禁止陨石遁/外星人解释",
    ],
    "言情": [
        "爱情写得一波三折；甜时细节要慢、虐时节奏要快、关键节点留白",
        "核心能力是共情力：细腻捕捉人物复杂微妙的情绪，心理描写占比高",
        "不在次要人物、次要事件及环境描写上浪费笔墨",
        "对话带潜文本（表面语言表达内心未说出的意图）",
    ],
}

# --- AI 味标记库 ---
# 量化指标按"多特征同时密集出现"判 AI 味，单一特征不作数。

AI_FLAVOR_MARKERS: list[AiFlavorMarker] = [
    {
        "rule_id": "ai_weak_adverb_density",
        "category": "weak_adverb",
        "description": "弱化副词密度（微微/淡淡/缓缓/轻轻/隐隐）",
        "measure_unit": "per_1000_chars",
        "threshold": 3.0,
        "severity": "warning",
        "instructions": [
            "能删就删（轻轻点了点头→点了点头）",
            "换具体动作",
            "用身体反应替代",
        ],
    },
    {
        "rule_id": "ai_metaphor_repeat",
        "category": "metaphor_repeat",
        "description": "同一喻体重复（像/如/仿佛…一样 后名词 ≥3 次）",
        "measure_unit": "absolute",
        "threshold": 3.0,
        "severity": "warning",
        "instructions": [
            "一个意象只服务一个场景",
            "同一情绪换不同感官的具象物",
        ],
    },
    {
        "rule_id": "ai_explanatory_voice",
        "category": "explanatory_voice",
        "description": "解释腔句式（他忽然明白/这意味着/他感到）",
        "measure_unit": "count",
        "threshold": 1.0,
        "severity": "warning",
        "instructions": [
            "删'他忽然明白/这意味着'",
            "改动作或矛盾呈现顿悟",
        ],
    },
    {
        "rule_id": "ai_shell_not_a_but_b",
        "category": "shell",
        "description": "'不是A而是B'空转壳句式",
        "measure_unit": "count",
        "threshold": 2.0,
        "severity": "low",
        "instructions": [
            "真对比（两种感知/解释差异）保留",
            "空转强调删除",
        ],
    },
    {
        "rule_id": "ai_parallel_four",
        "category": "parallel",
        "description": "四连及以上排比（逗号/顿号分隔同构项）",
        "measure_unit": "count",
        "threshold": 1.0,
        "severity": "low",
        "instructions": [
            "拆成具体句",
            "台词内可豁免",
        ],
    },
    {
        "rule_id": "ai_emotion_announcement",
        "category": "emotion",
        "description": "情绪宣布词（涌起一股/深吸一口气/眼眶一热）",
        "measure_unit": "per_1000_chars",
        "threshold": 2.0,
        "severity": "warning",
        "instructions": [
            "情绪动词直接+名词式情绪短语改用动作",
            "'心中涌起怒火'→'攥紧拳头'",
        ],
    },
    {
        "rule_id": "ai_dialogue_tag_density",
        "category": "dialogue_tag",
        "description": "僵硬对话标签（说道/问道/沉声道）",
        "measure_unit": "per_1000_chars",
        "threshold": 3.0,
        "severity": "warning",
        "instructions": [
            "删除多余标签，用动作/换行替代",
            "连续多句对白避免同一种标签",
        ],
    },
    {
        "rule_id": "ai_dash_colon_density",
        "category": "dash_colon",
        "description": "破折号+冒号密度（AI 约 2.7-3.2× 人类基线）",
        "measure_unit": "per_1000_chars",
        "threshold": 3.0,
        "severity": "warning",
        "instructions": [
            "破折号降密度，每千字 ≤3",
            "冒号+分号不要过于整齐的'一是…二是…三是'结构",
        ],
    },
    {
        "rule_id": "ai_connective_abuse",
        "category": "connective",
        "description": "段落/句首固定连接词（此外/同时/然而/综上所述等）",
        "measure_unit": "count",
        "threshold": 1.0,
        "severity": "low",
        "instructions": [
            "删段落开头固定连接词，直接进入事件/画面",
            "同一连接词连续出现即拆句",
        ],
    },
    {
        "rule_id": "ai_colon_enumeration",
        "category": "dash_colon",
        "description": "'一是…二是…三是…' 整齐枚举结构",
        "measure_unit": "count",
        "threshold": 1.0,
        "severity": "low",
        "instructions": [
            "冒号+分号不要过于整齐的'一是…二是…三是'结构",
            "枚举改成有主次的推进，避免罗列",
        ],
    },
]

# --- 基础标记集合（供量化分析器使用） ---

WEAK_ADVERB_SET: set[str] = {"微微", "淡淡", "缓缓", "轻轻", "隐隐", "低低", "悄悄"}

EXPLANATORY_PHRASES: list[str] = [
    "他忽然懂了",
    "他忽然明白",
    "他终于明白",
    "他终于懂了",
    "这意味着",
    "原来如此",
    "他觉得",
    "他感到",
    "他意识到",
]

SHELL_NOT_A_BUT_B_RE: str = r"不是[^。！？；\n]{1,15}而是[^。！？；\n]{1,15}"

PARALLEL_ITEM_SEP: str = "[，、,；；]"

# 显性连接词滥用（段落开头固定词）
CONNECTIVE_ABUSE_OPENERS: list[str] = [
    "此外",
    "同时",
    "然而",
    "值得注意的是",
    "不可否认的是",
    "众所周知",
    "总而言之",
    "综上所述",
    "鉴于此",
]

# 情绪宣布词
EMOTION_ANNOUNCEMENT_PHRASES: list[str] = [
    "他深吸一口气",
    "她眼眶一热",
    "涌起一股",
    "心头一紧",
    "心底一沉",
    "一股暖流涌上心头",
    "心中涌起",
]

# 僵硬对话标签
DIALOGUE_TAG_OVERUSE: list[str] = [
    "说道",
    "问道",
    "沉声道",
    "冷冷道",
    "缓缓说道",
    "低声道",
    "开口道",
]

# --- 作家文风锚点（供 LLM 提炼参考） ---

AUTHOR_STYLE_ANCHORS: dict[str, str] = {
    "金庸": "白描+史笔，大段绵密铺陈，招式与人物性格对应，语言端庄大气",
    "古龙": "短句、分行与留白，'长句如大河一泻而来，突然以短句相接如剑断水'",
    "猫腻": "文青气质，文字细腻有温度，思想内涵强",
    "烽火戏诸侯": "高逼格文青，掉书袋，金句频出，群像刻画血肉丰满",
    "priest": "行文流畅语言精练，幽默与深刻并存，感情线克制",
    "老舍": "京味白话、口语化、幽默感，白描精准，'大白话写力量'",
}

# =====================================================================
# 写作手法世界观（v3）：创作要素 × 手法谱系
# ---------------------------------------------------------------------
# 概念：作品由要素构成（描写/人物/对白/抒情/意象…），每个要素可选用
# 不同手法去写。这些表给出每种手法的定义、写作指令、误用警示与适用气质，
# 作为风格提炼的分类轴 / compose 注入的写作约束 / 审查规则的判断依据。
# 规则知识，非事实，非推断。形状对齐 TONE_STYLE_TRAITS（纯数据表）。
# =====================================================================


class TechniqueEntry(TypedDict):
    name: str  # 手法名，如 "白描"
    definition: str  # 定义（权威出处/美学依据）
    instruction: str  # 具体写作指令
    misuse: str  # 常见误用警示
    temperament_fit: list[str]  # 适用叙事气质桶


class TemperamentBucket(TypedDict):
    name: str  # 气质名
    description: str  # 气质定义
    default_focus: list[str]  # 该气质默认聚焦的手法/要素
    baseline_notes: list[str]  # 量化参考基线（供审查/相似度/注入）


# --- 描写手法轴（白描/细描/渲染/衬托/侧面/动静/点面） ---

DESCRIPTION_TECHNIQUES: list[TechniqueEntry] = [
    {
        "name": "白描",
        "definition": "以简洁素朴的语言直接勾勒事物形象，不施修饰色彩（'绘事后素'，素笔勾画）",
        "instruction": "用动词+名词打天下，删除不承载信息的形容词/副词；'她很美'→'她笑的时候，右边嘴角会先往上翘半分'",
        "misuse": "白描≠干瘪，缺乏具象动词会退化成流水账",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "细描(工笔)",
        "definition": "用密集细节精细刻画对象局部，放大决定性细节",
        "instruction": "选择一到两个决定性细节放大，不平均用力；'他数清了对面墙砖的裂缝，37条'",
        "misuse": "工笔不等于堆砌，面面俱到反失重点",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "渲染",
        "definition": "通过环境、气氛、情绪的铺陈烘托对象，营造氛围而非直接陈述",
        "instruction": "用景物/光影/声响铺气氛，让情绪从氛围中渗出；'雨下了整整一夜'承载未言明的离别",
        "misuse": "渲染过度=无信息量的辞藻堆砌；渲染须服务于情绪与主题",
        "temperament_fit": ["氛围型", "戏剧型"],
    },
    {
        "name": "衬托(正衬/反衬)",
        "definition": "以宾衬主，通过类似(正衬)或相反(反衬)事物突出主体，'烘云托月'",
        "instruction": "主角的情绪/处境由他人反应、环境细节侧面带出，不直写内心；'所有人都停下筷子'",
        "misuse": "衬托≠转移视角，被衬对象须始终在场；宾体不能喧宾夺主",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "侧面描写",
        "definition": "通过他人之眼、之言、之反应描写对象，不正面直写",
        "instruction": "用旁观者视角写主角的强/弱/魅力，读者自行推断",
        "misuse": "侧面描写过多会绕，关键信息仍需正面锚定",
        "temperament_fit": ["散文型"],
    },
    {
        "name": "动静结合",
        "definition": "静态画面与动态事件交错，以静衬动或以动衬静",
        "instruction": "大战前写极静的瞬间，以静势压住动势",
        "misuse": "动静是节奏手段，不宜机械交替",
        "temperament_fit": ["戏剧型", "氛围型"],
    },
    {
        "name": "点面结合",
        "definition": "全景(面)与特写(点)结合，既有全貌又有细节",
        "instruction": "写大场面先给全景一笔，再落一个具体人物的特写",
        "misuse": "点面无比例=大场面失焦",
        "temperament_fit": ["戏剧型", "信息型"],
    },
]

# --- 含蓄表现手法轴（象征/暗示/用典/双关） ---

SUBTLE_TECHNIQUES: list[TechniqueEntry] = [
    {
        "name": "象征",
        "definition": "以具体物象承载抽象含义，物象与含义有约定俗成的关联",
        "instruction": "一个象征物贯穿全篇，结尾变化/回归完成闭合（闭环物象）",
        "misuse": "象征不能过度注解，点到即止",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "暗示",
        "definition": "不点破，通过细节、伏线、留白让读者自行推断出结论",
        "instruction": "把结论藏进动作/物件/旁人反应里；顿悟用矛盾呈现，'可他从不记得来过'",
        "misuse": "暗示须有迹可循、线索公平；完全无据=故弄玄虚",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "用典",
        "definition": "引用典籍、史事、成句以含蓄表达",
        "instruction": "用典须贴合语境，为文脉服务而非掉书袋",
        "misuse": "过度用典增加阅读门槛",
        "temperament_fit": ["氛围型", "散文型"],
    },
    {
        "name": "双关",
        "definition": "同一表达承载字面与言外两层含义",
        "instruction": "关键对白用双关，让知情者读字面、当局者听弦外",
        "misuse": "双关须语境自然，生硬=冷笑话",
        "temperament_fit": ["氛围型", "戏剧型"],
    },
]

# --- 留白轴（点破/留白，Art of Omission） ---

OMISSION_AXIS: list[TechniqueEntry] = [
    {
        "name": "点破",
        "definition": "直接陈述信息、情绪与结论",
        "instruction": "信息型叙事/爽文节奏可用直给；情绪用动作呈现而非'他感到'",
        "misuse": "关键情绪全靠点破=无回味、AI 味",
        "temperament_fit": ["信息型", "戏剧型"],
    },
    {
        "name": "留白",
        "definition": "省略不写或只写一半，留由读者补全（Art of Omission）",
        "instruction": "关键动作写细、过渡/氛围一笔带过（密疏配比）；顿悟不点破",
        "misuse": "处处留白=读者不知所云；留白需与密写配比",
        "temperament_fit": ["散文型", "氛围型"],
    },
]

# --- 人物五法轴（肖像/动作/语言/心理/神态） ---

CHARACTER_METHODS: list[TechniqueEntry] = [
    {
        "name": "肖像",
        "definition": "外貌、装束、神色描画人物",
        "instruction": "用特征化细节而非罗列五官；'笔帽内侧刻着歪扭的勇字'",
        "misuse": "肖像不承载性格=无效描写",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "动作",
        "definition": "以动作写人物状态与性格",
        "instruction": "'她捏碎了玻璃杯'胜于'她很生气'；身份决定动作分寸",
        "misuse": "动作缺乏身份/情绪依据=炫技",
        "temperament_fit": ["散文型", "戏剧型"],
    },
    {
        "name": "语言",
        "definition": "以对白与说话方式呈现人物",
        "instruction": "对白贴合身份/性格/处境，不同人物可区分",
        "misuse": "所有人物同一种腔调=人物失格",
        "temperament_fit": ["散文型", "信息型"],
    },
    {
        "name": "心理",
        "definition": "直接呈现内心活动与独白",
        "instruction": "心理与内独白控制密度，show-don't-tell 优先；情绪靠身体反应",
        "misuse": "心理密度过高=解释腔/AI 味",
        "temperament_fit": ["氛围型", "戏剧型"],
    },
    {
        "name": "神态",
        "definition": "以神情变化传递未言之情绪",
        "instruction": "眼神/表情的微小变化承载大情绪；'他笑了，笑意没到眼底'",
        "misuse": "神态与情绪脱节=误导读者",
        "temperament_fit": ["散文型", "氛围型"],
    },
]

# --- 对白技巧轴（潜文本/性格化/言外之意） ---

DIALOGUE_TECHNIQUES: list[TechniqueEntry] = [
    {
        "name": "潜文本",
        "definition": "对白表面一层意思，内里藏着未说出的意图",
        "instruction": "对话带潜文本；'你今晚早点回来'可能意为'我在意你'",
        "misuse": "潜文本须有语境支撑，人人潜文本=故弄玄虚",
        "temperament_fit": ["散文型", "氛围型"],
    },
    {
        "name": "性格化",
        "definition": "对白风格因人物而异，隐藏人名也可辨别说话者",
        "instruction": "不同身份/性格用不同措辞、句长、口头禅",
        "misuse": "性格化靠堆口头禅=贴标签",
        "temperament_fit": ["散文型", "信息型"],
    },
    {
        "name": "言外之意",
        "definition": "借题发挥、声东击西表达真实意图",
        "instruction": "借一件小事传达另一件大事的试探/警告",
        "misuse": "言外之意过多=绕弯子拖节奏",
        "temperament_fit": ["氛围型", "戏剧型"],
    },
]

# --- 决策依据轴（选择为什么这么做；role 逻辑层，非手法） ---

DECISION_GROUNDING_AXIS: list[TechniqueEntry] = [
    {
        "name": "身份驱动",
        "definition": "选择由角色的身份、地位、处境约束决定——'一个人基于身份会做对什么做错什么'",
        "instruction": "每个关键选择须能回溯到身份：他是谁，这个身份在此情势下会怎么做",
        "misuse": "身份驱动≠刻板，同一身份不同性格仍有分歧空间",
        "temperament_fit": ["散文型", "戏剧型", "信息型", "氛围型"],
    },
    {
        "name": "信念驱动",
        "definition": "选择由角色的价值观、信念、理想、恐惧、缺陷驱动",
        "instruction": "写'他为什么不肯低头'时回溯到 inner_need/fear/flaw；选择像人而非理性人",
        "misuse": "信念须与人物弧一致，不能为情节临时改信念",
        "temperament_fit": ["散文型", "戏剧型", "信息型", "氛围型"],
    },
    {
        "name": "剧情需要(plot-driven)",
        "definition": "选择只服务剧情推进，缺乏角色内在依据——全局最优或随情节摆布（'剧情工具人'风险）",
        "instruction": "识别并提示：该选择是否有身份/信念依据？无则补依据或改为有依据的选择",
        "misuse": "审查时区分'有意的戏剧性反转'与'无依据的剧情需要'",
        "temperament_fit": ["警示项"],
    },
    {
        "name": "随机",
        "definition": "选择无内在逻辑，纯随机/掷骰子",
        "instruction": "警惕随机选择：除非有意写荒诞，否则是审稿警告信号",
        "misuse": "随机≠无理由的反转",
        "temperament_fit": ["警示项"],
    },
]

# --- 叙事气质桶（作品类型化的评价基准，与 genre 平行） ---

TEMPERAMENT_BUCKETS: list[TemperamentBucket] = [
    {
        "name": "散文型",
        "description": "以写人、写情、写意为主，重描述手法与留白，节奏舒缓",
        "default_focus": ["白描", "衬托", "侧面描写", "留白", "潜文本", "象征", "暗示"],
        "baseline_notes": [
            "低修饰负载（白描负代理）",
            "关键动作写细、过渡一笔带过（密疏）",
            "情绪由旁观者反应/环境细节带出，不直说",
        ],
    },
    {
        "name": "戏剧型",
        "description": "以冲突、张力、情绪起伏为主，重渲染与动静结合",
        "default_focus": ["渲染", "动静结合", "言外之意", "心理"],
        "baseline_notes": [
            "情绪张力密集，关键节点用 high-effectiveness 钩子",
            "动静交替制造节奏势能",
        ],
    },
    {
        "name": "信息型",
        "description": "以推进情节、传达信息为主，直给、快节奏、少留白",
        "default_focus": ["点面结合", "语言", "点破", "性格化"],
        "baseline_notes": [
            "对话优先，大段叙述是忌",
            "每章小结果、每3章中高潮",
            "直给密度高（非白描型）",
        ],
    },
    {
        "name": "氛围型",
        "description": "以意境、氛围、意象为主，重渲染与象征，虚实相生",
        "default_focus": ["渲染", "象征", "用典", "神态", "留白"],
        "baseline_notes": [
            "感官细节丰富，意境贴合结构节点",
            "意象承载情绪，物象闭环",
        ],
    },
]

# 全部气质桶名（校验 temperament_fit 指向用）
TEMPERAMENT_NAMES: list[str] = [bucket["name"] for bucket in TEMPERAMENT_BUCKETS]
