"""G7 内容无关评审协议：单候选评审 + 确定性比较 + 证据锚定仲裁.

旧 A/B 偏好评审（build_preference_judge_prompt）把两个候选并排展示，评审模型可以按
「候选甲」槽位作答而不是按内容（deepseek-v4-flash temp0 实测 position consistency 0.5
——把偏好名到「甲」槽位）。G7 修复把评审改成**内容无关**的三段式：

1. **单候选评审**（build_single_review_prompt → parse_single_review）：每轮只给一个
   候选 + 写作要求，评审不见「甲/乙」槽位、不见另一份候选、不见比较意图；产出内容
   摘要（content_digest）+ 带原文锚点的单轴判断 + 置信度/弃权。
2. **确定性程序比较**（compare_single_reviews）：硬轴消除（blocking+violated 少者胜）
   → 软轴帕累托支配（axis_scores 逐轴 ≥ 且至少一轴 >）→ no_difference / undecidable。
3. **证据锚定仲裁**（build_anchored_arbitration_prompt → parse_anchored_arbitration）：
   仅 undecidable 时执行。评审引用**被选候选自己的正文**的 decisive_anchor；程序把锚点
   映射到实际包含它的候选（内容优先于槽位名），锚点在两处都有 → 非区分性证据 →
   no_difference，都不在 → 捏造，raise。

防伪一致性（不依赖「先选甲」捷径）：
- 锚点必须逐字存在（compact 后子串匹配，_MIN_EXCERPT_LEN 以上）；捏造/越界整批拒绝。
- 匹配前统一剥除引号字形变体（ASCII/弯引号/全角）与强调排版记号（`* _ #`），同一对
  引号/排版记号不同字形不算捏造；存储锚点仍是定位后正文原串（response[start:end]），
  逐字真实性不因此削弱。
- 单候选评审结果与展示顺序无关；位置一致性按「两轮选同一内容」口径自然成立。
- 槽位名可以偏，内容不能偏——仲裁即使命名「甲」但其锚点只在「乙」，程序仍映射到乙。

调用方（auto_calibrate_short_form）用 ``make_review_judge`` 包出 judge_fn，交给
run_preference_judge / measure_position_consistency，不改它们的接口。
"""

from __future__ import annotations

import json
import re

from src.object_state.preference_review import (
    PreferenceAnchor,
    PreferenceReviewClaim,
    SingleCandidateReview,
)
from src.workflow_action.plan_search import compact_text

# 评审角色的单候选轴描述（与旧 _PREFERENCE_ROLE_AXES 语义一致，但改为单候选措辞）。
_ROLE_AXIS_GUIDE = {
    "fact_judge": "事实轴：文本是否与既定事实冲突、是否可信、确定性与文学歧义是否分离。",
    "character_judge": "人物轴：人物行为/动机/弧光是否符合人物设定与内在逻辑。",
    "reader_judge": "读者体验轴：是否引人入胜、有现场感、少阅读摩擦、满足写作要求。",
}

# 单候选评审协议合规失败后的有界重请求次数（只对解析/协议失败，不对网络失败）。
REVIEW_MAX_QUALITY_ATTEMPTS = 3


class ReviewQualityExhaustedError(ValueError):
    """单候选评审/仲裁在多次有界重请求后仍未通过协议合规校验.

    与网络重试无关：``call`` 抛出的 provider/网络错误会立即上抛，绝不进入此路径。
    只有解析层（parse_single_review / parse_anchored_arbitration）判定协议违规
    （锚点捏造/形状违例等）才会触发有界重请求；耗尽后以此异常诚实上抛。
    """


def parse_with_quality_retry(
    call,
    parse,
    *,
    max_attempts: int = REVIEW_MAX_QUALITY_ATTEMPTS,
    on_retry=None,
):
    """调用 provider 并解析；仅当 parse 抛 ``ValueError``（协议合规失败）时有界重请求.

    - ``call()`` 返回原始响应文本；``parse(text)`` 做严格解析（锚点捏造等 → ValueError）。
    - 网络/配置错误从 ``call`` 直接上抛，不做重试（与 provider_adapter 的单次尝试契约一致）。
    - 每次重请求是独立的全新调用；耗尽后抛 ``ReviewQualityExhaustedError``。
    - ``on_retry(attempt)`` 供调用方记录重请求次数（attempt 从 1 起）。
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        text = call()
        try:
            return parse(text)
        except ValueError as exc:
            last_error = exc
            if on_retry is not None:
                on_retry(attempt)
    assert last_error is not None
    raise ReviewQualityExhaustedError(str(last_error)) from last_error

_MIN_EXCERPT_LEN = 6
_MAX_DIGEST_LEN = 400

# compact_text 去除的字符类（从中提取做「原始定位」的间隙正则）。
_COMPACT_CLASS = re.match(r"\[([^]]+)\]", r"[\s，。！？；：、,.!?;:“”‘’—…・\-—…~·（()）【】《》「」『』]+").group(1)

# 引号字形变体（ASCII/弯引号/全角/低九）——同一对引号在不同来源里会用不同字形，
# 匹配前统一剥除，避免「逐字原文」因字形差异被误判为捏造。
_QUOTE_GLYPH_CHARS = "'\"‘’‚‛“”„‟＂＇"
# Markdown/强调排版记号（正文里作强调装饰，评审引用时常被省略）——同为非内容格式化字符，
# 匹配时与空白/标点一样忽略；存储锚点仍是定位后正文原串，逐字真实性不受影响。
_FORMAT_GLYPH_CHARS = "`*_#"
_IGNORED_GLYPH_CHARS = _QUOTE_GLYPH_CHARS + _FORMAT_GLYPH_CHARS
_QUOTE_GLYPH_RE = re.compile(f"[{_IGNORED_GLYPH_CHARS}]")


# 展示层/字形修复（围栏 + 未转义中文引号）从共享模块引入；保留 `_` 旧名兼容测试。
from src.workflow_action.json_repair import (  # noqa: E402  (循环依赖规避：本模块与 json_repair 无依赖环)
    parse_json as _parse_json,
    repair_unescaped_quotes as _repair_unescaped_quotes,
    strip_code_fence as _strip_code_fence,
)


def _locate_excerpt(response: str, excerpt: str) -> tuple[int, int] | None:
    """在 response 中定位 excerpt（compact 后子串匹配），返回真实 [start, end).

    excerpt 必须逐字来自 response（只允许空白/标点/引号/强调排版记号差异）；否则返回 None。
    """
    def _fold(text: str) -> str:
        return _QUOTE_GLYPH_RE.sub("", compact_text(text))

    hay = _fold(response)
    needle = _fold(excerpt)
    if not needle or len(needle) < _MIN_EXCERPT_LEN:
        return None
    if needle not in hay:
        return None
    # compact 抹掉了位置，需在原始文本里按「允许间隙字符」重定位。
    gap = f"[{_COMPACT_CLASS}{_IGNORED_GLYPH_CHARS}]*"
    pattern = re.escape(needle[0]) + "".join(
        gap + re.escape(c) for c in needle[1:]
    )
    match = re.search(pattern, response)
    if match is None:
        return None
    return match.start(), match.end()


# --------------------------------------------------------------------------
# 单候选评审
# --------------------------------------------------------------------------

def build_single_review_prompt(
    prompt: str,
    response: str,
    *,
    role: str = "reader_judge",
) -> str:
    """单候选评审 prompt：只给写作要求 + 一个候选，不见槽位、不见比较意图."""
    axis = _ROLE_AXIS_GUIDE.get(role, _ROLE_AXIS_GUIDE["reader_judge"])
    return f"""【单候选评审】（{role}）
你在独立评审一个文本在多大程度上满足了下面的写作要求。你**只看到这一个候选**，
不做任何比较——忠实评审它的内容本身。

{axis}

【写作要求】
{prompt}

【待评审候选】
{response}

【评审要求】
1. content_digest：用 2–4 句忠实概括该候选实际写了什么（主题/立场/结构/风格/情绪），
   让没看过原文的人也能凭摘要把它与其他候选区分开。必须基于文本内容，不得空泛套话。
2. claims：逐条**单轴**判断（axis 填一个短维度名，如“推进/人物/契约/阅读摩擦/语言/
   建设性歧义/事实”，聚焦“{axis}”）。每条必须引用该候选正文中确凿支持的连续原文片段
   作为锚点（excerpt 必须逐字来自正文；char_start/char_end 只作辅助，不必精确）。
   **excerpt 必须是一段连续原文**：禁止用省略号（……）拼接多个不连续片段，禁止改写/
   压缩/重排原文，**禁止在片段前后加任何标签/说明词（如『题记：』『原文：』『引用：』）**，
   从正文中一个字符一个字符地原样截取。若该判断找不到一段能逐字支撑的连续原文，就把
   该 claim 标为 inconclusive（或删去该 claim），不得为它编造锚点。
3. verdict = satisfied（满足）/ violated（违背）/ inconclusive（证据不足）；
   severity 只填 blocking（与写作要求/基本质量直接矛盾：离题、事实严重冲突、结构崩塌）
   或 advisory（软质量问题）。不确定时给 advisory + inconclusive。
4. 没有足够证据做任何判断时，置 abstain=true 并给 abstain_reason（claims 可为空）。
5. 禁止捏造锚点。**不要逐字数算 [char_start, char_end) 偏移**——excerpt 本身就是校验
   依据，系统会按“去空白/标点后逐字一致”自动定位它在正文中的真实位置并重算偏移；
   你只要原样复制一段连续正文作 excerpt，char_start/char_end 给出大致估计即可。
6. **JSON 字符串值内的引号**：正文里的中文引语一律用全角引号（“ ” 或 「 」），严禁在
   JSON 字符串值内写未转义的英文双引号 "（会破坏 JSON 语法）。

【输出格式】严格 JSON（只输出 JSON，不要 Markdown 代码块）：
{{
  "content_digest": "…",
  "claims": [
    {{
      "claim_id": "c1",
      "axis": "…",
      "verdict": "satisfied",
      "severity": "advisory",
      "anchors": [{{"excerpt": "…正文连续原文…", "char_start": 0, "char_end": 40}}],
      "confidence": 0.9,
      "rationale": "…"
    }}
  ],
  "experience_rating": 4,
  "overall_confidence": 0.8,
  "abstain": false,
  "abstain_reason": ""
}}
- experience_rating：1–5，该候选作为阅读体验的强度（仅读者视角；无把握时给 null）。
- overall_confidence：0–1。除非 abstain=true，否则 claims 至少一条。
"""


def parse_single_review(
    text: str,
    *,
    candidate_ref: str,
    response: str,
    role: str = "reader_judge",
) -> SingleCandidateReview:
    """严格解析单候选评审，核验锚点真实性（excerpt 必须逐字来自 response）.

    Raises ValueError：形状违例 / 锚点捏造 / 弃权无理由 / 非弃权零 claims。
    """
    del role  # 保留签名兼容；本解析不依赖角色
    try:
        data = _parse_json(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"single review is not JSON ({candidate_ref})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"single review must be a JSON object ({candidate_ref})")
    required = {
        "content_digest",
        "claims",
        "experience_rating",
        "overall_confidence",
        "abstain",
        "abstain_reason",
    }
    missing = sorted(required - set(data))
    extra = sorted(set(data) - required)
    if missing or extra:
        raise ValueError(
            f"single review must contain exactly {sorted(required)} "
            f"({candidate_ref}); missing {missing}, extra {extra}"
        )

    digest = data["content_digest"]
    if not isinstance(digest, str) or not digest.strip():
        raise ValueError(f"single review content_digest must be non-blank ({candidate_ref})")

    claims_raw = data["claims"]
    if not isinstance(claims_raw, list):
        raise ValueError(f"single review claims must be a list ({candidate_ref})")
    claims: list[PreferenceReviewClaim] = []
    for index, item in enumerate(claims_raw):
        if not isinstance(item, dict):
            raise ValueError(f"single review claim {index} must be a JSON object ({candidate_ref})")
        claim_required = {
            "claim_id",
            "axis",
            "verdict",
            "severity",
            "anchors",
            "confidence",
            "rationale",
        }
        claim_missing = sorted(claim_required - set(item))
        claim_extra = sorted(set(item) - claim_required)
        if claim_missing or claim_extra:
            raise ValueError(
                f"single review claim {index} must contain exactly {sorted(claim_required)} "
                f"({candidate_ref}); missing {claim_missing}, extra {claim_extra}"
            )
        anchors_raw = item["anchors"]
        if not isinstance(anchors_raw, list) or not anchors_raw:
            raise ValueError(
                f"single review claim {index} anchors must be a non-empty list ({candidate_ref})"
            )
        anchors: list[PreferenceAnchor] = []
        for a_index, anchor in enumerate(anchors_raw):
            if not isinstance(anchor, dict):
                raise ValueError(
                    f"single review claim {index} anchor {a_index} must be a JSON object ({candidate_ref})"
                )
            if set(anchor) != {"excerpt", "char_start", "char_end"}:
                raise ValueError(
                    f"single review claim {index} anchor {a_index} must contain exactly "
                    f"excerpt/char_start/char_end ({candidate_ref})"
                )
            excerpt = anchor["excerpt"]
            if not isinstance(excerpt, str) or not excerpt.strip():
                raise ValueError(
                    f"single review claim {index} anchor {a_index} excerpt must be non-empty ({candidate_ref})"
                )
            located = _locate_excerpt(response, excerpt)
            if located is None:
                raise ValueError(
                    f"single review claim {index} anchor {a_index} excerpt not found in "
                    f"response — fabricated anchor ({candidate_ref})"
                )
            start, end = located
            anchors.append(
                PreferenceAnchor(excerpt=response[start:end], char_start=start, char_end=end)
            )
        verdict = item["verdict"]
        severity = item["severity"]
        if verdict not in ("satisfied", "violated", "inconclusive"):
            raise ValueError(f"single review claim {index} verdict invalid ({candidate_ref})")
        if severity not in ("blocking", "advisory"):
            raise ValueError(f"single review claim {index} severity invalid ({candidate_ref})")
        confidence = item["confidence"]
        if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
            raise ValueError(
                f"single review claim {index} confidence out of range ({candidate_ref})"
            )
        rationale = item["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(
                f"single review claim {index} rationale must be non-blank ({candidate_ref})"
            )
        claims.append(
            PreferenceReviewClaim(
                claim_id=item["claim_id"],
                axis=item["axis"],
                verdict=verdict,
                severity=severity,
                anchors=anchors,
                confidence=float(confidence),
                rationale=rationale,
            )
        )

    abstain = data["abstain"]
    if not isinstance(abstain, bool):
        raise ValueError(f"single review abstain must be boolean ({candidate_ref})")
    abstain_reason = data["abstain_reason"]
    if abstain and (not isinstance(abstain_reason, str) or not abstain_reason.strip()):
        raise ValueError(
            f"single review abstain requires non-blank abstain_reason ({candidate_ref})"
        )
    rating = data["experience_rating"]
    if rating is not None and (
        not isinstance(rating, (int, float)) or not (1 <= rating <= 5)
    ):
        raise ValueError(
            f"single review experience_rating out of range ({candidate_ref})"
        )
    conf = data["overall_confidence"]
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        raise ValueError(
            f"single review overall_confidence out of range ({candidate_ref})"
        )
    if not abstain and not claims:
        raise ValueError(
            f"single review must have ≥1 claim or abstain=true ({candidate_ref})"
        )
    return SingleCandidateReview(
        review_id=candidate_ref,
        content_digest=digest,
        claims=claims,
        experience_rating=int(rating) if rating is not None else None,
        overall_confidence=float(conf),
        abstain=abstain,
        abstain_reason=abstain_reason,
    )


# --------------------------------------------------------------------------
# 确定性程序比较
# --------------------------------------------------------------------------

def compare_single_reviews(
    review_a: SingleCandidateReview,
    review_b: SingleCandidateReview,
) -> str:
    """确定性比较 → "A"(第一份候选更优) / "B"(第二份更优) / "no_difference" / "undecidable".

    1. 双方都弃权 → no_difference；一方弃权 → undecidable（仲裁决定）。
    2. 硬轴消除：blocking+violated 少者胜。
    3. 软轴帕累托：axis_scores 逐轴 ≥ 且至少一轴 > 则支配；全平 → no_difference；
       互不支配 → undecidable。
    """
    if review_a.abstain or review_b.abstain:
        return "no_difference" if review_a.abstain and review_b.abstain else "undecidable"
    hard_a = review_a.hard_violation_count()
    hard_b = review_b.hard_violation_count()
    if hard_a != hard_b:
        return "A" if hard_a < hard_b else "B"
    scores_a = review_a.axis_scores()
    scores_b = review_b.axis_scores()
    axes = sorted(set(scores_a) | set(scores_b))
    if not axes:
        return "undecidable"
    ge_a = all(scores_a.get(axis, 0) >= scores_b.get(axis, 0) for axis in axes)
    ge_b = all(scores_b.get(axis, 0) >= scores_a.get(axis, 0) for axis in axes)
    if ge_a and not ge_b:
        return "A"
    if ge_b and not ge_a:
        return "B"
    if ge_a and ge_b:
        return "no_difference"
    return "undecidable"


# --------------------------------------------------------------------------
# 证据锚定仲裁（仅 undecidable）
# --------------------------------------------------------------------------

def _render_claims(review: SingleCandidateReview) -> str:
    if review.abstain:
        return f"（该候选弃权：{review.abstain_reason or '无理由'}）"
    lines: list[str] = []
    for claim in review.claims:
        anchor_text = "；".join(a.excerpt for a in claim.anchors)
        lines.append(
            f"- {claim.axis} / {claim.verdict} / {claim.severity} (conf {claim.confidence}): "
            f"{claim.rationale} | 锚点原文: {anchor_text}"
        )
    return "\n".join(lines) if lines else "（无判断）"


def build_anchored_arbitration_prompt(
    prompt: str,
    review_a: SingleCandidateReview,
    review_b: SingleCandidateReview,
    *,
    role: str = "reader_judge",
) -> str:
    """证据锚定仲裁 prompt：只给两份单候选评审证据（摘要 + 判断 + 锚点），不给全文。

    decisive_anchor 必须从被选候选**自己的正文**引用（仲裁所见锚点原文即来自正文，
    程序随后映射到实际包含它的候选）。
    """
    axis = _ROLE_AXIS_GUIDE.get(role, _ROLE_AXIS_GUIDE["reader_judge"])
    return f"""【证据锚定仲裁】（{role}）
两个候选都做了独立单候选评审，评审证据未能直接分出高下。请你比较下面两份**评审证据**
（内容摘要 + 逐条判断 + 原文锚点），并引用你裁定所依据的**决定性原文片段**来仲裁。

{axis}

【写作要求】
{prompt}

【候选甲 内容摘要】
{review_a.content_digest[:_MAX_DIGEST_LEN]}
【候选甲 评审证据】
{_render_claims(review_a)}

【候选乙 内容摘要】
{review_b.content_digest[:_MAX_DIGEST_LEN]}
【候选乙 评审证据】
{_render_claims(review_b)}

【裁定要求】
1. preferred ∈ "A" / "B" / "no_difference"：哪个候选更满足写作要求。
2. decisive_anchor：从你选中的候选**自己的正文**中引用一段决定性证据——你裁定所依据的
   关键原文片段（excerpt 必须逐字来自该候选正文；char_start/char_end 只作辅助，不必精确）。
   **excerpt 必须是一段连续原文**：禁止用省略号（……）拼接多个不连续片段，禁止改写/
   压缩/重排，**禁止在片段前后加任何标签/说明词（如『题记：』『原文：』『引用：』）**。
   找不到连续原文支撑的裁定时，返回 "no_difference"。
   只有 preferred 为 "no_difference" 时才允许 decisive_anchor 为 null。
3. rationale：一句话理由。**不要逐字数算 [char_start, char_end) 偏移**——excerpt 就是
   校验依据，系统会按“去空白/标点后逐字一致”自动定位并映射到实际包含它的候选；
   你只要原样复制一段连续正文作 excerpt，偏移给出大致估计即可。禁止捏造锚点。
4. **JSON 字符串值内的引号**：正文里的中文引语一律用全角引号（“ ” 或 「 」），严禁在
   JSON 字符串值内写未转义的英文双引号 "（会破坏 JSON 语法）。

【输出格式】严格 JSON（只输出 JSON，不要 Markdown 代码块）：
{{
  "preferred": "A",
  "decisive_anchor": {{"excerpt": "…", "char_start": 0, "char_end": 40}},
  "rationale": "…"
}}
"""


def parse_anchored_arbitration(
    text: str,
    *,
    pair_id: str,
    response_a: str,
    response_b: str,
) -> str:
    """解析仲裁 → "A" / "B" / "no_difference". decisive_anchor 由程序映射到实际包含
    它的候选（内容优先于槽位名）：锚点在甲 → "A"，只在乙 → "B"，两处都有 →
    no_difference（非区分性证据），都不在 → 捏造，raise."""
    try:
        data = _parse_json(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"arbitration response is not JSON ({pair_id})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"arbitration response must be a JSON object ({pair_id})")
    required = {"preferred", "decisive_anchor", "rationale"}
    if set(data) != required:
        raise ValueError(
            f"arbitration response must contain exactly {sorted(required)} "
            f"({pair_id}); got {sorted(data)}"
        )
    preferred = data["preferred"]
    if preferred not in ("A", "B", "no_difference"):
        raise ValueError(
            f"arbitration preferred must be A/B/no_difference ({pair_id})"
        )
    rationale = data["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError(f"arbitration rationale must be non-blank ({pair_id})")
    if preferred == "no_difference":
        return "no_difference"
    anchor = data["decisive_anchor"]
    if not isinstance(anchor, dict):
        raise ValueError(
            f"arbitration decisive_anchor must be a JSON object ({pair_id})"
        )
    if set(anchor) != {"excerpt", "char_start", "char_end"}:
        raise ValueError(
            f"arbitration decisive_anchor must contain exactly excerpt/char_start/char_end "
            f"({pair_id})"
        )
    excerpt = anchor["excerpt"]
    if not isinstance(excerpt, str) or not excerpt.strip():
        raise ValueError(
            f"arbitration decisive_anchor excerpt must be non-blank ({pair_id})"
        )
    loc_a = _locate_excerpt(response_a, excerpt)
    loc_b = _locate_excerpt(response_b, excerpt)
    if loc_a and loc_b:
        return "no_difference"  # 锚点在两处都出现 → 非区分性证据
    if loc_a:
        return "A"  # 内容（锚点）指向甲
    if loc_b:
        return "B"  # 内容（锚点）指向乙
    raise ValueError(
        f"arbitration decisive_anchor not found in either response — fabricated ({pair_id})"
    )


# --------------------------------------------------------------------------
# 组装 judge_fn（供 run_preference_judge / measure_position_consistency）
# --------------------------------------------------------------------------

def predict_with_reviews(
    review_chosen: SingleCandidateReview,
    review_rejected: SingleCandidateReview,
    *,
    prompt: str,
    response_chosen: str,
    response_rejected: str,
    role: str,
    arbitrate_fn,
) -> str:
    """完整协议：确定性比较；undecidable 才仲裁。

    返回 "A"(chosen 胜) / "B"(rejected 胜) / "no_difference"，内容无关，
    可直接交给 run_preference_judge 的正确口径（A=选 chosen=正确）。
    """
    decision = compare_single_reviews(review_chosen, review_rejected)
    if decision != "undecidable":
        return decision
    return arbitrate_fn(
        prompt,
        review_chosen,
        review_rejected,
        response_chosen,
        response_rejected,
        role,
    )


def make_review_judge(review_fn, arbitrate_fn):
    """把单候选评审 + 仲裁包成 judge_fn(pair, role) → "A"/"B"/"no_difference".

    review_fn(prompt, response, role, candidate_ref) → SingleCandidateReview
    arbitrate_fn(prompt, r_chosen, r_rejected, response_chosen, response_rejected, role)
        → "A"/"B"/"no_difference"（A=chosen 胜）
    """

    def judge(pair, role: str) -> str:
        candidate_ref = pair.prompt_id
        r_chosen = review_fn(
            pair.prompt, pair.chosen, role, candidate_ref=f"{candidate_ref}:chosen"
        )
        r_rejected = review_fn(
            pair.prompt, pair.rejected, role, candidate_ref=f"{candidate_ref}:rejected"
        )
        return predict_with_reviews(
            r_chosen,
            r_rejected,
            prompt=pair.prompt,
            response_chosen=pair.chosen,
            response_rejected=pair.rejected,
            role=role,
            arbitrate_fn=arbitrate_fn,
        )

    return judge
