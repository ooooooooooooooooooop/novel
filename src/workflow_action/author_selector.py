"""MultiViewSelector — 多视角选择（作者性第三工作包 §14-20）.

四层判断，**禁止 `score=max`**（禁止 1：不做 `aesthetic_score=8.73` 选最高分；
Consistency / Reader / Style / Author 是四个不同的问题，压成一个标量最终必然
变成「大众平均评价最大化」，而不是作者性）：

1. **Consistency Gate**（硬约束，可阻断）：事实冲突/时间错/世界违反/角色知识
   越界/严重失真/无状态变化/伏笔逻辑错/信息通道违反。复用 `review._hard_rules`
   与候选 new_state 匹配检查。阻断 → 候选淘汰。
2. **Reader Model**（外部信号，**不阻断**）：现有 7 维 + 第 8 维 Interpretive
   Space（§17）——识别 AI 是否过度替人物/读者完成意义解释。本模块提供确定性
   离线代理；真实 Reader 是 LLM-judge（协议不变）。
3. **StyleProfile**（文风）：是否符合当前作品表达方式。但不能决定「故事该发生
   什么」。
4. **Author Evaluation**：初期 Kernel 不存在，先只记理由；Kernel 长出来后
   按六部打分（禁忌可否决——Costly Taste 的机制）。

Selector 工作方式（§20）：
```
A/B/C/D/E → Consistency Gate 淘汰 A、D → 剩 B/C/E
→ Reader/Style/Author 多视角比较 → 最终选择
```
允许「Reader 说 B 最好、Style 说 C 最稳、Author 说 E 更符合长期选择结构」
→ 最终选 E 完全合法，但**必须记录为什么愿意放弃 B 的读者优势**（tradeoff，
喂给 ChoiceLedger）。

选择偏好是**字典序**（作者对齐 → 文风 → 读者），不是加权总分：
保证每个候选的多视角表 + 拒绝理由 + tradeoff 全量留痕，信息不丢失。
"""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.object_state.authorkernel import (
    AuthorKernel,
    value_direction,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    RejectedRecord,
)
from src.object_state.styleprofile import StyleProfile
from src.workflow_action.authormemory import infer_value_conflicts
from src.workflow_action.continuation import ContinueUnit
from src.workflow_action.proposal_generator import candidate_label
from src.workflow_action.review import ReviewUnit


# ---------------------------------------------------------------------------
# 评估 schema
# ---------------------------------------------------------------------------
class CandidateEvaluation(BaseModel):
    """单个候选的四视角评估表."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="候选标签 A/B/C...")
    unit_id: str = Field(description="PlotUnit.unit_id")
    consistency_pass: bool = Field(description="Consistency Gate 是否通过")
    consistency_issues: list[dict] = Field(
        default_factory=list, description="Gate 命中的硬问题（blocking 阻断）"
    )
    reader_score: float = Field(ge=0, le=1, description="Reader 代理分（不阻断）")
    reader_notes: list[str] = Field(default_factory=list, description="Reader 诊断")
    style_score: float = Field(ge=0, le=1, description="文风吻合分（不阻断）")
    style_notes: list[str] = Field(default_factory=list, description="文风诊断")
    author_score: float = Field(ge=0, le=1, description="作者对齐分（Kernel 未形成=0.5）")
    author_notes: list[str] = Field(default_factory=list, description="作者视角理由")
    author_veto: bool = Field(
        default=False, description="作者硬禁忌否决（stable 禁忌命中）"
    )
    value_conflicts: list[str] = Field(
        default_factory=list, description="该候选触及的价值冲突（受限词汇表键）"
    )
    tradeoff_hint: str = Field(default="", description="LLM 附带的候选取舍提示")


class SelectionOutcome(BaseModel):
    """一次选择的结果（含全量多视角表，供 ChoiceRecord 落盘）."""

    model_config = ConfigDict(extra="forbid")

    selected_label: str
    evaluations: dict[str, CandidateEvaluation] = Field(
        description="label → 多视角评估表（含被淘汰者，禁止 4）"
    )
    rejected: list[dict] = Field(
        description="[{label, reason}] 被否候选及其理由（禁止 4）"
    )
    tradeoff: str = Field(description="放弃 X 换取 Y")
    value_conflicts: list[str] = Field(
        description="本次决策触及的价值冲突（全候选并集）"
    )
    all_vetoed: bool = Field(description="所有候选都被作者硬禁忌否决（仍须选一）")


# ---------------------------------------------------------------------------
# 视角代理（确定性离线；真实运行可换 LLM judge，协议不变）
# ---------------------------------------------------------------------------
_READER_RESOLUTION_MARKERS = (
    "终于明白", "彻底想通", "顿悟", "释然", "想通了", "恍然大悟",
    "从此改变了", "彻底改变",
)


def _package_text(package: dict) -> str:
    """候选的结构文本（goal/conflict/hook/consequences + scene_experience + hint）."""
    pu = package["plotunit"]
    parts = [
        pu.goal,
        pu.conflict,
        pu.hook or "",
        " ".join(pu.consequences),
        " ".join(pu.released_information),
    ]
    se = pu.scene_experience
    if se is not None:
        parts += [se.protagonist_sees, se.choice_grounding, se.outcome, se.cognition_shift]
        parts += se.obstacles
    parts.append(package.get("tradeoff_hint", ""))
    return " ".join(parts)


def reader_proxy_score(package: dict) -> tuple[float, list[str]]:
    """第 8 维 Interpretive Space 的确定性离线代理（§17）.

    诚实标注：真实 Reader 是 LLM-judge（外部信号，不阻断）；这里是纯代码启发式，
    只捕捉显式可量化的过度解释信号。扣分项=过度替人物/读者完成意义解释；
    加分项=现场感（scene_experience）存在、允许 unresolved。
    """
    pu = package["plotunit"]
    se = pu.scene_experience
    score = 0.5
    notes: list[str] = []

    if se is not None:
        score += 0.1  # 现场感五维存在（presence）
    else:
        notes.append("缺 scene_experience：现场感弱")

    # Interpretive Space 过度解释信号
    if se is not None and any(m in se.cognition_shift for m in _READER_RESOLUTION_MARKERS):
        score -= 0.15
        notes.append("认知立即产意义/过度理解自己（解析式收尾）")
    if se is not None and se.cognition_states:
        if "unresolved" in se.cognition_states:
            score += 0.1
            notes.append("允许 unresolved：不强行赋意义")
        else:
            score -= 0.05
            notes.append("认知状态未含 unresolved：不给留白")

    if not pu.hook:
        score -= 0.1
        notes.append("无钩子：章末悬念缺失")
    if not pu.consequences:
        score -= 0.1
        notes.append("无可见后果：反馈弱")

    score = max(0.0, min(1.0, score))
    return score, notes


def style_proxy_score(package: dict, style_profile: Optional[StyleProfile]) -> tuple[float, list[str]]:
    """文风吻合离线代理：禁忌词命中扣分（真实文风评判在正文层）."""
    if style_profile is None:
        return 0.5, ["无风格档案，文风视角中性"]
    text = _package_text(package)
    taboo = [w for w in style_profile.taboo_words if w and w in text]
    if taboo:
        penalty = min(0.4, 0.1 * len(taboo))
        return max(0.0, 1.0 - penalty), [f"命中作者禁忌词 {len(taboo)} 处: {taboo[:3]}"]
    return 1.0, ["无禁忌词命中"]


def author_proxy_score(
    package: dict, kernel: Optional[AuthorKernel]
) -> tuple[float, bool, list[str], list[str]]:
    """作者对齐离线代理：六部原则方向命中（禁忌可否决=Costly Taste 机制）.

    方向敏感（§23）：pro=符合价值/回避禁忌，contra=牺牲价值/犯禁忌；
    只有 contra 命中禁忌才可否决。Returns: (score 0-1, veto, notes, conflicts)
    """
    text = _package_text(package)
    conflicts = infer_value_conflicts(text)
    if kernel is None or not kernel.all_principles():
        return 0.5, False, ["kernel 未形成，作者视角中性"], conflicts

    score = 0.5
    notes: list[str] = []
    veto = False
    for p in kernel.all_principles():
        if p.status not in ("stable", "weak"):
            continue
        direction = value_direction(text, p.vocab_key)
        if direction is None:
            continue
        if p.category == "prohibition":
            if direction == "contra":
                penalty = 0.25 * p.strength
                score -= penalty
                notes.append(f"命中禁忌[{p.vocab_key}]（-{penalty:.2f}）")
                if p.strength >= 0.6 and p.status == "stable":
                    veto = True  # 硬禁忌：候选被作者否决（Reader 可能更高 → 记录 tradeoff）
            else:
                score += 0.1 * p.strength
                notes.append(f"回避禁忌[{p.vocab_key}]（+{0.1 * p.strength:.2f}）")
        elif p.category in ("value", "commitment"):
            if direction == "pro":
                bonus = 0.2 * p.strength
                score += bonus
                notes.append(f"符合{p.category}[{p.vocab_key}]（+{bonus:.2f}）")
            else:
                penalty = 0.2 * p.strength
                score -= penalty
                notes.append(f"违背{p.category}[{p.vocab_key}]（-{penalty:.2f}）")
        elif p.category in ("attention_bias", "interpretive_bias"):
            bonus = 0.1 * p.strength
            score += bonus
            notes.append(f"命中{p.category}[{p.vocab_key}]（+{bonus:.2f}）")
        else:  # tension
            notes.append(f"触及张力[{p.vocab_key}]")

    score = max(0.0, min(1.0, score))
    return score, veto, notes, conflicts


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------
def evaluate_candidates(
    packages: list[dict],
    objects: list,
    *,
    kernel: Optional[AuthorKernel] = None,
    style_profile: Optional[StyleProfile] = None,
    current_state_ref: str = "",
    review: Optional[ReviewUnit] = None,
) -> dict[str, CandidateEvaluation]:
    """对 N 个候选做四视角评估.

    Consistency Gate：复用 review._hard_rules + 候选 new_state 匹配检查
    （blocking issue → consistency_pass=False）。
    """
    review = review or ReviewUnit()
    evals: dict[str, CandidateEvaluation] = {}
    for index, package in enumerate(packages):
        label = candidate_label(index)
        pu = package["plotunit"]
        new_state = package["new_state"]

        # ---- Consistency Gate（硬约束，可阻断）----
        consistency_issues: list[dict] = []
        pass_gate = True
        if current_state_ref and pu.input_state_ref != current_state_ref:
            consistency_issues.append(
                {
                    "issue_type": "state_ref",
                    "severity": "blocking",
                    "description": (
                        f"candidate input_state_ref {pu.input_state_ref} != current {current_state_ref}"
                    ),
                }
            )
            pass_gate = False
        if pu.output_state_ref != new_state.state_id:
            consistency_issues.append(
                {
                    "issue_type": "state_ref",
                    "severity": "blocking",
                    "description": (
                        f"candidate output_state_ref {pu.output_state_ref} != "
                        f"new_state.state_id {new_state.state_id}"
                    ),
                }
            )
            pass_gate = False
        hard_issues = review._hard_rules(objects + [pu, new_state])
        for issue in hard_issues:
            consistency_issues.append(issue.model_dump(mode="json"))
            if issue.is_blocking():
                pass_gate = False

        # ---- 三视角（不阻断）----
        reader_score, reader_notes = reader_proxy_score(package)
        style_score, style_notes = style_proxy_score(package, style_profile)
        author_score, author_veto, author_notes, conflicts = author_proxy_score(
            package, kernel
        )

        evals[label] = CandidateEvaluation(
            label=label,
            unit_id=pu.unit_id,
            consistency_pass=pass_gate,
            consistency_issues=consistency_issues,
            reader_score=round(reader_score, 4),
            reader_notes=reader_notes,
            style_score=round(style_score, 4),
            style_notes=style_notes,
            author_score=round(author_score, 4),
            author_notes=author_notes,
            author_veto=author_veto,
            value_conflicts=conflicts,
            tradeoff_hint=package.get("tradeoff_hint", ""),
        )
    return evals


def _selection_preference(
    evals: dict[str, CandidateEvaluation],
    packages: list[dict],
    kernel: Optional[AuthorKernel],
):
    """字典序偏好：作者对齐（若 Kernel 形成）→ 文风 → 读者（禁止 score=max）."""
    has_kernel = kernel is not None and bool(kernel.all_principles())
    if has_kernel:
        def key(label: str):
            e = evals[label]
            return (e.author_score, e.style_score, e.reader_score)
    else:
        def key(label: str):
            e = evals[label]
            return (e.style_score, e.reader_score)
    return key


def select_candidate(
    packages: list[dict],
    evals: dict[str, CandidateEvaluation],
    *,
    kernel: Optional[AuthorKernel] = None,
) -> SelectionOutcome:
    """从评估表中选出最终候选，生成 rejected + tradeoff（非总分）.

    Author 硬禁忌否决：若某候选命中 stable 禁忌，即使 Reader/Style 分高也被
    降级——但**不静默丢弃**：若所有候选都被否决，仍须选一个（all_vetoed=True），
    并把全部否决理由记入 rejected/tradeoff（§21 Costly Taste 的落地）。
    """
    labels = [candidate_label(i) for i in range(len(packages))]
    survivors = [label for label in labels if evals[label].consistency_pass]
    if not survivors:
        raise ValueError("all proposals failed consistency gate")

    vetoed = [label for label in survivors if evals[label].author_veto]
    non_vetoed = [label for label in survivors if not evals[label].author_veto]
    all_vetoed = not non_vetoed
    pool = non_vetoed if non_vetoed else survivors

    key = _selection_preference(evals, packages, kernel)
    selected = max(pool, key=key)

    rejected: list[dict] = []
    for label in labels:
        if label == selected:
            continue
        e = evals[label]
        if not e.consistency_pass:
            blocking = [
                i["description"] for i in e.consistency_issues if i.get("severity") == "blocking"
            ]
            reason = "Consistency Gate 阻断：" + ("；".join(blocking) if blocking else "硬规则不通过")
        elif e.author_veto:
            reason = "作者硬禁忌否决（Reader/Style 可能更高，但违反长期选择边界）"
        else:
            # 多视角落选理由：对比选中的那一维
            se = evals[selected]
            dims = []
            if e.author_score < se.author_score:
                dims.append(f"作者对齐 {e.author_score} < {se.author_score}")
            if e.style_score < se.style_score:
                dims.append(f"文风 {e.style_score} < {se.style_score}")
            if e.reader_score < se.reader_score:
                dims.append(f"读者 {e.reader_score} < {se.reader_score}")
            reason = "多视角落选：" + ("；".join(dims) if dims else "偏好序靠后")
        rejected.append({"label": label, "reason": reason})

    # tradeoff：放弃落选者的优势，换取选中者的优势（逐维对比真实优势，
    # 不做笔记拼接——中性笔记不是"获得"）
    sel_eval = evals[selected]
    gained: list[str] = []
    best_loser = {
        dim: max(
            (getattr(evals[l], dim) for l in labels if l != selected),
            default=0.0,
        )
        for dim in ("author_score", "style_score", "reader_score")
    }
    if sel_eval.author_score > best_loser["author_score"]:
        gained.append(
            f"作者对齐更高（{sel_eval.author_score:.2f} vs 最高落选 {best_loser['author_score']:.2f}）"
        )
    if sel_eval.style_score > best_loser["style_score"]:
        gained.append(
            f"文风吻合更高（{sel_eval.style_score:.2f} vs 最高落选 {best_loser['style_score']:.2f}）"
        )
    if sel_eval.reader_score > best_loser["reader_score"]:
        gained.append(
            f"读者体验更高（{sel_eval.reader_score:.2f} vs 最高落选 {best_loser['reader_score']:.2f}）"
        )
    if best_loser["reader_score"] > sel_eval.reader_score:
        gained.append(
            f"接受 Reader 较低（放弃最高 {best_loser['reader_score']:.2f}，"
            f"选中 {sel_eval.reader_score:.2f}）"
        )
    tradeoff = "换取 ".join(["放弃候选落选者优势"] + gained) if gained else "多视角均衡，无显著取舍"
    if all_vetoed:
        tradeoff += "（注意：所有候选均命中作者禁忌，选的是相对最低伤害）"

    all_conflicts: list[str] = []
    for e in evals.values():
        for c in e.value_conflicts:
            if c not in all_conflicts:
                all_conflicts.append(c)

    return SelectionOutcome(
        selected_label=selected,
        evaluations=evals,
        rejected=rejected,
        tradeoff=tradeoff,
        value_conflicts=all_conflicts,
        all_vetoed=all_vetoed,
    )


def build_choice_record(
    packages: list[dict],
    outcome: SelectionOutcome,
    *,
    decision_id: str,
    decision_timestamp: str,
    plot_context: str,
    state_ref: str,
    character_refs: list[str],
    style_profile_id: Optional[str] = None,
) -> ChoiceRecord:
    """把一次选择落成 ChoiceRecord（禁止 4：含全部被拒候选）. 零 LLM."""
    candidates: list[CandidateRecord] = []
    for index, package in enumerate(packages):
        label = candidate_label(index)
        pu = package["plotunit"]
        candidates.append(
            CandidateRecord(
                candidate_id=label,
                summary=_one_line_summary(package),
                plotunit=pu.model_dump(mode="json"),
                new_state_ref=package["new_state"].state_id,
            )
        )
    selected_label = outcome.selected_label
    rejected = [
        RejectedRecord(candidate_id=r["label"], reason=r["reason"])
        for r in outcome.rejected
    ]
    return ChoiceRecord(
        decision_id=decision_id,
        decision_timestamp=decision_timestamp,
        plot_context=plot_context,
        state_ref=state_ref,
        character_refs=character_refs,
        style_profile_id=style_profile_id,
        candidates=candidates,
        selected_candidate=selected_label,
        rejected=rejected,
        tradeoff=outcome.tradeoff,
        value_conflicts=outcome.value_conflicts,
    )


def _one_line_summary(package: dict) -> str:
    pu = package["plotunit"]
    se = pu.scene_experience
    basis = se.choice_grounding if se is not None else ""
    return f"{pu.goal}｜{pu.conflict}｜{basis or pu.hook or ''}".strip("｜")


def render_selection_report(outcome: SelectionOutcome) -> str:
    """人类可读的选择报告（CLI 打印用）."""
    lines = [f"选中候选: {outcome.selected_label}"]
    lines.append(f"tradeoff: {outcome.tradeoff}")
    lines.append("多视角评估表:")
    for label, e in outcome.evaluations.items():
        gate = "PASS" if e.consistency_pass else "BLOCK"
        lines.append(
            f"  [{label}] gate={gate} reader={e.reader_score:.2f} "
            f"style={e.style_score:.2f} author={e.author_score:.2f} "
            f"veto={e.author_veto}"
        )
        for note in e.author_notes:
            lines.append(f"      author: {note}")
        for note in e.reader_notes:
            lines.append(f"      reader: {note}")
        for note in e.style_notes:
            lines.append(f"      style: {note}")
        if not e.consistency_pass:
            for issue in e.consistency_issues:
                if issue.get("severity") == "blocking":
                    lines.append(f"      block: {issue.get('description')}")
    lines.append("被否候选理由:")
    for r in outcome.rejected:
        lines.append(f"  {r['label']}: {r['reason']}")
    return "\n".join(lines)
