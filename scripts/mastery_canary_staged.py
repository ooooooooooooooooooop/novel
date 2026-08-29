#!/usr/bin/env python
"""2-Chapter Staged CLI Canary Regression Script (R9 整改验收).

模拟真实 2 章统一 CLI Staged 流水线：
1. 初始状态与编排计划 (NarrativeOrchestrator).
2. 章节 1：`novel compose` 触发 -> `pending` 侦测 -> 写入 staged 响应 -> `novel resume`
   -> 结构搜索 (RolloutStateSnapshot / RolloutTransition) -> 读者门禁 & 因果防线 -> 事务边界提交 (ChapterCommitBoundary / run_manifest.json).
3. 章节 2：状态继承 -> Hindsight 反哺更新 AuthorModel V3 -> 第二章编排与搜索 -> 事务提交.
4. Taste Stack 严格密码学证据链审计 (Layer 1 必须校验 committed manifest 与 reader_gate_report 哈希).
5. 严苛长程无人授权裁决 (未完成真人盲评前严格输出 long_run_not_authorized).

可独立运行：python scripts/mastery_canary_staged.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# 确保导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.boundary_control.chapter_commit import ChapterCommitBoundary
from src.boundary_control.reader_gate import evaluate_commit_reader_gate
from src.domain_layer.causal_defense import run_causal_defense
from src.object_state import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CandidateRecord,
    CausalRule,
    CharacterModel,
    ChoiceRecord,
    CrossWorkValidationResult,
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
    PlotUnit,
    RejectedRecord,
    SceneExperience,
    StructuralProposal,
    WorldModel,
)
from src.workflow_action.authormodel_v3 import (
    is_author_model_certified_for_production,
    save_author_model_v3,
    save_qualification_report,
    update_author_model_from_hindsight,
)
from src.workflow_action.choiceledger import load_choice_ledger
from src.workflow_action.human_eval import (
    evaluate_long_horizon_authorization,
    inspect_long_horizon_preconditions,
)
from src.workflow_action.narrative_orchestrator import (
    commit_orchestration_transition,
    derive_orchestration_plan,
    load_committed_orchestration_state,
)
from src.workflow_action.structural_search import (
    StructuralSearchEngine,
    evaluate_structural_diversity,
)
from src.workflow_action.taste_stack import build_unified_quality_report


def _run_cli(args: list[str], novels_root: Path) -> subprocess.CompletedProcess[str]:
    """执行真实 novel CLI 子进程命令."""
    env = os.environ.copy()
    env["NOVELS_ROOT"] = str(novels_root)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "novel_cli.py"), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_mastery_canary_subprocess(novels_root: Path, novel_name: str = "canary_staged_novel") -> dict:
    """通过真实 subprocess 管道跑通 2-Chapter Staged CLI 流程."""
    novel_dir = novels_root / novel_name
    output_dir = novel_dir / "output" / "compose"

    # 1. 章节 1：novel compose 启动（首次空工作区初始化）
    cp_compose = _run_cli(
        ["compose", novel_name, "--proposals", "2", "--structural-search", "on"],
        novels_root,
    )
    if cp_compose.returncode != 0:
        raise RuntimeError(f"novel compose failed (rc={cp_compose.returncode}):\n{cp_compose.stdout}\n{cp_compose.stderr}")
    assert "[WAITING]" in cp_compose.stdout or (output_dir / "proposals_prompt.txt").exists()

    # 启用 flow v3 事务式运行
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    # 2. 写入已认证 AuthorModel 与留一资格认证报告
    principle = AuthorPrincipleV3(
        principle_id="p_truth_over_safety",
        statement="坚持揭示残酷真相而非粉饰太平",
        value_vocab_key="courage_over_comfort",
        scope="author_global",
        confidence=0.85,
        status="stable",
    )
    author_model = AuthorModelV3(
        author_id="author_mastery",
        author_name="测试宗师",
        principles=[principle],
        known_works=["万物伏藏", "仙途诡事"],
        work_separation_audited=True,
    )
    save_author_model_v3(output_dir, author_model)
    qual_report_obj = CrossWorkValidationResult(
        author_id="author_mastery",
        holdout_work="万物伏藏",
        training_works=["仙途诡事", "剑道独尊"],
        choice_prediction_accuracy=0.88,
        baseline_accuracy=0.5,
        lexical_leakage_detected=False,
        is_valid_author_prior=True,
    )
    save_qualification_report(output_dir, qual_report_obj)

    # 检查 pending
    cp_pending = _run_cli(["pending", novel_name, "--json"], novels_root)
    assert cp_pending.returncode == 0
    pending_info = json.loads(cp_pending.stdout)
    assert pending_info["pending"][0]["slot_id"] == "proposals"

    # 写入 Chapter 1 Proposals Response
    pu_ch1_A = {
        "plotunit": {
            "unit_id": "pu_ch1_01",
            "level": "scene",
            "goal": "主角深夜排查，在阵眼残留中发现内门执法长老的私印残痕并收存物证",
            "participants": ["c001"],
            "conflict": "探查阵眼与暗处窥视",
            "input_state_ref": "ns_initial",
            "output_state_ref": "ns_ch1_A",
            "released_information": ["阵眼深处藏有内门紫玉印泥残痕"],
            "emotional_shift": "从警惕到决然",
            "hook": "紫玉残痕昭示着高层不可告人的秘密",
            "hook_type": "scene_hook",
            "formula_node": "investigation",
            "consequences": ["主角获取核心物证，由被动排查转入主动破局"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": "阵眼处的紫玉残粉",
                "obstacles": ["阵法反噬残留毒雾"],
                "choice_grounding": "退缩必成替罪羊",
                "outcome": "拿到核心物证",
                "cognition_shift": "认识到外门盗案实为高层灭口布局",
            },
        },
        "new_state": {
            "state_id": "ns_ch1_A",
            "current_time": "天启三年春三月望日",
            "current_location": "天玄宗外门密室",
            "active_characters": ["c001"],
            "current_situation": "获取关键物证，危机升级",
            "active_conflicts": ["内门强敌暗杀威胁"],
            "public_information": [],
            "hidden_information": ["主角掌握传功堂盗案物证"],
        },
        "new_facts": [
            {
                "fact_id": "f_ch1_01",
                "statement": "主角在阵眼处提取到传功堂紫玉印泥残痕",
                "fact_type": "event",
                "involved_entities": ["c001", "紫玉印泥"],
                "confirmed": True,
            }
        ],
        "confidence_gaps": [],
        "tradeoff_hint": "承担暴露风险以获取核心物证",
    }
    pu_ch1_B = {
        "plotunit": {
            "unit_id": "pu_ch1_02",
            "level": "scene",
            "goal": "主角顺水推舟，将嫌疑引向敌对执事以求自保",
            "participants": ["c001"],
            "conflict": "心魔反噬与道德困境",
            "input_state_ref": "ns_initial",
            "output_state_ref": "ns_ch1_B",
            "released_information": ["外门执事间互相倾轧"],
            "emotional_shift": "从迷茫到妥协",
            "hook": "暂时脱罪但留下致命把柄",
            "hook_type": "scene_hook",
            "formula_node": "compromise",
            "consequences": ["暂时摆脱嫌疑但沦为棋子"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": "同僚绝望的眼神",
                "obstacles": ["良知拷问"],
                "choice_grounding": "先求自保再图后事",
                "outcome": "成功嫁祸",
                "cognition_shift": "感受到宗门倾轧的残酷",
            },
        },
        "new_state": {
            "state_id": "ns_ch1_B",
            "current_time": "天启三年春三月望日",
            "current_location": "天玄宗执事堂",
            "active_characters": ["c001"],
            "current_situation": "暂时脱罪但暗藏危机",
            "active_conflicts": ["把柄泄露风险"],
            "public_information": ["某执事涉嫌盗案"],
            "hidden_information": [],
        },
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": "牺牲原则换取苟安",
    }
    (output_dir / "proposals_response.txt").write_text(
        json.dumps({"proposals": [pu_ch1_A, pu_ch1_B]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 运行 compose 进入 prose
    cp_res1 = _run_cli(["compose", novel_name, "--proposals", "2", "--structural-search", "on"], novels_root)
    assert cp_res1.returncode == 0
    assert "[WAITING]" in cp_res1.stdout or (output_dir / "prose_prompt.txt").exists()

    ch1_prose = (
        "第一章 残痕\n\n"
        "夜雨如注，天玄宗外门灵库的青石台阶上泛着冰冷的死光。狂风撕扯着残破的窗棂，发出刺耳的呜咽声。\n"
        "主角蹲下身子，指尖拂过阵眼凹槽处的焦黑痕迹。雨水冲刷不掉那层极淡的紫玉粉末——那是内门传功长老一脉独有的沉香玉印。\n"
        "“不是外贼，是灭口。”主角眼中寒芒闪动，迅速自怀中取出玉瓶，将残粉悉数收入瓶中封存。\n"
        "他深知，从这一刻起，自己已踏入九死一生的死局。宗门内部的倾轧比想象中更为残酷，若不尽快寻得破局之法，明日天明之时，便是执法堂前来拿人之刻。"
    )
    (output_dir / "prose_response.txt").write_text(ch1_prose, encoding="utf-8")

    # 运行 compose 进入 review
    cp_res2 = _run_cli(["compose", novel_name, "--proposals", "2", "--structural-search", "on"], novels_root)
    assert cp_res2.returncode == 0
    assert "[WAITING]" in cp_res2.stdout or (output_dir / "compose_review_prompt.txt").exists()

    review_pass = {
        "route": "pass",
        "issues": [],
        "reminders": [],
    }
    (output_dir / "compose_review_response.txt").write_text(
        json.dumps(review_pass, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 运行 compose 提交 Chapter 1
    cp_res3 = _run_cli(["compose", novel_name, "--proposals", "2", "--structural-search", "on"], novels_root)
    assert cp_res3.returncode == 0
    assert (novel_dir / "chapters" / "chapter_1.txt").exists()
    assert (output_dir / "run_manifest.json").exists()

    # 3. 章节 2：续写 Chapter 2
    # 模拟 Hindsight 回填 ChoiceRecord
    if (output_dir / "choice_ledger.json").exists():
        ledger = load_choice_ledger(output_dir)
        if ledger.choices:
            rec = ledger.choices[-1]
            rec.consequence = "成功锁定内门沉香玉印残粉物证并化为主动"
            rec.hindsight = "still_supported"
            rec.hindsight_note = "在后续大比揭露中起决定性作用"
            (output_dir / "choice_ledger.json").write_text(
                ledger.model_dump_json(indent=2),
                encoding="utf-8",
            )
            # Hindsight 回填更新 AuthorModel
            update_author_model_from_hindsight(
                author_model,
                [rec],
                work_name="万物伏藏",
            )
            save_author_model_v3(output_dir, author_model)

    # 启动 Chapter 2 proposals
    cp_ch2_start = _run_cli(["resume", novel_name], novels_root)
    assert cp_ch2_start.returncode == 0

    pu_ch2_A = {
        "plotunit": {
            "unit_id": "pu_ch2_01",
            "level": "scene",
            "goal": "主角借大比之机，当众揭露内门账目疑点与玉印物证，迫使暗处敌人现身",
            "participants": ["c001"],
            "conflict": "大比公开施压与执法堂对峙",
            "input_state_ref": "ns_ch1_A",
            "output_state_ref": "ns_ch2_A",
            "released_information": ["主角在大比之上亮出玉印残痕物证"],
            "emotional_shift": "从隐忍到雷霆一击",
            "hook": "传功长老杀机毕露，公审在即",
            "hook_type": "scene_hook",
            "formula_node": "climax",
            "consequences": ["全宗哗然，高层被迫立案公审"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": "高台之上长老骤变的脸色",
                "obstacles": ["大能威压震慑"],
                "choice_grounding": "唯有掀翻棋盘方能求生",
                "outcome": "迫使执法堂介入公开对质",
                "cognition_shift": "领悟权力斗争的虚妄与实力的绝对本质",
            },
        },
        "new_state": {
            "state_id": "ns_ch2_A",
            "current_time": "天启三年春三月廿日",
            "current_location": "天玄宗演武大殿",
            "active_characters": ["c001"],
            "current_situation": "当众亮证引发全宗震动，公审在即",
            "active_conflicts": ["公审对决与刺杀防范"],
            "public_information": ["灵库失窃系传功堂监守自盗"],
            "hidden_information": [],
        },
        "new_facts": [
            {
                "fact_id": "f_ch2_01",
                "statement": "主角公开展示沉香玉印残粉物证",
                "fact_type": "event",
                "involved_entities": ["c001", "演武大殿"],
                "confirmed": True,
            }
        ],
        "confidence_gaps": [],
        "tradeoff_hint": "彻底决裂换取公开破局",
    }
    pu_ch2_B = {
        "plotunit": {
            "unit_id": "pu_ch2_02",
            "level": "scene",
            "goal": "主角暗中联络内门敌对派系进行交易，出卖外门利益换取庇护",
            "participants": ["c001"],
            "conflict": "尊严践踏与利益博弈",
            "input_state_ref": "ns_ch1_A",
            "output_state_ref": "ns_ch2_B",
            "released_information": ["内门各峰之间的残酷竞争"],
            "emotional_shift": "压抑与屈辱",
            "hook": "成为新派系走狗",
            "hook_type": "scene_hook",
            "formula_node": "compromise",
            "consequences": ["获得暂时庇护但失去自主权"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": "新主子轻蔑的笑容",
                "obstacles": ["内门盘剥"],
                "choice_grounding": "别无选择",
                "outcome": "获得庇护",
                "cognition_shift": "深感寄人篱下之苦",
            },
        },
        "new_state": {
            "state_id": "ns_ch2_B",
            "current_time": "天启三年春三月廿日",
            "current_location": "天玄宗内门别院",
            "active_characters": ["c001"],
            "current_situation": "依附新势力但暗藏杀机",
            "active_conflicts": ["被当成炮灰驱使"],
            "public_information": [],
            "hidden_information": [],
        },
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": "出卖同门换取庇护",
    }
    (output_dir / "proposals_response.txt").write_text(
        json.dumps({"proposals": [pu_ch2_A, pu_ch2_B]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # resume 进入 Chapter 2 prose
    cp_ch2_res1 = _run_cli(["resume", novel_name], novels_root)
    assert cp_ch2_res1.returncode == 0

    ch2_prose = (
        "第二章 掀盘\n\n"
        "外门大比的钟声响彻天玄山脉，万千弟子瞩目之下，主角缓步走上演武台中央。狂风猎猎，拂动他的青色衣角。\n"
        "他没有拔剑，而是反手将一只青玉药瓶拍碎在测灵石上。紫色的沉香玉粉在灵力激荡下爆发出耀眼的灵光，显化出传功堂长老的本命云纹印记。\n"
        "“灵库三千灵石，非外贼所窃，乃本门高层监守自盗！”主角的声音借阵法回荡全山，引得满场哗然，所有围观弟子的目光瞬间集中到高台长老席上。\n"
        "看台之上，传功长老霍然起身，周身金丹威压骤然爆发，眼中杀机四溢，死死盯住台下的青年，整座演武广场的气氛瞬间降至冰点。"
    )
    (output_dir / "prose_response.txt").write_text(ch2_prose, encoding="utf-8")

    # resume 进入 Chapter 2 review
    cp_ch2_res2 = _run_cli(["resume", novel_name], novels_root)
    if cp_ch2_res2.returncode != 0:
        raise RuntimeError(f"cp_ch2_res2 failed (rc={cp_ch2_res2.returncode}):\n{cp_ch2_res2.stdout}\n{cp_ch2_res2.stderr}")
    assert cp_ch2_res2.returncode == 0

    (output_dir / "compose_review_response.txt").write_text(
        json.dumps(review_pass, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # resume 提交 Chapter 2
    cp_ch2_res3 = _run_cli(["resume", novel_name], novels_root)
    if cp_ch2_res3.returncode != 0:
        raise RuntimeError(
            f"cp_ch2_res3 failed (rc={cp_ch2_res3.returncode}):\n"
            f"{cp_ch2_res3.stdout}\n{cp_ch2_res3.stderr}"
        )
    assert (novel_dir / "chapters" / "chapter_2.txt").exists()

    # 4. 执行 CLI Quality (Taste Stack)
    cp_quality = _run_cli(["quality", novel_name, "--format", "json", "--strict"], novels_root)
    assert cp_quality.returncode == 0
    quality_json = json.loads(cp_quality.stdout)
    assert quality_json["layer1_hard_gates"]["status"] == "passed"
    assert quality_json["layer1_hard_gates"]["blocking_issues_count"] == 0

    # 5. 执行 CLI Human Eval 授权裁决
    (novel_dir / "provider_profiles.json").write_text(
        json.dumps({"active_provider": "deepseek-v4-flash", "budget_ceiling": 50.0}),
        encoding="utf-8",
    )
    (novel_dir / "release_record.json").write_text(
        json.dumps({"release_tag": "v0.1.3-q1", "commit": "91ab4e6"}),
        encoding="utf-8",
    )
    (output_dir / "pass_audit_report.json").write_text(
        json.dumps({"total_pass_chapters_audited": 5, "audit_finding_rate": 0.05}),
        encoding="utf-8",
    )
    (output_dir / "ab_blind_eval_report.json").write_text(
        json.dumps({
            "total_pairs_evaluated": 10,
            "better_count": 8,
            "worse_count": 2,
            "no_difference_count": 0,
            "uncertain_count": 0,
            "net_gain": 0.6,
        }),
        encoding="utf-8",
    )

    cp_auth = _run_cli(["human-eval", novel_name, "--action", "authorize", "--json"], novels_root)
    # 因为缺少真人连续阅读实验，应当严格返回 non-zero exit code (1) 并在 JSON 中标明 long_run_not_authorized
    auth_json = json.loads(cp_auth.stdout)
    assert auth_json["verdict"] == "long_run_not_authorized"
    assert any("缺少系统外真实人类连续阅读实验数据" in p for p in auth_json["unmet_preconditions"])

    return {
        "status": "success",
        "novel": novel_name,
        "chapter_1_committed": (novel_dir / "chapters" / "chapter_1.txt").exists(),
        "chapter_2_committed": (novel_dir / "chapters" / "chapter_2.txt").exists(),
        "taste_stack_layer1_passed": (quality_json["layer1_hard_gates"]["status"] == "passed"),
        "long_run_authorization_verdict": auth_json["verdict"],
        "unmet_preconditions": auth_json["unmet_preconditions"],
    }


def run_mastery_canary_staged(workspace_dir: Path) -> dict:
    """API-level 2-chapter staged canary test."""
    workspace_dir = Path(workspace_dir).resolve()
    novel_dir = workspace_dir
    output_dir = novel_dir / "output" / "compose"
    chapters_dir = novel_dir / "chapters"

    output_dir.mkdir(parents=True, exist_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)

    # 标记 flow_version = 3
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    # 0. 初始化世界模型与已认证 AuthorModel
    world = WorldModel(
        consequence_logic=["生死逆转必付同等代价且不可逆", "禁术反噬不可逆"],
        prohibitions=["无代价直接逆转生死"],
    )
    causal_rule = CausalRule(
        rule_id="rule_cost_irreversible",
        rule_type="prohibition",
        statement="本源精血献祭后不可逆，无法通过普通丹药恢复",
        applies_to=["本源精血", "林尘"],
        cost_type="cultivation",
        reversibility="strict_irreversible",
    )
    char_mc = CharacterModel(
        character_id="c_mc",
        name="林尘",
        identity="天玄宗外门执事",
        outer_goal="调查外门灵石失窃真相",
        inner_need="摆脱棋子命运",
        fear="重蹈覆辙沦为弃子",
        flaw="多疑",
        strength="隐忍果决",
        stance="中立",
        change_trajectory=["从明哲保身到主动布局"],
        self_image="我必须掌控自己的因果",
    )
    fact_1 = FactEntry(
        fact_id="f_init_01",
        statement="外门灵库三千下品灵石在月圆之夜被盗",
        fact_type="event",
        involved_entities=["灵库", "林尘"],
        confirmed=True,
    )
    fact_ledger = FactLedger(entries=[fact_1])
    foreshadow_1 = ForeshadowEntry(
        thread_id="th_spirit_theft",
        setup_point="第一章灵库勘察",
        content="库房门锁未被破坏，系内部阵法令牌开启",
        visibility_level="explicit",
        expected_payoff="第二章大比公开揭露内门长老罪证",
        current_status="active",
    )
    foreshadow_graph = ForeshadowGraph(entries=[foreshadow_1])

    state_ch1_in = NarrativeState(
        state_id="s_ch1_in",
        current_time="天启三年春三月",
        current_location="天玄宗外门灵库",
        current_situation="灵库失窃，执法堂限期三日破案",
        active_conflicts=["限期破案与暗流阻挠"],
        current_goals=["勘察现场锁定内鬼"],
    )

    principle = AuthorPrincipleV3(
        principle_id="p_truth_over_safety",
        statement="坚持揭示残酷真相而非粉饰太平",
        value_vocab_key="courage_over_comfort",
        scope="author_global",
        confidence=0.85,
        status="stable",
    )
    author_model = AuthorModelV3(
        author_id="author_mastery",
        author_name="测试宗师",
        principles=[principle],
        known_works=["万物伏藏", "仙途诡事"],
        work_separation_audited=True,
    )
    save_author_model_v3(output_dir, author_model)
    qual_report_obj = CrossWorkValidationResult(
        author_id="author_mastery",
        holdout_work="万物伏藏",
        training_works=["仙途诡事", "剑道独尊"],
        choice_prediction_accuracy=0.88,
        baseline_accuracy=0.5,
        lexical_leakage_detected=False,
        is_valid_author_prior=True,
    )
    save_qualification_report(output_dir, qual_report_obj)

    # 1. 章节 1 编排与提交
    orch_state_init = load_committed_orchestration_state(output_dir)
    plan_ch1 = derive_orchestration_plan(orch_state_init, [state_ch1_in], chapter_number=1)

    proposals_ch1 = [
        StructuralProposal(
            proposal_id="cand_ch1_A",
            primary_actor="林尘",
            core_choice="林尘深夜排查，在阵眼残留中发现内门执法长老的私印残痕并收存物证",
            resistance_source="阵法反噬残留毒雾与暗处窥视",
            cost="暴露在暗处强敌视线中，承担九死一生风险",
            state_change="获取核心物证，由被动排查转入主动破局",
            relationship_change="与内门传功长老一脉彻底对立",
            information_reveal="灵库失窃实为高层灭口布局",
            reader_expectation_delta="期待林尘如何利用物证在大比翻盘",
            impact_next_3_to_5_chapters="引发宗门大比公审与派系斗争",
            primary_risk="引来暗杀阻挠",
        ),
        StructuralProposal(
            proposal_id="cand_ch1_B",
            primary_actor="林尘",
            core_choice="林尘顺水推舟，将嫌疑引向敌对执事以求自保",
            resistance_source="心魔反噬与道德困境",
            cost="违背内心准则，留下致命把柄",
            state_change="暂时摆脱嫌疑但沦为棋子",
            relationship_change="与同僚决裂",
            information_reveal="外门执事间互相倾轧",
            reader_expectation_delta="担忧林尘能否守住底线",
            impact_next_3_to_5_chapters="受制于人难以自主",
            primary_risk="未来把柄被曝光",
        ),
    ]

    div_report_ch1 = evaluate_structural_diversity(proposals_ch1)
    if not div_report_ch1.is_diverse:
        raise RuntimeError("Chapter 1 proposals failed diversity gate")

    search_engine = StructuralSearchEngine(rollout_steps=3)
    objects_ch1 = [world, causal_rule, char_mc, fact_ledger, foreshadow_graph]
    search_res_ch1 = search_engine.search_and_evaluate(
        proposals=proposals_ch1,
        state=state_ch1_in,
        objects=objects_ch1,
        target_chapter=1,
        author_model=author_model,
        qualification_report=qual_report_obj,
    )
    winner_ch1 = next(p for p in proposals_ch1 if p.proposal_id == search_res_ch1.selected_proposal_id)

    (output_dir / "structural_search_report.json").write_text(
        json.dumps(search_res_ch1.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "diversity_report.json").write_text(
        json.dumps(div_report_ch1.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pu_ch1 = PlotUnit(
        unit_id="pu_ch1_01",
        level="scene",
        goal=winner_ch1.core_choice,
        conflict="探查阵眼与暗处窥视",
        participants=["c_mc"],
        input_state_ref="s_ch1_in",
        output_state_ref="s_ch1_out",
        released_information=["阵眼深处藏有内门紫玉印泥残痕"],
        consequences=["林尘被暗中神识锁定"],
        scene_experience=SceneExperience(
            protagonist_sees="阵眼处的紫玉残粉",
            obstacles=["阵法反噬残留毒雾"],
            choice_grounding="退缩必成替罪羊",
            outcome="拿到核心物证",
            cognition_shift="认识到外门盗案实为高层灭口布局",
        ),
    )

    state_ch1_out = NarrativeState(
        state_id="s_ch1_out",
        current_time="天启三年春三月望日",
        current_location="天玄宗外门密室",
        current_situation="获取关键物证，危机升级",
        active_conflicts=["内门强敌暗杀威胁"],
        current_goals=["破译玉印密文寻找盟友"],
    )

    ch1_prose = (
        "第一章 残痕\n\n"
        "夜雨如注，天玄宗外门灵库的青石台阶上泛着冰冷的死光。\n"
        "林尘蹲下身子，指尖拂过阵眼凹槽处的焦黑痕迹。雨水冲刷不掉那层极淡的紫玉粉末——那是内门传功长老一脉独有的沉香玉印。\n"
        "“不是外贼，是灭口。”林尘眼中寒芒闪动，将残粉收入玉瓶。\n"
        "他深知，从这一刻起，自己已踏入九死一生的死局。"
    )

    causal_issues_ch1 = run_causal_defense([world, causal_rule, fact_ledger, pu_ch1, state_ch1_out])
    assert len(causal_issues_ch1) == 0

    reader_gate_ch1, _, _ = evaluate_commit_reader_gate(
        output_dir=output_dir,
        chapters_dir=chapters_dir,
        draft_text=ch1_prose,
        facts=fact_ledger,
        characters=[char_mc],
        chapter_ref="chapter_1",
        causal_objects=[world, causal_rule, fact_ledger, pu_ch1, state_ch1_out],
        require_campaign_evidence=False,
    )
    assert reader_gate_ch1.route == "pass"

    commit_boundary = ChapterCommitBoundary(output_dir)
    ch1_gate_dict = {
        "route": reader_gate_ch1.route,
        "issues": [i.model_dump(mode="json") for i in reader_gate_ch1.issues],
        "reasons": reader_gate_ch1.reasons,
        "axes_armed": reader_gate_ch1.axes_armed,
    }
    ch1_gate_json = json.dumps(ch1_gate_dict, ensure_ascii=False, indent=2)
    (output_dir / "reader_gate_report.json").write_text(ch1_gate_json, encoding="utf-8")

    orch_state_ch1 = commit_orchestration_transition(
        output_dir,
        plan_ch1,
        pu_ch1,
        chapter_number=1,
        run_id="compose-1",
    )

    commit_res_ch1 = commit_boundary.commit(
        run_id="compose-1",
        mode="compose",
        chapter_number=1,
        chapter_text=ch1_prose,
        state_path=output_dir / "narrative_state.json",
        state_json=json.dumps(state_ch1_out.model_dump(mode="json")),
        frames_path=output_dir / "frames.json",
        frames_json=json.dumps({"current_scene": "scene_001", "completed": []}),
        reader_gate_report_json=ch1_gate_json,
        orchestration_state_json=json.dumps(orch_state_ch1.model_dump(mode="json")),
        orchestration_history_json=(output_dir / "orchestration_history.json").read_text(encoding="utf-8"),
        review_route="pass",
    )
    assert commit_res_ch1.ok

    choice_ch1 = ChoiceRecord(
        decision_id="dec_ch1_01",
        decision_timestamp="2026-08-17T00:00:00Z",
        plot_context="第一章灵库勘察排查内鬼",
        state_ref="s_ch1_in",
        character_refs=["c_mc"],
        chapter_number=1,
        candidates=[
            CandidateRecord(
                candidate_id="cand_ch1_A",
                summary="追查阵眼紫玉残印物证",
                plotunit=pu_ch1.model_dump(mode="json"),
                new_state_ref="s_ch1_out",
            ),
            CandidateRecord(
                candidate_id="cand_ch1_B",
                summary="自保脱罪嫁祸他人",
                plotunit=pu_ch1.model_dump(mode="json"),
                new_state_ref="s_ch1_out",
            ),
        ],
        selected_candidate=winner_ch1.proposal_id,
        rejected=[
            RejectedRecord(candidate_id="cand_ch1_B", reason="违背探求真相准则"),
        ],
        tradeoff="放弃短期自保便利，换取查清真相的因果主动权",
        value_conflicts=["courage_over_comfort"],
        consequence="成功锁定内门沉香玉印残粉物证",
        hindsight="still_supported",
        hindsight_note="在后续大比揭露中起决定性作用",
    )
    (output_dir / "choice_records.json").write_text(
        json.dumps([choice_ch1.model_dump(mode="json")], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2. 章节 2 编排与提交
    update_author_model_from_hindsight(
        author_model,
        [choice_ch1],
        work_name="万物伏藏",
    )
    save_author_model_v3(output_dir, author_model)

    plan_ch2 = derive_orchestration_plan(orch_state_ch1, [state_ch1_out], chapter_number=2)

    proposals_ch2 = [
        StructuralProposal(
            proposal_id="cand_ch2_A",
            primary_actor="林尘",
            core_choice="林尘借外门大比之机，当众揭露内门账目疑点与玉印物证，迫使暗处敌人现身",
            resistance_source="传功长老当场威压震慑",
            cost="彻底断绝宗门内部回旋余地",
            state_change="化暗为明，迫使高层立案公审",
            relationship_change="与传功堂彻底决裂，引得宗门中立派关注",
            information_reveal="公开沉香玉印与监守自盗真相",
            reader_expectation_delta="期待公审决战与长老伏诛",
            impact_next_3_to_5_chapters="引发内门大震荡与宗主出面",
            primary_risk="长老当场杀人灭口",
        ),
        StructuralProposal(
            proposal_id="cand_ch2_B",
            primary_actor="林尘",
            core_choice="林尘暗中联络内门敌对派系进行交易，出卖外门利益换取庇护",
            resistance_source="尊严践踏与利益博弈",
            cost="出卖外门同门，沦为新派系走狗",
            state_change="获得暂时庇护但失去自主权",
            relationship_change="成为内门附庸",
            information_reveal="内门各峰之间的残酷竞争",
            reader_expectation_delta="对林尘妥协感到压抑",
            impact_next_3_to_5_chapters="被新派系当成炮灰驱使",
            primary_risk="狡兔死走狗烹",
        ),
    ]

    div_report_ch2 = evaluate_structural_diversity(proposals_ch2)
    assert div_report_ch2.is_diverse

    fact_2 = FactEntry(
        fact_id="f_ch1_res",
        statement="林尘持有内门沉香玉印残粉物证",
        fact_type="event",
        involved_entities=["林尘", "玉印"],
        confirmed=True,
    )
    fact_ledger.entries.append(fact_2)

    search_engine_ch2 = StructuralSearchEngine(rollout_steps=3)
    objects_ch2 = [world, causal_rule, char_mc, fact_ledger, foreshadow_graph]
    search_res_ch2 = search_engine_ch2.search_and_evaluate(
        proposals=proposals_ch2,
        state=state_ch1_out,
        objects=objects_ch2,
        target_chapter=2,
        author_model=author_model,
        qualification_report=qual_report_obj,
    )
    winner_ch2 = next(p for p in proposals_ch2 if p.proposal_id == search_res_ch2.selected_proposal_id)

    pu_ch2 = PlotUnit(
        unit_id="pu_ch2_01",
        level="scene",
        goal=winner_ch2.core_choice,
        conflict="大比公开施压与执法堂对峙",
        participants=["c_mc"],
        input_state_ref="s_ch1_out",
        output_state_ref="s_ch2_out",
        released_information=["林尘在大比之上亮出玉印残痕物证"],
        consequences=["全宗哗然，高层被迫立案公审"],
        scene_experience=SceneExperience(
            protagonist_sees="高台之上长老骤变的脸色",
            obstacles=["大能威压震慑"],
            choice_grounding="唯有掀翻棋盘方能求生",
            outcome="迫使执法堂介入公开对质",
            cognition_shift="领悟权力斗争的虚妄与实力的绝对本质",
        ),
    )

    state_ch2_out = NarrativeState(
        state_id="s_ch2_out",
        current_time="天启三年春三月廿日",
        current_location="天玄宗演武大殿",
        current_situation="当众亮证引发全宗震动，公审在即",
        active_conflicts=["公审对决与刺杀防范"],
        current_goals=["在公审中彻底定案翻盘"],
    )

    ch2_prose = (
        "第二章 掀盘\n\n"
        "外门大比的钟声响彻天玄山脉，万千弟子瞩目之下，林尘缓步走上演武台中央。\n"
        "他没有拔剑，而是反手将一只青玉药瓶拍碎在测灵石上。紫色的沉香玉粉在灵力激荡下爆发出耀眼的灵光，显化出传功堂长老的本命云纹印记。\n"
        "“灵库三千灵石，非外贼所窃，乃本门高层监守自盗！”林尘的声音借阵法回荡全山，引得满场哗然。\n"
        "看台之上，传功长老霍然起身，杀机四溢。"
    )

    causal_issues_ch2 = run_causal_defense([world, causal_rule, fact_ledger, pu_ch2, state_ch2_out])
    assert len(causal_issues_ch2) == 0

    reader_gate_ch2, _, _ = evaluate_commit_reader_gate(
        output_dir=output_dir,
        chapters_dir=chapters_dir,
        draft_text=ch2_prose,
        facts=fact_ledger,
        characters=[char_mc],
        chapter_ref="chapter_2",
        causal_objects=[world, causal_rule, fact_ledger, pu_ch2, state_ch2_out],
        require_campaign_evidence=False,
    )
    assert reader_gate_ch2.route == "pass"

    ch2_gate_dict = {
        "route": reader_gate_ch2.route,
        "issues": [i.model_dump(mode="json") for i in reader_gate_ch2.issues],
        "reasons": reader_gate_ch2.reasons,
        "axes_armed": reader_gate_ch2.axes_armed,
    }
    ch2_gate_json = json.dumps(ch2_gate_dict, ensure_ascii=False, indent=2)
    (output_dir / "reader_gate_report.json").write_text(ch2_gate_json, encoding="utf-8")

    orch_state_ch2 = commit_orchestration_transition(
        output_dir,
        plan_ch2,
        pu_ch2,
        chapter_number=2,
        run_id="compose-2",
    )

    commit_res_ch2 = commit_boundary.commit(
        run_id="compose-2",
        mode="compose",
        chapter_number=2,
        chapter_text=ch2_prose,
        state_path=output_dir / "narrative_state.json",
        state_json=json.dumps(state_ch2_out.model_dump(mode="json")),
        frames_path=output_dir / "frames.json",
        frames_json=json.dumps({"current_scene": "scene_002", "completed": ["scene_001"]}),
        reader_gate_report_json=ch2_gate_json,
        prev_chapter_ref="chapter_1",
        orchestration_state_json=json.dumps(orch_state_ch2.model_dump(mode="json")),
        orchestration_history_json=(output_dir / "orchestration_history.json").read_text(encoding="utf-8"),
        review_route="pass",
    )
    assert commit_res_ch2.ok

    # 3. Taste Stack 密码学证据链审计
    taste_report = build_unified_quality_report(
        novel_name="canary_2ch",
        output_dir=output_dir,
        strict_evidence=True,
    )
    assert taste_report.layer1_hard_gates.status == "passed"
    assert taste_report.layer1_hard_gates.blocking_issues_count == 0

    # 4. 长程生产授权裁决
    (novel_dir / "provider_profiles.json").write_text(
        json.dumps({"active_provider": "deepseek-v4-flash", "budget_ceiling": 50.0}),
        encoding="utf-8",
    )
    (novel_dir / "release_record.json").write_text(
        json.dumps({"release_tag": "v0.1.3-q1", "commit": "91ab4e6"}),
        encoding="utf-8",
    )
    (output_dir / "pass_audit_report.json").write_text(
        json.dumps({"total_pass_chapters_audited": 5, "audit_finding_rate": 0.05}),
        encoding="utf-8",
    )
    (output_dir / "ab_blind_eval_report.json").write_text(
        json.dumps({
            "total_pairs_evaluated": 10,
            "better_count": 8,
            "worse_count": 2,
            "no_difference_count": 0,
            "uncertain_count": 0,
            "net_gain": 0.6,
        }),
        encoding="utf-8",
    )

    preconditions = inspect_long_horizon_preconditions(novel_dir)
    auth_verdict = evaluate_long_horizon_authorization(preconditions)

    assert auth_verdict.verdict == "long_run_not_authorized"
    assert any("缺少系统外真实人类连续阅读实验数据" in p for p in auth_verdict.unmet_preconditions)

    summary = {
        "status": "success",
        "novel": "canary_2ch",
        "chapter_1_committed": (chapters_dir / "chapter_1.txt").exists(),
        "chapter_2_committed": (chapters_dir / "chapter_2.txt").exists(),
        "taste_stack_layer1_passed": (taste_report.layer1_hard_gates.status == "passed"),
        "long_run_authorization_verdict": auth_verdict.verdict,
        "unmet_preconditions": auth_verdict.unmet_preconditions,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 2-Chapter Staged CLI Canary Regression")
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=REPO_ROOT / "novels" / "canary_staged_2ch",
        help="Workspace directory for staged canary",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean workspace before running",
    )
    parser.add_argument(
        "--use-cli",
        action="store_true",
        help="Use real subprocess novel CLI pipeline",
    )
    args = parser.parse_args()

    w_dir = args.workspace_dir
    if not args.no_clean and w_dir.exists():
        shutil.rmtree(w_dir)
    w_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Canary] Starting 2-chapter staged canary in: {w_dir}")
    try:
        if args.use_cli:
            summary = run_mastery_canary_subprocess(w_dir.parent, novel_name=w_dir.name)
        else:
            summary = run_mastery_canary_staged(w_dir)
        print("[Canary] Execution successful!")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"[Canary] Execution failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
