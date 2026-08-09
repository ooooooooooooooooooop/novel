"""StateModel — Narrative Living State（跨章持续运行态）.

四层模型之一: Author Model × Work Model × State − Generator Bias → next chapter.
本模块实现 State Model 的核心数据结构（Narrative Living State）：
不是"人物状态数据库"，而是"整个故事此刻仍然活着的所有东西"。

设计要点（对齐 output/state_model_v1_design.md）：
- 8 类状态：Factual / Knowledge / Intent / Relationship / Active Thread / Off-screen / Strategic / Narrative
- Thread Graph：节点=人物/组织/线程，边=利益/信息/关系/资源/共同事件
- Memory Provenance：CANON / INFERRED / PLANNED / SIMULATED / UNCERTAIN（防后台模拟污染成事实）
- 压缩层级：ACTIVE / WARM / DORMANT / ARCHIVED（Dormant ≠ Forgotten）
- 零成本契约：StateModel 全 Optional，缺省时不注入、不产生任何产物，prompt 字节不变
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Provenance(str, Enum):
    """状态来源分级（防自我污染）."""

    CANON = "canon"            # 正文明确写出的
    INFERRED = "inferred"      # 从正文推断的
    PLANNED = "planned"        # 规划/前瞻
    SIMULATED = "simulated"    # 后台模拟的可能（未写进正文前不升级为 canon）
    UNCERTAIN = "uncertain"    # 未确认


class CompressionLevel(str, Enum):
    """状态压缩层级（长程不可能无限保存全部状态）."""

    ACTIVE = "active"     # 当前活跃，全量
    WARM = "warm"         # 近期相关，主要字段
    DORMANT = "dormant"   # 压缩为 (身份/重要关系/过去关键事件/离场时目标/后台可能变化)
    ARCHIVED = "archived" # 归档，仅保留指针


# ---------------------------------------------------------------------------
# 八类状态之一：Knowledge State（按人物维护谁知道什么）
# ---------------------------------------------------------------------------

class KnowledgeEntry(BaseModel):
    """某人对某事实/信息的认知状态."""

    model_config = ConfigDict(extra="forbid")

    fact_ref: str = Field(description="事实/信息引用（可与 FactLedger 关联）")
    holder: str = Field(description="知道/误解/部分知道该信息的人物ID")
    status: str = Field(
        description="认知状态: knows / not_knows / misunderstands / partial / withholds"
    )
    detail: str = Field(default="", description="认知的细节/程度说明")
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")
    changed_at: Optional[str] = Field(default=None, description="最近变化章节/时间")


# ---------------------------------------------------------------------------
# 八类状态之二：Intent State（多尺度意图）
# ---------------------------------------------------------------------------

class IntentEntry(BaseModel):
    """某人当前的多尺度意图."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="意图主体（人物/组织）")
    intent_scale: str = Field(
        description="尺度: immediate / short_term / long_term / latent / hidden / imposed"
    )
    intent: str = Field(description="意图内容")
    active: bool = Field(default=True, description="后台意图是否仍活跃（离场不死亡）")
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")


# ---------------------------------------------------------------------------
# 八类状态之三：Relationship State（关系结构，非好感度）
# ---------------------------------------------------------------------------

class RelationshipEntry(BaseModel):
    """两方之间的结构化关系."""

    model_config = ConfigDict(extra="forbid")

    from_entity: str = Field(description="关系发起方")
    to_entity: str = Field(description="关系对象")
    bonds: list[str] = Field(
        default_factory=list,
        description="关系纽带: 亲密/试探/身份距离/共同经历/未说出口信息/互相了解/默契",
    )
    temperature: str = Field(default="", description="当前关系温度（定性描述）")
    why_changed: Optional[str] = Field(default=None, description="关系变化的原因（防 AI 只会 喜欢→更喜欢→冲突→和好）")
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")


# ---------------------------------------------------------------------------
# 八类状态之四：Active Thread State（正在运行的线程）
# ---------------------------------------------------------------------------

class ThreadState(BaseModel):
    """一条正在运行的叙事线程."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(description="线程唯一标识，如 thread_commercial_a")
    thread_type: str = Field(
        description="类型: 人物线/组织线/机构线/家庭线/生活线/战略线/关系线"
    )
    label: str = Field(description="线程名（用户可读）")
    current_state: str = Field(default="", description="当前状态")
    last_chapter: Optional[int] = Field(default=None, description="上次出现章节")
    recent_change: Optional[str] = Field(default=None, description="最近变化")
    next_natural_evolution: Optional[str] = Field(
        default=None, description="下一自然演化可能（供 Chapter Composition 参考）"
    )
    needs_protagonist: bool = Field(
        default=True, description="是否需要主角参与（false=可后台运行）"
    )
    can_background: bool = Field(
        default=False, description="是否可后台运行"
    )
    near_payoff: bool = Field(
        default=False, description="是否接近兑现"
    )
    compression: CompressionLevel = Field(
        default=CompressionLevel.ACTIVE, description="压缩层级"
    )
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")


# ---------------------------------------------------------------------------
# Thread Graph（节点=人物/组织/线程，边=关系/利益/信息/资源/共同事件）
# ---------------------------------------------------------------------------

class ThreadEdge(BaseModel):
    """线程图中连接两个节点的边."""

    model_config = ConfigDict(extra="forbid")

    from_node: str = Field(description="起点节点（人物/组织/线程）")
    to_node: str = Field(description="终点节点")
    edge_type: str = Field(
        description="边类型: 利益/信息/关系/资源/共同事件/联盟/冲突"
    )
    detail: str = Field(default="", description="边的关系说明")
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")


class ThreadGraph(BaseModel):
    """非线性叙事连接图，防止故事退化成任务链."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[str] = Field(default_factory=list, description="节点集合（人物/组织/线程）")
    edges: list[ThreadEdge] = Field(default_factory=list, description="边集合")


# ---------------------------------------------------------------------------
# 八类状态之五：Off-screen Process State（镜头外进程）
# ---------------------------------------------------------------------------

class OffScreenProcess(BaseModel):
    """镜头外仍在运行的进程."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="离场主体（人物/组织/公司/学校/家庭/社会环境）")
    last_seen_chapter: Optional[int] = Field(default=None, description="上次入镜章节")
    background_state: str = Field(
        default="", description="离场期间的当前状态（按时间/意图/环境/资源/关系推演）"
    )
    next_most_likely: Optional[str] = Field(
        default=None, description="最可能发生的事（SIMULATED，非 CANON）"
    )
    events_since: list[str] = Field(
        default_factory=list, description="离场期间已发生的模拟事件（provenance=simulated）"
    )
    provenance: Provenance = Field(
        default=Provenance.SIMULATED,
        description="后台推演默认 SIMULATED；只有写进正文才升级为 CANON",
    )


# ---------------------------------------------------------------------------
# 八类状态之六：Strategic State（战略：观察/判断/站位/等待/触发/兑现）
# ---------------------------------------------------------------------------

class StrategicPosition(BaseModel):
    """某重要人物的战略站位."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="战略主体")
    observation: list[str] = Field(default_factory=list, description="看见什么机会/趋势")
    judgment: list[str] = Field(default_factory=list, description="判断什么")
    positioning: list[str] = Field(default_factory=list, description="做了什么准备/留下什么后手")
    resources_committed: list[str] = Field(default_factory=list, description="调用了什么资源")
    waiting_for: list[str] = Field(default_factory=list, description="在等什么条件（不必现在处理）")
    triggers: list[str] = Field(default_factory=list, description="触发兑现的条件")
    pending_payoffs: list[str] = Field(default_factory=list, description="待兑现的布局")
    provenance: Provenance = Field(default=Provenance.CANON, description="来源分级")


# ---------------------------------------------------------------------------
# 八类状态之七：Narrative Opportunity（叙事关注债务）
# ---------------------------------------------------------------------------

class NarrativeOpportunity(BaseModel):
    """作品此刻在叙事上欠什么（可重新入镜的东西）."""

    model_config = ConfigDict(extra="forbid")

    opp_type: str = Field(
        description="类型: 人物重入/线程回归/关系变现/布局兑现/生活回归/配角发展/节奏调剂"
    )
    description: str = Field(description="机会描述")
    last_seen: Optional[int] = Field(default=None, description="上次出现章节（欠得越久优先级越高）")
    priority: int = Field(default=0, description="优先级（0-10，由欠账时长/重要性推定）")
    provenance: Provenance = Field(default=Provenance.INFERRED, description="来源分级")


# ---------------------------------------------------------------------------
# 容器：StateModel（Narrative Living State）
# ---------------------------------------------------------------------------

class StateModel(BaseModel):
    """跨章持续运行态容器（八类状态 + 线程图 + 后台 + 战略 + 叙事机会）.

    零成本契约：本对象整体 Optional。缺省时（无 StateModel）：
    - 不注入任何 prompt 段
    - 不产生任何检测/产物
    - 续写 prompt 字节与旧版逐字节相同
    """

    model_config = ConfigDict(extra="forbid")

    # Factual（最低价值层，防连续性错误）
    facts: list[str] = Field(default_factory=list, description="最底层事实快照")

    # Knowledge（按人物维护谁知道什么）
    knowledge: list[KnowledgeEntry] = Field(
        default_factory=list, description="谁知道什么/误解什么/隐瞒什么"
    )

    # Reader Knowledge（V2 §4.8：读者当前知道什么，独立于世界/角色/系统）
    reader_known: list[str] = Field(
        default_factory=list, description="读者当前已知的信息（Reader Knowledge）"
    )
    reader_revealed_at: dict[str, str] = Field(
        default_factory=dict, description="信息→在哪个章节向读者揭示（Narrative Timeline）"
    )
    world_timeline: list[str] = Field(
        default_factory=list, description="World Timeline：世界实际发生了什么（可能未向读者揭示）"
    )

    # Intent（多尺度意图，离场不死亡）
    intents: list[IntentEntry] = Field(default_factory=list, description="各方当前意图")

    # Relationship（关系结构 + 变化原因）
    relationships: list[RelationshipEntry] = Field(
        default_factory=list, description="结构化关系"
    )

    # Active Thread（正在运行的线程 + 线程图）
    threads: list[ThreadState] = Field(default_factory=list, description="活跃线程")
    thread_graph: ThreadGraph = Field(
        default_factory=ThreadGraph, description="线程连接图"
    )

    # Off-screen（镜头外进程）
    offscreen: list[OffScreenProcess] = Field(
        default_factory=list, description="镜头外仍在运行的进程"
    )

    # Strategic（战略站位）
    strategic: list[StrategicPosition] = Field(
        default_factory=list, description="重要人物的战略站位"
    )

    # Narrative（叙事关注债务）
    narrative_opportunities: list[NarrativeOpportunity] = Field(
        default_factory=list, description="当前值得重新入镜的机会池"
    )

    # 元数据
    last_chapter: Optional[int] = Field(default=None, description="最近更新章节")

    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        """零成本契约：无任何状态即为空（不注入）."""
        return not (
            self.facts
            or self.knowledge
            or self.intents
            or self.relationships
            or self.threads
            or self.thread_graph.nodes
            or self.thread_graph.edges
            or self.offscreen
            or self.strategic
            or self.narrative_opportunities
            or self.reader_known
            or self.world_timeline
        )

    def render_prompt_section(self) -> str:
        """渲染【跨章状态】注入段；空状态返回空串（零成本）."""
        if self.is_empty():
            return ""
        lines = ["【跨章状态】"]
        if self.threads:
            active = [t for t in self.threads if t.compression == CompressionLevel.ACTIVE]
            if active:
                lines.append("正在运行的线程：")
                for t in active:
                    lines.append(
                        f"- {t.label}（{t.thread_type}）当前：{t.current_state or '—'}"
                        f"{'，接近兑现' if t.near_payoff else ''}"
                        f"{'，可后台运行' if t.can_background and not t.needs_protagonist else ''}"
                    )
        if self.offscreen:
            lines.append("镜头外仍在进行的：")
            for o in self.offscreen[:5]:
                lines.append(f"- {o.entity}：{o.background_state or '—'}")
        if self.strategic:
            lines.append("战略站位：")
            for s in self.strategic:
                parts = []
                if s.waiting_for:
                    parts.append("在等" + "、".join(s.waiting_for))
                if s.pending_payoffs:
                    parts.append("待兑现" + "、".join(s.pending_payoffs))
                if parts:
                    lines.append(f"- {s.entity}：{'；'.join(parts)}")
        if self.narrative_opportunities:
            lines.append("叙事机会（可重新入镜）：")
            for o in sorted(self.narrative_opportunities, key=lambda x: -x.priority)[:5]:
                lines.append(f"- {o.description}")
        return "\n".join(lines)
