"""StyleUnit — 写作风格提炼与 lint 工作流.

StyleExtractUnit: 从小说章节采样提取质性风格（LLM，response-file 模式）。
StyleLintUnit: 纯代码对全文做 AI 味 lint，产出 ReviewIssue。
load_style_context: compose/extend 读取风格档案并渲染注入文本（支持风格库引用）。
style_library_dir: 风格库目录 <仓库根>/style_library。
"""

import datetime
import json
import os
import re
from pathlib import Path

from src.boundary_control.style_metrics import analyze_style_metrics
from src.domain_layer.style_rules import (
    build_style_knowledge_context,
    get_ai_flavor_markers,
    get_tone_style_traits,
    list_available_tones,
)
from src.object_state.reviewissue import ReviewIssue
from src.object_state.styleprofile import (
    StyleProfile,
    StyleQuantitativeStats,
    StyleRisk,
)

# 风格库默认根目录（与 novel_cli 的 DEFAULT_NOVELS_ROOT 一致）。
# 风格库是允许入库的综合积累，独立于私密的小说工作区（novels/）：
# 目录固定为 novels 的父目录（仓库根）/ style_library。
DEFAULT_NOVELS_ROOT = Path(__file__).resolve().parent.parent.parent / "novels"

# StyleExtractUnit 需要但不直接 import 的常量（供 parse 校验）
_REQUIRED_RESPONSE_FIELDS = (
    "tone_labels",
    "genre_guess",
    "narrative_pov",
    "pacing_description",
    "sentence_habits",
    "rhetorical_preferences",
    "show_dont_tell_notes",
    "closed_loop_objects",
    "chapter_end_hook_notes",
    "taboo_words",
    "style_references",
    "confidence_gaps",
)

# v2: 叙事维度质性字段（可选）。缺省补 []，出现则必须 list[str]。
# 可选化 = 向后兼容：现存 12 字段的手工 response 产物仍可解析。
_OPTIONAL_RESPONSE_FIELDS = (
    "environment_notes",        # 环境/景物：手法（白描/借景抒情/写实）+ 功能（交代时空/烘托情绪/转场）
    "scene_transition_notes",   # 场景转换：章内/章间切换方式 + 段落衔接
    "psychology_notes",         # 心理：密度判断 + 直接/间接内独白 + show-don't-tell 深化
    "rhythm_notes",             # 节奏：叙述/对话/动作/描写配比 + 事件推进方式
)


class StyleExtractUnit:
    """从小说章节采样中提炼质性写作风格."""

    def build_prompt(
        self,
        samples_text: str,
        total_stats: dict,
        quantitative_context: str,
        style_knowledge_context: str = "",
        available_tones: list[str] | None = None,
    ) -> str:
        """生成风格提炼 prompt.

        Args:
            samples_text: 章节采样文本（首+中+末均匀采样）
            total_stats: get_total_stats 的输出（章节数/字数）
            quantitative_context: 量化分析渲染文本
            style_knowledge_context: tone/genre 风格知识（给 LLM 分类轴）
            available_tones: 可用调性列表（未知调性进 confidence_gaps）
        """
        tones = available_tones or list_available_tones()
        knowledge_section = ""
        if style_knowledge_context:
            knowledge_section = (
                f"\n\n【风格知识参考（分类轴）】\n{style_knowledge_context}\n"
                f"可用调性标签: {' / '.join(tones)}"
            )

        return f"""你是一位小说文风分析专家。请从以下章节采样中提炼这部作品的写作风格档案。

【输入文本（章节采样）】
{samples_text}

【全文统计】
- 总章节数: {total_stats.get('chapter_count', '?')}
- 总字数: {total_stats.get('total_chars', '?')}
- 平均每章字数: {total_stats.get('avg_chars_per_chapter', '?')}

【量化分析（纯代码，已算出）】
{quantitative_context}
{knowledge_section}

【提炼要求】
1. tone_labels 从可用调性标签中选择（可多选；若文本不属于任何标签，写 '未标注'）
2. sentence_habits 描述句式习惯，如"叙述默认 20-30 字长句，情绪爆点用独立短句"
3. show_dont_tell_notes 描述情绪如何呈现（身体反应/动作/意象），不是"他感到"
4. closed_loop_objects 列出在文本中开头出现、结局变化/回归的闭环物象
5. chapter_end_hook_notes 描述章末如何留钩子
6. taboo_words 列出应避免的用词（本文本刻意回避的套话）
7. style_references 命中风格知识表中的规则（如 tone_kz_01），未知的不要编造
8. environment_notes 依据量化景物/感官密度判断环境描写手法（白描/借景抒情/写实）与功能（交代时空/烘托情绪/转场），可引用量化数据
9. scene_transition_notes 依据量化转场/时间标记计数判断场景切换方式（显式标记/无痕切换/时间跳转）与段落衔接
10. psychology_notes 依据量化心理动词密度判断内视角深度、直接/间接内独白与 show-don't-tell 深化手法
11. rhythm_notes 依据量化动作/叙述/对话/景物四占比判断章内配比与事件推进方式（章末钩子已在 chapter_end_hook_notes）

【输出格式】
严格输出 JSON，不要 Markdown 代码块标记:
{{
  "tone_labels": ["克制"],
  "genre_guess": "古典仙侠",
  "narrative_pov": "第三人称有限",
  "pacing_description": "叙述默认长句，情绪爆点短句独立成段",
  "sentence_habits": ["句式习惯1"],
  "rhetorical_preferences": ["修辞偏好1"],
  "show_dont_tell_notes": ["情绪呈现手法1"],
  "closed_loop_objects": ["物象1"],
  "chapter_end_hook_notes": ["章末钩子手法1"],
  "taboo_words": ["禁忌词1"],
  "style_references": ["tone_kz_01"],
  "confidence_gaps": ["不确定的信息"],
  "environment_notes": ["环境描写手法与功能（可选）"],
  "scene_transition_notes": ["场景转换手法（可选）"],
  "psychology_notes": ["心理与内视角表现（可选）"],
  "rhythm_notes": ["叙事节奏与结构（可选）"]
}}"""

    def parse_response(self, response: str) -> dict:
        """解析 LLM 风格提炼响应，严格校验字段.

        v2 起：_OPTIONAL_RESPONSE_FIELDS 允许出现（须 list[str]），缺省补 []。
        _REQUIRED_RESPONSE_FIELDS 仍必填。未知字段仍拒绝。
        """
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("Style extraction response must be a JSON object")

        missing = [field for field in _REQUIRED_RESPONSE_FIELDS if field not in data]
        if missing:
            raise ValueError(
                "Style extraction response missing required field(s): "
                + ", ".join(missing)
            )
        allowed = set(_REQUIRED_RESPONSE_FIELDS) | set(_OPTIONAL_RESPONSE_FIELDS)
        extra = sorted(set(data) - allowed)
        if extra:
            raise ValueError(
                "Style extraction response has unexpected field(s): "
                + ", ".join(extra)
            )

        list_fields = (
            "tone_labels",
            "sentence_habits",
            "rhetorical_preferences",
            "show_dont_tell_notes",
            "closed_loop_objects",
            "chapter_end_hook_notes",
            "taboo_words",
            "style_references",
            "confidence_gaps",
        )
        for field in list_fields:
            value = data[field]
            if not isinstance(value, list):
                raise ValueError(
                    f"Style extraction response field {field} must be a list"
                )
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(
                    f"Style extraction response field {field} must be a list of strings"
                )
        # v2 可选字段：出现则须 list[str]，缺省补 []
        for field in _OPTIONAL_RESPONSE_FIELDS:
            value = data.get(field, [])
            if not isinstance(value, list):
                raise ValueError(
                    f"Style extraction response field {field} must be a list"
                )
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(
                    f"Style extraction response field {field} must be a list of strings"
                )
            data[field] = value
        for field in ("genre_guess", "narrative_pov", "pacing_description"):
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Style extraction response field {field} must be a non-empty string"
                )
        return data

    def merge(
        self,
        qualitative: dict,
        stats: StyleQuantitativeStats,
        risks: list[StyleRisk],
        source_text_ref: str,
        profile_id: str = "style_001",
    ) -> StyleProfile:
        """合并质性提炼 + 量化统计为 StyleProfile.

        未知 tone_label 移入 confidence_gaps（graceful degradation）。
        """
        known_tones = set(list_available_tones())
        confidence_gaps = list(qualitative.get("confidence_gaps", []))
        tone_labels = list(qualitative.get("tone_labels", []))
        for tone in tone_labels:
            if tone not in known_tones and tone != "未标注":
                confidence_gaps.append(f"未知调性标签: {tone}")
        tone_labels = [tone for tone in tone_labels if tone in known_tones or tone == "未标注"]

        return StyleProfile(
            profile_id=profile_id,
            source_text_ref=source_text_ref,
            schema_version=2,
            tone_labels=tone_labels,
            genre_guess=qualitative.get("genre_guess"),
            narrative_pov=qualitative["narrative_pov"],
            pacing_description=qualitative["pacing_description"],
            sentence_habits=qualitative.get("sentence_habits", []),
            rhetorical_preferences=qualitative.get("rhetorical_preferences", []),
            show_dont_tell_notes=qualitative.get("show_dont_tell_notes", []),
            closed_loop_objects=qualitative.get("closed_loop_objects", []),
            chapter_end_hook_notes=qualitative.get("chapter_end_hook_notes", []),
            environment_notes=qualitative.get("environment_notes", []),
            scene_transition_notes=qualitative.get("scene_transition_notes", []),
            psychology_notes=qualitative.get("psychology_notes", []),
            rhythm_notes=qualitative.get("rhythm_notes", []),
            taboo_words=qualitative.get("taboo_words", []),
            style_references=qualitative.get("style_references", []),
            stats=stats,
            ai_flavor_risks=risks,
            confidence_gaps=confidence_gaps,
        )


class StyleLintUnit:
    """纯代码对全文做 AI 味 lint，产出 ReviewIssue."""

    def lint_stats(self, stats: StyleQuantitativeStats) -> list[StyleRisk]:
        """根据量化统计判断 AI 味风险."""
        risks: list[StyleRisk] = []
        markers = get_ai_flavor_markers()
        by_id = {marker["rule_id"]: marker for marker in markers}

        checks = [
            (
                "ai_weak_adverb_density",
                stats.weak_adverb_density_per_1000,
                "per_1000_chars",
            ),
            ("ai_metaphor_repeat", float(len(stats.metaphor_repeats)), "absolute"),
            (
                "ai_explanatory_voice",
                float(stats.explanatory_phrase_count),
                "count",
            ),
            (
                "ai_shell_not_a_but_b",
                float(stats.shell_counts.get("not_a_but_b", 0)),
                "count",
            ),
            ("ai_parallel_four", float(stats.shell_counts.get("parallel4", 0)), "count"),
            (
                "ai_emotion_announcement",
                stats.emotion_announcement_count / max(stats.total_chars, 1) * 1000,
                "per_1000_chars",
            ),
            (
                "ai_dialogue_tag_density",
                stats.dialogue_tag_density_per_1000,
                "per_1000_chars",
            ),
            ("ai_dash_colon_density", stats.dash_colon_density_per_1000, "per_1000_chars"),
            (
                "ai_connective_abuse",
                float(stats.connective_abuse_count),
                "count",
            ),
            (
                "ai_colon_enumeration",
                float(stats.colon_enumeration_count),
                "count",
            ),
        ]

        for rule_id, value, measure_unit in checks:
            marker = by_id.get(rule_id)
            if not marker:
                continue
            if value < marker["threshold"]:
                continue
            risks.append(
                StyleRisk(
                    rule_id=rule_id,
                    category="ai_flavor",
                    measure=marker["description"],
                    value=round(value, 2),
                    threshold=marker["threshold"],
                    severity=marker["severity"],  # type: ignore[arg-type]
                    description="；".join(marker["instructions"]),
                )
            )
        return risks

    def lint(self, text: str, location: str = "全文") -> list[ReviewIssue]:
        """对全文做 AI 味 lint，产出 ReviewIssue."""
        stats = analyze_style_metrics(text)
        risks = self.lint_stats(stats)
        issues: list[ReviewIssue] = []
        for risk in risks:
            issues.append(
                ReviewIssue(
                    issue_id=f"style_lint_{risk.rule_id}",
                    issue_type="generative_indicia",
                    severity=risk.severity,  # type: ignore[arg-type]
                    location=location,
                    scope_of_impact="表达层",
                    violated_rule=risk.measure,
                    description=(
                        f"{risk.measure}: {risk.value:.1f}"
                        f"（阈值{risk.threshold:.1f}）。建议: {risk.description}"
                    ),
                )
            )
        return issues

    def lint_taboo_words(
        self, text: str, taboo_words: list[str], location: str = "全文"
    ) -> list[ReviewIssue]:
        """按风格档案的禁忌词做 style_drift 检查.

        命中任意禁忌词即报一条 style_drift issue，并附出现次数。
        """
        if not taboo_words:
            return []
        issues: list[ReviewIssue] = []
        for word in taboo_words:
            if not word or not word.strip():
                continue
            count = text.count(word)
            if count <= 0:
                continue
            issues.append(
                ReviewIssue(
                    issue_id=f"style_drift_taboo_{word}",
                    issue_type="style_drift",
                    severity="low",
                    location=location,
                    scope_of_impact="表达层",
                    violated_rule=f"禁忌词: {word}",
                    description=(
                        f"风格档案禁忌词 '{word}' 在文本中出现 {count} 次。"
                        "作者自查清单要求回避此词，请替换为具体动作/身体反应。"
                    ),
                )
            )
        return issues


def style_library_dir(novels_root: Path | None = None) -> Path:
    """风格库目录: <仓库根>/style_library.

    风格库固定于仓库根（novels 的父目录），独立于私密的小说工作区（novels/）。
    novels_root 用于推导仓库根（novels_root.parent）；未指定时用
    NOVELS_ROOT 环境变量（与 novel_cli 一致），否则默认 <工程>/novels。
    """
    if novels_root is not None:
        root = Path(novels_root)
    else:
        root_env = os.environ.get("NOVELS_ROOT")
        root = Path(root_env).resolve() if root_env else DEFAULT_NOVELS_ROOT
    return root.parent / "style_library"


def style_library_profile_path(name: str, novels_root: Path | None = None) -> Path:
    """风格库档案路径: <仓库根>/style_library/<name>.json."""
    if not name or name.strip() != name or "/" in name or "\\" in name:
        raise ValueError(f"invalid style library name: {name!r}")
    return style_library_dir(novels_root) / f"{name}.json"


def load_style_context(output_dir: Path, style_name: str | None = None) -> str:
    """读取风格档案并渲染注入文本.

    style_name 指定时读风格库 <仓库根>/style_library/<name>.json；
    否则读规范位置 <output_dir 的上级>/style/style_profile.json。

    style 档案由 novel style 写到 <book>/output/style/。各消费模式的
    output_dir 不同：compose=<book>/output/compose、extend=<book>/output/extend，
    都需回到 <book>/output/style/ —— 即 output_dir.parent / "style"。
    不存在返回 ""；存在但损坏则抛错（stale/corrupt 文件应暴露）。
    """
    if style_name:
        profile_path = resolve_style_library_path(style_name)
    else:
        style_dir = output_dir.parent / "style"
        profile_path = style_dir / "style_profile.json"
    if not profile_path.exists():
        return ""
    profile = StyleProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    # include_header=False：双层段头修复，内层【写作风格画像】头由 continuation
    # 外层【写作风格】独占，避免叠层。
    return profile.to_prompt_context(include_header=False)


# =====================================================================
# 风格库 v2：中性 id 生成 / 相似度去重 / manifest 索引 / 检索
# ---------------------------------------------------------------------
# 目标：每次提炼出新风格自动入库（无 --name 时），用风格化中性名
# （克制-官商-001）落盘 + manifest 语义索引；入库前与库中档案算相似度，
# 高于阈值提示复用避免重复扩张；--style-search 走 manifest 模糊检索。
# 隐私：id 只含 tone/genre/seq 风格词；manifest 不含作品名/作者名/路径。
# =====================================================================

_MANIFEST_SCHEMA_VERSION = 1

# genre_guess → 中性类型 slug 映射（仅类型词，不含作品/作者名）
_GENRE_SLUGS: tuple[tuple[str, str], ...] = (
    ("官商", "官商"),
    ("重生", "重生"),
    ("都市", "都市"),
    ("仙侠", "仙侠"),
    ("玄幻", "玄幻"),
    ("科幻", "科幻"),
    ("悬疑", "悬疑"),
    ("推理", "推理"),
    ("言情", "言情"),
    ("历史", "历史"),
    ("军事", "军事"),
    ("灵异", "灵异"),
    ("武侠", "武侠"),
    ("权谋", "权谋"),
    ("古典", "古典"),
)
_DEFAULT_GENRE_SLUG = "杂"

# 相似度数值字段 → 归一化典型幅度（scale；比值/密度类用经验上界）
_SIM_NUMERIC_FIELDS: tuple[tuple[str, float], ...] = (
    ("avg_sentence_len", 50.0),
    ("short_sentence_ratio", 1.0),
    ("long_sentence_ratio", 1.0),
    ("dialogue_ratio", 1.0),
    ("weak_adverb_density_per_1000", 10.0),
    ("dash_colon_density_per_1000", 20.0),
    ("scenery_density_per_1000", 30.0),
    ("psych_verb_density_per_1000", 30.0),
    ("action_verb_density_per_1000", 30.0),
    ("narration_sentence_ratio", 1.0),
)

# 自动入库去重拦截阈值：新档案与库中最高相似度 ≥ 该值 → 提示复用，不盲目新建
STYLE_DEDUP_THRESHOLD = 0.90


def _sanitize_token(text: str, max_len: int = 4) -> str:
    """清洗为中性 id 片段：只保留汉字/字母/数字，超长截断."""
    cleaned = re.sub(r"[^\w一-鿿]", "", text)
    return cleaned[:max_len] or _DEFAULT_GENRE_SLUG


def _genre_slug(genre_guess: str | None) -> str:
    """genre_guess → 中性类型 slug（如 '都市官商重生' → '官商'）."""
    if not genre_guess:
        return _DEFAULT_GENRE_SLUG
    for key, slug in _GENRE_SLUGS:
        if key in genre_guess:
            return slug
    return _DEFAULT_GENRE_SLUG


def auto_style_id(
    profile: StyleProfile, manifest: dict | None = None
) -> str:
    """为新提炼档案生成风格化中性 id: <tone>-<genre>-<seq>（如 克制-官商-001）.

    同 tone+genre 前缀下 seq 自增；manifest 缺省时仅按已用 id 集合避免碰撞。
    """
    manifest = manifest or {"profiles": []}
    tone = profile.tone_labels[0] if profile.tone_labels else "未标注"
    prefix = f"{_sanitize_token(tone)}-{_genre_slug(profile.genre_guess)}"
    used = {entry.get("id") for entry in manifest.get("profiles", [])}
    seq = 1
    while f"{prefix}-{seq:03d}" in used:
        seq += 1
    return f"{prefix}-{seq:03d}"


def _stats_vector(profile: StyleProfile) -> dict[str, float]:
    """提取相似度数值字段向量（缺省字段按 0 计）."""
    stats = profile.stats
    return {
        field: float(getattr(stats, field, 0.0) or 0.0)
        for field, _ in _SIM_NUMERIC_FIELDS
    }


def _numeric_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """数值向量相似度：逐字段 1 - 归一化绝对差，加权平均."""
    if not a or not b:
        return 0.0
    total = 0.0
    for field, scale in _SIM_NUMERIC_FIELDS:
        va = a.get(field, 0.0)
        vb = b.get(field, 0.0)
        if scale <= 0:
            continue
        diff = abs(va - vb) / scale
        total += max(0.0, 1.0 - min(diff, 1.0))
    return total / len(_SIM_NUMERIC_FIELDS)


def _jaccard(a: list[str] | set[str], b: list[str] | set[str]) -> float:
    """字符串集合 Jaccard 相似（两端空集合视为一致，返回 1）."""
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def _categorical_similarity(a: StyleProfile, b: StyleProfile) -> float:
    """分类相似度：tone 交集 / genre slug / POV 各占权重."""
    tone = _jaccard(a.tone_labels, b.tone_labels)
    genre = 1.0 if _genre_slug(a.genre_guess) == _genre_slug(b.genre_guess) else 0.0
    pov = 1.0 if a.narrative_pov == b.narrative_pov else 0.0
    return 0.5 * tone + 0.25 * genre + 0.25 * pov


def _quality_similarity(a: StyleProfile, b: StyleProfile) -> float:
    """质性特征相似度：句式/修辞/物象/禁忌词 合并集合 Jaccard."""
    merged_a = (
        list(a.sentence_habits)
        + list(a.rhetorical_preferences)
        + list(a.closed_loop_objects)
        + list(a.taboo_words)
    )
    merged_b = (
        list(b.sentence_habits)
        + list(b.rhetorical_preferences)
        + list(b.closed_loop_objects)
        + list(b.taboo_words)
    )
    return _jaccard(merged_a, merged_b)


def profile_similarity(a: StyleProfile, b: StyleProfile) -> float:
    """两个风格档案的相似度 [0,1].

    数值 60%（句长/配比/密度归一化差）+ 分类 20%（tone/genre/POV）
    + 质性 20%（句式/修辞/物象/禁忌词 Jaccard）。
    """
    return (
        0.6 * _numeric_similarity(_stats_vector(a), _stats_vector(b))
        + 0.2 * _categorical_similarity(a, b)
        + 0.2 * _quality_similarity(a, b)
    )


def load_style_manifest(novels_root: Path | None = None) -> dict:
    """读取风格库 manifest（不存在返回空骨架）."""
    path = style_library_dir(novels_root) / "manifest.json"
    if not path.exists():
        return {"schema_version": _MANIFEST_SCHEMA_VERSION, "profiles": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": _MANIFEST_SCHEMA_VERSION, "profiles": []}


def save_style_manifest(
    manifest: dict, novels_root: Path | None = None
) -> Path:
    """写风格库 manifest，返回其路径."""
    manifest.setdefault("schema_version", _MANIFEST_SCHEMA_VERSION)
    path = style_library_dir(novels_root) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def _key_signatures(profile: StyleProfile, limit: int = 5) -> list[str]:
    """可检索的风格指纹：句式/修辞/闭环物象 前几条."""
    parts = (
        list(profile.sentence_habits)
        + list(profile.rhetorical_preferences)
        + list(profile.closed_loop_objects)
    )
    return parts[:limit]


def upsert_style_manifest(
    profile: StyleProfile,
    style_id: str,
    file_name: str,
    novels_root: Path | None = None,
    created_at: str | None = None,
) -> Path:
    """登记/更新档案条目到 manifest（id 幂等：存在则覆盖，否则追加）."""
    manifest = load_style_manifest(novels_root)
    entry = {
        "id": style_id,
        "file": file_name,
        "tone_labels": profile.tone_labels,
        "genre_guess": profile.genre_guess,
        "narrative_pov": profile.narrative_pov,
        "key_signatures": _key_signatures(profile),
        "avg_sentence_len": profile.stats.avg_sentence_len,
        "dialogue_ratio": profile.stats.dialogue_ratio,
        "created_at": created_at or datetime.date.today().isoformat(),
    }
    profiles = manifest.setdefault("profiles", [])
    for i, existing in enumerate(profiles):
        if existing.get("id") == style_id:
            profiles[i] = entry
            break
    else:
        profiles.append(entry)
    return save_style_manifest(manifest, novels_root)


def find_most_similar(
    profile: StyleProfile,
    manifest: dict | None = None,
    novels_root: Path | None = None,
) -> tuple[str | None, float]:
    """库中最相似的既有档案 (id, score)；空库返回 (None, 0.0).

    逐档案加载完整 StyleProfile 计算（manifest 只存摘要，完整相似需 stats）。
    """
    manifest = load_style_manifest(novels_root) if manifest is None else manifest
    lib_dir = style_library_dir(novels_root)
    best_id: str | None = None
    best_score = 0.0
    for entry in manifest.get("profiles", []):
        file_name = entry.get("file")
        if not file_name:
            continue
        path = lib_dir / file_name
        if not path.exists():
            continue
        try:
            other = StyleProfile.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            continue
        score = profile_similarity(profile, other)
        if score > best_score:
            best_id = entry.get("id")
            best_score = score
    return best_id, best_score


def search_style_manifest(
    manifest: dict | None, query: str
) -> list[dict]:
    """在 manifest 上做关键词检索：每个词须命中 tone/genre/pov/key_signatures 之一.

    返回按命中字段数降序的候选条目列表（未命中返回空列表）。
    """
    manifest = manifest or {"profiles": []}
    tokens = [t.strip() for t in re.split(r"[\s,，;；]+", query) if t.strip()]
    if not tokens:
        return []
    scored: list[tuple[int, dict]] = []
    for entry in manifest.get("profiles", []):
        haystack = " ".join(
            [
                entry.get("id") or "",
                " ".join(entry.get("tone_labels") or []),
                entry.get("genre_guess") or "",
                entry.get("narrative_pov") or "",
                " ".join(entry.get("key_signatures") or []),
            ]
        )
        hits = sum(1 for token in tokens if token in haystack)
        if hits >= len(tokens):
            scored.append((hits, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored]


def resolve_style_library_path(
    name: str, novels_root: Path | None = None
) -> Path:
    """按名字解析风格库档案路径（两路：manifest.id 优先，其次直接文件名）."""
    manifest = load_style_manifest(novels_root)
    for entry in manifest.get("profiles", []):
        if entry.get("id") == name and entry.get("file"):
            return style_library_dir(novels_root) / entry["file"]
    return style_library_profile_path(name, novels_root)
