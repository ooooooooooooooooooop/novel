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
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
from src.domain_layer.rules import get_structure_template
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.rebuild import RebuildUnit
from src.workflow_action.review import ReviewUnit
from src.workflow_action.rewrite import RewriteUnit
from src.workflow_action.style import load_style_context
from src.workflow_action.retrieval import load_retrieval_context
from src.workflow_action.excerpt import load_recent_excerpts
from src.workflow_action.timebook import build_time_context, load_time_book

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
    11. 再次重跑脚本，输出 output/extend_result.json。

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
        help="引用风格库中的已有档案 <name>（novels/_style_library/<name>.json），注入续写 prompt",
    )
    parser.add_argument(
        "--retrieval",
        default="on",
        choices=["on", "off"],
        help="状态检索注入开关（默认 on；off 时与旧版 prompt 字节一致）",
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
    continue_prompt_path = output_dir / "continue_prompt.txt"
    if continue_response_path.exists():
        response = _read_response_text(continue_response_path)
        plotunit, new_state, new_facts, cont_gaps = cont.parse_response(response)
        try:
            new_facts = admit_new_facts(facts, new_facts, plotunit.unit_id)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    else:
        retrieval_context = ""
        if args.retrieval == "on":
            retrieval_context = load_retrieval_context(
                output_dir,
                state=narrative_state,
                facts=facts,
                foreshadows=foreshadows,
            )
        continue_prompt_path.write_text(
            cont.build_prompt(
                state=narrative_state,
                characters=characters,
                facts=facts,
                foreshadows=foreshadows,
                workspec_context="",  # 可选: 从 objects 中提取 WorkSpec
                frame_context=frame_context,
                structure_template=structure_template_name,
                platform=workspec.platform,
                genre=workspec.genre,
                style_context=load_style_context(output_dir, style_name=args.style or None),
                retrieval_context=retrieval_context,
                timeline_context=facts.to_timeline_context(include_header=False),
                time_context=build_time_context(load_time_book(output_dir)),
                excerpt_context=load_recent_excerpts(text),
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

    # Step 3: Review
    print("\n" + "=" * 50)
    print("Step 3: Review")
    print("=" * 50)
    review_objects = objects + [plotunit, new_state]
    review_prompt_path = output_dir / "review_prompt.txt"
    if review_response_path.exists():
        response = _read_response_text(review_response_path)
        llm_issues, reminders, route = review.parse_response(response)

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
            llm_issues, reminders, route = review.parse_response(response)
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
    print("\nExtend complete: PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
