"""NarrativeFrameUnit - long-range narrative planning unit.

This workflow-action unit is not a new core narrative object. It owns the
book -> arc -> chapter -> scene planning frame, cross-level checks, and the
frame context passed to Continue.
"""

from typing import Literal, NotRequired, TypedDict


FrameLevel = Literal["book", "arc", "chapter", "scene"]
FrameStatus = Literal["planned", "active", "completed", "blocked"]
FrameIssueSeverity = Literal["blocking", "warning", "low"]

_LEVEL_RANK: dict[FrameLevel, int] = {
    "book": 0,
    "arc": 1,
    "chapter": 2,
    "scene": 3,
}
_EXPECTED_PARENT: dict[FrameLevel, FrameLevel] = {
    "arc": "book",
    "chapter": "arc",
    "scene": "chapter",
}
_REQUIRED_FRAME_FIELDS = ("frame_id", "level", "title", "purpose", "position", "status")
_FRAME_STATUSES = {"planned", "active", "completed", "blocked"}
_LIST_FRAME_FIELDS = ("target_plotunit_ids", "active_thread_ids")
_OPTIONAL_TEXT_FRAME_FIELDS = ("formula_node", "input_state_ref", "output_state_ref")


class FrameNode(TypedDict):
    """Single long-range narrative frame node."""

    frame_id: str
    level: FrameLevel
    title: str
    purpose: str
    position: str
    status: FrameStatus
    parent_id: NotRequired[str]
    order_index: NotRequired[int]
    formula_node: NotRequired[str]
    target_plotunit_ids: NotRequired[list[str]]
    active_thread_ids: NotRequired[list[str]]
    input_state_ref: NotRequired[str]
    output_state_ref: NotRequired[str]


class FrameCursor(TypedDict):
    """Current position in the narrative frame."""

    current_frame_id: str
    current_level: FrameLevel
    book_id: NotRequired[str]
    arc_id: NotRequired[str]
    chapter_id: NotRequired[str]
    scene_id: NotRequired[str]


class FrameValidationIssue(TypedDict):
    """Hierarchy or cross-level consistency issue."""

    issue_id: str
    issue_type: str
    severity: FrameIssueSeverity
    frame_id: str
    description: str
    suggested_fix: NotRequired[str]


class ContinueFrameContext(TypedDict):
    """Frame context passed to ContinueUnit."""

    cursor: FrameCursor
    current_frame: FrameNode
    parent_chain: list[FrameNode]
    sibling_context: list[FrameNode]
    active_threads: list[str]


class NarrativeFrameUnit:
    """Plan and inspect book -> arc -> chapter -> scene framing.

    Responsibilities:
    - maintain hierarchy
    - check cross-level consistency
    - provide "where are we now" context to Continue

    Non-responsibilities:
    - does not write FactLedger
    - does not expand CharacterModel
    - does not replace NarrativeState
    - does not generate PlotUnit prose
    """

    def build_frame(
        self,
        workspec_context: str,
        structure_template: list[dict],
    ) -> list[FrameNode]:
        """Build a minimal book -> arc -> chapter -> scene frame draft."""
        if not structure_template:
            raise ValueError("structure_template must contain at least one scene node")
        if not isinstance(workspec_context, str) or not workspec_context.strip():
            raise ValueError("workspec_context must be a non-empty string")
        frames: list[FrameNode] = [
            {
                "frame_id": "book_001",
                "level": "book",
                "title": "Book 1",
                "purpose": workspec_context,
                "position": "full",
                "status": "active",
                "order_index": 0,
            },
            {
                "frame_id": "arc_001",
                "level": "arc",
                "title": "Arc 1",
                "purpose": "Primary narrative arc",
                "position": "full",
                "status": "active",
                "parent_id": "book_001",
                "order_index": 0,
            },
            {
                "frame_id": "chapter_001",
                "level": "chapter",
                "title": "Chapter 1",
                "purpose": "Initial chapter progression",
                "position": "full",
                "status": "active",
                "parent_id": "arc_001",
                "order_index": 0,
            },
        ]

        for index, node in enumerate(structure_template, start=1):
            frames.append(
                {
                    "frame_id": f"scene_{index:03d}",
                    "level": "scene",
                    "title": node.get("name", f"Scene {index}"),
                    "purpose": node.get("purpose", ""),
                    "position": node.get("position", "flexible"),
                    "status": "active" if index == 1 else "planned",
                    "parent_id": "chapter_001",
                    "order_index": index - 1,
                    "formula_node": node.get("name", ""),
                    "target_plotunit_ids": [],
                    "active_thread_ids": [],
                }
            )

        return frames

    def get_cursor(self, frames: list[FrameNode]) -> FrameCursor | None:
        """Return the deepest active frame position.

        无 active frame（如整个结构都 completed 后）返回 None——调用方应进入
        no-active-frame 状态，不得继续注入陈旧的终止帧。
        """
        active_frames = [frame for frame in frames if frame["status"] == "active"]
        if not active_frames:
            return None

        current_frame = max(active_frames, key=lambda frame: _LEVEL_RANK[frame["level"]])
        return self._cursor_for_frame(frames, current_frame["frame_id"])

    def set_cursor(
        self,
        frames: list[FrameNode],
        frame_id: str,
    ) -> FrameCursor:
        """Move the active cursor to a specific frame."""
        target = self._require_frame(frames, frame_id)
        active_ids = {frame["frame_id"] for frame in self.get_parent_chain(frames, frame_id)}
        active_ids.add(target["frame_id"])

        for frame in frames:
            if frame["status"] == "active" and frame["frame_id"] not in active_ids:
                frame["status"] = "planned"
            if frame["frame_id"] in active_ids and frame["status"] != "completed":
                frame["status"] = "active"

        return self._cursor_for_frame(frames, frame_id)

    def advance_cursor(self, frames: list[FrameNode]) -> FrameCursor | None:
        """将 cursor 从当前 scene 推进到下一个同层级 scene.

        将当前 scene 标记为 completed，下一个 scene 标记为 active。
        如果没有下一个 scene，同样把当前 scene 标记为 completed（终止帧被消费），
        返回 None——调用方应进入 no-active-frame 状态，不再注入旧终止帧。
        """
        current_cursor = self.get_cursor(frames)
        if current_cursor is None:
            return None
        current_frame = self._require_frame(frames, current_cursor["current_frame_id"])

        if current_frame["level"] != "scene":
            return None

        siblings = self.get_sibling_context(frames, current_frame["frame_id"])
        all_siblings = [current_frame] + siblings
        all_siblings.sort(key=lambda f: f.get("order_index", 0))

        current_idx = None
        for i, frame in enumerate(all_siblings):
            if frame["frame_id"] == current_frame["frame_id"]:
                current_idx = i
                break

        # 终止帧消费：无论有无 successor，当前 scene 都已结束
        current_frame["status"] = "completed"

        if current_idx is None or current_idx + 1 >= len(all_siblings):
            # 无 successor：父链上不再有 active/planned 的子节点时一并完成
            self._complete_ancestors_if_done(frames, current_frame)
            return None

        next_frame = all_siblings[current_idx + 1]
        return self.set_cursor(frames, next_frame["frame_id"])

    def _complete_ancestors_if_done(
        self,
        frames: list[FrameNode],
        scene: FrameNode,
    ) -> None:
        """scene 结束后，若其父 chapter/arc 不再有 active/planned 子节点则一并完成。

        用于终止帧消费：整幕结束后旧 chapter/arc 不再作为 active 指导后续生成，
        进入 no-active-frame 状态（不自动造新 arc，由人工/规划层决定下一幕）。
        """
        frame_by_id = self._index_frames(frames)
        child_of: dict[str, list[FrameNode]] = {}
        for f in frames:
            pid = f.get("parent_id")
            if pid:
                child_of.setdefault(pid, []).append(f)

        cur = scene
        while parent_id := cur.get("parent_id"):
            parent = frame_by_id.get(parent_id)
            if parent is None:
                break
            children = child_of.get(parent["frame_id"], [])
            remaining = [
                c for c in children
                if c.get("status") in ("active", "planned")
            ]
            if remaining:
                break
            parent["status"] = "completed"
            cur = parent

    def get_parent_chain(
        self,
        frames: list[FrameNode],
        frame_id: str,
    ) -> list[FrameNode]:
        """Return the parent chain from book to the current node parent."""
        frame_by_id = self._index_frames(frames)
        current = self._require_frame(frames, frame_id)
        chain: list[FrameNode] = []

        while parent_id := current.get("parent_id"):
            if parent_id not in frame_by_id:
                raise ValueError(f"Missing parent frame: {parent_id}")
            parent = frame_by_id[parent_id]
            chain.append(parent)
            current = parent

        return list(reversed(chain))

    def get_sibling_context(
        self,
        frames: list[FrameNode],
        frame_id: str,
    ) -> list[FrameNode]:
        """Return sibling frames under the same parent and level."""
        current = self._require_frame(frames, frame_id)
        parent_id = current.get("parent_id")
        siblings = [
            frame
            for frame in frames
            if frame.get("parent_id") == parent_id
            and frame["level"] == current["level"]
            and frame["frame_id"] != frame_id
        ]
        return sorted(siblings, key=lambda frame: frame.get("order_index", 0))

    def link_plotunit(
        self,
        frames: list[FrameNode],
        frame_id: str,
        plotunit_id: str,
    ) -> list[FrameNode]:
        """Bind a PlotUnit reference to a frame node."""
        if not isinstance(plotunit_id, str) or not plotunit_id.strip():
            raise ValueError("plotunit_id must be a non-empty string")
        frame = self._require_frame(frames, frame_id)
        target_ids = frame.setdefault("target_plotunit_ids", [])
        if plotunit_id not in target_ids:
            target_ids.append(plotunit_id)
        return frames

    def validate_hierarchy(
        self,
        frames: list[FrameNode],
    ) -> list[FrameValidationIssue]:
        """Check book -> arc -> chapter -> scene parent rules."""
        issues: list[FrameValidationIssue] = []
        frame_by_id = self._index_frames(frames)

        for frame in frames:
            level = frame["level"]
            parent_id = frame.get("parent_id")
            if level == "book":
                if parent_id:
                    issues.append(
                        self._issue(
                            "book_has_parent",
                            "blocking",
                            frame["frame_id"],
                            "Book frame must not have a parent_id",
                        )
                    )
                continue

            if not parent_id:
                issues.append(
                    self._issue(
                        "missing_parent",
                        "blocking",
                        frame["frame_id"],
                        f"{level} frame must have a parent_id",
                    )
                )
                continue

            parent = frame_by_id.get(parent_id)
            if parent is None:
                issues.append(
                    self._issue(
                        "unknown_parent",
                        "blocking",
                        frame["frame_id"],
                        f"Parent frame does not exist: {parent_id}",
                    )
                )
                continue

            expected_parent_level = _EXPECTED_PARENT[level]
            if parent["level"] != expected_parent_level:
                issues.append(
                    self._issue(
                        "invalid_parent_level",
                        "blocking",
                        frame["frame_id"],
                        f"{level} frame parent must be {expected_parent_level}",
                    )
                )

        return issues

    def validate_frame_state(self, frames: object) -> list[FrameValidationIssue]:
        """Validate persisted frame state before it drives Continue."""
        if not isinstance(frames, list):
            return [
                self._issue(
                    "invalid_frame_state",
                    "blocking",
                    "<frames>",
                    "Frame state must be a list of frame nodes",
                )
            ]

        issues: list[FrameValidationIssue] = []
        seen_frame_ids: set[str] = set()

        for index, frame in enumerate(frames):
            frame_ref = f"index_{index}"
            if not isinstance(frame, dict):
                issues.append(
                    self._issue(
                        "invalid_frame_node",
                        "blocking",
                        frame_ref,
                        "Frame node must be an object",
                    )
                )
                continue

            frame_id = frame.get("frame_id")
            if not isinstance(frame_id, str) or not frame_id.strip():
                issues.append(
                    self._issue(
                        "blank_frame_id",
                        "blocking",
                        frame_ref,
                        "Frame node has blank frame_id",
                    )
                )
            elif frame_id in seen_frame_ids:
                issues.append(
                    self._issue(
                        "duplicate_frame_id",
                        "blocking",
                        frame_id,
                        f"Duplicate frame_id: {frame_id}",
                    )
                )
            else:
                seen_frame_ids.add(frame_id)

            for field in _REQUIRED_FRAME_FIELDS:
                if field == "frame_id":
                    continue
                value = frame.get(field)
                if field not in frame or not isinstance(value, str):
                    issues.append(
                        self._issue(
                            "missing_frame_field",
                            "blocking",
                            frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                            f"Frame node missing string field: {field}",
                        )
                    )
                elif not value.strip():
                    issues.append(
                        self._issue(
                            "blank_frame_field",
                            "blocking",
                            frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                            f"Frame node has blank required field: {field}",
                        )
                    )

            level = frame.get("level")
            if isinstance(level, str) and level.strip() and level not in _LEVEL_RANK:
                issues.append(
                    self._issue(
                        "invalid_frame_level",
                        "blocking",
                        frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                        f"Invalid frame level: {level}",
                    )
                )

            status = frame.get("status")
            if isinstance(status, str) and status.strip() and status not in _FRAME_STATUSES:
                issues.append(
                    self._issue(
                        "invalid_frame_status",
                        "blocking",
                        frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                        f"Invalid frame status: {status}",
                    )
                )

            parent_id = frame.get("parent_id")
            if "parent_id" in frame and (
                not isinstance(parent_id, str) or not parent_id.strip()
            ):
                issues.append(
                    self._issue(
                        "blank_parent_id",
                        "blocking",
                        frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                        "Frame node has blank parent_id",
                    )
                )

            order_index = frame.get("order_index")
            if "order_index" in frame and not isinstance(order_index, int):
                issues.append(
                    self._issue(
                        "invalid_order_index",
                        "blocking",
                        frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                        "Frame order_index must be an integer",
                    )
                )

            for field in _LIST_FRAME_FIELDS:
                value = frame.get(field)
                if field in frame and (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) or not item.strip() for item in value)
                ):
                    issues.append(
                        self._issue(
                            "invalid_frame_id_list",
                            "blocking",
                            frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                            f"Frame field must be a list of non-empty strings: {field}",
                        )
                    )

            for field in _OPTIONAL_TEXT_FRAME_FIELDS:
                value = frame.get(field)
                if field in frame and (
                    not isinstance(value, str) or not value.strip()
                ):
                    issues.append(
                        self._issue(
                            "blank_frame_field",
                            "blocking",
                            frame_id if isinstance(frame_id, str) and frame_id else frame_ref,
                            f"Frame node has blank optional field: {field}",
                        )
                    )

        if issues:
            return issues

        typed_frames = frames
        issues.extend(self.validate_hierarchy(typed_frames))
        active_frames = [frame for frame in typed_frames if frame["status"] == "active"]
        if not active_frames:
            # 合法的终止态：整个结构都 completed（幕/全书结束）。
            # 调用方经 get_cursor→None 进入 no-active-frame，不再注入陈旧终止帧。
            return []

        for level in _LEVEL_RANK:
            active_at_level = [frame for frame in active_frames if frame["level"] == level]
            if len(active_at_level) > 1:
                issues.append(
                    self._issue(
                        "multiple_active_frames",
                        "blocking",
                        level,
                        f"Multiple active frames at level: {level}",
                    )
                )

        blocking_hierarchy = [issue for issue in issues if issue["severity"] == "blocking"]
        if blocking_hierarchy:
            return issues

        deepest = max(active_frames, key=lambda frame: _LEVEL_RANK[frame["level"]])
        chain_ids = {
            frame["frame_id"] for frame in self.get_parent_chain(typed_frames, deepest["frame_id"])
        }
        chain_ids.add(deepest["frame_id"])
        extra_active = [
            frame["frame_id"]
            for frame in active_frames
            if frame["frame_id"] not in chain_ids
        ]
        if extra_active:
            issues.append(
                self._issue(
                    "active_frames_outside_cursor_chain",
                    "blocking",
                    deepest["frame_id"],
                    f"Active frames outside cursor chain: {', '.join(extra_active)}",
                )
            )

        return issues

    def require_valid_frame_state(self, frames: object) -> list[FrameNode]:
        """Raise when persisted frame state cannot safely drive runtime."""
        issues = self.validate_frame_state(frames)
        blocking = [issue for issue in issues if issue["severity"] == "blocking"]
        if blocking:
            details = "; ".join(
                f"{issue['issue_type']}({issue['frame_id']}): {issue['description']}"
                for issue in blocking
            )
            raise ValueError(f"invalid frame state: {details}")
        return frames

    def validate_cross_level_consistency(
        self,
        frames: list[FrameNode],
    ) -> list[FrameValidationIssue]:
        """Check parent status against child status."""
        issues: list[FrameValidationIssue] = []

        for parent in frames:
            if parent["status"] != "completed":
                continue
            for child in self._children_of(frames, parent["frame_id"]):
                if child["status"] == "active":
                    issues.append(
                        self._issue(
                            "completed_parent_has_active_child",
                            "warning",
                            parent["frame_id"],
                            "Completed frame has an active child frame",
                            suggested_fix=f"Complete or replan child {child['frame_id']}",
                        )
                    )

        return issues

    def build_continue_context(
        self,
        frames: list[FrameNode],
        cursor: FrameCursor | None,
    ) -> ContinueFrameContext:
        """Build frame context for ContinueUnit.

        cursor 为 None（无 active frame，整个结构已完成）时返回 no-active-frame
        上下文——不再注入陈旧终止帧；由人工/规划层指定下一幕。
        """
        if cursor is None:
            return {
                "cursor": None,
                "current_frame": None,
                "parent_chain": [],
                "sibling_context": [],
                "active_threads": [],
                "no_active_frame": True,
            }
        current_frame = self._require_frame(frames, cursor["current_frame_id"])
        parent_chain = self.get_parent_chain(frames, current_frame["frame_id"])
        sibling_context = self.get_sibling_context(frames, current_frame["frame_id"])
        active_threads = self._collect_active_threads(parent_chain + [current_frame])

        return {
            "cursor": cursor,
            "current_frame": current_frame,
            "parent_chain": parent_chain,
            "sibling_context": sibling_context,
            "active_threads": active_threads,
            "no_active_frame": False,
        }

    def _cursor_for_frame(
        self,
        frames: list[FrameNode],
        frame_id: str,
    ) -> FrameCursor:
        frame = self._require_frame(frames, frame_id)
        chain = self.get_parent_chain(frames, frame_id) + [frame]
        cursor: FrameCursor = {
            "current_frame_id": frame["frame_id"],
            "current_level": frame["level"],
        }
        for item in chain:
            cursor[f"{item['level']}_id"] = item["frame_id"]
        return cursor

    def _require_frame(self, frames: list[FrameNode], frame_id: str) -> FrameNode:
        frame_by_id = self._index_frames(frames)
        if frame_id not in frame_by_id:
            raise ValueError(f"Unknown frame_id: {frame_id}")
        return frame_by_id[frame_id]

    def _index_frames(self, frames: list[FrameNode]) -> dict[str, FrameNode]:
        frame_by_id: dict[str, FrameNode] = {}
        for frame in frames:
            frame_id = frame["frame_id"]
            if not isinstance(frame_id, str) or not frame_id.strip():
                raise ValueError("blank frame_id")
            if frame_id in frame_by_id:
                raise ValueError(f"duplicate frame_id: {frame_id}")
            frame_by_id[frame_id] = frame
        return frame_by_id

    def _children_of(self, frames: list[FrameNode], parent_id: str) -> list[FrameNode]:
        return [frame for frame in frames if frame.get("parent_id") == parent_id]

    def _collect_active_threads(self, frames: list[FrameNode]) -> list[str]:
        active_threads: list[str] = []
        for frame in frames:
            for thread_id in frame.get("active_thread_ids", []):
                if thread_id not in active_threads:
                    active_threads.append(thread_id)
        return active_threads

    def _issue(
        self,
        issue_type: str,
        severity: FrameIssueSeverity,
        frame_id: str,
        description: str,
        suggested_fix: str | None = None,
    ) -> FrameValidationIssue:
        issue: FrameValidationIssue = {
            "issue_id": f"frame_{issue_type}_{frame_id}",
            "issue_type": issue_type,
            "severity": severity,
            "frame_id": frame_id,
            "description": description,
        }
        if suggested_fix:
            issue["suggested_fix"] = suggested_fix
        return issue
