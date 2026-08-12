"""A1 T6 — 帕累托前沿 + 匿名 A/B 换位选择单元测试（design §7；tasks.md T6）.

覆盖：
- T6.4 软轴帕累托前沿：支配关系、缺失轴按 0、空分数全入选、输入顺序确定性。
- T6.2/T6.6 匿名换位 prompt：**绝不泄漏候选身份**（候选 id / 预承诺 id / 计划
  标签 / 版本号 / 正文哈希 / 生成模型身份）——reward hacking 与同模型自偏好的
  隔离面；角色指引随 role 切换。
- T6.3 严格解析 + 位置一致：A/B 与 B/A 两轮命名同一正文 → 位置一致；no_difference
  或换位不一致 → 位置不一致（位置偏置检测）。
- T6.5 淘汰赛：稳定胜者前进、判别轮、仍不一致该对淘汰、无稳定胜者 → None。
"""

import pytest

from src.workflow_action.pareto_tournament import (
    PairTournamentResult,
    build_anonymous_pair_prompt,
    parse_anonymous_pair_response,
    pareto_frontier,
    resolve_pair,
    selection_tournament,
)

_X = "prose_pu_candidate_v1"
_Y = "prose_pu_candidate_v2"


# ---------------------------------------------------------------- T6.4 帕累托前沿


class TestParetoFrontier:
    def test_single_candidate_is_itself(self):
        assert pareto_frontier([_X], {_X: {"a": 1}}) == [_X]

    def test_dominance_removes_dominated(self):
        # X 在全部轴 ≥Y 且至少一轴严格更好 → Y 被支配淘汰。
        scores = {_X: {"a": 2, "b": 1}, _Y: {"a": 1, "b": 1}}
        assert pareto_frontier([_X, _Y], scores) == [_X]

    def test_incomparable_both_survive(self):
        scores = {_X: {"a": 2, "b": 0}, _Y: {"a": 0, "b": 2}}
        assert pareto_frontier([_X, _Y], scores) == [_X, _Y]

    def test_equal_scores_no_dominance(self):
        scores = {_X: {"a": 1, "b": 1}, _Y: {"a": 1, "b": 1}}
        assert pareto_frontier([_X, _Y], scores) == [_X, _Y]

    def test_missing_axis_treated_as_zero(self):
        # X 缺 b 轴 → 按 0；Y 在 b 严格更好 → X 被支配。
        scores = {_X: {"a": 1}, _Y: {"a": 1, "b": 1}}
        assert pareto_frontier([_X, _Y], scores) == [_Y]

    def test_empty_scores_all_survive(self):
        assert pareto_frontier([_X, _Y], {}) == [_X, _Y]

    def test_input_order_preserved_deterministically(self):
        scores = {
            "c": {"a": 1},
            "a": {"b": 1},
            "b": {"a": 1, "b": 0},
        }
        # c/a/b 两两互不支配（各有一轴领先、其余轴平手）→ 全部入选，顺序保持。
        assert pareto_frontier(["c", "a", "b"], scores) == ["c", "a", "b"]


# ----------------------------------------- T6.2/T6.6 匿名换位 prompt 与解析


class TestAnonymousPairPrompt:
    def test_contains_neutral_markers_and_both_bodies(self):
        prompt = build_anonymous_pair_prompt("正文甲", "正文乙")
        assert "【候选甲（匿名）】" in prompt
        assert "【候选乙（匿名）】" in prompt
        assert "正文甲" in prompt
        assert "正文乙" in prompt
        assert "【匿名换位评审】" in prompt

    def test_no_candidate_identity_leaks(self):
        """reward hacking 隔离：prompt 不得含任何候选身份旁证."""
        prompt = build_anonymous_pair_prompt("甲方案", "乙方案")
        for leak in (
            "prose_",  # 候选 id 前缀
            _X,
            _Y,
            "precommit_plan",  # 预承诺 id
            "plan_0001",  # 计划标签
            "_v1",  # 版本号
            "sha256",
            "candidate_id",
            "generation",  # 生成模型身份/角色
            "request_model",
        ):
            assert leak not in prompt, f"匿名 prompt 泄漏身份旁证: {leak}"

    def test_no_generator_identity_for_self_preference(self):
        """同模型自偏好隔离：评审看不到生成器身份，无法按熟悉度自偏好."""
        prompt = build_anonymous_pair_prompt("甲", "乙")
        # 不出现任何模型/角色/版本身份；只要求不得利用来源。
        for leak in (
            "deepseek",
            "claude",
            "generation",
            "reader_judge",
            "fact_judge",
            "character_judge",
            "request_model",
            "actual_model",
            "prose_pu_candidate",
        ):
            assert leak not in prompt, f"泄漏生成器/评审身份: {leak}"
        assert "由你" not in prompt  # 不能暗示正文是本模型生成的
        assert "你生成的" not in prompt

    def test_role_guide_switches(self):
        fact = build_anonymous_pair_prompt("甲", "乙", role="fact_judge")
        character = build_anonymous_pair_prompt("甲", "乙", role="character_judge")
        reader = build_anonymous_pair_prompt("甲", "乙", role="reader_judge")
        assert "【事实】轴" in fact
        assert "【人物】轴" in character
        assert "【读者体验】轴" in reader
        assert fact != character != reader

    def test_contract_section_optional(self):
        with_contract = build_anonymous_pair_prompt(
            "甲", "乙", reader_contract_context="契约正文"
        )
        without = build_anonymous_pair_prompt("甲", "乙")
        assert "契约正文" in with_contract
        assert "契约正文" not in without
        assert "【读者契约】" not in without

    def test_output_format_spec_is_strict(self):
        prompt = build_anonymous_pair_prompt("甲", "乙")
        assert '"preferred"' in prompt
        assert '"no_difference"' in prompt


class TestParseAnonymousPairResponse:
    def test_valid_preferences(self):
        assert parse_anonymous_pair_response(
            '{"preferred": "A", "rationale": "更紧凑"}', "p1"
        ) == "A"
        assert parse_anonymous_pair_response(
            '{"preferred": "B", "rationale": "更有现场感"}', "p1"
        ) == "B"
        assert parse_anonymous_pair_response(
            '{"preferred": "no_difference", "rationale": "各有长短"}', "p1"
        ) == "no_difference"

    def test_non_json_rejected(self):
        with pytest.raises(ValueError):
            parse_anonymous_pair_response("not json", "p1")

    def test_non_object_rejected(self):
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('["A"]', "p1")

    def test_missing_or_extra_fields_rejected(self):
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('{"rationale": "x"}', "p1")
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('{"preferred": "A"}', "p1")
        with pytest.raises(ValueError):
            parse_anonymous_pair_response(
                '{"preferred": "A", "rationale": "x", "candidate_id": "leak"}', "p1"
            )

    def test_invalid_preferred_rejected(self):
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('{"preferred": "C", "rationale": "x"}', "p1")
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('{"preferred": "甲乙", "rationale": "x"}', "p1")

    def test_blank_rationale_rejected(self):
        with pytest.raises(ValueError):
            parse_anonymous_pair_response('{"preferred": "A", "rationale": "  "}', "p1")


# --------------------------------------------- T6.3 位置一致（换位稳定性）


class TestResolvePair:
    def test_both_rounds_name_x(self):
        # A/B：甲=x → "A"；B/A：甲=y，选 "B" 即选 x → 位置一致，x 胜。
        winner, consistent, _ = resolve_pair("A", "B", _X, _Y)
        assert winner == _X and consistent

    def test_both_rounds_name_y(self):
        winner, consistent, _ = resolve_pair("B", "A", _X, _Y)
        assert winner == _Y and consistent

    def test_position_bias_detected(self):
        """评审总是偏好位置甲 → 两轮命名不同正文 → 位置不一致（偏置暴露）."""
        winner, consistent, disagreement = resolve_pair("A", "A", _X, _Y)
        assert winner is None and not consistent
        assert "A/B→A, B/A→A" in disagreement

    def test_position_aversion_detected(self):
        winner, consistent, _ = resolve_pair("B", "B", _X, _Y)
        assert winner is None and not consistent

    def test_no_difference_is_inconsistent(self):
        for ab, ba in (("A", "no_difference"), ("no_difference", "B"),
                       ("no_difference", "no_difference")):
            winner, consistent, _ = resolve_pair(ab, ba, _X, _Y)
            assert winner is None and not consistent


# ----------------------------------------------------------- T6.5 淘汰赛


def _content_based_judge(prose_by_id):
    """内容基判别：永远偏好含「甲方案」标记的正文（换位一致）."""

    def judge(x, y):
        x_has_marker = "甲方案" in prose_by_id[x]
        pref_ab = "A" if x_has_marker else "B"
        # B/A 轮：甲=y。若 y 含标记 → "A"（即 y）；否则 "B"（即 x）。
        y_has_marker = "甲方案" in prose_by_id[y]
        pref_ba = "A" if y_has_marker else "B"
        return pref_ab, pref_ba

    return judge


def _position_biased_judge(x, y):
    """位置偏置：永远偏好位置甲（两轮都返回 "A"）→ 必然位置不一致."""
    return "A", "A"


def _swing_judge(calls, prose_by_id):
    """首轮位置偏置、判别轮回归内容基：验证判别轮收敛."""
    first = {"done": False}

    def judge(x, y):
        if not first["done"]:
            first["done"] = True
            return _position_biased_judge(x, y)
        return _content_based_judge(prose_by_id)(x, y)

    return judge


class TestSelectionTournament:
    def test_two_candidates_stable_winner(self):
        prose_by_id = {_X: "甲方案正文", _Y: "乙方案正文"}
        result = selection_tournament(
            [_X, _Y], _content_based_judge(prose_by_id), max_rounds=1
        )
        assert result.winner == _X
        assert result.position_consistency_rate == 1.0
        assert len(result.pairs) == 1
        assert result.pairs[0]["position_consistent"] is True
        assert result.pairs[0]["candidates"] == [_X, _Y]

    def test_position_bias_no_stable_winner(self):
        # 恒偏好位置甲 → 每对两轮命名不同 → 判别轮（max_rounds=1）后仍不稳定
        # → 该对双方淘汰 → 无稳定胜者。
        result = selection_tournament(
            [_X, _Y], _position_biased_judge, max_rounds=1
        )
        assert result.winner is None
        assert result.position_consistency_rate == 0.0
        assert result.pairs[0]["discriminator_rounds"] == 1

    def test_discriminator_round_converges(self):
        # max_rounds=2：首轮位置偏置 → 判别轮内容基收敛 → 稳定胜者 + 2 轮。
        prose_by_id = {_X: "甲方案正文", _Y: "乙方案正文"}
        result = selection_tournament(
            [_X, _Y], _swing_judge(None, prose_by_id), max_rounds=2
        )
        assert result.winner == _X
        assert result.pairs[0]["discriminator_rounds"] == 2
        assert result.position_consistency_rate == 1.0

    def test_three_candidates_knockout(self):
        _Z = "prose_pu_candidate_v3"
        prose_by_id = {_X: "甲方案正文", _Y: "乙方案正文", _Z: "丙方案正文"}
        # 淘汰赛：对1 (X,Y) → X；对2 (X,Z) → X。唯一稳定胜者 X。
        result = selection_tournament(
            [_X, _Y, _Z], _content_based_judge(prose_by_id), max_rounds=1
        )
        assert result.winner == _X
        assert len(result.pairs) == 2
        assert result.position_consistency_rate == 1.0
        # X 淘汰 Y 后与 Z 对位（Z 未与 Y 直接对位——淘汰赛语义）。
        assert result.pairs[1]["candidates"][0] == _X

    def test_unstable_pair_eliminates_both(self):
        # 单对不稳定 → 池变空 → None（对双方淘汰），rate 0。
        result = selection_tournament([_X, _Y], _position_biased_judge, max_rounds=1)
        assert result.winner is None

    def test_empty_frontier(self):
        result = selection_tournament([], _position_biased_judge, max_rounds=1)
        assert result.winner is None
        assert result.position_consistency_rate == 1.0

    def test_single_candidate_no_pairs(self):
        result = selection_tournament([_X], _position_biased_judge, max_rounds=1)
        assert result.winner == _X
        assert result.position_consistency_rate == 1.0
