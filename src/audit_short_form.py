#!/usr/bin/env python3
"""audit_short_form ? ???????????."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.handoff import HandoffBoundaryUnit
from src.boundary_control.report_formatter import format_markdown
from src.boundary_control.runtime_identity import file_content_hash, validate_run_hash
from src.boundary_control.runtime_args import validate_long_runtime_args
from src.boundary_control.runtime_state import require_continue_runtime_state
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
from src.object_state.audit_report import AuditReport
from src.workflow_action.rebuild import RebuildUnit
from src.workflow_action.review import ReviewUnit
from src.workflow_action.rewrite import RewriteUnit


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


def _outline_metadata(
    *,
    loaded_outline_used: bool,
    loaded_outline_arcs_count: int,
    book_outline,
) -> dict:
    outline_arcs_count = (
        loaded_outline_arcs_count
        if loaded_outline_used
        else (len(book_outline.arcs) if book_outline is not None else 0)
    )
    return {
        "outline_used": loaded_outline_used or (book_outline is not None),
        "outline_arcs_count": outline_arcs_count,
    }


def _require_applied_audit_rewrite(package, response_path: Path) -> tuple[list[dict], str]:
    metadata = package.metadata
    if not metadata.get("audit_rewrite_applied"):
        raise ValueError(
            "audit re-review requires rebuild_package.json with applied rewrite metadata"
        )
    current_hash = file_content_hash(response_path)
    if metadata.get("audit_rewrite_response_hash") != current_hash:
        raise ValueError("audit rewrite response changed after rewritten package was saved")
    fixes = metadata.get("audit_applied_fixes")
    if not isinstance(fixes, list):
        raise ValueError("audit rewrite metadata missing applied fixes")
    return fixes, current_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ? ? ????????")
    parser.add_argument("input_file", nargs="?", default="input.txt", help="????????")
    parser.add_argument(
        "--format", choices=["json", "markdown"], default="json", help="????"
    )
    parser.add_argument("--output-dir", default="output", help="????")
    parser.add_argument(
        "--chapter-wise",
        action="store_true",
        help="启用章节级重建（用于长文本，自动切分章节后逐章 Rebuild 再合并）",
    )
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
        "--outline-only",
        action="store_true",
        help="只生成结构概览（Outline），不进入详细 Rebuild",
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
    review_response_path = output_dir / "review_response.txt"
    audit_rewrite_response_path = output_dir / "audit_rewrite_response.txt"
    audit_rereview_response_path = output_dir / "audit_rereview_response.txt"
    rebuild_package_path = output_dir / "rebuild_package.json"
    rewrite_ready_for_rereview = (
        audit_rewrite_response_path.exists() and audit_rereview_response_path.exists()
    )
    fixes: list[dict] = []
    applied_rewrite_response_hash: str | None = None

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

    if len(chunks) > args.max_chapters and not args.chapter_range and not args.outline_only:
        print(f"Error: 检测到 {len(chunks)} 章，超过无 --range 时的上限 {args.max_chapters}")
        print(f"建议：使用 --range 指定处理范围，如 --range 1-{args.max_chapters}")
        print(f"或提高上限：--max-chapters {len(chunks)}")
        return 1

    chapter_wise = args.chapter_wise or bool(args.chapter_range) or len(text) > 10_000
    CHAPTERS_PER_BATCH = args.batch_size
    if chapter_wise:
        print(f"长文本检测: {len(text)} 字符，启用章节级重建")
    print(f"Loaded text: {len(text)} chars from {text_path}")

    if args.outline_only:
        from src.workflow_action.outline import OutlineUnit

        print("\n" + "=" * 50)
        print("Outline Mode: Structure Overview")
        print("=" * 50)

        outline = OutlineUnit()
        outline_prompt_path = output_dir / "outline_prompt.txt"
        outline_response_path = output_dir / "outline_response.txt"
        outline_result_path = output_dir / "outline_result.json"

        if outline_response_path.exists():
            response = _read_response_text(outline_response_path)
            book_outline = outline.parse_response(response)

            outline_result_path.write_text(
                book_outline.model_dump_json(indent=2, by_alias=True),
                encoding="utf-8",
            )
            print(f"Saved: {outline_result_path}")
            print(f"Arcs: {len(book_outline.arcs)}")
            for arc in book_outline.arcs:
                print(f"  {arc.arc_id}: {arc.name} ({arc.chapter_range})")
            print(f"Characters: {len(book_outline.characters)}")
            return 0

        samples = outline.sample_chapters(chunks)
        prompt = outline.build_prompt(
            text=text,
            chapter_samples=samples,
            total_chapters=len(chunks),
            total_chars=len(text),
        )
        outline_prompt_path.write_text(prompt, encoding="utf-8")
        print(f"[STEP: OUTLINE] Prompt saved: {outline_prompt_path}")
        print(f"[WAITING] Generate response to: {outline_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0

    rebuild = RebuildUnit()
    review = ReviewUnit()
    serializer = SerializationBoundaryUnit()
    handoff = HandoffBoundaryUnit()

    # Step 1: Rebuild (or load rewritten package)
    print("\n" + "=" * 50)
    print("Step 1: Rebuild")
    print("=" * 50)

    cross_issues: list = []
    book_outline = None
    loaded_outline_used = False
    loaded_outline_arcs_count = 0
    if audit_rewrite_response_path.exists():
        if not rebuild_package_path.exists():
            print(f"Error: audit rewrite requires saved package: {rebuild_package_path}")
            return 1
        # 已进入 rewrite 流程：从保存的 package 加载对象（两种模式通用）
        package = serializer.load(rebuild_package_path)
        if not _validate_no_regression(package):
            return 1
        objects = serializer.deserialize_package(package)
        gaps = []  # rewrite 后 gaps 已处理
        loaded_outline_used = package.metadata.get("outline_used", False)
        loaded_outline_arcs_count = package.metadata.get("outline_arcs_count", 0)
        if rewrite_ready_for_rereview:
            try:
                fixes, applied_rewrite_response_hash = _require_applied_audit_rewrite(
                    package,
                    audit_rewrite_response_path,
                )
            except ValueError as exc:
                print(f"Error: {exc}")
                return 1
        print(f"Loaded {len(objects)} objects from rewritten package")
    elif chapter_wise:
        # 章节级重建模式
        from src.workflow_action.reconcile import ReconcileUnit

        stats = get_total_stats(chunks)
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

        # 按批合并相邻章节
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

        print(f"合并为 {len(batches)} 个 batch（每批最多 {CHAPTERS_PER_BATCH} 章）")

        chapter_objects: list[list] = []
        missing_responses: list[str] = []

        for start_idx, end_idx, combined_text in batches:
            batch_name = f"batch_{start_idx:03d}_{end_idx:03d}"
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
                    print(f"[BATCH {start_idx}-{end_idx}] Prompt saved: {batch_prompt}")
                missing_responses.append(f"{start_idx}-{end_idx}")

        if missing_responses:
            print(f"\n[WAITING] Missing responses for batches: {missing_responses}")
            print("[RESUME] Re-run this script after saving all batch responses")
            return 0

        # 所有章节 response 已收集，执行 Reconcile
        reconciler = ReconcileUnit()
        objects, reconcile_issues = reconciler.reconcile(chapter_objects)
        gaps = []
        print(f"\nReconciled {len(objects)} global objects from {len(chunks)} chapters")
        cross_issues_list = reconciler.check_cross_chapter_consistency(objects)
        outline_issues = reconciler.check_outline_consistency(objects, book_outline)
        temporal_issues = reconciler.check_temporal_contradictions(objects)
        combined_cross = cross_issues_list + outline_issues + temporal_issues
        if combined_cross:
            cross_issues = combined_cross
            print(f"\nCross-chapter issues: {len(cross_issues)}")
            for issue in cross_issues:
                print(f"  [{issue.severity}] {issue.issue_type}: {issue.description}")
        if reconcile_issues:
            print("Reconcile issues:")
            for issue in reconcile_issues:
                print(f"  - {issue}")
    elif rebuild_response_path.exists():
        # 原有单章短文本模式
        response = _read_response_text(rebuild_response_path)
        objects, gaps = rebuild.parse_response(response)
        print(f"Rebuilt {len(objects)} objects")
    else:
        # 生成单章 rebuild prompt
        rebuild_prompt_path.write_text(rebuild.build_prompt(text), encoding="utf-8")
        print(f"[STEP: REBUILD] Prompt saved: {rebuild_prompt_path}")
        print(f"[WAITING] Generate response to: {rebuild_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Confidence gaps: {gaps}")
    try:
        require_continue_runtime_state(objects)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    package = serializer.build_package(*objects)
    package_metadata = _outline_metadata(
        loaded_outline_used=loaded_outline_used,
        loaded_outline_arcs_count=loaded_outline_arcs_count,
        book_outline=book_outline,
    )
    if rewrite_ready_for_rereview:
        package_metadata.update(
            {
                "audit_rewrite_applied": True,
                "audit_rewrite_response_hash": applied_rewrite_response_hash,
                "audit_applied_fixes": fixes,
            }
        )
    package = package.model_copy(update={"metadata": package_metadata})
    if not _validate_no_regression(package):
        return 1
    serializer.save(package, rebuild_package_path)
    print(f"Saved: {rebuild_package_path}")

    packet = handoff.build_rebuild_to_review(
        source_text_ref=str(text_path),
        reconstructed_objects={
            type(o).__name__: o.model_dump(mode="json") for o in objects
        },
        confidence_gaps=gaps,
    )
    ok, violations = handoff.verify(packet)
    if not ok:
        print("Handoff failed:", violations)
        return 1
    print("Handoff verified")

    # Step 2: Review
    print("\n" + "=" * 50)
    print("Step 2: Review")
    print("=" * 50)
    review_prompt_path = output_dir / "review_prompt.txt"
    active_review_response_path = (
        audit_rereview_response_path if rewrite_ready_for_rereview else review_response_path
    )
    if active_review_response_path.exists():
        response = _read_response_text(active_review_response_path)
        llm_issues, reminders, route = review.parse_response(response)

        # 合并代码预检 issues
        hard_issues = review._hard_rules(objects)
        domain_issues = review._domain_rules(objects)
        base_issues = [] if rewrite_ready_for_rereview else cross_issues
        issues = base_issues + hard_issues + domain_issues + llm_issues
        route = review.resolve_route(issues, route)
    else:
        review_prompt_path.write_text(
            review.build_prompt(objects, context="audit"),
            encoding="utf-8",
        )
        print(f"[STEP: REVIEW] Prompt saved: {review_prompt_path}")
        print(f"[WAITING] Generate response to: {review_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Issues: {len(issues)} (blocking: {sum(1 for i in issues if i.is_blocking())})")
    for issue in issues:
        print(f"  [{issue.severity}] {issue.issue_type}: {issue.description}")
    print(f"Reminders: {len(reminders)}")
    for reminder in reminders:
        print(
            f"  [{reminder.priority}] {reminder.family}: "
            f"{reminder.trigger_condition} | window={reminder.window} "
            f"-> {reminder.escalation_issue_type}"
        )
    print(f"Route: {route}")

    # Step 3: Rewrite (if route == "rewrite")
    if route == "rewrite" and not rewrite_ready_for_rereview:
        blocking_issues = [issue for issue in issues if issue.is_blocking()]
        if not blocking_issues:
            print("Route is rewrite but no blocking issues ? treating as pass")
            route = "pass"
        else:
            rewrite = RewriteUnit()
            audit_rewrite_prompt_path = output_dir / "audit_rewrite_prompt.txt"

            if not audit_rewrite_response_path.exists():
                audit_rewrite_prompt_path.write_text(
                    rewrite.build_prompt(blocking_issues, objects, context="audit"),
                    encoding="utf-8",
                )
                print(f"\n[STEP: REWRITE] Prompt saved: {audit_rewrite_prompt_path}")
                print(f"[WAITING] Generate response to: {audit_rewrite_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(audit_rewrite_response_path)
            fixes = rewrite.parse_response(response)
            try:
                applied = rewrite.apply_required_fixes(objects, fixes)
            except ValueError as exc:
                print(f"Rewrite failed: {exc}")
                return 1
            for fix in fixes:
                print(
                    f"  Applied: {fix.get('target_type')}.{fix.get('field')} -> {fix.get('action')}"
                )
            print(f"\nRewrite applied: {applied}/{len(fixes)}")

            package = serializer.build_package(*objects)
            rewrite_response_hash = file_content_hash(audit_rewrite_response_path)
            package_metadata = _outline_metadata(
                loaded_outline_used=loaded_outline_used,
                loaded_outline_arcs_count=loaded_outline_arcs_count,
                book_outline=book_outline,
            )
            package_metadata.update(
                {
                    "audit_rewrite_applied": True,
                    "audit_rewrite_response_hash": rewrite_response_hash,
                    "audit_applied_fixes": fixes,
                }
            )
            package = package.model_copy(update={"metadata": package_metadata})
            if not _validate_no_regression(package):
                return 1
            serializer.save(package, rebuild_package_path)
            print(f"Saved: {rebuild_package_path} (rewritten)")

            # Step 4: Re-Review
            print("\n" + "=" * 50)
            print("Step 4: Re-Review")
            print("=" * 50)
            audit_rereview_prompt_path = output_dir / "audit_rereview_prompt.txt"

            if not audit_rereview_response_path.exists():
                audit_rereview_prompt_path.write_text(
                    review.build_prompt(objects, context="audit-rereview"),
                    encoding="utf-8",
                )
                print(f"[STEP: REREVIEW] Prompt saved: {audit_rereview_prompt_path}")
                print(f"[WAITING] Generate response to: {audit_rereview_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(audit_rereview_response_path)
            llm_issues, reminders, route = review.parse_response(response)
            hard_issues = review._hard_rules(objects)
            domain_issues = review._domain_rules(objects)
            issues = hard_issues + domain_issues + llm_issues
            route = review.resolve_route(issues, route)
            print(f"Re-Review Route: {route}")
            print(
                f"Issues: {len(issues)} (blocking: {sum(1 for i in issues if i.is_blocking())})"
            )
            for issue in issues:
                print(f"  [{issue.severity}] {issue.issue_type}: {issue.description}")
            print(f"Reminders: {len(reminders)}")
            for reminder in reminders:
                print(
                    f"  [{reminder.priority}] {reminder.family}: "
                    f"{reminder.trigger_condition} | window={reminder.window} "
                    f"-> {reminder.escalation_issue_type}"
                )

    workspec_data = next(
        (o.model_dump(mode="json") for o in objects if type(o).__name__ == "WorkSpec"),
        None,
    )
    worldmodel_data = next(
        (o.model_dump(mode="json") for o in objects if type(o).__name__ == "WorldModel"),
        None,
    )
    characters_data = [
        o.model_dump(mode="json") for o in objects if type(o).__name__ == "CharacterModel"
    ]
    narrative_state_data = next(
        (
            o.model_dump(mode="json")
            for o in objects
            if type(o).__name__ == "NarrativeState"
        ),
        None,
    )
    fact_ledger_data = next(
        (o.model_dump(mode="json") for o in objects if type(o).__name__ == "FactLedger"),
        None,
    )
    foreshadow_graph_data = next(
        (
            o.model_dump(mode="json")
            for o in objects
            if type(o).__name__ == "ForeshadowGraph"
        ),
        None,
    )

    report = AuditReport(
        source_text_ref=str(text_path),
        route=route,
        workspec=workspec_data,
        worldmodel=worldmodel_data,
        characters=characters_data,
        narrative_state=narrative_state_data,
        fact_ledger=fact_ledger_data,
        foreshadow_graph=foreshadow_graph_data,
        issues=[i.model_dump(mode="json") for i in issues],
        reminders=[r.model_dump(mode="json") for r in reminders],
        confidence_gaps=gaps,
        rewrite_applied=audit_rewrite_response_path.exists(),
        applied_fixes=fixes if audit_rewrite_response_path.exists() else [],
        original_route="rewrite" if audit_rewrite_response_path.exists() else None,
        outline_used=(book_outline is not None) or loaded_outline_used,
        outline_arcs_count=(
            len(book_outline.arcs)
            if book_outline is not None
            else loaded_outline_arcs_count
        ),
    )
    report_data = report.model_dump(mode="json")

    if args.format == "markdown":
        md_text = format_markdown(report_data)
        (output_dir / "audit_report.md").write_text(md_text, encoding="utf-8")
        print(f"\nSaved: {output_dir}/audit_report.md")
    else:
        (output_dir / "audit_report.json").write_text(
            report.model_dump_json(indent=2, by_alias=True),
            encoding="utf-8",
        )
        print(f"\nSaved: {output_dir}/audit_report.json")

    if audit_rewrite_response_path.exists():
        print(f"  Rewrite applied: {len(report.applied_fixes)} fixes")
    print(f"  Issues: {len(report.issues)} (blocking: {sum(1 for i in issues if i.is_blocking())})")
    print(f"  Reminders: {len(report.reminders)}")

    review_data = {
        "issues": report_data["issues"],
        "reminders": report_data["reminders"],
        "route": report_data["route"],
    }
    (output_dir / "review_result.json").write_text(
        json.dumps(review_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    route_handoff = handoff.build_review_route(
        review_target_ref=str(output_dir / "review_result.json"),
        route=route,
        issues=report_data["issues"],
        reminders=report_data["reminders"],
        output_state_ref=(
            narrative_state_data.get("state_id")
            if narrative_state_data is not None
            else str(output_dir / "audit_report.json")
        ),
    )
    (output_dir / "route_handoff.json").write_text(
        route_handoff.model_dump_json(indent=2),
        encoding="utf-8",
    )

    if route == "pass":
        print("\nAudit complete: PASS")
    else:
        print(f"\nAudit complete: {route.upper()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
