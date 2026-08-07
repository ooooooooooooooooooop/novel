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
from src.workflow_action.authormemory import load_author_kernel
from src.workflow_action.author_selector import (
    build_choice_record,
    evaluate_candidates,
    render_selection_report,
    select_candidate,
)
from src.workflow_action.choiceledger import append_choice_record, load_choice_ledger
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


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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


def _package_by_label(packages: list[dict], label: str) -> dict:
    for index, package in enumerate(packages):
        if candidate_label(index) == label:
            return package
    raise ValueError(f"selected label not found: {label}")


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
) -> dict:
    """跑完整作者感知选择链，落 ChoiceLedger / ShadowLedger / DriftReview 侧车.

    Args:
        packages: proposal_generator 产出的 N 个候选包
        objects: Consistency Gate 用到的对象列表（当前运行时状态对象）
        author_mode_on: 生产选择是否作者感知（--author-mode on = Canary 6D）；
            off（默认）时生产选择用基线字典序（style→reader），kernel 只做影子对照。
        shadow_on: 是否并行跑作者感知影子选择（--shadow on = 6C，B 不进正文）
        drift_review_on: 是否对选中文本做作者漂移审查（--drift-review on = 6E）

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
        )
        ledger_path = append_choice_record(output_dir, record)
        print(f"ChoiceLedger: {ledger_path}")
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
