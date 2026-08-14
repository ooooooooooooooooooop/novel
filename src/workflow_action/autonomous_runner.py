"""A1 AutonomousRunner — 单候选闭环章节生产（doc 48 §6 step 2，T3）.

T3 范围：`novel auto` 无 [WAITING]、无 manual 路由；viability `stop` 先于任何
生成调用（stop 后零 provider 调用）；Provider/Schema/预算/证据错误不重试、
不 fallback、不吞异常；崩溃恢复只识别完整提交（recover() 通过且无孤儿），
失败运行不得进入后续上下文。

一个 run_dir 同时充当 flow v3 输出目录：

    run_dir/
      .flow_version                    "3"
      initial_chapter                  run 起点章节号（count↔abs 换算）
      manifest.json                    AutonomousRun 序列化（权威 A1 运行记录）
      terminal.json                    终态快照（终态后一次写入）
      calls/call_000001.json           Provider 调用审计（共享 ledger，崩溃一致）
      state/state_package.json         已提交 SerializationPackage
      state/frames.json                已提交 Frame 状态
      run_manifest.json + run_history/ flow v3 章节提交记录
      chapters/                        提交的 chapter_N.txt（novel_dir/chapters）
      viability_analysis.json          可行性分析（每次 step 零 LLM）
      pre_review_result.json / prose_draft.txt / reader_gate_report.json / …

隐私红线：prompt/正文/思维块/凭证不进审计与 manifest；只存 SHA-256、模型身份、
token 数与费用。Tier 0 staged CLI 语义与旧 release 证据不受影响。

运行状态机：manifest.json 只记录 created / running / 终态（committing 为进程内
瞬态，不落盘——崩溃时磁盘上仍是上一章的 running，由 recover() 判定完整提交）。
"""

from __future__ import annotations

import copy
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from src.boundary_control.chapter_commit import ChapterCommitBoundary, derive_run_id
from src.boundary_control.reader_gate import (
    evaluate_commit_reader_gate,
    write_reader_gate_report,
)
from src.boundary_control.runtime_state import (
    require_continue_runtime_state,
    require_single_object,
)
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.domain_layer.compliance_rules import build_nsfw_context
from src.domain_layer.rules import get_structure_template
from src.llm_interface import DirectAPIInterface
from src.object_state.autonomous import (
    TERMINAL_STATUSES,
    AutonomousDecision,
    AutonomousPolicy,
    AutonomousRun,
    AutonomousUsage,
    ProviderProfile,
    canonical_model_sha256,
    charge_usage,
    transition_autonomous_run,
)
from src.object_state.factledger import FactLedger
from src.object_state.judge_claim import (
    JudgeClaim,
    claim_is_hard_violation,
    soft_axis_score,
)
from src.object_state.plotunit import PlotUnit
from src.object_state.premise_candidate import PremiseCandidate
from src.object_state.prose_candidate import ProseCandidate
from src.object_state.run_manifest import sha256_text
from src.object_state.workspec import WorkSpec
from src.provider_adapter import AnthropicMessagesProvider, AutonomousBudgetLedger
from src.workflow_action.continuation import ContinueUnit, admit_new_facts
from src.workflow_action.continuation_viability import (
    analyze_continuation_viability,
    viability_continue_note,
)
from src.workflow_action.excerpt import (
    append_generated_chapters,
    load_original_style_sample,
    load_recent_excerpts,
)
from src.workflow_action.frame import NarrativeFrameUnit
from src.workflow_action.judge_council import (
    SOFT_AXES,
    build_judge_claim_prompt,
    parse_judge_claims,
)
from src.workflow_action.pareto_tournament import (
    build_anchored_pair_prompt,
    compare_judge_claims,
    pareto_frontier,
    selection_tournament,
)
from src.workflow_action.preference_review import (
    parse_anchored_arbitration,
    parse_with_quality_retry,
)
from src.workflow_action.plan_search import (
    build_plot_batch_prompt,
    compact_text,
    dedup_plan_candidates,
    parse_plot_batch_response,
    plan_candidate_signature,
    state_necessity_violation,
    verify_plan_diversity,
)
from src.workflow_action.precommit import (
    build_evaluator_precommit,
    falsify_blocking,
    falsify_prose_against_precommit,
)
from src.workflow_action.reader_contract import scene_experience_guard_review_issues
from src.workflow_action.reconcile import ReconcileUnit
from src.workflow_action.retrieval import load_retrieval_context
from src.workflow_action.review import ReviewUnit
from src.workflow_action.timebook import build_time_context
from src.workflow_action.autonomous_decision import resolve_autonomous_decision
from src.workflow_action import prose as prose_action
from src.workflow_action.long_horizon import (
    build_rolling_from_plan,
    evaluate_long_horizon_checkpoint,
    load_rolling_summary,
    reconcile,
    save_rolling_summary,
    summarize_prose,
)
from src.object_state.longhorizon import ProseSummary, RollingLongHorizonSummary
from src.workflow_action.premise_search import (
    build_premise_search_prompt,
    match_open_promise_threads,
    parse_premise_candidates,
    project_premise_frames,
    validate_premise_candidate,
)
from src.workflow_action.semantic_seam import (
    character_names,
    detect_event_replay,
    extract_event_fingerprints,
)

# 决策路由 → 运行终态（AutonomousDecisionRoute 无 "completed"；completed 由
# 前置预算检查直接转换，不经由决策解析器）。
_ROUTE_TERMINAL_STATUS = {
    "narrative_stopped": "narrative_stopped",
    "premise_exhausted": "premise_exhausted",
    "quality_exhausted": "quality_exhausted",
    "evaluation_incomplete": "evaluation_incomplete",
    "execution_failed": "execution_failed",
}


class AutonomousRunnerError(RuntimeError):
    """A1 运行器合同违例（非 Provider 错误；不得静默吞掉）。"""


def _orphan_number(path: Path) -> int:
    """chapter_N.txt → N；解析失败返回大数（视为不可管理的孤儿）. """
    try:
        return int(Path(path).stem[len("chapter_"):])
    except (ValueError, IndexError):
        return 10**9


class _SearchPremiseOutcome(NamedTuple):
    """前提搜索结果：成功 → decision=None 且 frames 为新投影帧；失败 → 终态决策."""

    decision: "AutonomousDecision | None"
    frames: "list | None"


class _VariantRecord:
    """一个正文候选的运行期记录（正文只在内存，绝不落盘、绝不进审计/manifest）.

    status 在构造时由硬门禁决定（candidate/rejected）；评审后 JudgeClaim 若含
    硬违例再置 rejected。软轴分数只在 candidate 之间比较。
    """

    __slots__ = (
        "plan_index",
        "prose_candidate",
        "text",
        "code_issues",
        "code_claims",
        "seam_findings",
        "judge_claims",
        "status",
    )

    def __init__(
        self,
        *,
        plan_index: int,
        prose_candidate: ProseCandidate,
        text: str,
        code_issues: list,
        code_claims: list,
        seam_findings: list,
    ) -> None:
        self.plan_index = plan_index
        self.prose_candidate = prose_candidate
        self.text = text
        self.code_issues = code_issues
        self.code_claims = code_claims
        self.seam_findings = seam_findings
        self.judge_claims: list = []
        self.status: str = prose_candidate.status


class AutonomousRunner:
    """单 run 目录的闭环叙事运行器。

    Parameters
    ----------
    run_dir : Path
        A1 运行目录（= flow v3 output_dir）。必须是 ``<novel>/output/<name>`` 形式，
        这样 ``run_dir.parent.parent / "chapters"`` 才解析到该小说正文目录，且
        reader 报告可从 ``run_dir.parent / "reader_experience"`` 载入。
    objects : list | None
        初始对象（WorkSpec/WorldModel/NarrativeState/CharacterModel/FactLedger/
        ForeshadowGraph）。仅全新 run 使用；resume 从 state/state_package.json 载入。
    frames : list | None
        初始 Frame 状态。仅全新 run 使用；缺省从 workspec 构建。
    source_text : str
        原书文本（用于接续锚点/文风参考/去重）；空 = compose 模式。
    reader_contract / time_book / style_context / nsfw_on
        与位置无关的上下文输入（每次调用由 CLI 从权威位置载入并传入）。
    initial_candidates_remaining : int
        每章候选配额（= policy.search.plot_candidates 上限，CLI 传入）。
    """

    def __init__(
        self,
        *,
        run_dir: Path,
        policy: AutonomousPolicy,
        profile: ProviderProfile,
        objects: list | None = None,
        frames: list | None = None,
        source_text: str = "",
        reader_contract=None,
        time_book=None,
        style_context: str = "",
        nsfw_on: bool = False,
        user_home: Path | None = None,
        failpoint=None,
        initial_candidates_remaining: int = 1,
        flow_mode: str = "extend",
    ) -> None:
        if policy.provider_profile_id != profile.profile_id:
            raise AutonomousRunnerError(
                "policy.provider_profile_id must reference profile.profile_id"
            )
        if initial_candidates_remaining < 1:
            raise AutonomousRunnerError(
                "initial_candidates_remaining must be at least 1"
            )
        if flow_mode not in ("compose", "extend"):
            raise AutonomousRunnerError("flow_mode must be compose or extend")
        self.run_dir = Path(run_dir).resolve()
        self.novel_dir = self.run_dir.parent.parent
        self.chapters_dir = self.novel_dir / "chapters"
        self.policy = policy
        self.profile = profile
        self._policy_sha256 = canonical_model_sha256(policy)
        self._profile_sha256 = canonical_model_sha256(profile)
        self._source_text = source_text
        self._reader_contract = reader_contract
        self._time_book = time_book
        self._style_context = style_context
        self._nsfw_on = nsfw_on
        self._failpoint = failpoint
        self._initial_candidates_remaining = initial_candidates_remaining
        self._candidates_remaining = initial_candidates_remaining
        self._initial_premise_candidates = policy.search.premise_candidates
        self._premise_candidates_remaining = self._initial_premise_candidates
        self._accepted_premise = None
        self._flow_mode = flow_mode
        self._last_accepted_candidate_id: str | None = None
        self._started_at = time.monotonic()
        self._judge_quality_retries = 0
        self._user_home = Path(user_home) if user_home else Path.home()
        self._target_chars = (
            policy.chapter.target_chinese_characters_min
            + policy.chapter.target_chinese_characters_max
        ) // 2
        self._serializer = SerializationBoundaryUnit()
        self._cont = ContinueUnit()
        self._review = ReviewUnit()
        self._frame_unit = NarrativeFrameUnit()

        if (self.run_dir / "manifest.json").is_file():
            self._open_resume()
        else:
            self._init_fresh(objects=objects, frames=frames)

    # ---- 构造 / 恢复 ----

    def _init_fresh(self, *, objects: list | None, frames: list | None) -> None:
        if self.run_dir.exists() and any(self.run_dir.iterdir()):
            raise AutonomousRunnerError(
                f"refuse overwrite: run directory is not empty: {self.run_dir}"
            )
        if objects is None:
            raise AutonomousRunnerError("fresh autonomous run requires initial objects")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / ".flow_version").write_text("3", encoding="utf-8")
        self._initial_abs = prose_action.next_chapter_number(self.chapters_dir)
        (self.run_dir / "initial_chapter").write_text(
            str(self._initial_abs), encoding="utf-8"
        )
        if frames is None:
            workspec = require_single_object(objects, WorkSpec)
            structure_template_name = workspec.structure_template or "eight_node"
            frames = self._frame_unit.build_frame(
                workspec_context=workspec.to_prompt_context(),
                structure_template=get_structure_template(structure_template_name),
            )
        self._write_state(objects=objects, frames=frames)
        (self._ledger, self._plan_provider, self._prose_provider,
         self._judge_providers, self._tournament_provider) = self._build_providers()
        self._run = AutonomousRun(
            run_id=self.policy.policy_id,
            policy_id=self.policy.policy_id,
            policy_sha256=self._policy_sha256,
            provider_profile_id=self.profile.profile_id,
            provider_profile_sha256=self._profile_sha256,
            status="created",
        )
        self._persist_manifest()

    def _open_resume(self) -> None:
        raw = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        run = AutonomousRun.model_validate(raw)
        if run.status in TERMINAL_STATUSES:
            raise AutonomousRunnerError(
                f"refuse to reopen terminal autonomous run: {run.status}"
            )
        initial_path = self.run_dir / "initial_chapter"
        if not initial_path.is_file():
            raise AutonomousRunnerError("resume requires an initial_chapter record")
        self._initial_abs = int(initial_path.read_text(encoding="utf-8").strip())
        self._run = run
        self._load_accepted_premise()
        audit_usage = self._usage_from_audits()
        (self._ledger, self._plan_provider, self._prose_provider,
         self._judge_providers, self._tournament_provider) = self._build_providers(
            usage=audit_usage
        )
        if run.status == "created":
            if run.committed_chapters != 0:
                raise AutonomousRunnerError(
                    "created run cannot already have committed chapters"
                )
            return
        if run.status != "running":
            raise AutonomousRunnerError(
                f"unexpected non-terminal run status: {run.status}"
            )
        recovery = ChapterCommitBoundary(self.run_dir, self.chapters_dir).recover()
        if recovery.recognized:
            self._verify_committed_head(recovery)
        elif (
            recovery.reason == "no_manifest"
            and run.committed_chapters == 0
            and not self._filter_orphans(recovery.orphans)
        ):
            # 首章提交前崩溃：磁盘无 flow manifest、A1 记录无已提交章、无
            # 起点之后的孤儿 → 从起点基线安全续跑（重跑被打断的章节）。
            return
        else:
            raise AutonomousRunnerError(
                f"refuse to resume: {recovery.reason}; "
                f"orphans={self._filter_orphans(recovery.orphans)}"
            )

    def _verify_committed_head(self, recovery) -> None:
        orphans = self._filter_orphans(recovery.orphans)
        if orphans:
            raise AutonomousRunnerError(
                "refuse to resume with unmanaged orphan artifacts: "
                + ", ".join(str(o) for o in orphans)
            )
        manifest = recovery.manifest
        if manifest is None or manifest.status != "committed":
            raise AutonomousRunnerError("resume requires a committed flow manifest")
        expected = manifest.chapter_number - self._initial_abs + 1
        if expected < 0:
            raise AutonomousRunnerError("resume chapter arithmetic is inconsistent")
        if self._run.committed_chapters > expected:
            raise AutonomousRunnerError(
                "A1 run record is ahead of the committed flow head; refusing to guess"
            )
        if self._run.committed_chapters < expected:
            # 崩溃发生在 flow commit 之后、A1 manifest 更新之前 → 吸收该提交。
            self._run = self._rebuild_run(committed_chapters=expected)
            self._persist_manifest()

    def _filter_orphans(self, orphans) -> list[Path]:
        """把起点之前的基线章节（原书/既有续写章）排除出孤儿名单."""
        return [
            Path(p) for p in orphans if _orphan_number(Path(p)) >= self._initial_abs
        ]

    def _build_providers(self, usage: AutonomousUsage | None = None):
        ledger = AutonomousBudgetLedger(
            budget=self.policy.budget,
            pricing=self.profile.pricing_usd_per_million_tokens,
            usage=usage,
        )
        plan_provider = AnthropicMessagesProvider(
            profile=self.profile,
            role="generation",
            max_output_tokens=self.policy.chapter.planner_max_output_tokens,
            audit_dir=self.run_dir / "calls",
            ledger=ledger,
            user_home=self._user_home,
        )
        prose_provider = AnthropicMessagesProvider(
            profile=self.profile,
            role="generation",
            max_output_tokens=self.policy.chapter.prose_max_output_tokens,
            audit_dir=self.run_dir / "calls",
            ledger=ledger,
            user_home=self._user_home,
        )
        # T6.1：三个上下文隔离的评审角色，各自独立的 Provider 实例（请求模型
        # 与响应实际模型在审计逐调用记录；profile 冻结要求三角色同一实际模型）。
        judge_providers = {
            role: AnthropicMessagesProvider(
                profile=self.profile,
                role=role,
                max_output_tokens=self.policy.chapter.judge_max_output_tokens,
                audit_dir=self.run_dir / "calls",
                ledger=ledger,
                user_home=self._user_home,
            )
            for role in self.policy.search.judge_roles
        }
        tournament_provider = AnthropicMessagesProvider(
            profile=self.profile,
            role="reader_judge",
            max_output_tokens=self.policy.chapter.judge_max_output_tokens,
            audit_dir=self.run_dir / "calls",
            ledger=ledger,
            user_home=self._user_home,
        )
        return (
            ledger,
            plan_provider,
            prose_provider,
            judge_providers,
            tournament_provider,
        )

    def _usage_from_audits(self) -> AutonomousUsage:
        """从 calls/ 审计重建 ledger usage（崩溃一致：只信任真实发生的调用）."""
        total = AutonomousUsage()
        for path in sorted((self.run_dir / "calls").glob("call_*.json")):
            audit = json.loads(path.read_text(encoding="utf-8"))
            try:
                total = charge_usage(
                    total,
                    self.policy.budget,
                    calls=1,
                    input_tokens=int(audit["input_tokens"]),
                    output_tokens=int(audit["output_tokens"]),
                    cost_usd=Decimal(str(audit["cost_usd"])),
                )
            except ValueError as exc:
                raise AutonomousRunnerError(
                    f"call audit usage exceeds frozen budget: {exc}"
                ) from exc
        return total

    # ---- 持久化 ----

    def _rebuild_run(self, **overrides) -> AutonomousRun:
        """重建 AutonomousRun（frozen 模型），并把 ledger usage 同步进记录.

        ledger 是调用级计账的真源；AutonomousRun.usage 只是持久化快照。崩溃后
        resume 以 calls/ 审计重建 ledger，再经本函数写回 manifest——usage 永不以
        旧 manifest 的瞬时值为准。
        """
        payload = self._run.model_dump(mode="python")
        payload.update(overrides)
        payload["usage"] = self._ledger.usage
        return AutonomousRun.model_validate(payload)

    def _transition(
        self,
        status: str,
        *,
        terminal_reason: str | None = None,
        accepted_candidate_id: str | None = None,
        committed_chapters: int | None = None,
    ) -> AutonomousRun:
        """带 transition 合法性校验 + usage 同步的状态迁移.

        先经 transition_autonomous_run 校验合法迁移（非法迁移 raise），再重建以
        覆盖 usage 快照。所有状态变更必须走本方法，避免 usage 与 ledger 分叉。
        """
        transition_autonomous_run(
            self._run,
            status,
            terminal_reason=terminal_reason,
            accepted_candidate_id=accepted_candidate_id,
            committed_chapters=committed_chapters,
        )
        return self._rebuild_run(
            status=status,
            terminal_reason=terminal_reason,
            accepted_candidate_id=accepted_candidate_id,
            committed_chapters=(
                self._run.committed_chapters
                if committed_chapters is None
                else committed_chapters
            ),
        )

    def _persist_manifest(self) -> None:
        (self.run_dir / "manifest.json").write_text(
            json.dumps(self._run.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _persist_terminal(self) -> None:
        (self.run_dir / "terminal.json").write_text(
            json.dumps(self._run.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_state(self, *, objects: list, frames: list) -> None:
        package = self._serializer.build_package(*objects)
        state_dir = self.run_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state_package.json").write_text(
            json.dumps(package.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (state_dir / "frames.json").write_text(
            json.dumps(frames, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_state(self) -> tuple[list, list]:
        package = self._serializer.load(self.run_dir / "state" / "state_package.json")
        objects = self._serializer.deserialize_package(package)
        frames = json.loads(
            (self.run_dir / "state" / "frames.json").read_text(encoding="utf-8")
        )
        return objects, frames

    # ---- 决策辅助 ----

    def _terminal(self, status: str, reason: str) -> None:
        # completed 契约要求 accepted_candidate_id（至少接受过一章才叫完成）。
        # 其余终态不接受候选 id（AutonomousRun 校验器强制）。
        accepted_candidate_id = (
            self._last_accepted_candidate_id if status == "completed" else None
        )
        self._run = self._transition(
            status,
            terminal_reason=reason,
            accepted_candidate_id=accepted_candidate_id,
        )
        self._persist_manifest()
        self._persist_terminal()
        return None

    def _terminal_from_decision(self, decision: AutonomousDecision) -> AutonomousDecision:
        status = _ROUTE_TERMINAL_STATUS[decision.route]
        reason = "; ".join(decision.reasons)
        self._run = self._transition(status, terminal_reason=reason)
        self._persist_manifest()
        self._persist_terminal()
        return decision

    def _stage_failure(self, stage: str, exc: Exception) -> AutonomousDecision:
        """Provider/Schema/预算/证据错误：只记错误类型，不落详情、不重试.

        评审/仲裁输出协议合规在有界重请求后仍失败（ReviewQualityExhaustedError）时，
        把重请求次数附在类型名后诚实上报（如 ``judge failed: ReviewQualityExhaustedError``
        因 retries=3 耗尽）——这是协议合规的诚实终态，不是网络重试。
        """
        error_label = type(exc).__name__
        if error_label == "ReviewQualityExhaustedError":
            error_label = f"{error_label}(retries={self._judge_quality_retries})"
        decision = resolve_autonomous_decision(
            provider_error=f"{stage} failed: {error_label}",
            viability_verdict="continue",
            premise_candidates_remaining=0,
            required_axes_armed=True,
            reader_route="pass",
            hard_violation=None,
            candidates_remaining=self._candidates_remaining,
            budget_available=True,
            accepted_candidate_id=None,
        )
        return self._terminal_from_decision(decision)

    def _budget_available(self, project_calls: int = 3) -> bool:
        """投影一次候选所需的最少调用数（默认 3 calls = 规划/成文/审查）。

        needs_premise 场景额外投影 1 次前提搜索调用（project_calls=4）：
        搜索调用会先于章节三调用计账，预算不足时应在进入生成前就暴露。
        """
        try:
            charge_usage(
                self._ledger.usage,
                self.policy.budget,
                calls=project_calls,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal("0"),
            )
            return True
        except ValueError:
            return False

    def _invoke(self, provider: AnthropicMessagesProvider, prompt: str) -> str:
        role_config = getattr(provider.profile.roles, provider.role)
        interface = DirectAPIInterface(
            model=role_config.request_model,
            provider_call=provider,
            expected_response_model=role_config.expected_actual_model,
        )
        return interface.call(prompt)

    # ---- T4 前提搜索 / 语义接缝 ----

    def _load_accepted_premise(self) -> None:
        """恢复崩溃前已批准的前提（premise.json 落盘，resume 一致）."""
        premise_path = self.run_dir / "premise.json"
        self._accepted_premise = (
            PremiseCandidate.model_validate(
                json.loads(premise_path.read_text(encoding="utf-8"))
            )
            if premise_path.is_file()
            else None
        )

    def _search_premise(
        self,
        *,
        frames: list,
        narrative_state,
        foreshadows,
        workspec,
        frame_context: dict | None,
        viability,
    ) -> _SearchPremiseOutcome:
        """needs_premise 自动搜索：生成候选 → 确定性验证 → 投影新帧.

        每个候选批消耗 1 次 provider 调用（由 ledger 计账）；批内全部失败则
        消耗一次前提预算重试；预算耗尽 → premise_exhausted。验证是纯代码，
        Provider 无法伪造通过；成功候选投影新 active 帧（写入 state/frames.json），
        使下一次 viability 回到 continue。
        """
        open_threads = foreshadows.get_active() if foreshadows is not None else []
        open_promises = [(thread.thread_id, thread.content) for thread in open_threads]
        attempts = 0
        last_reason = "no viable premise candidate"
        while self._premise_candidates_remaining > 0:
            self._premise_candidates_remaining -= 1
            attempts += 1
            try:
                prompt = build_premise_search_prompt(
                    state_context=narrative_state.to_prompt_context(),
                    workspec_context=workspec.to_prompt_context(),
                    frame_context=frame_context,
                    open_promises=open_promises,
                    contract_context=(
                        self._reader_contract.to_prompt_context()
                        if self._reader_contract
                        else ""
                    ),
                    required_premise=viability.required_premise or "",
                    count=self.policy.search.premise_candidates,
                )
                response = self._invoke(self._plan_provider, prompt)
                candidates = parse_premise_candidates(response)
            except Exception as exc:
                # Provider/Schema/预算错误：只记错误类型，不重试、不落详情。
                return _SearchPremiseOutcome(
                    resolve_autonomous_decision(
                        provider_error=f"premise search failed: {type(exc).__name__}",
                        viability_verdict="needs_premise",
                        premise_candidates_remaining=0,
                        required_axes_armed=True,
                        reader_route="pass",
                        hard_violation=None,
                        candidates_remaining=self._candidates_remaining,
                        budget_available=True,
                        accepted_candidate_id=None,
                    ),
                    None,
                )
            viable: list[PremiseCandidate] = []
            rejections: list[str] = []
            next_chapter_number = self._run.committed_chapters + self._initial_abs + 1
            for candidate in candidates:
                ok, reason = validate_premise_candidate(
                    candidate,
                    foreshadows=foreshadows,
                    frame_context=frame_context,
                    workspec=workspec,
                    contract=self._reader_contract,
                    frames=frames,
                    next_chapter_number=next_chapter_number,
                    recent_chapter_count=self._run.committed_chapters,
                )
                if ok:
                    viable.append(candidate)
                else:
                    rejections.append(f"{candidate.candidate_id}: {reason}")
            self._record_premise_search(
                prompt_sha256=sha256_text(prompt),
                response_sha256=sha256_text(response),
                candidate_ids=[candidate.candidate_id for candidate in candidates],
                accepted_id=viable[0].candidate_id if viable else None,
                rejections=rejections,
            )
            if viable:
                chosen = viable[0]
                matched = match_open_promise_threads(
                    chosen.obligations_to_old_promises, open_threads
                )
                projected = project_premise_frames(
                    chosen,
                    frames,
                    next_chapter_number=next_chapter_number,
                    matched_thread_ids=matched,
                )
                self._accepted_premise = chosen
                self._write_premise(chosen)
                self._write_frames(projected)
                # 新阶段获得全新前提预算（新一轮 needs_premise 可再次搜索）。
                self._premise_candidates_remaining = self._initial_premise_candidates
                return _SearchPremiseOutcome(None, projected)
            last_reason = (
                f"all {len(candidates)} premise candidate(s) failed deterministic validation"
            )
        # 前提预算耗尽：全部批次失败 → premise_exhausted（无 [WAITING]）。
        return _SearchPremiseOutcome(
            resolve_autonomous_decision(
                provider_error=None,
                viability_verdict="needs_premise",
                premise_candidates_remaining=0,
                required_axes_armed=True,
                reader_route="pass",
                hard_violation=None,
                candidates_remaining=self._candidates_remaining,
                budget_available=True,
                accepted_candidate_id=None,
            ),
            None,
        )

    def _write_premise(self, candidate: PremiseCandidate) -> None:
        (self.run_dir / "premise.json").write_text(
            json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_frames(self, frames: list) -> None:
        (self.run_dir / "state" / "frames.json").write_text(
            json.dumps(frames, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _record_premise_search(
        self,
        *,
        prompt_sha256: str,
        response_sha256: str,
        candidate_ids: list,
        accepted_id: str | None,
        rejections: list,
    ) -> None:
        path = self.run_dir / "premise_search.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "searches": []}
        )
        existing["searches"].append(
            {
                "prompt_sha256": prompt_sha256,
                "response_sha256": response_sha256,
                "candidate_ids": candidate_ids,
                "accepted_id": accepted_id,
                "rejections": rejections,
            }
        )
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_seam_findings(self, findings: list) -> None:
        path = self.run_dir / "seam_findings.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "findings": []}
        )
        existing["findings"].extend(
            finding.model_dump(mode="json") for finding in findings
        )
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---- T5 多候选章节生产（G5 证据落盘；正文只进内存）----

    def _projected_chapter_calls(self) -> int:
        """T6 一次章节循环的调用数上界（预算投影，确定性）。

        1 计划批次 + P×V 正文 + 3×P×V 评审（三角色）+ 淘汰赛上界
        2×(P×V−1)×(1+判别轮)。淘汰赛只在上界内消耗；实际上界在无
        位置不一致时为 2×(P×V−1)。
        """
        pv = self.policy.search.plot_candidates * self.policy.search.prose_variants_per_plot
        rounds = self.policy.search.max_decision_rounds
        tournament_upper = 2 * (pv - 1) * (1 + rounds) if pv >= 2 else 0
        return 1 + 4 * pv + tournament_upper

    def _trusted_state_hash(self, narrative_state, facts) -> str:
        """可信状态（facts ledger + 上一 NarrativeState）哈希——锁定评审基线."""
        payload = json.dumps(
            {
                "narrative_state": narrative_state.model_dump(mode="json"),
                "facts": [entry.model_dump(mode="json") for entry in facts.entries],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256_text(payload)

    def _record_plan_candidates(
        self,
        *,
        plans: list,
        deduped: list,
        survivors: list,
        ok: bool,
        reason: str,
        plan_rejections: list,
        chapter_ref: str,
    ) -> None:
        path = self.run_dir / "plan_candidates.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        existing["chapters"][chapter_ref] = {
            "requested": self.policy.search.plot_candidates,
            "parsed": len(plans),
            "after_dedup": len(deduped),
            "survivors": len(survivors),
            "diversity_ok": ok,
            "diversity_reason": reason,
            "plan_rejections": [
                {"axis": axis, "reason": why} for axis, why in plan_rejections
            ],
            "survivor_signatures": [
                plan_candidate_signature(plan) for plan in survivors
            ],
        }
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_precommits(self, precommits: list, chapter_ref: str) -> None:
        path = self.run_dir / "precommits.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        existing["chapters"][chapter_ref] = [
            precommit.model_dump(mode="json") for precommit in precommits
        ]
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_prose_candidates(self, records: list, chapter_ref: str) -> None:
        path = self.run_dir / "prose_candidates.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        existing["chapters"][chapter_ref] = [
            record.prose_candidate.model_dump(mode="json") for record in records
        ]
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_judge_claims(self, claims: list, chapter_ref: str) -> None:
        path = self.run_dir / "judge_claims.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        existing["chapters"][chapter_ref] = [
            claim.model_dump(mode="json") for claim in claims
        ]
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _record_candidate_selection(
        self,
        best,
        best_score,
        records: list,
        frontier: list,
        chapter_ref: str,
        tournament=None,
    ) -> None:
        path = self.run_dir / "candidate_selection.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        record = {
            "selected": (
                best.prose_candidate.candidate_id if best is not None else None
            ),
            "selected_soft_score": best_score,
            "rejected": [
                record.prose_candidate.candidate_id
                for record in records
                if record.status != "candidate"
            ],
            "selection_rule": (
                "hard-axis elimination + soft-axis Pareto frontier + "
                "deterministic compare + evidence-anchored A/B + B/A arbitration (T6)"
            ),
        }
        if frontier:
            record["frontier"] = list(frontier)
            record["soft_dominated"] = [
                record.prose_candidate.candidate_id
                for record in records
                if record.status == "candidate"
                and record.prose_candidate.candidate_id not in frontier
            ]
        if tournament is not None:
            record["position_consistency_rate"] = tournament.position_consistency_rate
            record["pair_count"] = len(tournament.pairs)
        existing["chapters"][chapter_ref] = record
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _prose_variant(
        self,
        plotunit: PlotUnit,
        new_state,
        workspec,
        facts,
        continuation_text: str,
        *,
        plan_label: str,
        variant_index: int,
        variant_count: int,
    ) -> str:
        prompt = prose_action.build_prompt(
            plotunit,
            new_state,
            workspec_context=workspec.to_prompt_context(),
            style_context=self._style_context,
            excerpt_context=load_recent_excerpts(continuation_text),
            original_style_context=load_original_style_sample(self._source_text),
            timeline_context=facts.to_timeline_context(include_header=False),
            time_context=build_time_context(self._time_book),
            prev_chapter_end=prose_action.prev_chapter_tail(continuation_text),
            target_chapter_chars=self._target_chars,
            reuse_source=self._source_text,
        )
        if variant_count > 1:
            prompt = prompt + (
                f"\n\n【多版要求】\n候选 {plan_label} 第 {variant_index + 1}/{variant_count}"
                " 版正文。在完全相同的 PlotUnit、新状态、事实与上文前提下展开，但"
                "展开方式必须与其他版本明显不同（不同的具体场面、动作次序、对白与"
                "意象）；每一版都必须忠于同一 PlotUnit 的输出状态变化。"
            )
        return prose_action.parse_response(
            self._invoke(self._prose_provider, prompt), target_chars=self._target_chars
        )

    def _seam_check(self, draft_text, chapter_number, characters, continuation_text) -> list:
        if not draft_text:
            return []
        return detect_event_replay(
            previous=extract_event_fingerprints(
                prose_action.prev_chapter_tail(continuation_text),
                chapter_number=max(1, chapter_number - 1),
                entities=character_names(characters),
                position="end",
            ),
            new=extract_event_fingerprints(
                draft_text,
                chapter_number=chapter_number,
                entities=character_names(characters),
                position="start",
            ),
        )

    def _record_judge_quality_retry(self, _attempt: int) -> None:
        """有界协议合规重请求计数（评审/仲裁 JSON 解析、锚点捏造等），诚实上报."""
        self._judge_quality_retries += 1

    def _judge_call(
        self, role: str, precommit, prose: str, chapter_ref: str
    ) -> list[JudgeClaim]:
        """T6.1：单角色带锚点评审——评审 prompt 只含该候选预承诺 + 正文 + 契约.

        三角色（fact_judge / character_judge / reader_judge）各自独立调用，评审
        上下文彼此隔离（不读生成 prompt/其他候选）。解析器强制锚点与 precommit_id
        绑定（T5.4），generator_source=角色由运行层注入。

        评审输出协议合规失败（JSON 无法解析/锚点捏造/形状违例）做有界重请求
        （parse_with_quality_retry）：每次重请求是独立全新调用；provider/网络错误
        从调用侧立即上抛，绝不重试。耗尽 → ReviewQualityExhaustedError → 诚实失败。
        """
        prompt = build_judge_claim_prompt(
            precommit,
            prose,
            reader_contract_context=(
                self._reader_contract.to_prompt_context()
                if self._reader_contract
                else ""
            ),
            role=role,
        )
        return parse_with_quality_retry(
            lambda: self._invoke(self._judge_providers[role], prompt),
            lambda text: parse_judge_claims(
                text,
                prose=prose,
                chapter_ref=chapter_ref,
                role=role,
                precommit=precommit,
            ),
            on_retry=self._record_judge_quality_retry,
        )

    def _arbitrate_pair(
        self,
        claims_x: list,
        claims_y: list,
        prose_x: str,
        prose_y: str,
        pair_id: str,
    ) -> str:
        """T6.2 证据锚定仲裁（单轮）：给两份单候选评审证据 + 决定性锚点 → 内容映射.

        评审命名「甲/乙」槽位无效力——parse_anchored_arbitration 把 decisive_anchor
        映射到实际包含它的候选（内容优先于槽位名，防候选甲槽位锚定偏置）。
        仲裁输出协议合规失败做有界重请求；provider/网络错误不重试。
        """
        prompt = build_anchored_pair_prompt(
            claims_x,
            claims_y,
            role="reader_judge",
            reader_contract_context=(
                self._reader_contract.to_prompt_context()
                if self._reader_contract
                else ""
            ),
        )
        return parse_with_quality_retry(
            lambda: self._invoke(self._tournament_provider, prompt),
            lambda text: parse_anchored_arbitration(
                text, pair_id=pair_id, response_a=prose_x, response_b=prose_y
            ),
            on_retry=self._record_judge_quality_retry,
        )

    def _tournament(
        self,
        prose_by_id: dict,
        claims_by_id: dict,
        frontier: list,
        chapter_ref: str,
    ):
        """T6.3：帕累托前沿淘汰赛——确定性比较优先，证据锚定仲裁兜底.

        确定性可判（硬轴消除 / 软轴支配）→ 零 provider 调用，两轮换位必然一致；
        证据互不支配（undecidable）**或完全等价（no_difference）** → 逐对 A/B +
        B/A 证据锚定仲裁（内容映射，两轮命名同一正文才一致）。no_difference 不直接
        淘汰：两份正文可能证据打平但正文内容可分（决定性锚点不同），直接淘汰会把
        有效候选误判为质量耗尽。位置不稳定执行判别轮（策略 max_decision_rounds），
        仍不稳定该对淘汰；无法收敛到唯一稳定胜者 → winner None → 运行层
        quality_exhausted（T6.5）。落盘只记候选 id、偏好与仲裁方式，正文只在内存。
        """
        def judge_pair(x: str, y: str) -> tuple[str, str]:
            pair_id = f"{chapter_ref}:{x}|{y}"
            claims_x = claims_by_id.get(x, [])
            claims_y = claims_by_id.get(y, [])
            decision = compare_judge_claims(claims_x, claims_y)
            if decision == "X":
                return ("A", "B")  # 确定性：x 胜，两轮一致（零 provider 调用）
            if decision == "Y":
                return ("B", "A")
            pref_ab = self._arbitrate_pair(
                claims_x, claims_y, prose_by_id[x], prose_by_id[y], pair_id + ":ab"
            )
            pref_ba = self._arbitrate_pair(
                claims_y, claims_x, prose_by_id[y], prose_by_id[x], pair_id + ":ba"
            )
            return pref_ab, pref_ba

        result = selection_tournament(
            frontier,
            judge_pair,
            max_rounds=self.policy.search.max_decision_rounds,
        )
        path = self.run_dir / "tournament.json"
        existing = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        existing["chapters"][chapter_ref] = {
            "frontier": list(frontier),
            "pairs": result.pairs,
            "position_consistency_rate": result.position_consistency_rate,
            "stable_winner": result.winner,
            "min_position_consistency": self.policy.evaluation.pairwise_position_consistency_min,
        }
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    # ---- 主循环 ----

    def step(self) -> AutonomousDecision | None:
        """推进一个决策周期；返回该周期产生的决策，运行进入终态后返回 None."""
        if self._run.status in TERMINAL_STATUSES:
            return None
        if self._run.status == "created":
            self._run = self._transition("running")
            self._persist_manifest()

        # 前置预算：墙钟 / 章节配额（均为正常完成的终态，不经由决策解析器）。
        if time.monotonic() - self._started_at > self.policy.budget.max_wall_clock_seconds:
            return self._terminal("completed", "wall clock budget exceeded")
        if self._run.committed_chapters >= self.policy.budget.max_chapters_per_run:
            return self._terminal(
                "completed",
                f"reached frozen chapter budget ({self.policy.budget.max_chapters_per_run})",
            )
        if self._candidates_remaining <= 0:
            return self._terminal("quality_exhausted", "no prose candidate remains")

        # 载入可信状态（提交头）。
        objects, frames = self._load_state()
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
            return self._stage_failure("runtime state", exc)

        structure_template_name = workspec.structure_template or "eight_node"
        try:
            frames = self._frame_unit.require_valid_frame_state(frames)
            frame_cursor = self._frame_unit.get_cursor(frames)
            frame_context = self._frame_unit.build_continue_context(frames, frame_cursor)
        except ValueError as exc:
            return self._stage_failure("frame state", exc)

        # 可行性门禁：零 LLM，先于任何生成调用。stop → narrative_stopped 且
        # 后续零 provider 调用；needs_premise → search_premise（前提搜索，见下）
        # 或 premise_exhausted（前提预算耗尽）。
        viability = analyze_continuation_viability(
            narrative_state=narrative_state,
            foreshadows=foreshadows,
            frame_context=frame_context,
            workspec=workspec,
            contract=self._reader_contract,
            recent_chapter_count=self._run.committed_chapters,
        )
        (self.run_dir / "viability_analysis.json").write_text(
            json.dumps(viability.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        need_premise_search = (
            viability.verdict == "needs_premise" and self._premise_candidates_remaining > 0
        )
        decision = resolve_autonomous_decision(
            provider_error=None,
            viability_verdict=viability.verdict,
            premise_candidates_remaining=self._premise_candidates_remaining,
            required_axes_armed=True,
            reader_route="pass",
            hard_violation=None,
            candidates_remaining=self._candidates_remaining,
            budget_available=self._budget_available(
                project_calls=self._projected_chapter_calls()
                + (1 if need_premise_search else 0)
            ),
            accepted_candidate_id=None,
        )
        if decision.route in _ROUTE_TERMINAL_STATUS:
            if viability.verdict in ("stop", "needs_premise"):
                (self.run_dir / "viability_report.json").write_text(
                    json.dumps(
                        viability.model_dump(mode="json"), ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
            return self._terminal_from_decision(decision)
        if decision.route == "search_premise":
            # T4：自动前提搜索。成功 → 投影新 active 帧并重新进入 viability；
            # 失败（预算耗尽）→ premise_exhausted（无 [WAITING]、无人工路径）。
            outcome = self._search_premise(
                frames=frames,
                narrative_state=narrative_state,
                foreshadows=foreshadows,
                workspec=workspec,
                frame_context=frame_context,
                viability=viability,
            )
            if outcome.decision is not None:
                (self.run_dir / "viability_report.json").write_text(
                    json.dumps(
                        viability.model_dump(mode="json"), ensure_ascii=False, indent=2
                    ),
                    encoding="utf-8",
                )
                return self._terminal_from_decision(outcome.decision)
            frames = outcome.frames
            frame_cursor = self._frame_unit.get_cursor(frames)
            frame_context = self._frame_unit.build_continue_context(frames, frame_cursor)
            viability = analyze_continuation_viability(
                narrative_state=narrative_state,
                foreshadows=foreshadows,
                frame_context=frame_context,
                workspec=workspec,
                contract=self._reader_contract,
                recent_chapter_count=self._run.committed_chapters,
            )
            if viability.verdict != "continue":
                return self._terminal(
                    "premise_exhausted",
                    "applied premise failed viability re-entry",
                )

        # decision.route == "continue_generation"：多 PlotUnit 候选批次 → 计划硬闸
        # → 正文前冻结 EvaluatorPrecommit → 每计划多版正文 → 确定性证伪 + 语义接缝
        # → 带锚点 JudgeClaim 评审 → 软轴分数选择 → 读者门禁 → 原子提交。
        continuation_text = append_generated_chapters(self._source_text, self.chapters_dir)
        chapter_number = prose_action.next_chapter_number(self.chapters_dir)
        chapter_ref = f"chapter_{chapter_number}"
        plot_candidates = self.policy.search.plot_candidates
        prose_variants = self.policy.search.prose_variants_per_plot

        # T5.1/T5.2 多 PlotUnit 候选：一次 provider 调用返回批次，严格解析，
        # 语义去重（输出状态变化签名）+ 数量差异约束（G5 可验证），封顶 plot_candidates。
        try:
            base_prompt = self._build_continue_prompt(
                narrative_state, characters, facts, foreshadows, workspec,
                frame_context, structure_template_name, continuation_text, viability,
            )
            response = self._invoke(
                self._plan_provider, build_plot_batch_prompt(base_prompt, plot_candidates)
            )
            plan_tuples = parse_plot_batch_response(response, count=plot_candidates)
        except Exception as exc:
            return self._stage_failure("plan", exc)

        deduped = dedup_plan_candidates(plan_tuples, max_candidates=plot_candidates)
        ok, reason = verify_plan_diversity(deduped, max_candidates=plot_candidates)
        survivors: list = []
        plan_rejections: list[tuple[str, str]] = []
        for plotunit, new_state, _new_facts, _gaps in deduped:
            violation = state_necessity_violation(plotunit, narrative_state, new_state)
            if violation is not None:
                plan_rejections.append(violation)
                continue
            try:
                plan_issues = self._code_issues(
                    plotunit, objects + [plotunit, new_state], objects
                )
            except Exception as exc:
                return self._stage_failure("pre-review", exc)
            blocking = [issue for issue in plan_issues if issue.is_blocking()]
            if blocking:
                plan_rejections.append(
                    (
                        "pre-review",
                        f"plan {plotunit.unit_id} blocking: "
                        + "; ".join(f"{i.issue_type}: {i.description}" for i in blocking),
                    )
                )
                continue
            survivors.append((plotunit, new_state, _new_facts, _gaps))
        self._record_plan_candidates(
            plans=plan_tuples,
            deduped=deduped,
            survivors=survivors,
            ok=ok,
            reason=reason,
            plan_rejections=plan_rejections,
            chapter_ref=chapter_ref,
        )
        if not survivors:
            return self._terminal(
                "quality_exhausted",
                "all plot candidates failed hard plan gates (state_necessity/pre-review)",
            )

        # T5.3 正文前冻结 EvaluatorPrecommit（不可修改，零 LLM）——同一份预承诺
        # 对后续所有正文章节做证伪；预承诺无正文字段（结构保证 G5 不可变）。
        trusted_hash = self._trusted_state_hash(narrative_state, facts)
        precommits = [
            build_evaluator_precommit(
                precommit_id=f"precommit_plan_{index + 1:04d}",
                plotunit=survivors[index][0],
                input_state=narrative_state,
                new_state=survivors[index][1],
                trusted_state_hash=trusted_hash,
            )
            for index in range(len(survivors))
        ]
        self._record_precommits(precommits, chapter_ref)

        # T5.4 每计划多版正文 + 纯代码确定性硬门禁（证伪 + 语义接缝，零 LLM）。
        variant_records: list[_VariantRecord] = []
        for index in range(len(survivors)):
            plotunit, new_state, _new_facts, _gaps = survivors[index]
            plan_issues = []
            for variant_index in range(prose_variants):
                try:
                    text = self._prose_variant(
                        plotunit,
                        new_state,
                        workspec,
                        facts,
                        continuation_text,
                        plan_label=f"plan_{index + 1:04d}",
                        variant_index=variant_index,
                        variant_count=prose_variants,
                    )
                except Exception as exc:
                    return self._stage_failure("prose", exc)
                code_claims = falsify_prose_against_precommit(
                    precommits[index], text, chapter_ref
                )
                seam_findings = self._seam_check(
                    text, chapter_number, characters, continuation_text
                )
                if seam_findings:
                    self._record_seam_findings(seam_findings)
                hard = falsify_blocking(code_claims) or bool(seam_findings)
                variant_records.append(
                    _VariantRecord(
                        plan_index=index,
                        prose_candidate=ProseCandidate(
                            candidate_id=f"prose_{plotunit.unit_id}_v{variant_index + 1}",
                            plotunit_id=plotunit.unit_id,
                            prose_sha256=sha256_text(text),
                            prose_chars=len(compact_text(text)),
                            status="rejected" if hard else "candidate",
                        ),
                        text=text,
                        code_issues=plan_issues,
                        code_claims=code_claims,
                        seam_findings=seam_findings,
                    )
                )
        self._record_prose_candidates(variant_records, chapter_ref)

        # T5.5/T6.1 带正文锚点 JudgeClaim——三个上下文隔离角色（事实/人物/读者）
        # 各自独立评审每个存活候选；评审上下文与生成器隔离（只读预承诺 + 正文 +
        # 契约，不读生成 prompt/其他候选）。任一角色硬违例 → 候选淘汰。
        all_judge_claims: list[JudgeClaim] = []
        for record in variant_records:
            if record.prose_candidate.status != "candidate":
                continue
            try:
                claims = [
                    claim
                    for role in self.policy.search.judge_roles
                    for claim in self._judge_call(
                        role, precommits[record.plan_index], record.text, chapter_ref
                    )
                ]
            except Exception as exc:
                return self._stage_failure("judge", exc)
            record.judge_claims = claims
            all_judge_claims.extend(claims)
            if any(claim_is_hard_violation(claim) for claim in claims):
                record.status = "rejected"
        self._record_judge_claims(all_judge_claims, chapter_ref)

        # T6.4/T6.5 选择：软轴帕累托前沿 + 匿名 A/B 换位淘汰赛。
        # - 硬违例（含三角色 blocking+violated）已在上方淘汰，不进入前沿。
        # - 前沿 = 软轴非支配候选；单候选直接胜出；多候选 → 淘汰赛逐对 A/B+B/A。
        # - 淘汰赛无法收敛唯一稳定胜者 → quality_exhausted（不转人工）。
        best: _VariantRecord | None = None
        best_score: int | None = None
        axis_scores: dict[str, dict[str, int]] = {}
        for record in variant_records:
            if record.status != "candidate":
                continue
            scores = {
                axis: soft_axis_score(
                    tuple(record.code_claims + record.judge_claims), axis
                )
                for axis in SOFT_AXES
            }
            axis_scores[record.prose_candidate.candidate_id] = scores
            score_sum = sum(scores.values())
            if best_score is None or score_sum > best_score:
                best, best_score = record, score_sum
        frontier = pareto_frontier(list(axis_scores), axis_scores)
        tournament = None
        if len(frontier) > 1:
            # 多候选前沿 → 确定性比较优先，证据锚定仲裁兜底；无法收敛 → quality_exhausted。
            prose_by_id = {
                record.prose_candidate.candidate_id: record.text
                for record in variant_records
                if record.status == "candidate"
            }
            claims_by_id = {
                record.prose_candidate.candidate_id: tuple(record.judge_claims)
                for record in variant_records
                if record.status == "candidate"
            }
            try:
                tournament = self._tournament(
                    prose_by_id, claims_by_id, frontier, chapter_ref
                )
            except Exception as exc:
                return self._stage_failure("tournament", exc)
            if tournament.winner is not None:
                best = next(
                    record
                    for record in variant_records
                    if record.prose_candidate.candidate_id == tournament.winner
                )
                best_score = sum(
                    axis_scores[best.prose_candidate.candidate_id].values()
                )
            else:
                best = None
                best_score = None
        self._record_candidate_selection(
            best, best_score, variant_records, frontier, chapter_ref, tournament
        )
        if best is None:
            return self._terminal(
                "quality_exhausted",
                "no stable pairwise winner on the Pareto frontier",
            )

        # 提交点读者门禁链（确定性，无 provider 调用）。
        gate_verdict, gate_package, gate_reconcile_issues = evaluate_commit_reader_gate(
            output_dir=self.run_dir,
            chapters_dir=self.chapters_dir,
            draft_text=best.text,
            facts=facts,
            characters=characters,
            time_book=self._time_book,
            reader_contract=self._reader_contract,
            chapter_ref=chapter_ref,
        )
        gate_package_hash = (
            sha256_text(gate_package.model_dump_json())
            if gate_package is not None
            else ""
        )
        write_reader_gate_report(
            self.run_dir,
            gate_verdict,
            chapter_ref=chapter_ref,
            package_hash=gate_package_hash,
            reconcile_count=len(gate_reconcile_issues),
        )

        gate_hard_violation = (
            f"reader gate: {gate_verdict.route}"
            if gate_verdict.route != "pass"
            else None
        )
        decision = resolve_autonomous_decision(
            provider_error=None,
            viability_verdict="continue",
            premise_candidates_remaining=self._premise_candidates_remaining,
            required_axes_armed=True,
            reader_route=gate_verdict.route,
            hard_violation=gate_hard_violation,
            candidates_remaining=self._candidates_remaining,
            budget_available=self._budget_available(self._projected_chapter_calls()),
            accepted_candidate_id=(
                best.prose_candidate.candidate_id
                if gate_verdict.route == "pass"
                else None
            ),
        )

        if decision.route == "accepted":
            self._commit(
                objects, frames, frame_context, facts,
                survivors[best.plan_index], best, chapter_ref, gate_verdict,
                gate_package, gate_reconcile_issues, chapter_number,
            )
            self._candidates_remaining = self._initial_candidates_remaining
            # T7.1/T7.2 长程对账检查点：提交后若 run 章数落在冻结检查点，从已提交
            # 正文重建结构/人物/承诺摘要并与滚动摘要对账；漂移超阈值 → 阻断继续
            # 生产（不进下一章），否则持久化对账后的滚动摘要。
            long_horizon_terminal = self._run_long_horizon_checkpoint(
                chapter_number, characters, narrative_state, foreshadows
            )
            if long_horizon_terminal is not None:
                return long_horizon_terminal
            return decision
        if decision.route == "reject_candidate":
            self._candidates_remaining -= 1
            if self._candidates_remaining == 0:
                decision = resolve_autonomous_decision(
                    provider_error=None,
                    viability_verdict="continue",
                    premise_candidates_remaining=self._premise_candidates_remaining,
                    required_axes_armed=True,
                    reader_route="pass",
                    hard_violation=gate_hard_violation,
                    candidates_remaining=0,
                    budget_available=self._budget_available(
                        self._projected_chapter_calls()
                    ),
                    accepted_candidate_id=None,
                )
                return self._terminal_from_decision(decision)
            return decision
        return self._terminal_from_decision(decision)

    def run_until_terminal(self) -> AutonomousRun:
        """循环 step() 直到进入终态；返回终态 AutonomousRun."""
        while self._run.status not in TERMINAL_STATUSES:
            self.step()
        return self._run

    @property
    def status(self) -> str:
        """当前运行状态（对 CLI 只读暴露，不改状态机）."""
        return self._run.status

    # ---- 各阶段 ----

    def _build_continue_prompt(
        self,
        narrative_state,
        characters: list,
        facts,
        foreshadows,
        workspec,
        frame_context: dict | None,
        structure_template_name: str,
        continuation_text: str,
        viability,
    ) -> str:
        retrieval_context = load_retrieval_context(
            self.run_dir, state=narrative_state, facts=facts, foreshadows=foreshadows
        )
        contract_context = (
            self._reader_contract.to_prompt_context() if self._reader_contract else ""
        )
        prompt = self._cont.build_prompt(
            state=narrative_state,
            characters=characters,
            facts=facts,
            foreshadows=foreshadows,
            workspec_context=workspec.to_prompt_context(),
            frame_context=frame_context,
            structure_template=structure_template_name,
            platform=workspec.platform,
            genre=workspec.genre,
            style_context=self._style_context,
            retrieval_context=retrieval_context,
            timeline_context=facts.to_timeline_context(include_header=False),
            time_context=build_time_context(self._time_book),
            excerpt_context=load_recent_excerpts(continuation_text),
            original_style_context=load_original_style_sample(self._source_text),
            nsfw_context=build_nsfw_context(
                self._nsfw_on,
                genre=workspec.genre,
                theme=workspec.theme,
                subgenre=workspec.subgenre,
            ),
            contract_context=contract_context,
            viability_note=viability_continue_note(viability),
        )
        if self._accepted_premise is not None:
            premise = self._accepted_premise
            prompt = prompt + (
                "\n\n【续写前提（本轮已批准）】\n"
                f"- 新外部冲突：{premise.new_external_conflict}\n"
                f"- 新阶段目标：{premise.new_phase_goal}\n"
                f"- 必须兑现：{'；'.join(premise.obligations_to_old_promises)}\n"
                f"- 可产生的新状态变化：{premise.new_state_change}\n"
            )
        return prompt

    def _code_issues(self, plotunit: PlotUnit, review_objects: list, objects: list) -> list:
        hard = self._review._hard_rules(review_objects)
        domain = self._review._domain_rules(review_objects)
        temporal = list(ReconcileUnit().check_temporal_contradictions(objects))
        return hard + domain + temporal + scene_experience_guard_review_issues(plotunit)

    def _commit(
        self,
        objects: list,
        frames: list,
        frame_context: dict | None,
        facts,
        plan: tuple,
        best: _VariantRecord,
        chapter_ref: str,
        gate_verdict,
        gate_package,
        gate_reconcile_issues: list,
        chapter_number: int,
    ) -> None:
        plotunit, new_state, raw_new_facts, _gaps = plan
        # committing 为进程内瞬态：不落盘。崩溃点在 boundary.commit 内，磁盘上
        # manifest.json 仍是上一章 running → 重启按 recover() 判定。
        self._last_accepted_candidate_id = best.prose_candidate.candidate_id
        self._run = self._transition(
            "committing", accepted_candidate_id=best.prose_candidate.candidate_id
        )
        # 只把选中计划的新事实并入可信 ledger（其余候选的事实从不进入提交状态）。
        plan_ledger = copy.deepcopy(facts)
        admit_new_facts(plan_ledger, raw_new_facts, plotunit.unit_id)
        final_objects = [
            plan_ledger if isinstance(o, FactLedger) else o for o in objects
        ] + [plotunit, new_state]
        final_package = self._serializer.build_package(*final_objects)
        self._frame_unit.advance_cursor(frames)
        frames_json = json.dumps(frames, ensure_ascii=False, indent=2)
        state_json = json.dumps(final_package.model_dump(), ensure_ascii=False, indent=2)

        prov_path = self.run_dir / "chapter_provenance.json"
        prov_existing = (
            json.loads(prov_path.read_text(encoding="utf-8"))
            if prov_path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        prov_entry = prose_action.build_chapter_provenance_entry(
            chapter_number,
            flow_version="3",
            review_issues=best.code_issues,
            final_draft_chars=len("".join((best.text or "").split())),
            active_frame_id=(
                ((frame_context or {}).get("current_frame") or {}).get("frame_id")
            ),
            active_formula_node=(
                ((frame_context or {}).get("current_frame") or {}).get("formula_node")
            ),
        )
        prov_json = json.dumps(
            prose_action.merge_chapter_provenance(prov_existing, prov_entry),
            ensure_ascii=False,
            indent=2,
        )
        gate_package_hash = (
            sha256_text(gate_package.model_dump_json()) if gate_package is not None else ""
        )
        write_reader_gate_report(
            self.run_dir,
            gate_verdict,
            chapter_ref=chapter_ref,
            package_hash=gate_package_hash,
            reconcile_count=len(gate_reconcile_issues),
        )
        source_text_hash = sha256_text(self._source_text) if self._source_text else None

        boundary = ChapterCommitBoundary(
            self.run_dir, self.chapters_dir, failpoint=self._failpoint
        )
        result = boundary.commit(
            run_id=derive_run_id(self._flow_mode, chapter_number),
            mode=self._flow_mode,
            chapter_number=chapter_number,
            chapter_text=best.text,
            state_path=self.run_dir / "state" / "state_package.json",
            state_json=state_json,
            frames_path=self.run_dir / "state" / "frames.json",
            frames_json=frames_json,
            archive_text=best.text,
            provenance_json=prov_json,
            prev_chapter_ref=(
                f"chapter_{chapter_number - 1}" if chapter_number > 1 else None
            ),
            source_text_hash=source_text_hash,
            facts_package_hash=gate_package_hash,
            review_route="pass",
        )
        if not result.ok:
            raise AutonomousRunnerError(f"chapter commit failed: {result.error}")
        self._run = self._transition(
            "running",
            committed_chapters=chapter_number - self._initial_abs + 1,
            accepted_candidate_id=None,
        )
        self._persist_manifest()
        print(f"  A1 committed chapter_{chapter_number} (run committed_chapters="
              f"{self._run.committed_chapters})")

    # ---- T7.1/T7.2 长程对账检查点（design §9）----

    def _run_long_horizon_checkpoint(
        self,
        chapter_number: int,
        characters: list,
        narrative_state,
        foreshadows,
    ) -> AutonomousDecision | None:
        """提交后检查点门：run 章数落在冻结检查点 → 正文重建对账，block 则终态.

        Returns: block 时的终态决策；未到检查点或对账通过 → None（继续）。
        """
        checkpoints = self.policy.canary.long_horizon_checkpoints
        committed = self._run.committed_chapters
        if committed not in checkpoints:
            return None
        try:
            checkpoint = self._check_long_horizon(
                committed, chapter_number, characters, narrative_state, foreshadows
            )
        except Exception as exc:
            return self._stage_failure("long_horizon", exc)
        if checkpoint.route == "block":
            return self._terminal_from_decision(
                AutonomousDecision(
                    route="quality_exhausted",
                    reasons=(f"long-horizon block: {checkpoint.reason}",),
                    generation_allowed=False,
                    commit_allowed=False,
                    frame_advance_allowed=False,
                )
            )
        return None

    def _check_long_horizon(
        self,
        checkpoint: int,
        chapter_number: int,
        characters: list,
        narrative_state,
        foreshadows,
    ):
        """单检查点：从已提交正文重建摘要 vs 上一检查点滚动信念对账.

        - 首个检查点：只建立基线（不阻断——承诺刚立，给一个完整窗口落地）；
        - 后续检查点：仅「上一检查点相信开放且此刻仍开放」的承诺参与漂移判定，
          未在正文落地 → block（quality_exhausted 终态）；
        - 通过时以「正文落地提及 ∪ 此刻仍开放承诺」持久化滚动摘要（旧摘要不能
          无限自我继承）。落盘 gates/long_horizon_<checkpoint>.json（只记摘要与
          漂移指标，不记正文）。
        """
        corpus = self._load_committed_prose(chapter_number)
        labels: dict[str, list[str]] = {}
        for cm in characters or []:
            cid = getattr(cm, "character_id", None)
            name = getattr(cm, "name", None)
            if cid:
                labels[cid] = [label for label in (name, cid) if label]
        current_open: dict[str, str] = {}
        for entry in getattr(foreshadows, "entries", None) or []:
            if entry.current_status in ("active", "open", "delayed"):
                current_open[entry.thread_id] = entry.content
        active_characters = list(
            getattr(narrative_state, "active_characters", None) or []
        )
        structural_nodes = self._load_structure_nodes()
        prev_rolling = load_rolling_summary(self.run_dir)
        if prev_rolling is None:
            belief = None  # 首个检查点：pass + 建基线
        else:
            still_open = {
                tid for tid in prev_rolling.summary.promise_mentions
                if tid in current_open
            }
            belief = RollingLongHorizonSummary(
                last_checkpoint=prev_rolling.last_checkpoint,
                summary=ProseSummary(
                    chapter_count=prev_rolling.summary.chapter_count,
                    character_mentions={cid: 0 for cid in active_characters},
                    promise_mentions={tid: 0 for tid in still_open},
                    structural_nodes=prev_rolling.summary.structural_nodes,
                ),
            )
        result = evaluate_long_horizon_checkpoint(
            checkpoint, corpus, belief,
            labels=labels, promise_tokens=current_open,
            structural_nodes=structural_nodes,
        )
        gates_dir = self.run_dir / "gates"
        gates_dir.mkdir(parents=True, exist_ok=True)
        (gates_dir / f"long_horizon_{checkpoint}.json").write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if result.route == "pass":
            rebuilt = summarize_prose(
                corpus, labels=labels, promise_tokens=current_open,
                structural_nodes=structural_nodes,
            )
            save_rolling_summary(
                self.run_dir,
                reconcile(belief or build_rolling_from_plan(current_open), rebuilt,
                          checkpoint,
                          open_promises=current_open,
                          active_characters=active_characters),
            )
        return result

    def _load_committed_prose(self, chapter_number: int) -> list[str]:
        """读取已提交正文 chapter_1..N（UTF-8-sig/UTF-8，尽力解码）."""
        texts: list[str] = []
        if not self.chapters_dir.exists():
            return texts
        for path in sorted(self.chapters_dir.glob("chapter_*.txt")):
            m = re.match(r"chapter_0*(\d+)\.txt$", path.name)
            if not m or int(m.group(1)) > chapter_number:
                continue
            for encoding in ("utf-8-sig", "utf-8"):
                try:
                    texts.append(path.read_text(encoding=encoding))
                    break
                except UnicodeDecodeError:
                    continue
        return texts

    def _load_structure_nodes(self) -> list[str]:
        """从 chapter_provenance.json 按章序提取结构节点标签（可空）."""
        prov_path = self.run_dir / "chapter_provenance.json"
        if not prov_path.is_file():
            return []
        data = json.loads(prov_path.read_text(encoding="utf-8"))
        chapters = data.get("chapters", {}) or {}

        def _number(key: str) -> int:
            m = re.search(r"(\d+)", key)
            return int(m.group(1)) if m else 0

        nodes: list[str] = []
        for key in sorted(chapters, key=_number):
            node = chapters[key].get("active_formula_node")
            if node:
                nodes.append(node)
        return nodes
