"""Context Firewall —— Chapter Packet（V2 核心之三：上下文隔离）.

V2 与 V1 最大架构区别：
- V1：Full State → Prompt → 正文（诱导模型"既然告诉我就写出来"）。
- V2：Full State → Candidate Pool → Selection → Chapter Packet → 正文。

正文生成器【原则上看不到完整 State】，只能看到 Chapter Packet：
- 本章实际需要的 Canon
- 当前场景人物所需知识
- SELECT Candidate
- 必要关系状态
- 必要行为约束（隐藏计划 → 行为约束，不传完整计划）
- 当前允许 Reveal 的信息
- Work Model 中与本章直接相关的组织规律

禁止正文模型看到：BACKGROUND / DORMANT / 完整 Thread Graph / 所有长期计划 /
不相关人物状态 / 当前不允许揭示的秘密。

这样 Silence 不再依赖"模型自觉不要写"，而是"正文模型根本拿不到不该写的素材"。
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.statemodel import Provenance
from src.workflow_action.candidate_pool import Candidate
from src.workflow_action.narrative_selector import SelectionResult


class ChapterPacket(BaseModel):
    """正文模型唯一可见的上下文包."""

    model_config = ConfigDict(extra="forbid")

    chapter: Optional[int] = Field(default=None, description="章节号")
    # 本章真正需要的 Canon（最小集，不是全部事实）
    canon_required: list[str] = Field(default_factory=list, description="本章需要的正文确认事实")
    # 当前场景人物所需知识（按人物，非全量）
    scene_character_knowledge: list[str] = Field(
        default_factory=list, description="当前场景人物需要知道/持有的信息"
    )
    # SELECT 候选（正文要写的）
    selected: list[Candidate] = Field(default_factory=list, description="本章入镜候选")
    # 必要关系状态（只给涉及本章人物的关系，非全量）
    necessary_relations: list[str] = Field(default_factory=list, description="必要关系状态")
    # 行为约束（隐藏计划 → 约束，不传完整计划）
    behavior_constraints: list[str] = Field(
        default_factory=list, description="行为约束（含未公开动机的克制表述）"
    )
    # 允许 Reveal 的信息（Reader Knowledge 允许揭露的部分）
    allowed_reveals: list[str] = Field(default_factory=list, description="本章允许向读者揭示的信息")
    # 与本章直接相关的 Work 组织规律
    work_organization: list[str] = Field(default_factory=list, description="作品本章相关组织规律")

    def is_empty(self) -> bool:
        return not (
            self.canon_required or self.scene_character_knowledge or self.selected
            or self.necessary_relations or self.behavior_constraints
            or self.allowed_reveals or self.work_organization
        )

    def render(self) -> str:
        """渲染【本章上下文包】注入段（空则空串，零成本）."""
        if self.is_empty():
            return ""
        lines = ["【本章上下文包】（本章真正需要的内容；未列入的世界状态请勿提及）"]
        if self.selected:
            lines.append("本章应自然承载：")
            for c in self.selected:
                lines.append(f"- {c.current_change or c.source_thread}")
        if self.canon_required:
            lines.append("本章事实前提：")
            for f in self.canon_required[:6]:
                lines.append(f"- {f}")
        if self.scene_character_knowledge:
            lines.append("场景人物知识：")
            for k in self.scene_character_knowledge[:6]:
                lines.append(f"- {k}")
        if self.behavior_constraints:
            lines.append("行为约束（不主动解释未公开动机）：")
            for b in self.behavior_constraints[:4]:
                lines.append(f"- {b}")
        if self.allowed_reveals:
            lines.append("本章可向读者揭示：")
            for r in self.allowed_reveals[:4]:
                lines.append(f"- {r}")
        if self.work_organization:
            lines.append("作品组织规律（本章相关）：")
            for w in self.work_organization[:4]:
                lines.append(f"- {w}")
        return "\n".join(lines)


def build_chapter_packet(
    selection: SelectionResult,
    canon_required: Optional[list[str]] = None,
    scene_character_knowledge: Optional[list[str]] = None,
    necessary_relations: Optional[list[str]] = None,
    behavior_constraints: Optional[list[str]] = None,
    allowed_reveals: Optional[list[str]] = None,
    work_organization: Optional[list[str]] = None,
    chapter: Optional[int] = None,
) -> ChapterPacket:
    """从 SelectionResult 构建 Chapter Packet.

    - 只取 SELECT 候选（BACKGROUND / DORMANT 不进包 → 正文看不到）
    - 隐藏计划 → 转成行为约束（不传完整计划，防提前解释）
    - allowed_reveals 只含允许揭示的信息
    """
    return ChapterPacket(
        chapter=chapter,
        canon_required=canon_required or [],
        scene_character_knowledge=scene_character_knowledge or [],
        selected=list(selection.selected),
        necessary_relations=necessary_relations or [],
        behavior_constraints=behavior_constraints or [],
        allowed_reveals=allowed_reveals or [],
        work_organization=work_organization or [],
    )
