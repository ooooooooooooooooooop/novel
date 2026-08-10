"""ProseEvidencePackage — 从待提交正文提取的、可核对的事实/状态断言包.

Q1 核心原则：PlotUnit 是写作意图，正文才是最终事实；状态只能根据通过审查的
实际正文更新。本包把「正文说了什么」固化为带证据锚点的断言，供跨章硬一致性
核对（src/workflow_action/prose_reconcile.py）与提交边界消费
（src/boundary_control/chapter_commit.py）。

每条断言必须携带正文证据片段（evidence 为原文 substring），无证据的结论
不得写入状态。包内断言按 kind 分类，reconcile 阶段按类与上一可信状态、
PlotUnit 预期、TimeBook 逐一核对。
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

EvidenceKind = Literal[
    "fact",  # 明确陈述的事实
    "time",  # 时间/季节/历法断言（含显式闪回标记）
    "entity_status",  # 人物/实体在场与状态（找到/失踪/死亡/在X/离开）
    "prop_identity",  # 道具身份与状态（票根/花瓣/夹在/拈出）
    "relation",  # 角色关系变化
    "choice",  # 作出的选择
    "consequence",  # 选择的可见后果
    "promise",  # 承诺新增/推进/兑现
    "state_change",  # 本章真正发生的状态变化（事件/新事实）
    "meta_text",  # 编辑/生成过程文字（上一章/本章/第N章等元文本泄漏）
]


class ProseEvidenceItem(BaseModel):
    """单条正文断言，带证据锚点."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(description="断言唯一标识")
    kind: EvidenceKind = Field(description="断言类别")
    claim: str = Field(description="从正文提炼的断言，如'时间进入十二月'")
    evidence: str = Field(description="正文证据片段（原文 substring，无证据不得为空）")
    location: str = Field(description="章内位置锚点，如'开头/中段/结尾'或行号")
    flashback_marked: bool = Field(
        default=False,
        description="是否带显式闪回/回忆/往昔标记（合法时间跳跃必须显式标记才放行）",
    )

    @classmethod
    def new(
        cls,
        seq: int,
        kind: EvidenceKind,
        claim: str,
        evidence: str,
        location: str = "",
        flashback_marked: bool = False,
    ) -> "ProseEvidenceItem":
        return cls(
            item_id=f"pe_{seq:03d}",
            kind=kind,
            claim=claim,
            evidence=evidence,
            location=location,
            flashback_marked=flashback_marked,
        )


class ProseEvidencePackage(BaseModel):
    """一章正文的证据包."""

    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(description="包标识，如 run/commit 上下文")
    chapter_ref: str = Field(description="章节标识，如 chapter_24 或 待提交章编号")
    source_text_hash: str = Field(description="草稿正文 SHA-256")
    items: list[ProseEvidenceItem] = Field(default_factory=list, description="断言列表")

    def of_kind(self, kind: EvidenceKind) -> list[ProseEvidenceItem]:
        return [i for i in self.items if i.kind == kind]

    def has_kind(self, kind: EvidenceKind) -> bool:
        return any(i.kind == kind for i in self.items)

    def all_evidence(self) -> list[str]:
        return [i.evidence for i in self.items]
