"""RewriteUnit - rewrite workflow action."""

import json

from src.object_state import ReviewIssue
from src.object_state.audit_report import VALID_REWRITE_TARGET_TYPES


class RewriteUnit:
    VALID_FIX_ACTIONS = {"add", "remove", "replace"}
    VALID_FIX_FIELDS = {
        "target_type",
        "target_id",
        "field",
        "action",
        "old_value",
        "new_value",
        "reason",
    }
    REQUIRED_FIX_FIELDS = ("target_type", "field", "action")

    """基于 ReviewIssue 的最小修复单元。"""

    def build_prompt(
        self,
        issues: list[ReviewIssue],
        objects: list,
        context: str = "",
    ) -> str:
        """生成改写 prompt."""
        issue_ctx = []
        for i in issues:
            issue_ctx.append(
                f"- [{i.severity}] {i.issue_type} @ {i.location}: {i.description}\n"
                f"  suggested_fix: {i.suggested_fix or '无'}"
            )

        obj_ctx = []
        for o in objects:
            if hasattr(o, "to_prompt_context"):
                obj_ctx.append(f"【{type(o).__name__}】\n{o.to_prompt_context()}")

        issues_text = "\n".join(issue_ctx)
        objects_text = "\n---\n".join(obj_ctx)

        return f"""你是一位叙事修复专家。请基于以下审查发现的问题，生成最小修复方案。

【修复上下文】
{context}

【当前对象状态】
{objects_text}

【待修复问题】
{issues_text}

【Track 2 约束 - 必须遵守】
- 只修复 same-packet 内的问题
- 不得跨 handoff，不得跨复检补偿
- 每个修复必须有明确的目标对象和字段
- 如果问题超出 same-packet 范围，标记为 cannot_fix 而非猜测

【输出格式】
严格输出 JSON 数组:
[
  {{
    "target_type": "CharacterModel|FactLedger|NarrativeState|PlotUnit|WorldModel|ForeshadowGraph",
    "target_id": "对象ID或留空",
    "field": "字段名，支持点号路径，如 entries.0.confirmed",
    "action": "add|remove|replace",
    "old_value": "可选，用于校验",
    "new_value": "新值",
    "reason": "修复理由"
  }}
]

如果无法修复，返回空数组 []。"""

    def parse_response(self, response: str) -> list[dict]:
        """解析 LLM 改写响应."""
        data = json.loads(response)
        if isinstance(data, list):
            fixes = data
        elif not isinstance(data, dict):
            raise ValueError("rewrite response must be a fix list or an object with fixes")
        else:
            if "fixes" not in data:
                raise ValueError("rewrite response missing required field: fixes")
            extra = sorted(set(data) - {"fixes"})
            if extra:
                raise ValueError(
                    f"rewrite response has unexpected field(s): {', '.join(extra)}"
                )
            fixes = data["fixes"]
            if not isinstance(fixes, list):
                raise ValueError("rewrite response fixes must be a list")
        for index, fix in enumerate(fixes, start=1):
            self._validate_fix_contract(fix, index)
        return fixes

    def _validate_fix_contract(self, fix: dict, index: int) -> None:
        if not isinstance(fix, dict):
            raise ValueError(f"rewrite fix {index} must be an object")

        unknown = sorted(set(fix) - self.VALID_FIX_FIELDS)
        if unknown:
            raise ValueError(
                f"rewrite fix {index} has unexpected field(s): {', '.join(unknown)}"
            )

        missing = [field for field in self.REQUIRED_FIX_FIELDS if field not in fix]
        if missing:
            raise ValueError(
                f"rewrite fix {index} missing required field(s): {', '.join(missing)}"
            )

        for field in self.REQUIRED_FIX_FIELDS:
            value = fix[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"rewrite fix {index} field {field} must be non-empty")

        action = fix["action"]
        if action not in self.VALID_FIX_ACTIONS:
            raise ValueError(f"invalid rewrite fix action: {action}")

        target_type = fix["target_type"]
        if target_type not in VALID_REWRITE_TARGET_TYPES:
            raise ValueError(f"invalid rewrite fix target_type: {target_type}")

    def _resolve_path(self, obj, path: str):
        """按点号路径解析对象属性，支持列表索引和字典键。"""
        current = obj
        for segment in path.split("."):
            current = self._get_path_segment(current, segment)
        return current

    def _set_path(self, obj, path: str, value):
        """按点号路径设置对象属性值。"""
        parent, final_segment = self._resolve_parent(obj, path, create_missing=True)
        self._set_path_segment(parent, final_segment, value)

    def _get_path_segment(self, obj, segment: str):
        if isinstance(obj, list):
            if not segment.isdigit():
                raise IndexError(segment)
            return obj[int(segment)]
        if isinstance(obj, dict):
            return obj[segment]
        return getattr(obj, segment)

    def _set_path_segment(self, obj, segment: str, value):
        if isinstance(obj, list):
            if not segment.isdigit():
                raise IndexError(segment)
            obj[int(segment)] = value
        elif isinstance(obj, dict):
            obj[segment] = value
        else:
            setattr(obj, segment, value)

    def _resolve_parent(self, obj, path: str, create_missing: bool = False):
        segments = path.split(".")
        if not segments:
            raise AttributeError(path)

        current = obj
        for index, segment in enumerate(segments[:-1]):
            try:
                current = self._get_path_segment(current, segment)
            except (AttributeError, IndexError, KeyError):
                if not create_missing:
                    raise
                next_segment = segments[index + 1]
                created = [] if next_segment.isdigit() else {}
                self._set_path_segment(current, segment, created)
                current = created
        return current, segments[-1]

    def _object_identifier(self, obj) -> str | None:
        for field in (
            "character_id",
            "state_id",
            "unit_id",
            "fact_id",
            "thread_id",
            "issue_id",
        ):
            if hasattr(obj, field):
                value = getattr(obj, field)
                return str(value) if value is not None else None
        return None

    def _select_target(self, objects: list, target_type: str, target_id: str | None):
        targets = [o for o in objects if type(o).__name__ == target_type]
        if not targets:
            return None

        if target_id:
            matches = [
                target
                for target in targets
                if self._object_identifier(target) == str(target_id)
            ]
            if len(matches) == 1:
                return matches[0]
            return None

        if len(targets) == 1:
            return targets[0]
        return None

    def apply_fix(self, objects: list, fix: dict) -> bool:
        """尝试应用单条修复到对象列表。

        Returns:
            True if applied, False if skipped.
        """
        target_type = fix.get("target_type")
        target_id = fix.get("target_id")
        field = fix.get("field")
        action = fix.get("action")
        new_value = fix.get("new_value")
        old_value = fix.get("old_value")

        if not target_type or not field:
            return False

        target = self._select_target(objects, target_type, target_id)
        if target is None:
            return False

        try:
            current = self._resolve_path(target, field)
        except (AttributeError, IndexError, KeyError):
            if action == "add" and old_value is None:
                current = None
            else:
                return False

        if old_value is not None and str(current) != str(old_value):
            print(f"[REWRITE SKIP] {target_type}.{field} old_value mismatch")
            return False

        if action == "replace":
            self._set_path(target, field, new_value)
            return True

        if action == "add":
            if isinstance(current, list):
                current.append(new_value)
                return True
            if isinstance(current, dict):
                if isinstance(new_value, dict):
                    current.update(new_value)
                    return True
                return False
            try:
                parent, final_segment = self._resolve_parent(target, field)
            except (AttributeError, IndexError, KeyError):
                return False
            if isinstance(parent, dict):
                parent[final_segment] = new_value
                return True

        if action == "remove":
            if isinstance(current, list) and new_value in current:
                current.remove(new_value)
                return True
            if isinstance(current, dict):
                key = new_value if new_value is not None else old_value
                if key in current:
                    current.pop(key)
                    return True
                return False
            try:
                parent, final_segment = self._resolve_parent(target, field)
            except (AttributeError, IndexError, KeyError):
                return False
            if isinstance(parent, list):
                value_to_remove = old_value if old_value is not None else current
                if value_to_remove in parent:
                    parent.remove(value_to_remove)
                    return True
            if isinstance(parent, dict) and final_segment in parent:
                parent.pop(final_segment)
                return True

        return False

    def apply_required_fixes(self, objects: list, fixes: list[dict]) -> int:
        """Apply a rewrite response that is required to fix blocking issues."""
        if not fixes:
            raise ValueError("rewrite produced no fixes for blocking issues")

        applied = 0
        for index, fix in enumerate(fixes, start=1):
            if self.apply_fix(objects, fix):
                applied += 1
                continue

            target_type = fix.get("target_type", "<missing target_type>")
            field = fix.get("field", "<missing field>")
            action = fix.get("action", "<missing action>")
            raise ValueError(
                f"rewrite fix {index} did not apply: "
                f"{target_type}.{field} -> {action}"
            )

        return applied
