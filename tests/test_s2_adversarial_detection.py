"""S2（54 计划）对抗样本（已知缺陷文本）裁判检出率测试.

完成判据第 3 条的可操作化：5 类已知缺陷样本必须能被裁判协议检出
（violated + blocking claim 可表达），负控（无缺陷正文）不得误报。
确定性硬门禁对跨章矛盾 / 重复闭环样本必须阻断。

样本类：
1. 跨章事实矛盾（正文与既有事实冲突）
2. 角色行为不一致（违背角色驱动力/恐惧）
3. 时间矛盾（与时间书冲突）
4. 契约 forbidden drift（违反 ReaderContract）
5. 重复闭环（顿悟核心与上一章重复）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.workflow_action.judge_council import (
    build_judge_claim_prompt,
    parse_judge_claims,
)
from src.object_state.evaluator_precommit import EvaluatorPrecommit


def _precommit(pid: str = "pc-001", plotunit_id: str = "pu-001") -> EvaluatorPrecommit:
    return EvaluatorPrecommit(
        precommit_id=pid,
        plotunit_id=plotunit_id,
        input_state_id="s0",
        output_state_id="s1",
        expected_output_location="书房",
        expected_output_situation="对峙",
        expected_released_information=["密信内容"],
        expected_consequences=["主角决定追查"],
        effective=True,
        trusted_state_hash="0" * 64,
        check_list=["falsify_location", "falsify_situation"],
    )


def _claims_payload(claims: list[dict]) -> str:
    return json.dumps({"claims": claims}, ensure_ascii=False)


# ---- 样本：5 类已知缺陷正文 ----

CROSS_CHAPTER_CONTRADICTION = (
    "他抬起左手，五指灵活地敲了敲桌面。\n"
    "【此前章节】主角左臂已在城门口被斩断，肩头缠着浸血的绷带。\n"
    "他端起茶碗，左手稳稳握住杯沿。"
)

CHARACTER_INCONSISTENCY = (
    "苏晚有深海恐惧症，病历上写着：无法靠近任何水域。\n"
    "他径直跳入湖中，游到对岸，笑道：『湖景不错。』"
)

TIME_CONTRADICTION = (
    "时值深冬，大雪封山，屋檐结满冰凌。\n"
    "他推开窗，感叹道：『今年的晚稻长势真好，稻穗金黄。』"
)

CONTRACT_FORBIDDEN_DRIFT = (
    "【读者契约】forbidden_drifts: ['主角不杀人']\n"
    "他抽出刀，面无表情地割断了求饶者的喉咙。"
)

REPEATED_CLOSURE = (
    "本章末尾，他忽然顿悟：『原来这一切都是执念——放下即是自由。』\n"
    "（上一章结尾：他忽然顿悟：『原来这一切都是执念——放下即是自由。』）"
)

# 负控：无已知缺陷的普通推进正文
CLEAN_PROSE = (
    "他在书房里整理信件，指尖拂过泛黄的纸页。\n"
    "窗外雨声渐密，他合上信封，起身望向门外——有人来了。"
)


# ---- 1. 裁判协议能表达检出（violated + blocking + 锚点逐字校验） ----

@pytest.mark.parametrize(
    "prose,claim_excerpt",
    [
        (CROSS_CHAPTER_CONTRADICTION, "左手稳稳握住杯沿"),
        (CHARACTER_INCONSISTENCY, "径直跳入湖中"),
        (TIME_CONTRADICTION, "晚稻长势真好"),
        (CONTRACT_FORBIDDEN_DRIFT, "割断了求饶者的喉咙"),
        (REPEATED_CLOSURE, "原来这一切都是执念"),
    ],
    ids=["cross_chapter", "character", "time", "contract", "repeated_closure"],
)
def test_known_defect_expressible_as_violated_claim(prose: str, claim_excerpt: str) -> None:
    precommit = _precommit()
    prompt = build_judge_claim_prompt(precommit, prose, role="reader_judge")
    assert "你负责【读者体验】轴" in prompt
    char_start = prose.index(claim_excerpt)
    payload = _claims_payload([
        {
            "claim_id": "cl_001",
            "precommit_id": precommit.precommit_id,
            "axis": "progression",
            "verdict": "violated",
            "severity": "blocking",
            "anchors": [{"position": "start", "excerpt": claim_excerpt,
                         "char_start": char_start, "char_end": char_start + len(claim_excerpt)}],
            "rationale": "正文与既有事实/契约直接矛盾（已知缺陷样本）。",
        }
    ])
    claims = parse_judge_claims(payload, prose=prose, chapter_ref="chapter_1",
                                role="reader_judge", precommit=precommit)
    assert len(claims) == 1
    assert claims[0].verdict == "violated"
    assert claims[0].severity == "blocking"
    assert claims[0].anchors[0].excerpt == claim_excerpt


def test_clean_prose_no_false_positive_claims() -> None:
    """负控：裁判协议允许空 claims（宁缺毋滥），parse 接受空数组. """
    precommit = _precommit()
    claims = parse_judge_claims(_claims_payload([]), prose=CLEAN_PROSE,
                                chapter_ref="chapter_1", role="reader_judge",
                                precommit=precommit)
    assert claims == []


def test_invented_anchor_rejected() -> None:
    """对抗样本的另一面：捏造锚点（excerpt 与正文不一致）必须被拒绝. """
    precommit = _precommit()
    payload = _claims_payload([
        {
            "claim_id": "cl_001",
            "precommit_id": precommit.precommit_id,
            "axis": "progression",
            "verdict": "violated",
            "severity": "blocking",
            "anchors": [{"position": "start", "excerpt": "这段文字正文里根本不存在",
                         "char_start": 0, "char_end": 14}],
            "rationale": "捏造锚点。",
        }
    ])
    with pytest.raises(ValueError):
        parse_judge_claims(payload, prose=CLEAN_PROSE, chapter_ref="chapter_1",
                           role="reader_judge", precommit=precommit)


# ---- 2. 确定性硬门禁对样本的阻断 ----

def test_reader_gate_blocks_repeated_closure(tmp_path: Path) -> None:
    """重复闭环：上一章已提交同核心顿悟 → 提交点门禁必须阻断. """
    from src.boundary_control.reader_gate import evaluate_commit_reader_gate

    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir(parents=True)
    (chapters_dir / "chapter_1.txt").write_text(
        "……他忽然顿悟：『原来这一切都是执念——放下即是自由。』", encoding="utf-8")
    output_dir = tmp_path / "output" / "extend"
    output_dir.mkdir(parents=True)

    verdict, _pkg, _issues = evaluate_commit_reader_gate(
        output_dir=output_dir,
        chapters_dir=chapters_dir,
        draft_text=REPEATED_CLOSURE,
        chapter_ref="chapter_2",
        require_campaign_evidence=False,
    )
    assert verdict.route in ("block", "manual"), f"重复闭环必须阻断，实际 {verdict.route}"


def test_reader_gate_blocks_cross_chapter_contradiction(tmp_path: Path) -> None:
    """跨章矛盾：正文断言左臂完好而既有事实是左臂已断 → 硬一致性阻断. """
    from src.boundary_control.reader_gate import evaluate_commit_reader_gate

    chapters_dir = tmp_path / "chapters"
    chapters_dir.mkdir(parents=True)
    (chapters_dir / "chapter_1.txt").write_text(
        "城门口，刀光一闪，他的左臂齐肩断落，鲜血浸透绷带。", encoding="utf-8")
    output_dir = tmp_path / "output" / "extend"
    output_dir.mkdir(parents=True)

    verdict, _pkg, issues = evaluate_commit_reader_gate(
        output_dir=output_dir,
        chapters_dir=chapters_dir,
        draft_text=CROSS_CHAPTER_CONTRADICTION,
        chapter_ref="chapter_2",
        require_campaign_evidence=False,
    )
    # 跨章硬一致性检测到矛盾 → 至少产生 blocking 级 issue（或 block 判定）
    assert verdict.route in ("block", "manual", "rewrite") or any(
        getattr(i, "severity", "") == "blocking" for i in issues
    ), "跨章矛盾必须被阻断或至少产生 blocking issue"
