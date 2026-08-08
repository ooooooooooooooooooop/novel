#!/usr/bin/env python3
"""extend_short_form — 第二个有界实现切片入口.

用法:
    python src/extend_short_form.py <input_text_file>
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.handoff import HandoffBoundaryUnit
from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.boundary_control.runtime_args import validate_long_runtime_args
from src.boundary_control.runtime_state import require_continue_runtime_state
from src.boundary_control.response_file import reset_consumed_responses
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
from src.object_state.charactermodel import CharacterModel
from src.object_state.foreshadowgraph import ForeshadowGraph
from src.domain_layer.compliance_rules import build_nsfw_context
from src.domain_layer.rules import get_structure_template
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.rebuild import RebuildUnit
from src.workflow_action.review import ReviewUnit, recheck_against_prose
from src.workflow_action.rewrite import RewriteUnit
from src.domain_layer.style_rules import build_temperament_guidance
from src.workflow_action.style import load_style_context
from src.workflow_action.retrieval import load_retrieval_context
from src.workflow_action.character_updates import (
    admit_character_updates,
    append_character_updates,
    build_character_update_prompt,
    parse_character_updates_response,
)
from src.workflow_action.author_selection import (
    load_style_profile,
    resolve_kernel,
    run_author_selection,
)
from src.workflow_action.excerpt import append_generated_chapters, load_recent_excerpts
from src.workflow_action.proposal_generator import (
    build_proposal_prompt,
    parse_proposals_response,
)
from src.workflow_action.timebook import build_time_context, load_time_book
from src.workflow_action import prose as prose_action

continuation_module = importlib.import_module("src.workflow_action.continuation")
ContinueUnit = continuation_module.ContinueUnit
admit_new_facts = continuation_module.admit_new_facts


def _validate_no_regression(package) -> bool:
    violations = NoRegressionValidationUnit().run(package)
    if not violations:
        return True
    print("No-regression validation failed:")
    for violation in violations:
        print(f"  - {violation}")
    return False


def _extend_temporal_issues(objects: list) -> list:
    """FACTTRACK 时间矛盾检测（挂进 extend 流）。

    独立 helper 规避 chapter-wise 分支内 ReconcileUnit 函数级 import 的遮蔽。
    无时间矛盾时返回空列表（当前语料零产出，不破测试）。
    """
    from src.workflow_action.reconcile import ReconcileUnit

    return ReconcileUnit().check_temporal_contradictions(objects)


def _read_response_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


HELP_TEXT = """Usage:
  python src/extend_short_form.py [input_text_file] [--chapter-wise] [--resume]

Extend 流（续写）：
  标准模式（短文本）：
    1. 运行脚本，生成 output/rebuild_prompt.txt 后退出。
    2. Codex 生成 JSON 响应，保存到 output/rebuild_response.txt。
    3. 重跑脚本，生成 output/continue_prompt.txt 后退出。
    4. Codex 生成 JSON 响应，保存到 output/continue_response.txt。
    5. 重跑脚本，生成 output/review_prompt.txt 后退出。
    6. Codex 生成 JSON 响应，保存到 output/review_response.txt。
    7. 若 route 为 rewrite，生成 output/extend_rewrite_prompt.txt 后退出。
    8. Codex 生成 JSON 响应，保存到 output/extend_rewrite_response.txt。
    9. 重跑脚本，生成 output/extend_rereview_prompt.txt 后退出。
    10. Codex 生成 JSON 响应，保存到 output/extend_rereview_response.txt。
    11. 再次重跑脚本，生成 output/prose_prompt.txt 后退出。
    12. Codex 生成纯文本章节正文，保存到 output/prose_response.txt。
    13. 再次重跑脚本，正文落盘到 chapters/chapter_<N>.txt，输出 output/extend_result.json。
    （--no-prose 跳过 11-13，保持旧版纯结构产物。）

  章节级模式（长文本 >10000字符自动启用，或 --chapter-wise 强制启用）：
    1. 脚本自动切分章节，逐批生成 extend_batch_XXX_YYY_rebuild_prompt.txt。
    2. 所有 batch response 收集后自动 Reconcile 合并为全局对象。
    3. 合并后的全局状态进入 Continue → Review 流。
    4. 后续步骤与标准模式相同。

  Resume 模式：
    1. 从 output/extend_rebuild_package.json 加载上次保存的对象状态。
    2. 从 output/extend_frames.json 加载 frame cursor 状态。
    3. 跳过 Rebuild，直接进入 Continue。
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extend 流（续写）",
        epilog=HELP_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_file", nargs="?", default="input.txt", help="输入文本文件")
    parser.add_argument(
        "--chapter-wise",
        action="store_true",
        help="启用章节级重建（用于长文本，自动切分章节后逐批 Rebuild 再合并）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从上次保存的状态继续（跳过 Rebuild，加载已有对象和 frame 状态）",
    )
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument(
        "--range",
        dest="chapter_range",
        metavar="START-END",
        help="处理指定章节范围，如 '1-50'。不指定则处理全部。",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="每批处理的章节数（默认 50）",
    )
    parser.add_argument(
        "--max-chapters",
        type=int,
        default=100,
        help="无 --range 时的最大允许章节数（默认 100，超过则硬阻止）",
    )
    parser.add_argument(
        "--style",
        default="",
        help="引用风格库中的已有档案 <name>（style_library/<name>.json），注入续写 prompt",
    )
    parser.add_argument(
        "--temperament",
        default="",
        help="叙事气质（散文型/戏剧型/信息型/氛围型）；无风格档案时注入气质桶指导",
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
        "--no-prose",
        action="store_true",
        help="跳过章节正文落盘（只产出 PlotUnit 结构；默认自动成文落盘 chapters/）",
    )
    args = parser.parse_args()
    try:
        selected_range = validate_long_runtime_args(
            chapter_range=args.chapter_range,
            batch_size=args.batch_size,
            max_chapters=args.max_chapters,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    resume_mode = args.resume

    text_path = Path(args.input_file)
    if not text_path.exists():
        print(f"Error: Input file not found: {text_path}")
        return 1

    def _read_text(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法解码文件: {path}")

    text = _read_text(text_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # 文风锚点/前章结尾应基于『原书 + 已续写章节』，否则多章续写后仍锁死原书首章
    continuation_text = append_generated_chapters(
        text, output_dir.parent.parent / "chapters"
    )

    rebuild_prompt_path = output_dir / "rebuild_prompt.txt"
    rebuild_response_path = output_dir / "rebuild_response.txt"
    rebuild_package_path = output_dir / "extend_rebuild_package.json"
    frames_path = output_dir / "extend_frames.json"
    continue_response_path = output_dir / "continue_response.txt"
    review_response_path = output_dir / "review_response.txt"
    extend_rewrite_response_path = output_dir / "extend_rewrite_response.txt"
    extend_rereview_response_path = output_dir / "extend_rereview_response.txt"

    if resume_mode and not rebuild_package_path.exists():
        print(f"Error: --resume requires saved state file: {rebuild_package_path}")
        return 1

    if resume_mode and not frames_path.exists():
        print(f"Error: --resume requires saved frame file: {frames_path}")
        return 1

    hash_path = output_dir / ".input_hash"
    current_hash = file_content_hash(text_path)
    hash_errors = validate_run_hash(
        hash_path=hash_path,
        current_hash=current_hash,
        output_dir=output_dir,
        label="input file",
    )
    if hash_errors:
        for error in hash_errors:
            print(error)
        return 1

    from src.boundary_control.chunking import get_total_stats, split_by_chapters

    chunks = split_by_chapters(text)
    if selected_range:
        start, end = selected_range
        chunks = [c for c in chunks if start <= c.chapter_index <= end]
        print(f"Range filter: 只处理第 {start}-{end} 章，共 {len(chunks)} 章")
        if not chunks:
            print(f"Error: no chapters selected by --range {args.chapter_range}")
            return 1

    if len(chunks) > args.max_chapters and not args.chapter_range:
        print(f"Error: 检测到 {len(chunks)} 章，超过无 --range 时的上限 {args.max_chapters}")
        print(f"建议：使用 --range 指定处理范围，如 --range 1-{args.max_chapters}")
        print(f"或提高上限：--max-chapters {len(chunks)}")
        return 1

    chapter_wise = args.chapter_wise or bool(args.chapter_range) or len(text) > 10_000
    CHAPTERS_PER_BATCH = args.batch_size
    print(f"Loaded text: {len(text)} chars")

    # 时间域：rebuild 顺带校准既有 TimeBook 的章节时间锚
    # （无 TimeBook 文件时零成本：不产生文件、无额外字节）
    from src.workflow_action.timebook import refresh_time_book_anchors

    refresh_time_book_anchors(output_dir, chunks)

    rebuild = RebuildUnit()
    cont = ContinueUnit()
    review = ReviewUnit()
    frame_unit = NarrativeFrameUnit()
    serializer = SerializationBoundaryUnit()
    handoff = HandoffBoundaryUnit()

    # Step 1: Rebuild
    print("\n" + "=" * 50)
    print("Step 1: Rebuild (partial recovery)")
    print("=" * 50)

    objects: list = []
    gaps: list[str] = []
    frames: list = []
    book_outline = None

    if resume_mode:
        # Resume 模式：从保存的包加载对象
        print(f"Resume mode: loading from {rebuild_package_path}")
        package = serializer.load(rebuild_package_path)
        if not _validate_no_regression(package):
            return 1
        objects = serializer.deserialize_package(package)
        print(f"Loaded {len(objects)} objects")

        frames = json.loads(frames_path.read_text(encoding="utf-8"))
        print(f"Loaded frame state from {frames_path}")

    if not objects and chapter_wise and not rebuild_response_path.exists():
        # 章节级重建模式
        from src.workflow_action.reconcile import ReconcileUnit

        stats = get_total_stats(chunks)
        print(f"长文本检测: {len(text)} 字符，启用章节级重建")
        print(
            f"Detected {stats['chapter_count']} chapters, "
            f"avg {stats['avg_chars_per_chapter']} chars/chapter"
        )

        if len(chunks) >= 30:
            from src.workflow_action.outline import BookOutline, OutlineUnit

            outline = OutlineUnit()
            outline_prompt_path = output_dir / "outline_prompt.txt"
            outline_response_path = output_dir / "outline_response.txt"
            outline_result_path = output_dir / "outline_result.json"

            if outline_result_path.exists():
                book_outline = BookOutline.model_validate_json(
                    outline_result_path.read_text(encoding="utf-8")
                )
                print(f"Loaded outline prior: {outline_result_path}")
            elif outline_response_path.exists():
                try:
                    response = _read_response_text(outline_response_path)
                    book_outline = outline.parse_response(response)
                except Exception as exc:
                    print(f"Error: failed to parse outline response: {exc}")
                    return 1

                outline_result_path.write_text(
                    book_outline.model_dump_json(indent=2, by_alias=True),
                    encoding="utf-8",
                )
                print(f"Saved outline prior: {outline_result_path}")
            else:
                samples = outline.sample_chapters(chunks)
                prompt = outline.build_prompt(
                    text=text,
                    chapter_samples=samples,
                    total_chapters=len(chunks),
                    total_chars=len(text),
                )
                if not outline_prompt_path.exists():
                    outline_prompt_path.write_text(prompt, encoding="utf-8")
                print(f"[STEP: OUTLINE] Prompt saved: {outline_prompt_path}")
                print(f"[WAITING] Generate response to: {outline_response_path}")
                print("[RESUME] Re-run this script after saving outline response")
                return 0

        batches: list[tuple[int, int, str]] = []
        for i in range(0, len(chunks), CHAPTERS_PER_BATCH):
            batch_chunks = chunks[i:i + CHAPTERS_PER_BATCH]
            start_idx = batch_chunks[0].chapter_index
            end_idx = batch_chunks[-1].chapter_index
            combined = "\n\n".join(
                f"--- 第{c.chapter_index}章: {c.chapter_title} ---\n{c.text}"
                for c in batch_chunks
            )
            batches.append((start_idx, end_idx, combined))

        chapter_objects: list[list] = []
        missing_responses: list[str] = []

        for start_idx, end_idx, combined_text in batches:
            batch_name = f"extend_batch_{start_idx:03d}_{end_idx:03d}"
            batch_prompt = output_dir / f"{batch_name}_rebuild_prompt.txt"
            batch_response = output_dir / f"{batch_name}_rebuild_response.txt"

            if batch_response.exists():
                response = _read_response_text(batch_response)
                objs, _ = rebuild.parse_response(response)
                chapter_objects.append(objs)
            else:
                if not batch_prompt.exists():
                    batch_prompt.write_text(
                        rebuild.build_prompt(combined_text, book_outline=book_outline),
                        encoding="utf-8",
                    )
                    print(f"[EXTEND BATCH {start_idx}-{end_idx}] Prompt saved: {batch_prompt}")
                missing_responses.append(f"{start_idx}-{end_idx}")

        if missing_responses:
            print(f"\n[WAITING] Missing responses for extend batches: {missing_responses}")
            print("[RESUME] Re-run this script after saving all batch responses")
            return 0

        # 所有 batch response 已收集，执行 Reconcile
        reconciler = ReconcileUnit()
        objects, reconcile_issues = reconciler.reconcile(chapter_objects)
        gaps = []
        print(f"\nReconciled {len(objects)} global objects from {len(chunks)} chapters")
        if reconcile_issues:
            print("Reconcile issues:")
            for issue in reconcile_issues:
                print(f"  - {issue}")

        # 序列化保存 Reconcile 结果
        package = serializer.build_package(*objects)
        if not _validate_no_regression(package):
            return 1
        serializer.save(package, rebuild_package_path)
        print(f"Saved: {rebuild_package_path}")

    elif not objects and rebuild_response_path.exists():
        # 单文本模式（已有 response）
        response = _read_response_text(rebuild_response_path)
        objects, gaps = rebuild.parse_response(response)
        print(f"Rebuilt {len(objects)} objects, gaps: {gaps}")

        # 序列化保存
        package = serializer.build_package(*objects)
        if not _validate_no_regression(package):
            return 1
        serializer.save(package, rebuild_package_path)
        print(f"Saved: {rebuild_package_path}")
    elif not objects:
        # 单文本模式（无 response，生成 prompt）
        rebuild_prompt_path.write_text(rebuild.build_prompt(text), encoding="utf-8")
        print(f"[STEP: REBUILD] Prompt saved: {rebuild_prompt_path}")
        print(f"[WAITING] Generate response to: {rebuild_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    # 提取关键对象
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

    # Step 2: Continue
    print("\n" + "=" * 50)
    print("Step 2: Continue")
    print("=" * 50)
    proposals_n = max(1, args.proposals)
    multi_proposals = proposals_n >= 2
    continue_prompt_path = output_dir / "continue_prompt.txt"
    proposals_prompt_path = output_dir / "proposals_prompt.txt"
    proposals_response_path = output_dir / "proposals_response.txt"
    if not multi_proposals and continue_response_path.exists():
        response = _read_response_text(continue_response_path)
        plotunit, new_state, new_facts, cont_gaps = cont.parse_response(response)
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
        selection = run_author_selection(
            packages,
            objects,
            output_dir=output_dir,
            decision_context=narrative_state.current_situation or "Extend 续写决策",
            state_ref=narrative_state.state_id,
            current_state_ref=narrative_state.state_id,
            kernel=kernel,
            style_profile=style_profile,
            style_profile_id=args.style or None,
            author_mode_on=args.author_mode == "on",
            shadow_on=args.shadow == "on",
            drift_review_on=args.drift_review == "on",
            review=review,
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
        cont_gaps = selected_package["confidence_gaps"]
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
        # extend 无 workspec，气质桶仅来自 CLI --temperament。
        style_context = load_style_context(output_dir, style_name=args.style or None)
        if not style_context and args.temperament:
            style_context = build_temperament_guidance(args.temperament)
        if multi_proposals:
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
                    excerpt_context=load_recent_excerpts(continuation_text),
                    nsfw_context=build_nsfw_context(args.nsfw == "on"),
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
                    excerpt_context=load_recent_excerpts(continuation_text),
                    nsfw_context=build_nsfw_context(args.nsfw == "on"),
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
    print(f"Confidence gaps: {cont_gaps}")

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

    # Step 3: Review
    print("\n" + "=" * 50)
    print("Step 3: Review")
    print("=" * 50)
    review_objects = objects + [plotunit, new_state]
    review_prompt_path = output_dir / "review_prompt.txt"
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

        # 合并代码预检 issues
        hard_issues = review._hard_rules(review_objects)
        domain_issues = review._domain_rules(review_objects)
        temporal_issues = _extend_temporal_issues(objects)
        issues = hard_issues + domain_issues + temporal_issues + llm_issues
        route = review.resolve_route(issues, route)
    else:
        review_prompt_path.write_text(
            review.build_prompt(review_objects, context="extend"),
            encoding="utf-8",
        )
        print(f"[STEP: REVIEW] Prompt saved: {review_prompt_path}")
        print(f"[WAITING] Generate response to: {review_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Route: {route}")
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

    # Step 4: Rewrite (if needed)
    if route == "rewrite":
        blocking_issues = [i for i in issues if i.is_blocking()]
        if not blocking_issues:
            print("Route is rewrite but no blocking issues — treating as pass")
            route = "pass"
        else:
            rewrite = RewriteUnit()
            rewrite_prompt_path = output_dir / "extend_rewrite_prompt.txt"

            if not extend_rewrite_response_path.exists():
                rewrite_prompt_path.write_text(
                    rewrite.build_prompt(blocking_issues, review_objects, context="extend"),
                    encoding="utf-8",
                )
                print(f"\n[STEP: REWRITE] Prompt saved: {rewrite_prompt_path}")
                print(f"[WAITING] Generate response to: {extend_rewrite_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(extend_rewrite_response_path)
            fixes = rewrite.parse_response(response)
            try:
                applied = rewrite.apply_required_fixes(review_objects, fixes)
            except ValueError as exc:
                print(f"Rewrite failed: {exc}")
                return 1
            for fix in fixes:
                print(f"  Applied: {fix.get('target_type')}.{fix.get('field')} -> {fix.get('action')}")
            print(f"\nRewrite applied: {applied}/{len(fixes)}")

            # Step 5: Re-Review
            print("\n" + "=" * 50)
            print("Step 5: Re-Review")
            print("=" * 50)
            rereview_prompt_path = output_dir / "extend_rereview_prompt.txt"

            if not extend_rereview_response_path.exists():
                rereview_prompt_path.write_text(
                    review.build_prompt(review_objects, context="extend-rereview"),
                    encoding="utf-8",
                )
                print(f"[STEP: REREVIEW] Prompt saved: {rereview_prompt_path}")
                print(f"[WAITING] Generate response to: {extend_rereview_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(extend_rereview_response_path)
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
            temporal_issues = _extend_temporal_issues(objects)
            issues = hard_issues + domain_issues + temporal_issues + llm_issues
            route = review.resolve_route(issues, route)
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

    review_data = {
        "plotunit": plotunit.model_dump(mode="json"),
        "new_state": new_state.model_dump(mode="json"),
        "new_facts": new_facts,
        "issues": [i.model_dump(mode="json") for i in issues],
        "reminders": [r.model_dump(mode="json") for r in reminders],
        "route": route,
        "outline_used": book_outline is not None,
        "outline_arcs_count": len(book_outline.arcs) if book_outline is not None else 0,
    }
    if args.character_update == "on":
        review_data["character_updates"] = character_updates
    extend_result_path = output_dir / "extend_result.json"
    extend_result_path.write_text(
        json.dumps(review_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {extend_result_path}")
    route_handoff = handoff.build_review_route(
        review_target_ref=str(extend_result_path),
        route=route,
        issues=review_data["issues"],
        reminders=review_data["reminders"],
        output_state_ref=new_state.state_id,
    )
    (output_dir / "route_handoff.json").write_text(
        route_handoff.model_dump_json(indent=2),
        encoding="utf-8",
    )

    if route != "pass":
        print(f"\nExtend blocked: route={route}; candidate state not saved")
        return 1

    # Step 6: Prose（章节正文成文落盘；--no-prose 跳过）
    chapter_written = False
    if not args.no_prose:
        prose_prompt_path = output_dir / "prose_prompt.txt"
        prose_response_path = output_dir / "prose_response.txt"
        if not prose_response_path.exists():
            style_context = load_style_context(
                output_dir, style_name=args.style or None
            )
            if not style_context and args.temperament:
                style_context = build_temperament_guidance(args.temperament)
            prose_prompt_path.write_text(
                prose_action.build_prompt(
                    plotunit,
                    new_state,
                    workspec_context=workspec.to_prompt_context(),
                    style_context=style_context,
                    excerpt_context=load_recent_excerpts(continuation_text),
                    timeline_context=facts.to_timeline_context(include_header=False),
                    time_context=build_time_context(load_time_book(output_dir)),
                    prev_chapter_end=prose_action.prev_chapter_tail(continuation_text),
                    target_chapter_chars=prose_action.average_chapter_chars(chunks),
                    reuse_source=text,
                ),
                encoding="utf-8",
            )
            print(f"\n[STEP: PROSE] Prompt saved: {prose_prompt_path}")
            print(f"[WAITING] Generate response to: {prose_response_path}")
            print("[RESUME] Re-run this script after saving response")
            return 0
        chapter_text = prose_action.parse_response(
            _read_response_text(prose_response_path),
            target_chars=prose_action.average_chapter_chars(chunks),
        )
        chapters_dir = output_dir.parent.parent / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        if prose_action.is_duplicate_of_last(chapter_text, chapters_dir):
            print(
                "Error: candidate prose is nearly identical to the last chapter; "
                "refusing to write a duplicate (staged response may have been reused)."
            )
            return 1
        chapter_file = prose_action.chapter_path(
            chapters_dir, prose_action.next_chapter_number(chapters_dir)
        )
        chapter_file.write_text(chapter_text, encoding="utf-8")
        chapter_written = True
        print(f"Saved chapter: {chapter_file}")

        # F5 原文长段去重：记录新章与原文逐字重叠片段（只标注，不改 route）
        overlap_spans = prose_action.find_overlapping_spans(chapter_text, text)
        if overlap_spans:
            review_data["prose_overlap"] = overlap_spans
            extend_result_path.write_text(
                json.dumps(review_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"Prose overlap: {len(overlap_spans)} verbatim span(s) "
                f"from source (≥{prose_action.REUSE_MIN_CHARS} chars)"
            )
        else:
            print("Prose overlap: none")

        # F3a Review 挂 prose 复核：对象层 issue 是否被正文兑现（只标注，不改 route）
        prose_recheck = recheck_against_prose(issues, chapter_text)
        confirmed = [
            r for r in prose_recheck if r["prose_confirmed"] is True
        ]
        if confirmed:
            review_data["prose_recheck"] = prose_recheck
            extend_result_path.write_text(
                json.dumps(review_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"Prose recheck: {len(confirmed)}/{len(prose_recheck)} issue(s) "
                f"confirmed by prose"
            )
            for r in confirmed:
                print(
                    f"  [prose-confirmed] {r['issue_type']} "
                    f"{r['issue_id']}: {r.get('evidence', '')[:40]}"
                )

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

    serializer.save(final_package, rebuild_package_path)
    print(f"Saved: {rebuild_package_path}")

    if chapter_written:
        reset_consumed_responses(output_dir)
        print(
            f"[CYCLE] 本章 staged 响应已消费，下一章将从全新 prompt 开始"
            f"（避免重跑复用上一章响应产生重复章节）"
        )

    print("\nExtend complete: PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
