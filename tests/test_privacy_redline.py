"""隐私红线断言 — 风格库 / 源码 / 文档 / 测试不得含具体小说信息.

红线（CLAUDE.md）：所有具体小说信息（标题/正文/角色/工作区名/作者笔名）一律不入
GitHub；风格库允许入库的是中性写作风格积累，不得含机器路径/角色名/作品名。

本测试锁两条：
1. **静态红线**：tracked 文件（style_library/、src/、docs/、tests/）不含已知真实
   角色名/公司名/作品名；风格库 source_text_ref 不含机器路径（盘符/novels/ 工作区）。
2. **脱敏函数**：style_redact 的 source_ref 去路径 + 实体词替换行为。
"""

import re
import subprocess
from pathlib import Path

from src.domain_layer.style_redact import (
    assign_placeholders,
    parse_redact_arg,
    redact_profile,
    redact_text,
    sanitize_source_ref,
)
from src.object_state.styleprofile import (
    StyleProfile,
    StyleQuantitativeStats,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _mk_profile(pov: str = "以张恪为锚", ref: str = "D:\\x\\novels\\a\\input.txt"):
    """构造最小合法 StyleProfile（仅必填字段）。"""
    return StyleProfile(
        profile_id="s1",
        source_text_ref=ref,
        narrative_pov=pov,
        pacing_description="长句铺陈",
        stats=StyleQuantitativeStats(
            total_chars=100,
            sentence_count=10,
            avg_sentence_len=10,
            short_sentence_ratio=0.1,
            long_sentence_ratio=0.1,
            dialogue_ratio=0.1,
            weak_adverb_density_per_1000=0.0,
            explanatory_phrase_count=0,
            dialogue_tag_density_per_1000=0.0,
            emotion_announcement_count=0,
            dash_colon_density_per_1000=0.0,
        ),
    )

# 已知真实实体（角色/公司/作品名）——红线扫描词表。新增作品入库时在此登记。
KNOWN_ENTITY_TERMS = [
    "张恪",
    "李馨予",
    "翟丹青",
    "王海粟",
    "傅俊",
    "魏岚",
    "董简年",
    "江敏之",
    "魏东强",
    "严文介",
    "林雪",
    "罗君",
    "锦湖",
    "信通银行",
    "海粟科技",
    "珀斯",
    "官路商途",
    "重生之官路商途",
    "万物生长",
    "星尘归处",
    "逆命令",
    "柳青",
    "秋水",
]

_SCAN_SUFFIXES = (".py", ".md", ".json", ".txt", ".toml")
_SCAN_DIRS = ("style_library", "src", "docs", "tests")


def _tracked_texts():
    """产出被扫描目录下的 tracked 文本内容（(相对路径, 内容)）。"""
    files = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.split()
    for f in files:
        if not f.endswith(_SCAN_SUFFIXES):
            continue
        if not f.startswith(_SCAN_DIRS):
            continue
        if f == "tests/test_privacy_redline.py":
            # 词表登记文件自身豁免：本文件必然包含已知实体名（KNOWN_ENTITY_TERMS
            # 与脱敏函数的用例数据）。红线约束的是其他 tracked 文件，非本登记文件。
            continue
        try:
            content = (PROJECT_ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield f, content


def test_no_known_entity_terms_in_tracked_files():
    """tracked 的 style_library/src/docs/tests 不得含已知真实实体名."""
    leaked = []
    for f, content in _tracked_texts():
        for term in KNOWN_ENTITY_TERMS:
            if term in content:
                leaked.append(f"{f}: {term}")
    assert not leaked, f"隐私红线违反——tracked 文件含真实实体：\n" + "\n".join(leaked)


def test_style_library_source_ref_no_machine_path():
    """风格库档案的 source_text_ref 不得含盘符 / novels/ 工作区路径."""
    lib = PROJECT_ROOT / "style_library"
    if not lib.exists():
        return  # 空库不扫描
    bad = []
    for p in sorted(lib.glob("*.json")):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"\"source_text_ref\"\s*:\s*\"([^\"]*)\"", text):
            ref = m.group(1)
            if not ref:
                continue
            if re.search(r"[A-Za-z]:[\\/]", ref) or "/novels/" in ref or "\\novels\\" in ref:
                bad.append(f"{p.name}: {ref}")
    assert not bad, f"风格库 source_text_ref 含机器路径：\n" + "\n".join(bad)


def test_redact_text_replaces_terms():
    assert redact_text("以张恪为锚", {"张恪": "主角"}) == "以主角为锚"


def test_redact_text_longest_first():
    # 长词优先，避免前缀误伤
    assert redact_text("锦湖集团上市", {"锦湖": "集团", "锦湖集团": "大集团"}) == "大集团上市"


def test_sanitize_source_ref_drops_machine_path():
    assert (
        sanitize_source_ref(r"D:\Desktop\novel\novels\示例\input.txt")
        == "input.txt"
    )
    assert sanitize_source_ref("input.txt") == "input.txt"
    assert sanitize_source_ref("") == ""


def test_redact_profile_deep_copy_and_source_ref():
    profile = _mk_profile()
    redacted = redact_profile(profile, {"张恪": "主角"})
    assert redacted.narrative_pov == "以主角为锚"
    assert redacted.source_text_ref == "input.txt"
    # 原 profile 不被改动
    assert profile.narrative_pov == "以张恪为锚"
    assert profile.source_text_ref.startswith("D:")


def test_redact_profile_without_terms_still_sanitizes_ref():
    profile = _mk_profile()
    redacted = redact_profile(profile)
    assert redacted.source_text_ref == "input.txt"
    assert redacted.narrative_pov == "以张恪为锚"  # 未传词表则不替换


def test_assign_placeholders_and_parse():
    assert assign_placeholders(["张恪", "王海粟"]) == {"张恪": "角色A", "王海粟": "角色B"}
    assert parse_redact_arg("张恪，王海粟, 锦湖") == ["张恪", "王海粟", "锦湖"]
    assert parse_redact_arg("") == []
