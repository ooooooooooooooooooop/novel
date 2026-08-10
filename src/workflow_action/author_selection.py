"""author_selection — 作者感知选择链 CLI 助手（compose/extend 共用）.

把「解析 N 候选 → 多视角评估 → 选择 → ChoiceLedger → Shadow → Drift Review」
整条作者感知链封装为一步，供 compose_short_form / extend_short_form 的 Continue
步骤在 `--proposals > 1` 时调用（阶段四：多候选选择 + 6C Shadow + 6E Drift）。

零成本契约（§10）：
- `--proposals 1`（默认）完全不调用本模块：N=1 走原 Continue，prompt 字节不变。
- kernel 未形成 / 无风格档案时各视角中性（0.5），不产生额外文件。
- 幂等：选择侧车（ChoiceLedger / ShadowLedger / ChallengeLedger）按 decision_id
  去重——Review 等后续阶段保存 response 后重跑，不产生重复记录。

隐私：侧车含作品语境（候选/理由/tradeoff），存 novels/<名>/output/<mode>/，
本地 gitignored，不入风格库。
"""

import datetime
from pathlib import Path
from typing import Optional

from src.object_state.authorkernel import AuthorKernel
from src.object_state.styleprofile import StyleProfile
from src.workflow_action.authormemory import (
    load_author_kernel,
    save_author_kernel,
)
from src.workflow_action.author_selector import (
    build_choice_record,
    evaluate_candidates,
    render_selection_report,
    select_candidate,
)
from src.workflow_action.choiceledger import append_choice_record, load_choice_ledger
from src.workflow_action.consolidation import (
    ConsolidationResult,
    consolidate_ledger,
    render_consolidation_report,
)
from src.workflow_action.drift_review import (
    ChallengeLedger,
    load_challenge_ledger,
    record_challenge,
    review_author_drift,
    save_challenge_ledger,
)
from src.workflow_action.proposal_generator import candidate_label
from src.workflow_action.review import ReviewUnit
from src.workflow_action.shadow import (
    ShadowLedger,
    load_shadow_ledger,
    record_shadow_comparison,
    render_shadow_comparison,
    run_shadow_selection,
    save_shadow_ledger,
)
from src.workflow_action.style import resolve_style_library_path

# 攒够 N 条 ChoiceRecord 才开始归纳内核（§22：攒 N 个 ChoiceRecord 后；禁止 5：
# 短期压力与长期身份分离——不每条选择都改 Kernel）。
CONSOLIDATION_MIN_CHOICES = 5


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def maybe_consolidate_and_save(
    output_dir: Path,
    *,
    timestamp: str,
    min_choices: Optional[int] = None,
    min_support: Optional[int] = None,
    contested_ratio: Optional[float] = None,
) -> Optional[ConsolidationResult]:
    """台账攒够后 consolidate → save（Phase 8→9 接线）.

    让真实 ChoiceLedger 能自动长成可消费内核：后续 `--author-mode on` 无 `--kernel`
    时由 `resolve_kernel` → `load_author_kernel` 自动读取（闭环：Choice → Consolidation
    → Kernel → 未来选择）。

    台账不足 / 合并后无 stable/weak 原则时返回 None（零成本，不写文件）。
    """
    ledger = load_choice_ledger(output_dir)
    threshold = min_choices if min_choices is not None else CONSOLIDATION_MIN_CHOICES
    if len(ledger.choices) < threshold:
        return None
    existing = load_author_kernel(output_dir)
    # Author Drift Review 闭环：把 open KernelChallenge 并入反例证据（§43 Growth）
    challenge_dir = output_dir / "drift_review" / "challenge_ledger.json"
    challenges = None
    if challenge_dir.exists():
        challenge_ledger = load_challenge_ledger(challenge_dir)
        if challenge_ledger and challenge_ledger.open_challenges:
            challenges = challenge_ledger.open_challenges
    result = consolidate_ledger(
        ledger,
        kernel=existing,
        timestamp=timestamp,
        challenges=challenges,
        min_support=min_support if min_support is not None else 2,
        contested_ratio=contested_ratio if contested_ratio is not None else 0.5,
    )
    if not any(p.status in ("stable", "weak") for p in result.kernel.all_principles()):
        return None
    path = save_author_kernel(output_dir, result.kernel)
    print(render_consolidation_report(result))
    print(f"AuthorKernel: {path}")
    return result


def load_style_profile(output_dir: Path, style_name: str = "") -> Optional[StyleProfile]:
    """当前生效的 StyleProfile 对象（选择器文风视角；无档案返回 None）."""
    if style_name:
        profile_path = resolve_style_library_path(style_name)
    else:
        profile_path = output_dir.parent / "style" / "style_profile.json"
    if not profile_path.exists():
        return None
    return StyleProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))


def resolve_kernel(output_dir: Path, kernel_path: str = "") -> Optional[AuthorKernel]:
    """作者内核：--kernel PATH 优先，否则作品工作区 author_kernel.json（无则 None）."""
    if kernel_path:
        return AuthorKernel.model_validate_json(
            Path(kernel_path).read_text(encoding="utf-8")
        )
    return load_author_kernel(output_dir)


def build_author_prompt_context(
    output_dir: Path,
    decision_context: str,
    kernel_path: str = "",
) -> str:
    """作者感知注入（§29/§30）：render_kernel_context + render_memory_context.

    供多候选 Proposal prompt 注入（N>=2 时才调用）。Kernel 未形成 / 无相关选择史
    时返回空串 → 零成本，prompt 字节不变。Level 3（选择史 tradeoff）+ Level 4
    （已压缩的长期价值结构）都在这里进入生成模型——让「作者」真正影响候选生成，
    而不只是选择器里的关键词打分。
    """
    from src.workflow_action.authormemory import (
        render_kernel_context,
        render_memory_context,
        select_memory_injections,
    )

    kernel = resolve_kernel(output_dir, kernel_path)
    ledger = load_choice_ledger(output_dir)
    selection = select_memory_injections(ledger, kernel, decision_context)
    parts: list[str] = []
    kc = render_kernel_context(kernel)
    if kc:
        parts.append(kc)
    mc = render_memory_context(selection)
    if mc:
        parts.append(mc)
    return "\n\n".join(parts)


def _package_by_label(packages: list[dict], label: str) -> dict:
    for index, package in enumerate(packages):
        if candidate_label(index) == label:
            return package
    raise ValueError(f"selected label not found: {label}")


# ---------------------------------------------------------------------------
# 语义作者判断者（--author-judge on）：Kernel→Selection 因果集成的生产入口
# ---------------------------------------------------------------------------
class JudgeWaiting(Exception):
    """语义 judge 响应缺失（--author-judge on 且 kernel 已形成）→ [WAITING]."""


def build_author_judge(
    packages: list[dict],
    output_dir: Path,
    kernel: Optional[AuthorKernel],
    *,
    enabled: bool,
) -> Optional[object]:
    """生产语义 judge：启用且 kernel 已形成 → 返回 AuthorJudge；否则 None（fallback）.

    启用但响应缺失 → 写 judge prompt 并抛 JudgeWaiting（operator 填响应后重跑）。
    零成本契约：未启用 / kernel 未形成 → 不产文件，返回 None（关键词代理照旧）。
    """
    if not enabled or kernel is None or not kernel.all_principles():
        return None
    from src.object_state.authorkernel import VALUE_VOCAB_DESCRIPTIONS

    judge_dir = output_dir / "author_judge"
    prompt_path = judge_dir / "prompt.txt"
    resp_path = judge_dir / "response.json"
    if not resp_path.exists():
        judge_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "# 作者视角判断（--author-judge on）",
            "",
            "下面是该作者的选择结构（只含中性方法论原则，不含作品/历史信息），以及本次",
            "续写的 N 个候选方案。对每个候选，相对每条 stable/weak 原则判断方向：",
            "pro=该候选表达/保护这条价值；contra=该候选违反/牺牲这条价值；不命中省略。",
            "按语义判断（候选的实际故事走向），不是字面关键词。",
            "",
            "## 作者选择结构",
        ]
        for p in kernel.all_principles():
            if p.status not in ("stable", "weak"):
                continue
            cat = {
                "value": "价值", "prohibition": "禁忌", "commitment": "承诺",
                "tension": "张力", "attention_bias": "注意偏置",
                "interpretive_bias": "解释偏置",
            }.get(p.category, p.category)
            lines.append(
                f"- [{cat}] {VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)}"
                f"（{p.status}）"
            )
        lines.append("")
        lines.append("## 本次候选")
        for index, package in enumerate(packages):
            pu = package["plotunit"]
            se = pu.scene_experience
            grounding = se.choice_grounding if se is not None else ""
            lines.append(
                f"- 候选 {candidate_label(index)} [{pu.unit_id}]：目标『{pu.goal}』"
                f"冲突『{pu.conflict}』钩子『{pu.hook or ''}』"
                f"后果『{'；'.join(pu.consequences)}』依据『{grounding}』"
            )
        lines += [
            "",
            "## 输出格式（严格 JSON）",
            '{ "judgments": { "<unit_id>": { "<vocab_key>": "pro" | "contra" } } }',
            "只写判定命中的 (候选, 原则)；原则键用 vocab_key。",
        ]
        prompt_path.write_text("\n".join(lines), encoding="utf-8")
        raise JudgeWaiting(str(resp_path))
    return FileAuthorJudge(resp_path, kernel)


class FileAuthorJudge:
    """把 operator 填的语义方向响应适配成 AuthorJudge 协议."""

    def __init__(self, resp_path: Path, kernel: AuthorKernel):
        import json as _json

        data = _json.loads(resp_path.read_text(encoding="utf-8"))
        judgments = data.get("judgments", {})
        valid = {p.vocab_key for p in kernel.all_principles()
                 if p.status in ("stable", "weak")}
        self._directions: dict[str, dict[str, str]] = {
            uid: {k: v for k, v in kv.items() if k in valid}
            for uid, kv in judgments.items()
        }

    def judge_candidate(self, kernel, package, candidate_text, context=""):
        return self._directions.get(package["plotunit"].unit_id, {})


def _selected_text(package: dict) -> str:
    """选中候选的结构文本（Author Drift Review 用，对齐 author_selector._package_text）."""
    pu = package["plotunit"]
    parts = [pu.goal, pu.conflict, pu.hook or "", " ".join(pu.consequences)]
    se = pu.scene_experience
    if se is not None:
        parts += [
            se.protagonist_sees,
            se.choice_grounding,
            se.outcome,
            se.cognition_shift,
        ]
    return " ".join(parts)


def run_author_selection(
    packages: list[dict],
    objects: list,
    *,
    output_dir: Path,
    decision_context: str,
    state_ref: str,
    current_state_ref: str,
    kernel: Optional[AuthorKernel] = None,
    style_profile: Optional[StyleProfile] = None,
    style_profile_id: Optional[str] = None,
    author_mode_on: bool = False,
    shadow_on: bool = False,
    drift_review_on: bool = False,
    review: Optional[ReviewUnit] = None,
    timestamp: Optional[str] = None,
    chapter_number: Optional[int] = None,
    consolidation_min: Optional[int] = None,
    consolidation_min_support: Optional[int] = None,
    consolidation_contested_ratio: Optional[float] = None,
    author_judge: Optional[object] = None,
    contract=None,
) -> dict:
    """跑完整作者感知选择链，落 ChoiceLedger / ShadowLedger / DriftReview 侧车.

    Args:
        packages: proposal_generator 产出的 N 个候选包
        objects: Consistency Gate 用到的对象列表（当前运行时状态对象）
        author_mode_on: 生产选择是否作者感知（--author-mode on = Canary 6D）；
            off（默认）时生产选择用基线字典序（style→reader），kernel 只做影子对照。
        shadow_on: 是否并行跑作者感知影子选择（--shadow on = 6C，B 不进正文）
        drift_review_on: 是否对选中文本做作者漂移审查（--drift-review on = 6E）
        author_judge: 可选语义作者判断者（AuthorJudge 协议）。提供时 kernel 已
            形成则用语义判定（Kernel→Selection 因果集成）；缺省用关键词代理
            （author_proxy_score，零成本契约不变）。

    Returns:
        {
          "selected": 选中的候选包 {"plotunit","new_state","new_facts",...},
          "outcome": SelectionOutcome,
          "decision_id": str,
          "drift_result": DriftReviewResult | None,
        }
    """
    review = review or ReviewUnit()
    evals = evaluate_candidates(
        packages,
        objects,
        kernel=kernel,
        style_profile=style_profile,
        current_state_ref=current_state_ref,
        review=review,
        author_judge=author_judge,
        contract=contract,
    )
    production_kernel = kernel if author_mode_on else None
    outcome = select_candidate(packages, evals, kernel=production_kernel)
    print(render_selection_report(outcome))

    selected = outcome.selected_label
    selected_package = _package_by_label(packages, selected)
    plotunit = selected_package["plotunit"]
    ts = timestamp or _utc_now()
    decision_id = f"dec_{plotunit.unit_id}"

    # ---- ChoiceLedger（禁止 4：全候选 + 拒绝理由 + tradeoff；按 decision_id 幂等）----
    ledger = load_choice_ledger(output_dir)
    if decision_id not in {c.decision_id for c in ledger.choices}:
        record = build_choice_record(
            packages,
            outcome,
            decision_id=decision_id,
            decision_timestamp=ts,
            plot_context=decision_context,
            state_ref=state_ref,
            character_refs=list(plotunit.participants),
            style_profile_id=style_profile_id,
            chapter_number=chapter_number,
        )
        ledger_path = append_choice_record(output_dir, record)
        print(f"ChoiceLedger: {ledger_path}")
        # Phase 8→9：台账攒够后 consolidate → save，使后续 --author-mode on
        # 无 --kernel 时能自动消费 output_dir/author_kernel.json（resolve_kernel 读它）
        maybe_consolidate_and_save(
            output_dir,
            timestamp=ts,
            min_choices=consolidation_min,
            min_support=consolidation_min_support,
            contested_ratio=consolidation_contested_ratio,
        )
    else:
        print(f"ChoiceLedger: {decision_id} 已记录，跳过重复落盘")

    # ---- Shadow Mode（6C，B 不进正文；按 decision_id 幂等）----
    if shadow_on:
        comparison = run_shadow_selection(
            packages,
            objects,
            production_label=selected,
            decision_id=decision_id,
            timestamp=ts,
            state_ref=state_ref,
            kernel=kernel,
            style_profile=style_profile,
            current_state_ref=current_state_ref,
            review=review,
        )
        if comparison is not None:
            shadow_path = output_dir / "shadow" / "shadow_ledger.json"
            shadow_ledger = load_shadow_ledger(shadow_path) or ShadowLedger()
            if decision_id not in {c.decision_id for c in shadow_ledger.comparisons}:
                record_shadow_comparison(shadow_ledger, comparison)
                save_shadow_ledger(shadow_path, shadow_ledger)
            print(render_shadow_comparison(comparison))
            print(f"ShadowLedger: {shadow_path}")

    # ---- Author Drift Review（6E，只出信号不自动 Rewrite；challenge 幂等）----
    drift_result = None
    if drift_review_on:
        drift_result = review_author_drift(
            kernel,
            _selected_text(selected_package),
            tradeoff=outcome.tradeoff,
            decision_id=decision_id,
            timestamp=ts,
        )
        drift_dir = output_dir / "drift_review"
        drift_dir.mkdir(parents=True, exist_ok=True)
        drift_path = drift_dir / "drift_review.json"
        drift_path.write_text(drift_result.model_dump_json(indent=2), encoding="utf-8")
        print(f"Author Drift Review: {drift_result.verdict}")
        print(f"  {drift_result.reason}")
        print(f"DriftReview: {drift_path}")
        if drift_result.challenge is not None:
            challenge_path = drift_dir / "challenge_ledger.json"
            challenge_ledger = load_challenge_ledger(challenge_path) or ChallengeLedger()
            if drift_result.challenge.challenge_id not in {
                c.challenge_id for c in challenge_ledger.challenges
            }:
                record_challenge(challenge_ledger, drift_result.challenge)
                save_challenge_ledger(challenge_path, challenge_ledger)
            print(f"ChallengeLedger: {challenge_path}")

    return {
        "selected": selected_package,
        "outcome": outcome,
        "decision_id": decision_id,
        "drift_result": drift_result,
    }
