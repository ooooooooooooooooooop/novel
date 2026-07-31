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
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
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
from src.workflow_action.frame import NarrativeFrameUnit
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


HELP_TEXT = """Usage:
  python src/compose_short_form.py [workspec_json_file] [--resume]

Compose 流（从 WorkSpec 创作）：
  1. 无参数时使用默认 WorkSpec；有参数时读取指定 WorkSpec JSON。
  2. 运行脚本，生成 output/compose_continue_prompt.txt 后退出。
  3. Codex 生成 JSON 响应，保存到 output/compose_continue_response.txt。
  4. 重跑脚本，生成 output/compose_review_prompt.txt 后退出。
  5. Codex 生成 JSON 响应，保存到 output/compose_review_response.txt。
  6. 若 route 为 rewrite：生成 output/compose_rewrite_prompt.txt 后退出。
  7. Codex 生成 JSON 响应，保存到 output/compose_rewrite_response.txt。
  8. 重跑脚本，生成 output/compose_rereview_prompt.txt 后退出。
  9. Codex 生成 JSON 响应，保存到 output/compose_rereview_response.txt。
  10. 再次重跑脚本，输出最终结果。

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

    continue_prompt_path = output_dir / "compose_continue_prompt.txt"
    continue_response_path = output_dir / "compose_continue_response.txt"
    if continue_response_path.exists():
        response = _read_response_text(continue_response_path)
        plotunit, new_state, new_facts, gaps = cont.parse_response(response)
        try:
            new_facts = admit_new_facts(facts, new_facts, plotunit.unit_id)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
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

    # Step 3: Review
    print("\n" + "=" * 50)
    print("Step 3: Review")
    print("=" * 50)
    review_objects = objects + [plotunit, new_state]
    review_prompt_path = output_dir / "compose_review_prompt.txt"
    review_response_path = output_dir / "compose_review_response.txt"
    if review_response_path.exists():
        response = _read_response_text(review_response_path)
        llm_issues, reminders, route = review.parse_response(response)
        hard_issues = review._hard_rules(review_objects)
        domain_issues = review._domain_rules(review_objects)
        issues = hard_issues + domain_issues + llm_issues
        route = review.resolve_route(issues, route)
    else:
        review_prompt_path.write_text(
            review.build_prompt(review_objects, context="compose"),
            encoding="utf-8",
        )
        print(f"[STEP: REVIEW] Prompt saved: {review_prompt_path}")
        print(f"[WAITING] Generate response to: {review_response_path}")
        print("[RESUME] Re-run this script after saving response")
        return 0
    print(f"Route: {route}")
    print(f"Issues: {len(issues)}")
    print(f"Reminders: {len(reminders)}")
    for reminder in reminders:
        print(
            f"  [{reminder.priority}] {reminder.family}: "
            f"{reminder.trigger_condition} | window={reminder.window} "
            f"-> {reminder.escalation_issue_type}"
        )

    fixes = []

    # Step 4: Rewrite (if route == "rewrite")
    if route == "rewrite":
        blocking_issues = [i for i in issues if i.is_blocking()]
        if not blocking_issues:
            print("Route is rewrite but no blocking issues — treating as pass")
            route = "pass"
        else:
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

            # Step 5: Re-Review
            print("\n" + "=" * 50)
            print("Step 5: Re-Review")
            print("=" * 50)
            compose_rereview_prompt_path = output_dir / "compose_rereview_prompt.txt"
            compose_rereview_response_path = output_dir / "compose_rereview_response.txt"

            if not compose_rereview_response_path.exists():
                compose_rereview_prompt_path.write_text(
                    review.build_prompt(review_objects, context="compose-rereview"),
                    encoding="utf-8",
                )
                print(f"[STEP: REREVIEW] Prompt saved: {compose_rereview_prompt_path}")
                print(f"[WAITING] Generate response to: {compose_rereview_response_path}")
                print("[RESUME] Re-run this script after saving response")
                return 0

            response = _read_response_text(compose_rereview_response_path)
            llm_issues, reminders, route = review.parse_response(response)
            hard_issues = review._hard_rules(review_objects)
            domain_issues = review._domain_rules(review_objects)
            issues = hard_issues + domain_issues + llm_issues
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
    }
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
        print(f"\nCompose blocked: route={route}; candidate state not saved")
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

    serializer.save(final_package, compose_state_path)
    print(f"Saved: {compose_state_path}")
    print("\nCompose complete: PASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
