#!/usr/bin/env python3
"""rewrite_short_form — Rewrite 入口."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.runtime_state import require_continue_runtime_state
from src.boundary_control.validation import NoRegressionValidationUnit
from src.object_state import ReviewIssue
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


def _load_review_issues(review_path: Path) -> list[ReviewIssue]:
    review_data = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(review_data, dict):
        raise ValueError(f"invalid review result object: {review_path}")
    if "issues" not in review_data:
        raise ValueError(f"review result missing required field: issues: {review_path}")
    if not isinstance(review_data["issues"], list):
        raise ValueError(f"review result issues must be a list: {review_path}")
    return [ReviewIssue(**issue) for issue in review_data["issues"]]


def main() -> int:
    review_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/review_result.json")
    if not review_path.exists():
        print(f"Error: Review result not found: {review_path}")
        return 1

    try:
        issues = _load_review_issues(review_path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    blocking = [i for i in issues if i.is_blocking()]

    if not blocking:
        print("No blocking issues to rewrite")
        return 0

    # 加载对象状态（从 rebuild_package.json 或 extend_result.json）
    # 简化：先支持 audit 路径，从 rebuild_package.json 加载
    package_path = Path("output/rebuild_package.json")
    if not package_path.exists():
        print(f"Error: blocking rewrite requires object state package: {package_path}")
        return 1

    serializer = SerializationBoundaryUnit()
    pkg = serializer.load(package_path)
    if not _validate_no_regression(pkg):
        return 1
    objects = serializer.deserialize_package(pkg)
    try:
        require_continue_runtime_state(objects)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    rewrite = RewriteUnit()
    rewrite_prompt_path = Path("output/rewrite_prompt.txt")
    rewrite_response_path = Path("output/rewrite_response.txt")

    # 检查 response 是否存在
    if rewrite_response_path.exists():
        # 解析并应用修复
        response = _read_response_text(rewrite_response_path)
        fixes = rewrite.parse_response(response)
        print(f"Parsed {len(fixes)} fixes")

        try:
            applied = rewrite.apply_required_fixes(objects, fixes)
        except ValueError as exc:
            print(f"Rewrite failed: {exc}")
            return 1
        for fix in fixes:
            print(f"Applied: {fix.get('target_type')}.{fix.get('field')} -> {fix.get('action')}")

        print(f"\nRewrite complete: {applied}/{len(fixes)} applied")

        # 保存修复后的对象状态
        if objects:
            serializer = SerializationBoundaryUnit()
            rewritten_package = serializer.build_package(*objects)
            if not _validate_no_regression(rewritten_package):
                return 1
            serializer.save(rewritten_package, Path("output/rebuild_package.json"))
            print("Saved: output/rebuild_package.json (rewritten)")

        # 保存修复后的状态（简化：保存 fixes 列表）
        result = {
            "original_issues": [i.model_dump(mode="json") for i in blocking],
            "fixes": fixes,
            "applied_count": applied,
        }
        Path("output/rewrite_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("Saved: output/rewrite_result.json")
        return 0

    # response 不存在：生成 prompt
    prompt = rewrite.build_prompt(blocking, objects, context="rewrite")
    rewrite_prompt_path.write_text(prompt, encoding="utf-8")
    print(f"[STEP: REWRITE] Prompt saved: {rewrite_prompt_path}")
    print(f"[WAITING] Generate response to: {rewrite_response_path}")
    print("[RESUME] Re-run this script after saving response")
    return 0


if __name__ == "__main__":
    sys.exit(main())
