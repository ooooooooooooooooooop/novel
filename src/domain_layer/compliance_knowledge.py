"""网文合规领域层 — 敏感词库与平台政策规则.

规则知识，非事实，非推断。结构与 web_fiction.py / style_knowledge.py 对齐：
TypedDict 纯数据表 + 供 compliance_rules.py 消费。

设计要点（对齐项目惯例）：
- 敏感词**做成开关**：全量渲染为 --sensitive on|off，off 时整个词库不参与扫描。
- 目标平台 = **通用中文**（不锁死番茄/起点/七猫任一）；具体平台条目作参考，不存在时回退通用。
- 词库内容从公开词库（Sensitive-lexicon）导入 + 自建分类，本模块只做接入与分类，不自行生成敏感词。
- 本模块是风险降低不是保证：平台审核是黑箱，过检 ≠ 不封号。

内容来源：
- 公开敏感词库（konsheng/Sensitive-lexicon）分类结构
- 网文平台政策研究（2026-08 盲点审查）：起点 2025-04 起封 AI 直出；番茄 2026 封 855 AI 账号
"""

from typing import TypedDict


class SensitiveEntry(TypedDict):
    word: str
    category: str  # 涉黄 | 涉政 | 涉黑 | 涉赌 | 涉毒 | 迷信 | 暴力 | 未成年人 | 宗教民族 | 性别对立
    severity: str  # block（封号级）| high | medium | low
    note: str  # 语境说明


class PlatformPolicy(TypedDict):
    description: str
    chapter_length_target: str
    update_frequency: str
    ai_direct_output: str
    redline_categories: list[str]
    source: str


# --- 敏感词库 ---
# 通用中文词库，分类齐全。--sensitive off 时整个词库不参与扫描。

SENSITIVE_LEXICON: dict[str, list[SensitiveEntry]] = {
    "涉黄": [
        {"word": "性交", "category": "涉黄", "severity": "block", "note": "直接性行为描写，平台红线"},
        {"word": "做爱", "category": "涉黄", "severity": "block", "note": "直接性行为描写，平台红线"},
        {"word": "阴道", "category": "涉黄", "severity": "block", "note": "直接性器官描写，平台红线"},
        {"word": "阴茎", "category": "涉黄", "severity": "block", "note": "直接性器官描写，平台红线"},
        {"word": "强奸", "category": "涉黄", "severity": "block", "note": "性犯罪描写，平台红线"},
        {"word": "裸体", "category": "涉黄", "severity": "high", "note": "大尺度裸露描写"},
        {"word": "春药", "category": "涉黄", "severity": "high", "note": "性药描写"},
        {"word": "情欲", "category": "涉黄", "severity": "medium", "note": "过度情欲描写"},
        {"word": "销魂", "category": "涉黄", "severity": "medium", "note": "情色语境用词"},
    ],
    "涉政": [
        {"word": "法轮功", "category": "涉政", "severity": "block", "note": "邪教组织，平台红线"},
        {"word": "天安门事件", "category": "涉政", "severity": "block", "note": "敏感历史事件，平台红线"},
        {"word": "六四", "category": "涉政", "severity": "block", "note": "敏感历史事件，平台红线"},
        {"word": "西藏独立", "category": "涉政", "severity": "block", "note": "分裂主张，平台红线"},
        {"word": "台独", "category": "涉政", "severity": "block", "note": "分裂主张，平台红线"},
        {"word": "疆独", "category": "涉政", "severity": "block", "note": "分裂主张，平台红线"},
        {"word": "习近平", "category": "涉政", "severity": "high", "note": "真实国家领导人，禁止娱乐化/负面描写"},
        {"word": "中央军委", "category": "涉政", "severity": "high", "note": "真实国家机构，禁止虚构"},
        {"word": "中南海", "category": "涉政", "severity": "high", "note": "真实政治场所，禁止虚构"},
        {"word": "公安部", "category": "涉政", "severity": "high", "note": "真实国家机构，禁止虚构"},
        {"word": "政法委", "category": "涉政", "severity": "high", "note": "真实国家机构，禁止虚构"},
    ],
    "涉黑": [
        {"word": "黑社会", "category": "涉黑", "severity": "high", "note": "涉黑组织描写"},
        {"word": "帮派火拼", "category": "涉黑", "severity": "medium", "note": "涉黑暴力描写"},
        {"word": "收保护费", "category": "涉黑", "severity": "medium", "note": "涉黑行为描写"},
        {"word": "砍人", "category": "涉黑", "severity": "high", "note": "涉黑暴力描写"},
    ],
    "涉赌": [
        {"word": "赌博", "category": "涉赌", "severity": "medium", "note": "赌博行为描写"},
        {"word": "赌场", "category": "涉赌", "severity": "medium", "note": "赌博场所描写"},
        {"word": "庄家", "category": "涉赌", "severity": "low", "note": "赌博术语"},
        {"word": "下注", "category": "涉赌", "severity": "low", "note": "赌博术语"},
    ],
    "涉毒": [
        {"word": "毒品", "category": "涉毒", "severity": "block", "note": "毒品描写，平台红线"},
        {"word": "海洛因", "category": "涉毒", "severity": "block", "note": "毒品描写，平台红线"},
        {"word": "冰毒", "category": "涉毒", "severity": "block", "note": "毒品描写，平台红线"},
        {"word": "大麻", "category": "涉毒", "severity": "high", "note": "毒品描写"},
        {"word": "吸毒", "category": "涉毒", "severity": "high", "note": "吸毒行为描写"},
        {"word": "制毒", "category": "涉毒", "severity": "block", "note": "制毒描写，平台红线"},
    ],
    "迷信": [
        {"word": "招魂", "category": "迷信", "severity": "medium", "note": "封建迷信描写"},
        {"word": "下咒", "category": "迷信", "severity": "medium", "note": "封建迷信描写"},
        {"word": "符水", "category": "迷信", "severity": "low", "note": "封建迷信描写"},
        {"word": "跳大神", "category": "迷信", "severity": "medium", "note": "封建迷信描写"},
    ],
    "暴力": [
        {"word": "碎尸", "category": "暴力", "severity": "high", "note": "过度暴力描写"},
        {"word": "凌迟", "category": "暴力", "severity": "high", "note": "过度暴力描写"},
        {"word": "分尸", "category": "暴力", "severity": "high", "note": "过度暴力描写"},
        {"word": "血腥", "category": "暴力", "severity": "low", "note": "暴力语境用词"},
        {"word": "虐杀", "category": "暴力", "severity": "high", "note": "过度暴力描写"},
    ],
    "未成年人": [
        {"word": "幼女", "category": "未成年人", "severity": "block", "note": "未成年人性化描写，平台红线"},
        {"word": "幼童", "category": "未成年人", "severity": "block", "note": "未成年人性化描写，平台红线"},
        {"word": "童婚", "category": "未成年人", "severity": "block", "note": "未成年人性化描写，平台红线"},
    ],
    "宗教民族": [
        {"word": "回民", "category": "宗教民族", "severity": "high", "note": "民族描写需谨慎"},
        {"word": "藏独", "category": "宗教民族", "severity": "block", "note": "分裂主张，平台红线"},
        {"word": "阿拉", "category": "宗教民族", "severity": "medium", "note": "宗教用语需谨慎"},
        {"word": "真主", "category": "宗教民族", "severity": "medium", "note": "宗教用语需谨慎"},
    ],
    "性别对立": [
        {"word": "直男癌", "category": "性别对立", "severity": "medium", "note": "性别对立用语"},
        {"word": "田园女权", "category": "性别对立", "severity": "medium", "note": "性别对立用语"},
    ],
}


# --- 平台政策表 ---
# 目标平台 = 通用中文。具体平台条目作参考，不存在时回退"通用"。

PLATFORM_POLICY: dict[str, PlatformPolicy] = {
    "通用": {
        "description": "通用中文平台基准（不锁死任一具体平台）",
        "chapter_length_target": "2000-3000",
        "update_frequency": "daily 4000+",
        "ai_direct_output": "禁止",
        "redline_categories": [
            "涉黄",
            "涉政",
            "涉黑",
            "涉赌",
            "涉毒",
            "侮辱英雄先烈",
            "未成年人不良引导",
        ],
        "source": "platform_policy_research_2026-08",
    },
    "番茄": {
        "description": "番茄小说：签约须满足平台内容规则，违规取消全勤/追回稿费",
        "chapter_length_target": "2000-2300",
        "update_frequency": "daily 4000+",
        "ai_direct_output": "禁止",
        "redline_categories": ["涉黄", "涉黑", "涉政", "侮辱英雄先烈"],
        "source": "platform_policy_research_2026-08",
    },
    "起点": {
        "description": "起点中文网：2025-04 起封 AI 直出账号",
        "chapter_length_target": "2000-2100",
        "update_frequency": "daily 4000+",
        "ai_direct_output": "禁止",
        "redline_categories": ["涉黄", "涉政", "涉黑", "涉赌", "涉毒"],
        "source": "platform_policy_research_2026-08",
    },
    "晋江": {
        "description": "晋江文学城：禁 AI 生成叙事场景，分级处罚（锁章/黄牌/禁榜/退订）",
        "chapter_length_target": "3000-5000",
        "update_frequency": "2-3 per week",
        "ai_direct_output": "禁止",
        "redline_categories": ["涉黄", "涉政", "涉黑"],
        "source": "platform_policy_research_2026-08",
    },
}


# 通用中文平台键（默认目标）
DEFAULT_PLATFORM = "通用"

# 常见 404 词汇（平台过度审查可能误伤的普通词，作者自查用）
# 不参与敏感词扫描，只作提示性参考
COMMON_404_WORDS: list[str] = ["湿", "抱", "吻", "抚摸", "紧贴", "喘息"]


# --- NSFW 内容分级策略（compose/extend 生成侧注入 + compliance 扫描侧联动） ---
# 「涉黄」是敏感词库中的成人内容分类，NSFW 开关专门控制它。
NSFW_CATEGORY = "涉黄"

# --nsfw off（默认，正常向）：注入生成 prompt 的内容分级禁令。
NSFW_SAFE_CONTENT_POLICY = (
    "本作品为正常向（非成人向）作品。禁止出现任何色情、性行为、性器官、性暗示"
    "或成人向描写；感情与亲密描写须含蓄克制，不得越界。"
)

# --nsfw on（成人向）：注入生成 prompt 的明确授权。
NSFW_ALLOW_CONTENT_POLICY = (
    "本作品已显式开启成人向（NSFW）内容，可包含成人/性相关描写；"
    "但仍须遵守平台合规红线（涉政、涉黑、涉赌、涉毒、未成年人等），"
    "不得违反法律与公序良俗。"
)


# 题材 → 正常向禁边界细化文案（--nsfw off 且已知题材时按题材注入）。
# 纯数据映射表（可测）；键为题材关键词，theme/subgenre/genre 任一命中即用。
# 未命中任何键时回退 NSFW_SAFE_CONTENT_POLICY（字节不变，零成本契约）。
# 每条约文的"禁色情核心句"与 NSFW_SAFE_CONTENT_POLICY 一致，另加题材特有边界。
NSFW_GENRE_BOUNDARIES: dict[str, str] = {
    "亲情": (
        "本作品为正常向（非成人向）作品，题材为亲情向。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；情感以亲情为轴，亲密接触须极度含蓄克制，"
        "任何性化表达均属越界。"
    ),
    "热血": (
        "本作品为正常向（非成人向）作品，题材为热血向。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；打斗与冲突不渲染血腥、虐杀等暴力细节，"
        "燃点靠意志与行动而非感官刺激。"
    ),
    "仙侠": (
        "本作品为正常向（非成人向）作品，题材为仙侠。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；双修、情缘等仙侠亲密设定须含蓄克制，"
        "不得展开露骨或性化描写。"
    ),
    "悬疑": (
        "本作品为正常向（非成人向）作品，题材为悬疑。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；凶案与惊悚场面不渲染血腥细节，"
        "恐怖感靠氛围而非感官堆砌。"
    ),
    "科幻": (
        "本作品为正常向（非成人向）作品，题材为科幻。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；感情线含蓄克制，不得借科幻设定展开性化描写。"
    ),
    "都市": (
        "本作品为正常向（非成人向）作品，题材为都市。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；感情线含蓄克制，亲密场景点到即止不越界。"
    ),
    "奇幻": (
        "本作品为正常向（非成人向）作品，题材为奇幻。禁止出现任何色情、性行为、"
        "性器官、性暗示或成人向描写；异族情缘等亲密设定含蓄克制，不得越界。"
    ),
}

