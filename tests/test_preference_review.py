"""G7 内容无关评审协议测试（single-candidate review + deterministic compare + anchored arbitration）.

锁死三件事：
1. 单候选评审解析的**锚点真实性**——excerpt 必须逐字来自被评审文本，捏造即拒。
2. 确定性程序比较的**硬轴/软轴语义**——hard elimination 优先，软轴帕累托支配。
3. 证据锚定仲裁的**内容优先于槽位名**——preferred 命名「甲」但锚点只在乙 → 映射到乙；
   槽位命名型仲裁（恒命名甲 + 引甲槽位正文）在换位测量下必须暴露为 0.0 一致性，
   内容稳定型仲裁必须 1.0。
"""

import json

import pytest

from src.object_state.preference_review import (
    PreferenceAnchor,
    PreferenceReviewClaim,
    SingleCandidateReview,
)
from src.workflow_action.auto_calibrate import measure_position_consistency
from src.workflow_action.preference_review import (
    ReviewQualityExhaustedError,
    _locate_excerpt,
    _repair_unescaped_quotes,
    build_anchored_arbitration_prompt,
    build_single_review_prompt,
    compare_single_reviews,
    make_review_judge,
    parse_anchored_arbitration,
    parse_single_review,
    parse_with_quality_retry,
    predict_with_reviews,
)
from src.object_state.qualitythresholds import PreferencePair

# 两段内容互不支配的文本：X 推进强、语言无；Y 语言强、推进无 → 评审证据 undecidable。
_TEXT_X = "故事在推进。主线在发展，人物的目标逐渐清晰。"
_TEXT_Y = "文字流畅。语感舒服，句子长短错落有致。"


def _pair(prompt_id="p-001", chosen=_TEXT_X, rejected=_TEXT_Y) -> PreferencePair:
    return PreferencePair(
        prompt_id=prompt_id,
        tag="散文",
        prompt="写一段",
        chosen=chosen,
        rejected=rejected,
        split="calibration",
        bucket=0,
    )


def _claim(verdict: str, axis: str, excerpt: str, severity: str = "advisory") -> PreferenceReviewClaim:
    return PreferenceReviewClaim(
        claim_id="c1",
        axis=axis,
        verdict=verdict,
        severity=severity,
        anchors=[PreferenceAnchor(excerpt=excerpt, char_start=0, char_end=len(excerpt))],
        confidence=0.9,
        rationale="测试。",
    )


# ---------------------------------------------------------------------------
# 单候选评审 prompt 与解析（锚点真实性）
# ---------------------------------------------------------------------------

def test_build_single_review_prompt_has_no_slots():
    prompt = build_single_review_prompt("写一段", "正文内容", role="reader_judge")
    assert "【待评审候选】" in prompt
    assert "候选甲" not in prompt and "候选乙" not in prompt  # 不见槽位、不见比较
    assert "content_digest" in prompt


def _review_payload(excerpt, verdict="satisfied") -> dict:
    return {
        "content_digest": "推进型文本，主线在发展。",
        "claims": [
            {
                "claim_id": "c1",
                "axis": "推进",
                "verdict": verdict,
                "severity": "advisory",
                "anchors": [
                    {"excerpt": excerpt, "char_start": 0, "char_end": len(excerpt)}
                ],
                "confidence": 0.9,
                "rationale": "测试。",
            }
        ],
        "experience_rating": 4,
        "overall_confidence": 0.8,
        "abstain": False,
        "abstain_reason": "",
    }


def test_parse_single_review_accepts_real_anchor():
    excerpt = "故事在推进。主线在发展"
    review = parse_single_review(
        json.dumps(_review_payload(excerpt), ensure_ascii=False),
        candidate_ref="p:chosen",
        response=_TEXT_X,
        role="reader_judge",
    )
    assert review.review_id == "p:chosen"
    assert review.claims[0].axis == "推进"
    # 程序定位回填真实偏移
    assert review.claims[0].anchors[0].char_start >= 0
    assert review.claims[0].anchors[0].char_end <= len(_TEXT_X)


def test_parse_single_review_rejects_fabricated_anchor():
    payload = _review_payload("这句话根本不在原文里出现。")
    with pytest.raises(ValueError, match="fabricated"):
        parse_single_review(
            json.dumps(payload, ensure_ascii=False),
            candidate_ref="p:chosen",
            response=_TEXT_X,
            role="reader_judge",
        )


def test_parse_single_review_rejects_too_short_excerpt():
    payload = _review_payload("甲")
    with pytest.raises(ValueError, match="fabricated"):
        parse_single_review(
            json.dumps(payload, ensure_ascii=False),
            candidate_ref="p:chosen",
            response=_TEXT_X,
            role="reader_judge",
        )


@pytest.mark.parametrize(
    ("excerpt", "source", "expected"),
    [
        # 来源用弯引号，评审用 ASCII 引号包同一短语 → 字形差异不算捏造，应匹配
        ("写下'今天的云像被揉碎的棉花糖'也是",
         '我们写下"今天的云像被揉碎的棉花糖"也是必然',
         '写下"今天的云像被揉碎的棉花糖"也是'),
        # 反向：来源用 ASCII 引号，评审用弯引号
        ('他说“今天很好”我们出发', '他说"今天很好"我们出发了。', '他说"今天很好"我们出发'),
        # 来源用 ** 强调记号，评审引用时省略 → 排版记号差异不算捏造，应匹配
        ("去拥抱未知，因为那里藏着你人生的惊喜！",
         "去拥抱未知，因为那里藏着你人生的惊喜！**去大胆尝试**",
         "去拥抱未知，因为那里藏着你人生的惊喜"),
        # 真正不同的文本仍必须拒绝
        ("写下'今天的云像被揉碎的棉花糖'也是",
         '我们写下完全不同的另一句原文也是必然',
         None),
    ],
)
def test_locate_excerpt_quote_glyph_variants(excerpt, source, expected):
    located = _locate_excerpt(source, excerpt)
    if expected is None:
        assert located is None
    else:
        assert located is not None
        start, end = located
        # 存储的锚点必须是来源逐字原串（含原字形），不是评审文本
        assert source[start:end] == expected



def test_parse_single_review_accepts_markdown_code_fence():
    # prism claude-sonnet-4-6 常在 JSON 外裹 ```json ... ``` 围栏——展示层装饰，应被剥除。
    fence = "```json\n" + json.dumps(_review_payload("故事在推进。主线在发展"), ensure_ascii=False) + "\n```"
    review = parse_single_review(
        fence,
        candidate_ref="p:chosen",
        response=_TEXT_X,
        role="reader_judge",
    )
    assert review.review_id == "p:chosen"
    assert review.claims[0].axis == "推进"


def test_parse_anchored_arbitration_accepts_markdown_code_fence():
    fence = "```json\n" + json.dumps(
        {
            "preferred": "B",
            "decisive_anchor": {"excerpt": "故事在推进。主线在发展", "char_start": 0, "char_end": 10},
            "rationale": "测试。",
        },
        ensure_ascii=False,
    ) + "\n```"
    assert (
        parse_anchored_arbitration(
            fence, pair_id="p", response_a=_TEXT_X, response_b=_TEXT_Y
        )
        == "A"
    )


# ---------------------------------------------------------------------------
# 未转义引号修复（prism claude-sonnet-4-6 中文引语被写成裸 ASCII "）
# ---------------------------------------------------------------------------

def test_repair_unescaped_quotes_clean_json_unchanged():
    clean = '{"a": "故事在推进。", "b": [1, 2], "c": {"d": "文字流畅"}}'
    assert _repair_unescaped_quotes(clean) == clean


def test_repair_unescaped_quotes_chinese_quote_in_value():
    # "快点儿" 裸 ASCII 引号夹在汉字间 → 必须转义为 \"，否则 JSON 非法。
    bad = '{"content_digest": "文章以总分总结构议论"快点儿"的辩证意义"}'
    repaired = _repair_unescaped_quotes(bad)
    # 修复只保证 JSON 合法，不改字形：解析后仍是模型写下的 ASCII 引号。
    assert json.loads(repaired)["content_digest"] == "文章以总分总结构议论\"快点儿\"的辩证意义"
    # 字节级：裸 " 已被转义为 \"。
    assert '\\"快点儿\\"' in repaired


def test_repair_unescaped_quotes_escaped_quotes_left_alone():
    # 已正确转义的 \" 不得被二次改动。
    clean = '{"a": "他说\\"你好\\""}'
    assert _repair_unescaped_quotes(clean) == clean


def test_parse_single_review_accepts_unescaped_quote_in_digest():
    # 围栏 + 未转义中文引号同时出现（prism 实测缺陷）→ 解析必须成功。
    payload = (
        '```json\n'
        '{\n'
        '  "content_digest": "文章以总分总结构议论"快点儿"的辩证意义：引言指出人们惯于",\n'
        '  "claims": [\n'
        '    {\n'
        '      "claim_id": "c1",\n'
        '      "axis": "推进",\n'
        '      "verdict": "satisfied",\n'
        '      "severity": "advisory",\n'
        '      "anchors": [{"excerpt": "故事在推进。主线在发展", "char_start": 0, "char_end": 10}],\n'
        '      "confidence": 0.9,\n'
        '      "rationale": "测试。"\n'
        '    }\n'
        '  ],\n'
        '  "experience_rating": 4,\n'
        '  "overall_confidence": 0.8,\n'
        '  "abstain": false,\n'
        '  "abstain_reason": ""\n'
        '}\n'
        '```'
    )
    review = parse_single_review(payload, candidate_ref="p:chosen", response=_TEXT_X, role="reader_judge")
    assert review.claims[0].axis == "推进"
    assert "快点儿" in review.content_digest


def test_parse_anchored_arbitration_accepts_unescaped_quote_in_rationale():
    payload = (
        '```json\n'
        '{\n'
        '  "preferred": "A",\n'
        '  "decisive_anchor": {"excerpt": "故事在推进。主线在发展", "char_start": 0, "char_end": 10},\n'
        '  "rationale": "它说"推进"了"\n'
        '}\n'
        '```'
    )
    assert (
        parse_anchored_arbitration(payload, pair_id="p", response_a=_TEXT_X, response_b=_TEXT_Y)
        == "A"
    )


def test_parse_single_review_tolerates_prose_preamble_and_trailing_fence():
    # prism claude-sonnet-4-6 实测：先写推理散文再给 JSON，JSON 又包在 ```json 围栏里
    # （smoke7 judge JSONDecodeError 根因）。提取第一个平衡 JSON 对象必须解析成功。
    payload = (
        'I need to carefully review the chapter. Let me check the factual claims '
        'and verify the timestamps are internally consistent.\n'
        'The chapter handles the price discrepancy well.\n'
        '```json\n'
        '{\n'
        '  "content_digest": "文章以总分总结构议论"快点儿"的辩证意义",\n'
        '  "claims": [\n'
        '    {\n'
        '      "claim_id": "c1",\n'
        '      "axis": "推进",\n'
        '      "verdict": "satisfied",\n'
        '      "severity": "advisory",\n'
        '      "anchors": [{"excerpt": "故事在推进。主线在发展", "char_start": 0, "char_end": 10}],\n'
        '      "confidence": 0.9,\n'
        '      "rationale": "测试。"\n'
        '    }\n'
        '  ],\n'
        '  "experience_rating": 4,\n'
        '  "overall_confidence": 0.8,\n'
        '  "abstain": false,\n'
        '  "abstain_reason": ""\n'
        '}\n'
        '```'
    )
    review = parse_single_review(payload, candidate_ref="p:chosen", response=_TEXT_X, role="reader_judge")
    assert review.claims[0].axis == "推进"
    assert "快点儿" in review.content_digest


def test_parse_json_preamble_with_fence_and_unescaped_quote():
    # 与上一个用例同构但直接走 parse_json：前导散文 + 围栏 + 裸中文引号三合一。
    from src.workflow_action.json_repair import parse_json

    payload = (
        'Let me think step by step about whether the anchor is verbatim.\n'
        'The anchor "故事在推进。主线在发展" appears early in the text.\n'
        '```json\n'
        '{"content_digest": "它说"推进"了", "claims": []}\n'
        '```'
    )
    obj = parse_json(payload)
    assert obj["content_digest"] == '它说"推进"了'


def test_parse_json_preamble_contains_braces_skips_prose_object():
    # 前导散文本身含 {...}（如 anchor/position 说明）时，首个 '{' 落在散文里；
    # 逐个候选扫描必须跳过散文对象，取真正的 JSON。此前只取首个 '{' 直接失败。
    from src.workflow_action.json_repair import parse_json

    payload = (
        'I reviewed the anchor {position: "middle", excerpt: "快点儿"} and '
        'checked the evidence.\n'
        '```json\n'
        '{"claims": [{"claim_id": "c1", "precommit_id": "p1", "axis": "x",'
        ' "verdict": "satisfied", "severity": "advisory", "rationale": "ok",'
        ' "anchors": [{"position": "middle", "excerpt": "快点儿",'
        ' "char_start": 0, "char_end": 3}]}]}\n'
        '```'
    )
    obj = parse_json(payload)
    assert isinstance(obj, dict) and set(obj) == {"claims"}
    assert obj["claims"][0]["claim_id"] == "c1"


def test_parse_single_review_abstain_and_strict_shape():
    abstain = {
        "content_digest": "难以判断。",
        "claims": [],
        "experience_rating": None,
        "overall_confidence": 0.3,
        "abstain": True,
        "abstain_reason": "文本过短，无法形成判断。",
    }
    review = parse_single_review(
        json.dumps(abstain, ensure_ascii=False),
        candidate_ref="p:chosen",
        response=_TEXT_X,
        role="reader_judge",
    )
    assert review.abstain is True
    # 非弃权却零 claims → 拒
    bad = {**abstain, "abstain": False, "abstain_reason": ""}
    with pytest.raises(ValueError, match="≥1 claim"):
        parse_single_review(
            json.dumps(bad, ensure_ascii=False),
            candidate_ref="p:chosen",
            response=_TEXT_X,
            role="reader_judge",
        )
    # 弃权却无理由 → 拒
    with pytest.raises(ValueError, match="abstain_reason"):
        parse_single_review(
            json.dumps({**abstain, "abstain_reason": ""}, ensure_ascii=False),
            candidate_ref="p:chosen",
            response=_TEXT_X,
            role="reader_judge",
        )


# ---------------------------------------------------------------------------
# 确定性程序比较
# ---------------------------------------------------------------------------

def _review(review_id, claims, digest="摘要") -> SingleCandidateReview:
    return SingleCandidateReview(
        review_id=review_id,
        content_digest=digest,
        claims=claims,
        experience_rating=4,
        overall_confidence=0.8,
        abstain=False,
        abstain_reason="",
    )


def test_compare_hard_axis_elimination_first():
    hard = _review("a", [_claim("violated", "推进", "没有推进。", severity="blocking")])
    soft = _review("b", [_claim("violated", "推进", "没有推进。", severity="advisory")])
    assert compare_single_reviews(soft, hard) == "A"  # 硬违例少者胜
    assert compare_single_reviews(hard, soft) == "B"


def test_compare_soft_pareto_dominance():
    better = _review("a", [_claim("satisfied", "推进", "故事在推进。")])
    worse = _review("b", [_claim("violated", "推进", "故事没有推进。")])
    assert compare_single_reviews(better, worse) == "A"
    assert compare_single_reviews(worse, better) == "B"


def test_compare_cross_dominating_is_undecidable():
    x = _review("x", [_claim("satisfied", "推进", "故事在推进。")])
    y = _review("y", [_claim("satisfied", "语言", "文字流畅。")])
    assert compare_single_reviews(x, y) == "undecidable"


def test_compare_all_equal_is_no_difference():
    a = _review("a", [_claim("satisfied", "推进", "故事在推进。")])
    b = _review("b", [_claim("satisfied", "推进", "故事在推进。")])
    assert compare_single_reviews(a, b) == "no_difference"


def test_compare_abstain_semantics():
    abstain_a = _review("a", [], digest="弃权")
    abstain_a.abstain = True
    abstain_a.abstain_reason = "过短"
    normal = _review("b", [_claim("satisfied", "推进", "故事在推进。")])
    assert compare_single_reviews(abstain_a, abstain_a) == "no_difference"
    assert compare_single_reviews(abstain_a, normal) == "undecidable"


# ---------------------------------------------------------------------------
# 证据锚定仲裁（内容优先于槽位名）
# ---------------------------------------------------------------------------

def test_build_arbitration_prompt_has_both_evidence_and_contract():
    prompt = build_anchored_arbitration_prompt(
        "写一段",
        _review("a", [_claim("satisfied", "推进", "故事在推进。")]),
        _review("b", [_claim("satisfied", "语言", "文字流畅。")]),
        role="reader_judge",
    )
    assert "【候选甲 评审证据】" in prompt and "【候选乙 评审证据】" in prompt
    assert "decisive_anchor" in prompt


def _arb_text(preferred: str, excerpt: str, pair_id: str, resp_a: str, resp_b: str) -> str:
    return parse_anchored_arbitration(
        json.dumps(
            {
                "preferred": preferred,
                "decisive_anchor": {
                    "excerpt": excerpt,
                    "char_start": 0,
                    "char_end": len(excerpt),
                },
                "rationale": "测试。",
            },
            ensure_ascii=False,
        ),
        pair_id=pair_id,
        response_a=resp_a,
        response_b=resp_b,
    )


def test_arbitration_maps_anchor_to_content_not_slot_name():
    # 评审命名「甲」，但决定性锚点只在乙正文里 → 程序映射到乙（内容优先于槽位名）。
    assert _arb_text("A", "文字流畅。语感舒服", "p", _TEXT_X, _TEXT_Y) == "B"
    assert _arb_text("B", "故事在推进。主线在发展", "p", _TEXT_X, _TEXT_Y) == "A"


def test_arbitration_anchor_in_both_is_no_difference():
    shared = "今天天气很好"
    # shared 在两个候选都出现（非区分性证据）→ no_difference
    assert (
        _arb_text("A", shared, "p", "今天天气很好，我们出发了。", "今天天气很好，我们回家了。")
        == "no_difference"
    )


def test_arbitration_fabricated_anchor_raises():
    with pytest.raises(ValueError, match="fabricated"):
        _arb_text("A", "这段文字哪都不存在", "p", _TEXT_X, _TEXT_Y)


def test_arbitration_no_difference_no_anchor():
    assert (
        parse_anchored_arbitration(
            json.dumps(
                {"preferred": "no_difference", "decisive_anchor": None, "rationale": "难分。"},
                ensure_ascii=False,
            ),
            pair_id="p",
            response_a=_TEXT_X,
            response_b=_TEXT_Y,
        )
        == "no_difference"
    )


# ---------------------------------------------------------------------------
# 组装 judge → 位置一致性（内容无关）与正确性
# ---------------------------------------------------------------------------

def _cross_axis_review(prompt, response, role, candidate_ref):
    """内容评审：X 推进、Y 语言 → 两份证据互不支配 → undecidable → 走仲裁."""
    if "推进" in response:
        claims = [_claim("satisfied", "推进", "故事在推进。主线在发展")]
        digest = "推进型"
    else:
        claims = [_claim("satisfied", "语言", "文字流畅。语感舒服")]
        digest = "语言型"
    return SingleCandidateReview(
        review_id=candidate_ref,
        content_digest=digest,
        claims=claims,
        experience_rating=4,
        overall_confidence=0.8,
        abstain=False,
        abstain_reason="",
    )


def _content_arbitrate(prompt, r_chosen, r_rejected, response_chosen, response_rejected, role):
    """内容稳定仲裁：恒偏好含「推进」的文本（X），锚点引其真实原文——无论 X 在哪个槽位."""
    x_is_chosen = "推进" in response_chosen
    preferred = "A" if x_is_chosen else "B"
    excerpt = "故事在推进。主线在发展"
    return parse_anchored_arbitration(
        json.dumps(
            {
                "preferred": preferred,
                "decisive_anchor": {"excerpt": excerpt, "char_start": 0, "char_end": len(excerpt)},
                "rationale": "推进优先。",
            },
            ensure_ascii=False,
        ),
        pair_id="content",
        response_a=response_chosen,
        response_b=response_rejected,
    )


def _slot_biased_arbitrate(prompt, r_chosen, r_rejected, response_chosen, response_rejected, role):
    """槽位命名仲裁：恒命名「甲」并引当前甲槽位正文——内容映射下换位必须暴露为不一致."""
    excerpt = response_chosen[:12]
    return parse_anchored_arbitration(
        json.dumps(
            {
                "preferred": "A",
                "decisive_anchor": {"excerpt": excerpt, "char_start": 0, "char_end": len(excerpt)},
                "rationale": "恒甲。",
            },
            ensure_ascii=False,
        ),
        pair_id="slot",
        response_a=response_chosen,
        response_b=response_rejected,
    )


def test_position_consistency_content_stable_review_judge_is_1():
    judge = make_review_judge(_cross_axis_review, _content_arbitrate)
    pairs = [_pair(prompt_id=f"p-{i:03d}") for i in range(3)]
    assert measure_position_consistency(pairs, judge, role="reader_judge") == 1.0


def test_position_consistency_slot_naming_arbitration_is_0():
    judge = make_review_judge(_cross_axis_review, _slot_biased_arbitrate)
    pairs = [_pair(prompt_id=f"p-{i:03d}") for i in range(3)]
    assert measure_position_consistency(pairs, judge, role="reader_judge") == 0.0


def test_make_review_judge_correctness_follows_content():
    judge = make_review_judge(_cross_axis_review, _content_arbitrate)
    # chosen=X（推进型）→ 内容仲裁选 X → "A"（正确）；rejected=X → "B"（rejected 胜）。
    assert judge(_pair(chosen=_TEXT_X, rejected=_TEXT_Y), "reader_judge") == "A"
    assert judge(_pair(chosen=_TEXT_Y, rejected=_TEXT_X), "reader_judge") == "B"


def test_predict_with_reviews_arbitrates_only_when_undecidable():
    x = _review("x", [_claim("satisfied", "推进", "故事在推进。")])
    y = _review("y", [_claim("satisfied", "语言", "文字流畅。")])
    calls = {"n": 0}

    def counting_arbitrate(*args, **kwargs):
        calls["n"] += 1
        return "A"

    # 决定性 → 不仲裁
    decisive = predict_with_reviews(
        x, x, prompt="p", response_chosen=_TEXT_X, response_rejected=_TEXT_Y,
        role="reader_judge", arbitrate_fn=counting_arbitrate,
    )
    assert decisive == "no_difference" and calls["n"] == 0
    # undecidable → 仲裁
    undecided = predict_with_reviews(
        x, y, prompt="p", response_chosen=_TEXT_X, response_rejected=_TEXT_Y,
        role="reader_judge", arbitrate_fn=_content_arbitrate,
    )
    assert undecided == "A"


# ---------------------------------------------------------------------------
# 有界协议合规重请求（parse_with_quality_retry）——只重请求解析失败，不重试网络
# ---------------------------------------------------------------------------

def test_quality_retry_returns_first_success():
    """parse 前两次 ValueError（协议违规）→ 第三次成功，on_retry 记录次数."""
    calls = []
    retries = []

    def call():
        calls.append(1)
        return "resp"

    def parse(text):
        if len(calls) == 1:
            raise ValueError("fabricated anchor")
        if len(calls) == 2:
            raise ValueError("malformed json")
        return "parsed-ok"

    result = parse_with_quality_retry(
        call, parse, on_retry=lambda attempt: retries.append(attempt)
    )
    assert result == "parsed-ok"
    assert len(calls) == 3
    assert retries == [1, 2]


def test_quality_retry_exhausts_to_review_quality_exhausted_error():
    """每次 parse 都 ValueError → 有界次数后抛 ReviewQualityExhaustedError（不无限重试）."""
    calls = []

    def call():
        calls.append(1)
        return "resp"

    def parse(text):
        raise ValueError("fabricated anchor")

    with pytest.raises(ReviewQualityExhaustedError):
        parse_with_quality_retry(call, parse, max_attempts=3)
    assert len(calls) == 3  # 1 次原始 + 2 次重请求


def test_quality_retry_network_error_propagates_without_retry():
    """provider/网络错误从 call 直接上抛，绝不进入重请求路径."""
    calls = []

    def call():
        calls.append(1)
        raise RuntimeError("provider 5xx")

    def parse(text):
        raise AssertionError("parse 不应被调用")

    with pytest.raises(RuntimeError, match="5xx"):
        parse_with_quality_retry(call, parse)
    assert len(calls) == 1  # 单次 attempt，无重试
