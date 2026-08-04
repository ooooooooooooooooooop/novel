"""timebook — 时间域持久先验的加载/提取/上下文渲染.

对齐 style.py 的 load_style_context 先例：TimeBook 是 spec 先验，持久于
`<novel>/output/time/time_book.json`。无 TimeBook → 所有消费点返回空串/零产出，
行为与旧版逐字节相同（零成本契约）。
"""

import re
from datetime import date as _date
from pathlib import Path
from typing import Optional

from src.object_state.timebook import EraContext, TimeAnchor, TimeBook, TimeInitial


def resolve_time_dir(output_dir: Path) -> Path:
    """从任意模式 output_dir 解析时间域目录.

    各模式 output_dir 形如 `<novel>/output/<mode>`；时间域 home 恒为
    `<novel>/output/time`。time 模式自身即该目录。
    """
    if output_dir.name == "time":
        return output_dir
    return output_dir.parent / "time"


TIME_BOOK_FILENAME = "time_book.json"


def load_time_book(output_dir: Path) -> Optional[TimeBook]:
    """加载 TimeBook；缺失/损坏时返回 None（零成本降级）."""
    path = resolve_time_dir(output_dir) / TIME_BOOK_FILENAME
    if not path.exists():
        return None
    try:
        return TimeBook.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_time_book(output_dir: Path, tb: TimeBook) -> Path:
    """保存 TimeBook 到时间域目录."""
    time_dir = resolve_time_dir(output_dir)
    time_dir.mkdir(parents=True, exist_ok=True)
    path = time_dir / TIME_BOOK_FILENAME
    path.write_text(
        tb.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return path


# --- 章节时间锚提取（复用 chunking） -----------------------------------------

_DATE_RE = re.compile(
    r"(?P<y>\d{4})\s*[-/.年]\s*(?P<m>\d{1,2})\s*[-/.月]\s*(?P<d>\d{1,2})\s*日?"
)
_LUNAR_KEYWORDS = (
    "除夕", "春节", "元宵", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
    "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒",
    "腊月", "正月", "冬月", "中秋", "端午", "重阳", "七夕",
)
_TOD_KEYWORDS = (
    "清晨", "凌晨", "早晨", "破晓", "上午", "中午", "正午", "午后", "下午",
    "傍晚", "黄昏", "入夜", "晚上", "深夜", "夜里", "半夜", "午夜",
)


def _first_paragraphs(text: str, limit: int = 220) -> str:
    return text[:limit]


def extract_time_anchors(chunks: list) -> list[TimeAnchor]:
    """从章节块提取时间锚（复用 chunking 的 ChapterChunk）.

    只自动提取日期/农历节气/时段；地点等需要语境的字段留空（手写/编辑补齐）。
    无法提取任何信息的章节产出 None 字段锚，由调用方过滤或保留。
    """
    anchors: list[TimeAnchor] = []
    for chunk in chunks:
        head = _first_paragraphs(getattr(chunk, "text", ""))
        date_str = None
        m = _DATE_RE.search(head)
        if m:
            date_str = f"{int(m.group('y')):04d}-{int(m.group('m')):02d}-{int(m.group('d')):02d}"
        lunar = next((kw for kw in _LUNAR_KEYWORDS if kw in head), None)
        tod = next((kw for kw in _TOD_KEYWORDS if kw in head), None)
        chapter = f"第{chunk.chapter_index}章"
        if date_str or lunar or tod:
            anchors.append(
                TimeAnchor(
                    chapter=chapter,
                    date=date_str,
                    lunar=lunar,
                    tod=tod,
                    loc=None,
                )
            )
    return anchors


def refresh_time_book_anchors(output_dir: Path, chunks: list) -> Optional[TimeBook]:
    """校准既有 TimeBook 的章节时间锚（rebuild 顺带）.

    零成本契约：无 TimeBook 文件时不做任何事、不产生任何文件；
    有 TimeBook 时按章节号去重合并新提取的锚。
    """
    tb = load_time_book(output_dir)
    if tb is None:
        return None
    extracted = extract_time_anchors(chunks)
    if not extracted:
        return tb
    seen_chapters = {a.chapter for a in tb.anchors if a.chapter}
    merged = list(tb.anchors)
    for anchor in extracted:
        if anchor.chapter and anchor.chapter in seen_chapters:
            continue
        merged.append(anchor)
        if anchor.chapter:
            seen_chapters.add(anchor.chapter)
    tb.anchors = merged
    save_time_book(output_dir, tb)
    return tb


# --- 宏观时间表（领域知识，参考层） -----------------------------------------

CHINA_MACRO_TIMELINE: dict[int, dict] = {
    2000: {
        "events": ["国企改革进入攻坚期", "互联网泡沫破裂", "西部大开发启动"],
        "note": "手机/互联网普及初期",
    },
    2001: {
        "events": ["中国加入世贸组织(WTO)", "申奥成功(北京2008)", "APEC 上海峰会"],
        "note": "入世元年，出口与电子制造业窗口",
    },
    2002: {
        "events": ["党的十六大", "新一轮换届启动"],
        "note": "党政班子调整年",
    },
    2003: {
        "events": ["非典(SARS)", "振兴东北战略"],
        "note": "公共卫生事件冲击，医疗/消毒物资行情",
    },
    2004: {
        "events": ["宏观调控收紧", "国有银行股改试点"],
        "note": "土地/信贷双收紧，房价上涨前夜",
    },
    2005: {
        "events": ["股权分置改革", "人民币汇改(参考一篮子)"],
        "note": "资本市场制度转折年",
    },
    2006: {
        "events": ["农业税废止", "青藏铁路通车"],
        "note": "三农政策利好，基建提速",
    },
    2007: {
        "events": ["股市大牛市见顶", "食品价格上涨"],
        "note": "通胀抬头，流动性泛滥",
    },
    2008: {
        "events": ["南方雪灾", "汶川地震", "北京奥运会", "全球金融危机", "四万亿刺激"],
        "note": "危机与大规模基建窗口",
    },
    2009: {
        "events": ["四万亿全面铺开", "房地产复苏", "3G 牌照发放"],
        "note": "基建/地产/通信三线扩张",
    },
    2010: {
        "events": ["上海世博会", "广州亚运会", "房价调控(限购)"],
        "note": "智能手机元年，移动互联网起步",
    },
}


def fill_era_from_macro(tb: TimeBook, year_from: int, year_to: int) -> TimeBook:
    """按年份区间用内置宏观时间表填充 era（参考层，可架空）."""
    known_years = {e.year for e in tb.era}
    for year in range(year_from, year_to + 1):
        if year in known_years or year not in CHINA_MACRO_TIMELINE:
            continue
        entry = CHINA_MACRO_TIMELINE[year]
        tb.era.append(
            EraContext(
                year=year,
                events=list(entry["events"]),
                note=entry.get("note"),
            )
        )
    tb.era = sorted(tb.era, key=lambda e: e.year)
    return tb


# --- 日期解析（供注入与审计共用） -------------------------------------------

def parse_date(s: Optional[str]) -> Optional[tuple[int, int, int]]:
    """把 ISO/中文日期串解析为 (年,月,日). 失败返回 None.

    支持 YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日 / YYYY-MM(月末) / YYYY年M月(月末)。
    无法解析时保守返回 None（不误报）。
    """
    if not s:
        return None
    s = s.strip()
    m = _DATE_RE.search(s)
    if m:
        return (int(m.group("y")), int(m.group("m")), int(m.group("d")))
    m = re.search(r"(?P<y>\d{4})\s*[-/.年]\s*(?P<m>\d{1,2})\s*(?:月)?$", s)
    if m:
        year, month = int(m.group("y")), int(m.group("m"))
        if not (1 <= month <= 12):
            return None
        # YYYY-MM 视为月末（保守：不早于声明区间结束前判逾期）
        if month == 12:
            day = 31
        else:
            import calendar

            day = calendar.monthrange(year, month)[1]
        return (year, month, day)
    return None


def _anchor_month_loc(anchor: TimeAnchor) -> Optional[tuple[int, str]]:
    parsed = parse_date(anchor.date)
    if parsed is None:
        return None
    return parsed[1], (anchor.loc or "")


# --- 【时间上下文】注入渲染 --------------------------------------------------

def _cn_month_to_int(s: str) -> Optional[int]:
    """中文数字月份 → 整数; 失败返回 None."""
    table = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
    }
    return table.get(s.strip())


def _season_note(date_str: Optional[str], loc: Optional[str], rules: list[str]) -> str:
    """按软规则给日期/地点追加季节注记, 如 '(南半球盛夏)'. 无法推导返回空串."""
    if not rules or not date_str or not loc:
        return ""
    parsed = parse_date(date_str)
    if parsed is None:
        return ""
    month = parsed[1]
    for rule in rules:
        m = re.search(
            r"(.{0,12}?" + re.escape(loc) + r".{0,12}?)\s*"
            r"(\d+|[一二三四五六七八九十]+)\s*月\s*(?:为|是)\s*"
            r"(盛夏|酷暑|寒冬|严冬|暖冬|初春|仲春|暮春|初夏|仲夏|暮夏|初秋|仲秋|深秋|冬天|夏天|春天|秋天)",
            rule,
        )
        if not m:
            continue
        decl_month = _cn_month_to_int(m.group(2))
        if m.group(2).isdigit():
            decl_month = int(m.group(2))
        if decl_month != month:
            continue
        descriptor = m.group(1).replace(loc, "").strip("()（）（）")
        if descriptor:
            return f"({descriptor}{m.group(3)})"
        return f"({m.group(3)})"
    return ""


def _next_chapter_label(chapter: Optional[str]) -> Optional[str]:
    """由最新锚点章节标识推下一章标识.

    - 尾部数字递增: '第1章' -> '第2章'，'第10章' -> '第11章'
    - 占位字母延续: '第N章' -> '第N+1章'
    - 其余无数字标识（如 '序章'/'尾声'）返回 None，不渲染本章行
    """
    if not chapter:
        return None
    m = re.search(r"(\d+)(章)?$", chapter)
    if m:
        return f"{chapter[:m.start(1)]}{int(m.group(1)) + 1}{m.group(2) or ''}"
    m = re.match(r"^(第)([A-Za-z])(章)$", chapter)
    if m:
        return f"{m.group(1)}{m.group(2)}+1{m.group(3)}"
    return None


def _format_prev_anchor(a: TimeAnchor) -> str:
    """上章行: '{chapter} {date}({lunar}){tod} {loc}'.

    对齐 37_time_domain_design §5 示例：
      上章: 第N章 2001-01-22(腊月廿九)入夜 某城
    农历/时段是锚点细节，紧贴日期；地点以空格分隔。
    """
    head: list[str] = []
    if a.chapter:
        head.append(a.chapter)
    if a.date:
        head.append(a.date)
    s = " ".join(head)
    if a.lunar:
        s += f"({a.lunar})"
    if a.tod:
        s += a.tod
    if a.loc:
        s += " " + a.loc
    return s


def _format_next_anchor(chapter: str, initial: TimeInitial, rules: list[str]) -> str:
    """本章行: '{chapter} {date} {lunar} {loc}{季节注记}'.

    对齐 37_time_domain_design §5 示例：
      本章: 第N+1章 2001-01-23 除夕 某城(南半球盛夏)
    起点日期/农历/地点为正文 token，季节注记（软规则推导）紧贴地点。
    """
    s = chapter
    if initial.date:
        s += " " + initial.date
    if initial.lunar:
        s += " " + initial.lunar
    if initial.loc:
        s += " " + initial.loc
    note = _season_note(initial.date, initial.loc, rules)
    if note:
        s += note
    return s


def build_time_context(tb: Optional[TimeBook]) -> str:
    """渲染【时间上下文】正文（不含外层段头，consumer 独占段头）.

    无 TimeBook / 无锚且无 initial 时返回空串（零成本降级）。
    """
    if tb is None:
        return ""
    lines: list[str] = []
    latest = tb.latest_anchor()
    if latest is not None:
        prev = _format_prev_anchor(latest)
        if prev:
            lines.append("上章: " + prev)
    if tb.initial is not None and not tb.initial.is_empty():
        if latest is not None:
            next_chapter = _next_chapter_label(latest.chapter)
        else:
            # 无锚点（compose 初跑 / extend 重建前）：以起点作为第1章
            next_chapter = "第1章"
        if next_chapter:
            next_line = _format_next_anchor(next_chapter, tb.initial, tb.rules)
            if next_line:
                lines.append("本章: " + next_line)
    year = None
    if latest is not None and latest.date:
        parsed = parse_date(latest.date)
        if parsed:
            year = parsed[0]
    if year is None and tb.initial is not None and tb.initial.date:
        parsed = parse_date(tb.initial.date)
        if parsed:
            year = parsed[0]
    if year is not None:
        era_match = next((e for e in tb.era if e.year == year), None)
        if era_match is not None and era_match.events:
            lines.append(
                f"时代背景({year}): " + "、".join(era_match.events)
            )
    if tb.rules:
        lines.append("时间规则: " + " / ".join(tb.rules))
    return "\n".join(lines)
