#!/usr/bin/env python3
"""compose_short_form — 第三个有界实现切片入口.

用法:
    python src/compose_short_form.py <workspec_json_file>
    # 或交互式：python src/compose_short_form.py
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.handoff import HandoffBoundaryUnit
from src.boundary_control.runtime_identity import model_content_hash, validate_run_hash
from src.boundary_control.runtime_state import require_continue_runtime_state
from src.boundary_control.response_file import reset_consumed_responses
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
from src.boundary_control.chapter_commit import (
    ChapterCommitBoundary,
    derive_run_id,
    read_flow_version,
    set_run_status,
)
from src.boundary_control.reader_gate import (
    evaluate_commit_reader_gate,
    write_reader_gate_report,
)
from src.object_state.run_manifest import sha256_text
from src.domain_layer.compliance_rules import build_nsfw_context
from src.domain_layer.rules import get_structure_template
from src.domain_layer.web_fiction import EMOTIONAL_ARC_TEMPLATES, GENRE_RULES
from src.object_state import (
    CharacterModel,
    FactLedger,
    ForeshadowGraph,
    NarrativeState,
    WorkSpec,
    WorldModel,
)
from src.workflow_action.continuation import ContinueUnit, admit_new_facts
from src.workflow_action.character_updates import (
    admit_character_updates,
    append_character_updates,
    build_character_update_prompt,
    parse_character_updates_response,
)
from src.workflow_action.author_selection import (
    JudgeWaiting,
    build_author_judge,
    build_author_prompt_context,
    load_style_profile,
    resolve_kernel,
    run_author_selection,
)
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.proposal_generator import (
    build_proposal_prompt,
    parse_proposals_response,
)
from src.workflow_action.review import ReviewUnit
from src.workflow_action.rewrite import RewriteUnit
from src.domain_layer.style_rules import build_temperament_guidance
from src.workflow_action.style import load_style_context
from src.workflow_action.retrieval import load_retrieval_context
from src.workflow_action.timebook import build_time_context, load_time_book, save_time_book
from src.workflow_action.continuation_viability import (
    ContinuationViabilityUnit,
    analyze_continuation_viability,
    viability_continue_note,
)
from src.workflow_action.reader_contract import (
    load_reader_contract,
    scene_experience_guard_review_issues,
)
from src.workflow_action import prose as prose_action
from src.object_state.timebook import TimeBook, TimeInitial


def _validate_no_regression(package) -> bool:
    violations = NoRegressionValidationUnit().run(package)
    if not violations:
        return True
    print("No-regression validation failed:")
    for violation in violations:
        print(f"  - {violation}")
    return False


def _read_response_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


HELP_TEXT = """Usage:
  python src/compose_short_form.py [workspec_json_file] [--resume]

Compose 流（从 WorkSpec 创作）——时序为 先成文、后审查（42 设计 F3b）：
  1. 无参数时使用默认 WorkSpec；有参数时读取指定 WorkSpec JSON。
  2. 运行脚本，生成 output/compose_continue_prompt.txt 后退出。
  3. Codex 生成 JSON 响应，保存到 output/compose_continue_response.txt。
  4. 重跑脚本，Pre-Review（代码闸，无 LLM）。若结构阻断，生成
     output/compose_pre_rewrite_prompt.txt 后退出 → 保存响应 → 重跑。
  5. 生成 output/prose_prompt.txt 后退出。
  6. Codex 生成纯文本章节正文，保存到 output/prose_response.txt。
  7. 重跑脚本，正文落盘 chapters/chapter_<N>.txt，生成 output/compose_review_prompt.txt
     （已注入【本章正文】）后退出。
  8. Codex 生成 JSON 响应，保存到 output/compose_review_response.txt。
  9. 重跑脚本，若 route=rewrite：正文层修订生成 output/prose_revise_prompt.txt
     后退出 → 保存修订正文到 output/prose_revise_response.txt → 重跑；
     （--no-prose 时走对象层 compose_rewrite_prompt.txt）。
  10. 生成 output/compose_rereview_prompt.txt 后退出 → 保存响应 → 重跑。
  11. 输出最终结果。
  （--no-prose 跳过正文落盘，Review 不注入正文，保持纯结构产物。）

Resume 模式：
  1. 从 output/compose_state.json 加载上次保存的对象状态。
  2. 从 output/compose_frames.json 加载 frame cursor 状态。
  3. 跳过 Initialize，直接进入 Continue。
"""


def initialize_from_workspec(workspec: WorkSpec) -> list:
    """从 WorkSpec 初始化 stub 对象 (compose 模式 Rebuild)."""
    objects = [workspec]

    genre_rules = GENRE_RULES.get(workspec.genre, [])

    world = WorldModel(
        world_facts=[],
        power_system=f"{workspec.genre}基础力量体系（待具体化）",
        social_structure=f"{workspec.genre}典型社会结构（待具体化）",
        factions=[],
        time_rules=[],
        prohibitions=[
            f"{workspec.genre}通用禁律：力量使用需有代价"
        ]
        if genre_rules
        else [],
        consequence_logic=genre_rules[:2] if genre_rules else [],
    )
    objects.append(world)

    theme_goal_map = {
        "成长": "突破自身限制",
        "复仇": "向仇人讨还代价",
        "真相": "揭开隐藏的真相",
        "救赎": "弥补过去的错误",
        "归属": "找到属于自己的位置",
    }
    theme_need_map = {
        "成长": "被认可",
        "复仇": "公正",
        "真相": "安心",
        "救赎": "自我原谅",
        "归属": "被接纳",
    }

    outer_goal = theme_goal_map.get(workspec.theme, f"围绕{workspec.theme}展开行动")
    inner_need = theme_need_map.get(workspec.theme, "待探索的内在需求")

    char = CharacterModel(
        character_id="c001",
        name="主角",
        identity=f"{workspec.genre}世界中追求{workspec.theme}的核心人物",
        outer_goal=outer_goal,
        inner_need=inner_need,
        fear="失去所追求之物",
        flaw=f"与{workspec.theme}相关的盲点和执念",
        strength=f"与{workspec.theme}相关的韧性和执着",
        stance="被动卷入，逐渐主动",
    )
    objects.append(char)

    tone_temperature_map = {
        "克制": "压抑",
        "热血": "激昂",
        "暗黑": "沉重",
        "轻松": "平稳",
    }
    theme_arc_map = {
        "成长": "catharsis_arc",
        "复仇": "comeback_arc",
        "真相": "revelation_arc",
        "救赎": "sacrifice_arc",
        "归属": "loss_arc",
    }
    arc_name = theme_arc_map.get(workspec.theme)
    arc_nodes = EMOTIONAL_ARC_TEMPLATES.get(arc_name, []) if arc_name else []
    arc_initial_emotion = arc_nodes[0]["emotion"] if arc_nodes else None

    state = NarrativeState(
        state_id="ns_initial",
        current_time="故事起始",
        current_location=f"{workspec.genre}典型起点场景",
        current_situation="日常被打破的前夕",
        active_characters=["c001"],
        primary_goal=outer_goal,
        emotional_temperature=tone_temperature_map.get(workspec.tone, arc_initial_emotion),
    )
    objects.append(state)

    # empty FactLedger + ForeshadowGraph
    objects.append(FactLedger())
    objects.append(ForeshadowGraph())

    return objects


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法解码文件: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compose 流（从 WorkSpec 创作）",
        epilog=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("workspec_file", nargs="?", help="WorkSpec JSON 文件（可选）")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从上次保存的状态继续（跳过 Initialize，加载已有对象和 frame 状态）",
    )
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--style",
        default="",
        help="引用风格库中的已有档案 <name>（style_library/<name>.json），注入续写 prompt",
    )
    parser.add_argument(
        "--temperament",
        default="",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；CLI 优先，缺省回落到 workspec.temperament。无风格档案时注入气质桶指导",
    )
    parser.add_argument(
        "--retrieval",
        default="on",
        choices=["on", "off"],
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
    )
    parser.add_argument(
        "--nsfw",
        default="off",
        choices=["on", "off"],
        help="成人向（NSFW）开关（默认 off 正常向：注入禁成人内容分级；on：允许成人向内容）",
    )
    parser.add_argument(
        "--character-update",
        default="off",
        choices=["on", "off"],
        help="角色变更提案开关（默认 off 零成本；on：Continue 后新增角色更新阶段，"
        "产物落 output/character_updates.json 并 apply 到角色动态字段）",
    )
    parser.add_argument(
        "--proposals",
        type=int,
        default=1,
        metavar="N",
        help="Continue 多候选生成数（默认 1 零成本：单 PlotUnit 与原路径 prompt 字节一致；"
        "N>=2 启用多候选选择链：Proposal → Consistency Gate → 多视角评估 → 选择 → "
        "ChoiceLedger 留痕）",
    )
    parser.add_argument(
        "--author-mode",
        default="off",
        choices=["on", "off"],
        help="生产选择是否作者感知（默认 off：基线字典序 style→reader；on=Canary 6D，"
        "用 AuthorKernel 做生产选择）",
    )
    parser.add_argument(
        "--kernel",
        default="",
        metavar="PATH",
        help="AuthorKernel JSON 路径（默认读 <output_dir>/author_kernel.json；无则 kernel 未形成）",
    )
    parser.add_argument(
        "--shadow",
        default="off",
        choices=["on", "off"],
        help="影子选择开关（默认 off；on=6C：生产照常出结果，作者感知影子结果 B 不进正文，"
        "分叉记入 output/shadow/shadow_ledger.json）",
    )
    parser.add_argument(
        "--drift-review",
        default="off",
        choices=["on", "off"],
        help="作者漂移审查开关（默认 off；on=6E：选择后审查选中文本是否无因果漂移，"
        "active_break 记入 output/drift_review/challenge_ledger.json）",
    )
    parser.add_argument(
        "--author-judge",
        default="off",
        choices=["on", "off"],
        help="语义作者判断者开关（默认 off：关键词代理；on=Kernel→Selection 因果集成："
        "kernel 已形成时对每个候选做逐原则语义判定，缺响应 [WAITING] 填 author_judge/response.json）",
    )
    parser.add_argument(
        "--consolidation-min",
        type=int,
        default=None,
        metavar="N",
        help="AuthorKernel 归纳最少 ChoiceRecord 数（默认 5；实验可调低以观察 kernel "
        "在短程内形成并影响后续选择）",
    )
    parser.add_argument(
        "--consolidation-min-support",
        type=int,
        default=None,
        metavar="N",
        help="原则形成最少支持证据数（默认 2；短程实验可调为 1）",
    )
    parser.add_argument(
        "--consolidation-contested-ratio",
        type=float,
        default=None,
        metavar="R",
        help="反例占比达到即 contested（默认 0.5；短程实验可调高避免过早 contested）",
    )
    parser.add_argument(
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构；默认自动成文落盘 chapters/）",
    )
    args = parser.parse_args()

    resume_mode = args.resume

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_state_path = output_dir / "compose_state.json"
    frames_path = output_dir / "compose_frames.json"
    workspec_hash_path = output_dir / ".workspec_hash"

    serializer = SerializationBoundaryUnit()
    frame_unit = NarrativeFrameUnit()
    cont = ContinueUnit()
    review = ReviewUnit()

    # Step 1: Initialize or Resume
    print("\n" + "=" * 50)
    print("Step 1: Initialize from WorkSpec" if not resume_mode else "Step 1: Resume from saved state")
    print("=" * 50)

    objects: list = []
    frames: list = []

    if resume_mode and not compose_state_path.exists():
        print(f"Error: --resume requires saved state file: {compose_state_path}")
        return 1

    if resume_mode and not frames_path.exists():
        print(f"Error: --resume requires saved frame file: {frames_path}")
        return 1

    if resume_mode:
        # Resume 模式：从保存的包加载对象
        print(f"Resume mode: loading from {compose_state_path}")
        package = serializer.load(compose_state_path)
        if not _validate_no_regression(package):
            return 1
        objects = serializer.deserialize_package(package)
        print(f"Loaded {len(objects)} objects")

        frames = json.loads(frames_path.read_text(encoding="utf-8"))
        print(f"Loaded frame state from {frames_path}")

    if not objects:
        # 原有 Initialize 流程
        if args.workspec_file:
            workspec_path = Path(args.workspec_file)
            if workspec_path.exists():
                workspec = WorkSpec.model_validate_json(_read_text(workspec_path))
            else:
                print(f"Error: WorkSpec file not found: {workspec_path}")
                return 1
        else:
            workspec = WorkSpec(
                genre="仙侠",
                audience="青年",
                theme="成长",
                tone="克制",
                pacing="前快中稳后爆",
            )
            print("Using default WorkSpec (no file provided)")

        print(f"\nWorkSpec loaded: {workspec.genre} / {workspec.theme}")
        hash_errors = validate_run_hash(
            hash_path=workspec_hash_path,
            current_hash=model_content_hash(workspec),
            output_dir=output_dir,
            label="WorkSpec",
        )
        if hash_errors:
            for error in hash_errors:
                print(error)
            return 1
        objects = initialize_from_workspec(workspec)
        print(f"Initialized {len(objects)} stub objects")

    try:
        (
            workspec,
            _worldmodel,
            narrative_state,
            characters,
            facts,
            foreshadows,
        ) = require_continue_runtime_state(objects)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    # ---- 迁移检测（42 设计 §7）：新版时序 = Continue → Pre-Review → Prose → Review ----
    # 旧版（Review 在成文前）工作区若停在「Review 后、Prose 前」，残留
    # compose_review_response.txt 且缺 prose_response.txt → fail-fast 提示迁移。
    # 放在 hash 校验之后：不干扰首次运行的「空目录」判定。
    flow_version_path = output_dir / ".flow_version"
    if not flow_version_path.exists():
        flow_version_path.write_text("2", encoding="utf-8")
    # flow v3（事务式提交与版本化运行）：仅经 `novel migrate --to-flow 3` 显式启用；
    # 默认 v2 语义不变（零成本契约：不产生 manifest、prompt/落盘字节不变）。
    flow_version = read_flow_version(output_dir)
    if (
        not args.no_prose
        and (output_dir / "compose_review_response.txt").exists()
        and not (output_dir / "prose_response.txt").exists()
    ):
        print(
            "Error: 检测到旧版流程（Review 在成文前）残留的 compose_review_response.txt，"
            "且缺少 prose_response.txt——新版时序为先成文后审查。"
        )
        print("请将 compose_review_response.txt 移走/删除后重跑，流程将按新时序继续。")
        return 1

    # 时间域：workspec.time 可选字段 → 初始化 TimeBook 初稿（无该字段 / 已有 TimeBook 时零成本）
    if workspec.time is not None and load_time_book(output_dir) is None:
        tb = TimeBook(initial=workspec.time)
        save_time_book(output_dir, tb)
        init_bits = " ".join(
            b for b in (workspec.time.date, workspec.time.lunar, workspec.time.loc) if b
        )
        print(f"TimeBook initialized from workspec.time: {init_bits or '(empty initial)'}")

    # Step 2: Continue
    print("\n" + "=" * 50)
    print("Step 2: Continue (first PlotUnit)")
    print("=" * 50)

    structure_template_name = workspec.structure_template or "eight_node"
    if not frames:
        frames = frame_unit.build_frame(
            workspec_context=workspec.to_prompt_context(),
            structure_template=get_structure_template(structure_template_name),
        )
    try:
        frames = frame_unit.require_valid_frame_state(frames)
        frame_cursor = frame_unit.get_cursor(frames)
        frame_context = frame_unit.build_continue_context(frames, frame_cursor)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    # ---- Q1 R1: 续写可行性门禁（flow v3；v2 字节不变，零成本）----
    # 首章必然有活跃帧（fresh 默认 continue）；续写章在结构闭合 / 承诺未兑现 /
    # 契约结束条件触发时，由确定性信号判 continue / stop / needs_premise，
    # 信号冲突时写 staged prompt 交操作者确认。stop / needs_premise 时跳过 Continue。
    reader_contract = load_reader_contract(output_dir) if flow_version == "3" else None
    viability_note = ""
    if flow_version == "3":
        viability_analysis = analyze_continuation_viability(
            narrative_state=narrative_state,
            foreshadows=foreshadows,
            frame_context=frame_context,
            workspec=workspec,
            contract=reader_contract,
        )
        (output_dir / "viability_analysis.json").write_text(
            json.dumps(viability_analysis.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        viability_prompt_path = output_dir / "viability_prompt.txt"
        viability_response_path = output_dir / "viability_response.txt"
        if viability_analysis.deterministic:
            viability_decision = viability_analysis
        elif not viability_response_path.exists():
            viability_prompt_path.write_text(
                ContinuationViabilityUnit().build_prompt(
                    viability_analysis,
                    workspec_context=workspec.to_prompt_context(),
                    excerpt_context="",
                    contract_context=(
                        reader_contract.to_prompt_context() if reader_contract else ""
                    ),
                ),
                encoding="utf-8",
            )
            print("\n[STEP: VIABILITY] 续写可行性信号冲突——需操作者确认")
            print(f"[WAITING] Generate response to: {viability_response_path}")
            print("[RESUME] Re-run this script after saving response")
            return 0
        else:
            viability_decision = ContinuationViabilityUnit().parse_response(
                _read_response_text(viability_response_path)
            )
        if viability_decision.verdict in ("stop", "needs_premise"):
            (output_dir / "viability_report.json").write_text(
                json.dumps(viability_decision.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            label = "故事已闭合" if viability_decision.verdict == "stop" else "需要新前提/新结构"
            print(f"\nContinuationViability: {viability_decision.verdict}（{label}）——不生成下一章")
            for reason in viability_decision.reasons:
                print(f"  - {reason}")
            if viability_decision.required_premise:
                print(f"  required_premise: {viability_decision.required_premise}")
            print(f"  report: {output_dir / 'viability_report.json'}")
            return 0
        if viability_decision.verdict == "continue":
            viability_note = viability_continue_note(viability_decision)

    proposals_n = max(1, args.proposals)
    multi_proposals = proposals_n >= 2
    continue_prompt_path = output_dir / "compose_continue_prompt.txt"
    continue_response_path = output_dir / "compose_continue_response.txt"
    proposals_prompt_path = output_dir / "proposals_prompt.txt"
    proposals_response_path = output_dir / "proposals_response.txt"
    if not multi_proposals and continue_response_path.exists():
        response = _read_response_text(continue_response_path)
        plotunit, new_state, new_facts, gaps = cont.parse_response(response)
        try:
            new_facts = admit_new_facts(facts, new_facts, plotunit.unit_id)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    elif multi_proposals and proposals_response_path.exists():
        print(f"Multi-proposal Continue (--proposals {proposals_n})")
        response = _read_response_text(proposals_response_path)
        packages = parse_proposals_response(response, proposals_n)
        kernel = resolve_kernel(output_dir, args.kernel)
        style_profile = load_style_profile(output_dir, args.style or "")
        try:
            author_judge = build_author_judge(
                packages, output_dir, kernel, enabled=args.author_judge == "on"
            )
        except JudgeWaiting as exc:
            print(f"[WAITING] 作者语义判断响应缺失：{exc}")
            return 0
        next_chapter = prose_action.next_chapter_number(
            output_dir.parent.parent / "chapters"
        )
        selection = run_author_selection(
            packages,
            objects,
            output_dir=output_dir,
            decision_context=narrative_state.current_situation or "Compose 续写决策",
            state_ref=narrative_state.state_id,
            current_state_ref=narrative_state.state_id,
            kernel=kernel,
            style_profile=style_profile,
            style_profile_id=args.style or None,
            author_mode_on=args.author_mode == "on",
            shadow_on=args.shadow == "on",
            drift_review_on=args.drift_review == "on",
            review=review,
            chapter_number=next_chapter,
            consolidation_min=args.consolidation_min,
            consolidation_min_support=args.consolidation_min_support,
            consolidation_contested_ratio=args.consolidation_contested_ratio,
            author_judge=author_judge,
            contract=reader_contract,
        )
        selected_package = selection["selected"]
        plotunit = selected_package["plotunit"]
        new_state = selected_package["new_state"]
        try:
            new_facts = admit_new_facts(
                facts, selected_package["new_facts"], plotunit.unit_id
            )
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
        gaps = selected_package["confidence_gaps"]
    else:
        retrieval_context = ""
        if args.retrieval == "on":
            retrieval_context = load_retrieval_context(
                output_dir,
                state=narrative_state,
                facts=facts,
                foreshadows=foreshadows,
            )
        # 风格注入：风格档案 > 气质桶指导（无档案且指定气质时）。
        # 气质桶是通用分类（散文/戏剧/信息/氛围），CLI --temperament 优先，
        # 缺省回落到 workspec.temperament。workspec 无该字段（旧 JSON）时默认为空。
        style_context = load_style_context(output_dir, style_name=args.style or None)
        if not style_context:
            temperament = args.temperament or (workspec.temperament or "")
            if temperament:
                style_context = build_temperament_guidance(temperament)
        if multi_proposals:
            author_context = build_author_prompt_context(
                output_dir,
                decision_context=narrative_state.current_situation or "Compose 续写决策",
                kernel_path=args.kernel,
            )
            proposals_prompt_path.write_text(
                build_proposal_prompt(
                    cont,
                    proposals_n,
                    narrative_state,
                    characters,
                    facts,
                    foreshadows,
                    workspec_context=workspec.to_prompt_context(),
                    frame_context=frame_context,
                    structure_template=structure_template_name,
                    platform=workspec.platform,
                    genre=workspec.genre,
                    style_context=style_context,
                    retrieval_context=retrieval_context,
                    timeline_context=facts.to_timeline_context(include_header=False),
                    time_context=build_time_context(load_time_book(output_dir)),
                    nsfw_context=build_nsfw_context(
                        args.nsfw == "on",
                        genre=workspec.genre,
                        theme=workspec.theme,
                        subgenre=workspec.subgenre,
                    ),
                    author_context=author_context,
                    contract_context=(
                        reader_contract.to_prompt_context() if reader_contract else ""
                    ),
                    viability_note=viability_note,
                ),
                encoding="utf-8",
            )
            print(f"[STEP: PROPOSALS] Prompt saved: {proposals_prompt_path}")
            print(f"[WAITING] Generate response to: {proposals_response_path}")
        else:
            continue_prompt_path.write_text(
                cont.build_prompt(
                    state=narrative_state,
                    characters=characters,
                    facts=facts,
                    foreshadows=foreshadows,
                    workspec_context=workspec.to_prompt_context(),
                    frame_context=frame_context,
                    structure_template=structure_template_name,
                    platform=workspec.platform,
                    genre=workspec.genre,
                    style_context=style_context,
                    retrieval_context=retrieval_context,
                    timeline_context=facts.to_timeline_context(include_header=False),
                    time_context=build_time_context(load_time_book(output_dir)),
                    nsfw_context=build_nsfw_context(
                        args.nsfw == "on",
                        genre=workspec.genre,
                        theme=workspec.theme,
                        subgenre=workspec.subgenre,
                    ),
                    contract_context=(
                        reader_contract.to_prompt_context() if reader_contract else ""
                    ),
                    viability_note=viability_note,
                ),
                encoding="utf-8",
            )
            print(f"[STEP: CONTINUE] Prompt saved: {continue_prompt_path}")
            print(f"[WAITING] Generate response to: {continue_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Generated PlotUnit: {plotunit.unit_id}")
    print(f"Goal: {plotunit.goal}")
    print(f"New facts: {len(new_facts)}")

    # Step 2.5: Character Update（可选，--character-update on；默认 off 零成本）
    character_updates: list[dict] = []
    if args.character_update == "on":
        print("\n" + "=" * 50)
        print("Step 2.5: Character Update")
        print("=" * 50)
        cu_prompt_path = output_dir / "character_update_prompt.txt"
        cu_response_path = output_dir / "character_update_response.txt"
        if cu_response_path.exists():
            response = _read_response_text(cu_response_path)
            updates = parse_character_updates_response(response)
            try:
                character_updates = admit_character_updates(
                    characters, updates, plotunit.unit_id, apply=True
                )
            except ValueError as exc:
                print(f"Error: {exc}")
                return 1
            append_character_updates(output_dir, character_updates)
        else:
            cu_prompt_path.write_text(
                build_character_update_prompt(characters, plotunit, new_state),
                encoding="utf-8",
            )
            print(f"[STEP: CHARACTER UPDATE] Prompt saved: {cu_prompt_path}")
            print(f"[WAITING] Generate response to: {cu_response_path}")
            print("[RESUME] Re-run this script after saving response")
            return 0
        print(f"Generated CharacterUpdates: {len(character_updates)}")

    # Step 3: Pre-Review（代码闸，零 LLM 成本）——结构硬错误在成文前拦截
    print("\n" + "=" * 50)
    print("Step 3: Pre-Review (code gate)")
    print("=" * 50)
    review_objects = objects + [plotunit, new_state]
    pre_rewrite_prompt_path = output_dir / "compose_pre_rewrite_prompt.txt"
    pre_rewrite_response_path = output_dir / "compose_pre_rewrite_response.txt"

    def _run_code_rules() -> tuple[list, list]:
        merged = review._hard_rules(review_objects) + review._domain_rules(review_objects)
        # v3 强制（Q1 R3）：产生主动选择的关键单元必须携带 SceneExperience
        # （选择依据/可见后果），否则在成文前进入对象层 rewrite。
        if flow_version == "3":
            merged = merged + scene_experience_guard_review_issues(plotunit)
        return merged, [i for i in merged if i.is_blocking()]

    code_issues, pre_blocking = _run_code_rules()
    pre_review_result = {
        "schema_version": 1,
        "code_issues": [i.model_dump(mode="json") for i in code_issues],
        "blocking": [i.model_dump(mode="json") for i in pre_blocking],
    }
    (output_dir / "pre_review_result.json").write_text(
        json.dumps(pre_review_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if pre_blocking:
        print(f"Pre-Review blocked: {len(pre_blocking)} structural blocking issue(s) "
              f"-> object-layer rewrite")
        rewrite = RewriteUnit()
        if not pre_rewrite_response_path.exists():
            pre_rewrite_prompt_path.write_text(
                rewrite.build_prompt(pre_blocking, review_objects, context="compose-preview"),
                encoding="utf-8",
            )
            print(f"\n[STEP: PRE-REWRITE] Prompt saved: {pre_rewrite_prompt_path}")
            print(f"[WAITING] Generate response to: {pre_rewrite_response_path}")
            print("[RESUME] Re-run this script after saving response")
            return 0
        response = _read_response_text(pre_rewrite_response_path)
        fixes = rewrite.parse_response(response)
        try:
            applied = rewrite.apply_required_fixes(review_objects, fixes)
        except ValueError as exc:
            print(f"Rewrite failed: {exc}")
            return 1
        for fix in fixes:
            print(f"  Applied: {fix.get('target_type')}.{fix.get('field')} -> {fix.get('action')}")
        print(f"\nPre-rewrite applied: {applied}/{len(fixes)}")
        code_issues, pre_blocking = _run_code_rules()
        if pre_blocking:
            print(f"Pre-Review still blocked after object rewrite: "
                  f"{len(pre_blocking)} blocking issue(s)")
            return 1
        print("Pre-Review clear after object rewrite")
    else:
        print(f"Pre-Review clear (code issues: {len(code_issues)}, none blocking)")

    # Step 4: Prose → 草稿（Draft，不进 chapters/）。Draft/Commit 边界：PASS 前正文
    # 只是 staged draft，下游不消费未提交稿；PASS 后才提交为正式 chapter。
    draft_text: str | None = None
    if not args.no_prose:
        print("\n" + "=" * 50)
        print("Step 4: Prose (draft)")
        print("=" * 50)
        prose_prompt_path = output_dir / "prose_prompt.txt"
        prose_response_path = output_dir / "prose_response.txt"
        if not prose_response_path.exists():
            style_context = load_style_context(
                output_dir, style_name=args.style or None
            )
            if not style_context:
                temperament = args.temperament or (workspec.temperament or "")
                if temperament:
                    style_context = build_temperament_guidance(temperament)
            prose_prompt_path.write_text(
                prose_action.build_prompt(
                    plotunit,
                    new_state,
                    workspec_context=workspec.to_prompt_context(),
                    style_context=style_context,
                    timeline_context=facts.to_timeline_context(include_header=False),
                    time_context=build_time_context(load_time_book(output_dir)),
                ),
                encoding="utf-8",
            )
            print(f"\n[STEP: PROSE] Prompt saved: {prose_prompt_path}")
            print(f"[WAITING] Generate response to: {prose_response_path}")
            print("[RESUME] Re-run this script after saving response")
            return 0
        draft_text = prose_action.parse_response(
            _read_response_text(prose_response_path)
        )
        prose_draft_path = output_dir / "prose_draft.txt"
        prose_draft_path.write_text(draft_text, encoding="utf-8")
        # flow v3：正文草稿已落盘 → 运行状态 draft（未提交，下游不消费）
        if flow_version == "3":
            set_run_status(
                output_dir,
                run_id=derive_run_id(
                    "compose",
                    prose_action.next_chapter_number(output_dir.parent.parent / "chapters"),
                ),
                mode="compose",
                status="draft",
                chapter_number=prose_action.next_chapter_number(
                    output_dir.parent.parent / "chapters"
                ),
                notes=["prose draft staged (output/prose_draft.txt)"],
            )
        # 首次解析的 raw 归档（操作者扩写入 provenance——只写一次，后续重跑不覆盖）
        prose_action.archive_raw_prose(
            output_dir,
            prose_action.next_chapter_number(output_dir.parent.parent / "chapters"),
            draft_text,
        )
        print(f"Staged prose draft: {prose_draft_path}")

    # Step 5: Review（后置，读正文）
    print("\n" + "=" * 50)
    print("Step 5: Review (post-prose, reads chapter)")
    print("=" * 50)
    review_prompt_path = output_dir / "compose_review_prompt.txt"
    review_response_path = output_dir / "compose_review_response.txt"
    if review_response_path.exists():
        response = _read_response_text(review_response_path)
        _review_foreshadows = [
            o for o in review_objects if isinstance(o, ForeshadowGraph)
        ]
        _review_chars = [
            o for o in review_objects if isinstance(o, CharacterModel)
        ]
        llm_issues, reminders, route = review.parse_response(
            response,
            foreshadows=_review_foreshadows,
            character_models=_review_chars,
        )
        hard_issues = review._hard_rules(review_objects)
        domain_issues = review._domain_rules(review_objects)
        issues = hard_issues + domain_issues + llm_issues
        route = review.resolve_route(issues, route)
    else:
        review_prompt_path.write_text(
            review.build_prompt(
                review_objects,
                context="compose",
                prose_text=draft_text if draft_text is not None else None,
            ),
            encoding="utf-8",
        )
        print(f"[STEP: REVIEW] Prompt saved: {review_prompt_path}")
        print(f"[WAITING] Generate response to: {review_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Route: {route}")
    print(f"Issues: {len(issues)} (blocking: {sum(1 for i in issues if i.is_blocking())})")
    print(f"Reminders: {len(reminders)}")
    for reminder in reminders:
        print(
            f"  [{reminder.priority}] {reminder.family}: "
            f"{reminder.trigger_condition} | window={reminder.window} "
            f"-> {reminder.escalation_issue_type}"
        )

    fixes = []

    # Step 6: Rewrite（正文已存在 → 正文层修订优先；--no-prose → 对象层修复）
    if route == "rewrite":
        blocking_issues = [i for i in issues if i.is_blocking()]
        if not blocking_issues:
            print("Route is rewrite but no blocking issues — treating as pass")
            route = "pass"
        else:
            if draft_text is not None:
                # 正文层修复：带阻断 issue 直接修订 draft
                prose_revise_prompt_path = output_dir / "prose_revise_prompt.txt"
                prose_revise_response_path = output_dir / "prose_revise_response.txt"
                if not prose_revise_response_path.exists():
                    prose_revise_prompt_path.write_text(
                        prose_action.build_revision_prompt(
                            blocking_issues,
                            draft_text,
                            plotunit=plotunit,
                        ),
                        encoding="utf-8",
                    )
                    print(f"\n[STEP: PROSE REVISE] Prompt saved: {prose_revise_prompt_path}")
                    print(f"[WAITING] Generate response to: {prose_revise_response_path}")
                    print("[RESUME] Re-run this script after saving response")
                    return 0
                revised = prose_action.parse_response(
                    _read_response_text(prose_revise_response_path)
                )
                prose_action.record_prose_revision(
                    output_dir,
                    cycle_id=plotunit.unit_id,
                    issues=blocking_issues,
                    original=draft_text,
                    revision=revised,
                )
                draft_text = revised
                prose_draft_path.write_text(revised, encoding="utf-8")
                print(f"Revised prose draft: {prose_draft_path}")
            else:
                # --no-prose：对象层修复
                rewrite = RewriteUnit()
                compose_rewrite_prompt_path = output_dir / "compose_rewrite_prompt.txt"
                compose_rewrite_response_path = output_dir / "compose_rewrite_response.txt"

                if not compose_rewrite_response_path.exists():
                    compose_rewrite_prompt_path.write_text(
                        rewrite.build_prompt(blocking_issues, review_objects, context="compose"),
                        encoding="utf-8",
                    )
                    print(f"\n[STEP: REWRITE] Prompt saved: {compose_rewrite_prompt_path}")
                    print(f"[WAITING] Generate response to: {compose_rewrite_response_path}")
                    print("[RESUME] Re-run this script after saving response")
                    return 0

                response = _read_response_text(compose_rewrite_response_path)
                fixes = rewrite.parse_response(response)
                try:
                    applied = rewrite.apply_required_fixes(review_objects, fixes)
                except ValueError as exc:
                    print(f"Rewrite failed: {exc}")
                    return 1
                for fix in fixes:
                    print(
                        f"  Applied: {fix.get('target_type')}.{fix.get('field')} -> {fix.get('action')}"
                    )
                print(f"\nRewrite applied: {applied}/{len(fixes)}")

            # Step 7: Re-Review
            print("\n" + "=" * 50)
            print("Step 7: Re-Review")
            print("=" * 50)
            compose_rereview_prompt_path = output_dir / "compose_rereview_prompt.txt"
            compose_rereview_response_path = output_dir / "compose_rereview_response.txt"

            if not compose_rereview_response_path.exists():
                compose_rereview_prompt_path.write_text(
                    review.build_prompt(
                        review_objects,
                        context="compose-rereview",
                        prose_text=draft_text if draft_text is not None else None,
                    ),
                    encoding="utf-8",
                )
                print(f"[STEP: REREVIEW] Prompt saved: {compose_rereview_prompt_path}")
                print(f"[WAITING] Generate response to: {compose_rereview_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(compose_rereview_response_path)
            _rereview_foreshadows = [
                o for o in review_objects if isinstance(o, ForeshadowGraph)
            ]
            _rereview_chars = [
                o for o in review_objects if isinstance(o, CharacterModel)
            ]
            llm_issues, reminders, route = review.parse_response(
                response,
                foreshadows=_rereview_foreshadows,
                character_models=_rereview_chars,
            )
            hard_issues = review._hard_rules(review_objects)
            domain_issues = review._domain_rules(review_objects)
            issues = hard_issues + domain_issues + llm_issues
            route = review.resolve_route(issues, route)
            if route == "rewrite":
                # 单趟 rewrite+re-review 已过，仍有阻断 → 交人工
                route = "block"
            print(f"Re-Review Route: {route}")
            print(f"Issues: {len(issues)} (blocking: {sum(1 for i in issues if i.is_blocking())})")
            for i in issues:
                print(f"  [{i.severity}] {i.issue_type}: {i.description}")
            print(f"Reminders: {len(reminders)}")
            for reminder in reminders:
                print(
                    f"  [{reminder.priority}] {reminder.family}: "
                    f"{reminder.trigger_condition} | window={reminder.window} "
                    f"-> {reminder.escalation_issue_type}"
                )

    result = {
        "workspec": workspec.model_dump(mode="json"),
        "plotunit": plotunit.model_dump(mode="json"),
        "new_state": new_state.model_dump(mode="json"),
        "new_facts": new_facts,
        "issues": [i.model_dump(mode="json") for i in issues],
        "reminders": [r.model_dump(mode="json") for r in reminders],
        "route": route,
        "rewrite_applied": len(fixes) > 0,
        "applied_fixes": fixes,
        "pre_review": pre_review_result,
        "prose_context": "draft" if draft_text is not None else None,
    }
    if args.character_update == "on":
        result["character_updates"] = character_updates
    compose_result_path = output_dir / "compose_result.json"
    compose_result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {compose_result_path}")
    route_handoff = HandoffBoundaryUnit().build_review_route(
        review_target_ref=str(compose_result_path),
        route=route,
        issues=result["issues"],
        reminders=result["reminders"],
        output_state_ref=new_state.state_id,
    )
    (output_dir / "route_handoff.json").write_text(
        route_handoff.model_dump_json(indent=2),
        encoding="utf-8",
    )

    if route != "pass":
        # flow v3：阻断 → rejected 终态（不产生 committed 提交记录）
        if flow_version == "3":
            set_run_status(
                output_dir,
                run_id=derive_run_id(
                    "compose",
                    prose_action.next_chapter_number(output_dir.parent.parent / "chapters"),
                ),
                mode="compose",
                status="rejected",
                chapter_number=prose_action.next_chapter_number(
                    output_dir.parent.parent / "chapters"
                ),
                notes=[f"review route={route}; candidate not committed"],
            )
        print(f"\nCompose blocked: route={route}; candidate state not saved")
        if draft_text is not None:
            print("注意：本章正文仍是未提交 draft（output/prose_draft.txt），未进入 chapters/；"
                  "请人工处理或删除。")
        return 1

    # flow v3：Review PASS → reviewed（提交前置态）
    if flow_version == "3":
        set_run_status(
            output_dir,
            run_id=derive_run_id(
                "compose",
                prose_action.next_chapter_number(output_dir.parent.parent / "chapters"),
            ),
            mode="compose",
            status="reviewed",
            chapter_number=prose_action.next_chapter_number(
                output_dir.parent.parent / "chapters"
            ),
            notes=[f"review route={route} PASS"],
        )

    # Commit：PASS 后才把 draft 提交为正式 chapter_N.txt（落盘闸门在此兜底 staged 复用）
    chapter_committed = False
    if not args.no_prose and draft_text is not None:
        chapters_dir = output_dir.parent.parent / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        if prose_action.is_duplicate_of_last(draft_text, chapters_dir):
            print(
                "Error: draft is nearly identical to the last committed chapter; "
                "refusing to commit (staged response may have been reused)."
            )
            return 1
        if flow_version == "3":
            # v3 事务式提交：正文/归档/provenance/Frame/状态包绑定同一提交记录，
            # run_manifest.json 最后原子写入 → 崩溃重启只识别完整提交。
            chapter_number = prose_action.next_chapter_number(chapters_dir)
            chapter_file = prose_action.chapter_path(chapters_dir, chapter_number)

            # ---- Q1 Phase 4: 提交点读者门禁链（正文证据提取 → 跨章核对 → 门禁）----
            gate_verdict, gate_package, gate_reconcile_issues = (
                evaluate_commit_reader_gate(
                    output_dir=output_dir,
                    chapters_dir=chapters_dir,
                    draft_text=draft_text,
                    facts=facts,
                    characters=characters,
                    time_book=load_time_book(output_dir),
                    reader_contract=reader_contract,
                    chapter_ref=f"chapter_{chapter_number}",
                )
            )
            gate_package_hash = (
                sha256_text(gate_package.model_dump_json())
                if gate_package is not None
                else ""
            )
            write_reader_gate_report(
                output_dir,
                gate_verdict,
                chapter_ref=f"chapter_{chapter_number}",
                package_hash=gate_package_hash,
                reconcile_count=len(gate_reconcile_issues),
            )
            if gate_verdict.route != "pass":
                set_run_status(
                    output_dir,
                    run_id=derive_run_id("compose", chapter_number),
                    mode="compose",
                    status="rejected",
                    chapter_number=chapter_number,
                    notes=[
                        "reader gate "
                        + gate_verdict.route
                        + (": " + "; ".join(gate_verdict.reasons) if gate_verdict.reasons else "")
                    ],
                )
                print(f"\nReader gate {gate_verdict.route}: 本章不提交")
                for i in gate_verdict.issues:
                    print(f"  [{i.severity}] {i.issue_type}: {i.description}")
                print(f"  report: {output_dir / 'reader_gate_report.json'}")
                if gate_verdict.route == "rewrite":
                    print("  提示: 关键读者维度 weak——请 prose 修订正文后重跑")
                elif gate_verdict.route == "manual":
                    print("  提示: 连续阅读审美分歧——请人工决定是否接受/改写")
                return 1
            print(f"Reader gate pass (axes armed: {gate_verdict.axes_armed})")

            final_objects = objects + [plotunit, new_state]
            final_package = serializer.build_package(*final_objects)
            if not _validate_no_regression(final_package):
                return 1
            new_cursor = frame_unit.advance_cursor(frames)
            if new_cursor:
                print(f"\nFrame cursor advanced to: {new_cursor['current_frame_id']}")
            else:
                print("\nFrame cursor: no more scenes to advance")
            frames_json = json.dumps(frames, ensure_ascii=False, indent=2)
            state_json = json.dumps(final_package.model_dump(), ensure_ascii=False, indent=2)
            prov_path = output_dir / "chapter_provenance.json"
            prov_existing = (
                json.loads(prov_path.read_text(encoding="utf-8"))
                if prov_path.exists()
                else {"schema_version": 1, "chapters": {}}
            )
            prov_entry = prose_action.build_chapter_provenance_entry(
                chapter_number,
                flow_version="3",
                review_issues=issues,
                final_draft_chars=len("".join((draft_text or "").split())),
                active_frame_id=(
                    ((frame_context or {}).get("current_frame") or {}).get("frame_id")
                    if frame_context else None
                ),
                active_formula_node=(
                    ((frame_context or {}).get("current_frame") or {}).get("formula_node")
                    if frame_context else None
                ),
            )
            prov_json = json.dumps(
                prose_action.merge_chapter_provenance(prov_existing, prov_entry),
                ensure_ascii=False,
                indent=2,
            )
            boundary = ChapterCommitBoundary(output_dir, chapters_dir)
            result = boundary.commit(
                run_id=derive_run_id("compose", chapter_number),
                mode="compose",
                chapter_number=chapter_number,
                chapter_text=draft_text,
                state_path=compose_state_path,
                state_json=state_json,
                frames_path=frames_path,
                frames_json=frames_json,
                archive_text=draft_text,
                provenance_json=prov_json,
                prev_chapter_ref=None,
                source_text_hash=model_content_hash(workspec),
                facts_package_hash=gate_package_hash,
                review_route=route,
            )
            if not result.ok:
                print(f"Error: chapter commit failed: {result.error}")
                return 1
            chapter_committed = True
            print(f"Committed chapter: {chapter_file}")
            print(f"  run manifest: {output_dir / 'run_manifest.json'} (status=committed)")
        else:
            # v2 原样：先写正文，再归档/provenance（旧时序保持字节不变）
            chapter_file = prose_action.chapter_path(
                chapters_dir, prose_action.next_chapter_number(chapters_dir)
            )
            chapter_file.write_text(draft_text, encoding="utf-8")
            chapter_committed = True
            prose_action.archive_draft(
                output_dir,
                int(chapter_file.stem[len("chapter_"):]),
                draft_text,
            )
            prose_action.record_chapter_provenance(
                output_dir,
                int(chapter_file.stem[len("chapter_"):]),
                review_issues=issues,
                final_draft_chars=len("".join((draft_text or "").split())),
                active_frame_id=(
                    ((frame_context or {}).get("current_frame") or {}).get("frame_id")
                    if frame_context else None
                ),
                active_formula_node=(
                    ((frame_context or {}).get("current_frame") or {}).get("formula_node")
                    if frame_context else None
                ),
            )
            print(f"Committed chapter: {chapter_file}")

    if flow_version == "2":
        # v2 原样：build package → 校验 → advance Frame → save state（旧时序）
        final_objects = objects + [plotunit, new_state]
        final_package = serializer.build_package(*final_objects)
        if not _validate_no_regression(final_package):
            return 1

        new_cursor = frame_unit.advance_cursor(frames)
        if new_cursor:
            print(f"\nFrame cursor advanced to: {new_cursor['current_frame_id']}")
            frames_path.write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Saved frame state: {frames_path}")
        else:
            print("\nFrame cursor: no more scenes to advance")

        serializer.save(final_package, compose_state_path)
        print(f"Saved: {compose_state_path}")

    if chapter_committed:
        reset_consumed_responses(output_dir)
        print(
            f"[CYCLE] 本章 staged 响应已消费，下一章将从全新 prompt 开始"
            f"（避免重跑复用上一章响应产生重复章节）"
        )

    print("\nCompose complete: PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
