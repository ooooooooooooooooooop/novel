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
import hashlib
import json
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from src.boundary_control.chapter_commit import ChapterCommitBoundary, derive_run_id
from src.boundary_control.reader_gate import (
    evaluate_commit_reader_gate,
    load_recent_chapters,
    write_reader_gate_report,
)
from src.boundary_control.runtime_state import (
    require_continue_runtime_state,
    require_single_object,
)
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.domain_layer.compliance_rules import build_nsfw_context
from src.experiment.pass_audit import PassAuditUnit
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
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.object_state.premise_candidate import PremiseCandidate
from src.object_state.prose_candidate import ProseCandidate
from src.object_state.run_manifest import read_run_manifest, sha256_file, sha256_text
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
    tournament_position_gate,
)
from src.workflow_action.preference_review import (
    ReviewQualityExhaustedError,
    content_anchor_id,
    parse_anchored_arbitration,
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
from src.workflow_action.serial_reader import SerialReaderUnit
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


_MECHANISM_FILES = (
    "src/auto_short_form.py",
    "src/workflow_action/autonomous_runner.py",
    "src/workflow_action/judge_council.py",
    "src/workflow_action/preference_review.py",
    "src/workflow_action/pareto_tournament.py",
    "src/workflow_action/review.py",
    "src/workflow_action/serial_reader.py",
    "src/workflow_action/prose.py",
    "src/boundary_control/reader_gate.py",
    "src/boundary_control/chapter_commit.py",
    "src/object_state/autonomous.py",
    "src/object_state/run_manifest.py",
    "src/object_state/reviewissue.py",
)


def _mechanism_source_sha256(repo_root: Path) -> str:
    rows = [
        f"{relative}:{sha256_file(repo_root / relative)}"
        for relative in _MECHANISM_FILES
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


class AutonomousRunnerError(RuntimeError):
    """A1 运行器合同违例（非 Provider 错误；不得静默吞掉）。"""


def _orphan_number(path: Path) -> int:
    """chapter_N.txt → N；解析失败返回大数（视为不可管理的孤儿）. """
    try:
        return int(Path(path).stem[len("chapter_"):])
    except (ValueError, IndexError):
        return 10**9


def _remap_historical_fact_id_collisions(
    new_facts: list,
    new_state: NarrativeState,
    existing_ids: set[str],
    chapter_ref: str,
) -> None:
    """纠偏模型把历史 fact_id 复用于本章新事实的转写错误.

    只处理与可信 ledger 的碰撞；同一响应内部的重复 ID 保持原样，继续由
    ``admit_new_facts`` 严格拒绝。纠偏后同步当前状态的事实引用。
    """
    response_ids = [
        raw.get("fact_id")
        for raw in new_facts
        if isinstance(raw, dict)
        and isinstance(raw.get("fact_id"), str)
        and raw.get("fact_id")
    ]
    counts = {fact_id: response_ids.count(fact_id) for fact_id in set(response_ids)}
    occupied = set(existing_ids) | set(response_ids)
    for raw_fact in new_facts:
        if not isinstance(raw_fact, dict):
            continue
        fact_id = raw_fact.get("fact_id")
        if (
            not isinstance(fact_id, str)
            or not fact_id
            or counts.get(fact_id) != 1
            or fact_id not in existing_ids
        ):
            continue
        remapped = f"{fact_id}__{chapter_ref}"
        suffix = 2
        while remapped in occupied:
            remapped = f"{fact_id}__{chapter_ref}_{suffix}"
            suffix += 1
        raw_fact["fact_id"] = remapped
        occupied.add(remapped)
        new_state.current_facts_in_scope = [
            remapped if ref == fact_id else ref
            for ref in new_state.current_facts_in_scope
        ]


_CLAIM_ISSUE_TYPE = {
    "fact_conflict": "fact_conflict",
    "character_fidelity": "character_distortion",
    "character_contradiction": "character_distortion",
    "progression": "weak_progression",
    "friction": "generative_indicia",
    "language_distinctiveness": "style_drift",
    "constructive_ambiguity": "interpretive_space",
    "contract_fulfillment": "promise_loss",
    "contract_drift": "promise_loss",
}


def _violated_claim_issues(claims: list[JudgeClaim]) -> list[dict]:
    """把获胜候选已发现的违例物化为 PASS Audit 可消费的 canonical O."""
    issues: list[dict] = []
    for claim in claims:
        if claim.verdict != "violated":
            continue
        anchor = claim.anchors[0]
        issues.append(
            {
                "issue_id": claim.claim_id,
                "issue_type": _CLAIM_ISSUE_TYPE.get(claim.axis, "other"),
                "severity": "blocking" if claim.severity == "blocking" else "low",
                "location": anchor.excerpt,
                "description": claim.rationale,
            }
        )
    return issues


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
        campaign_identity_path: Path | None = None,
        base_state_hash: str | None = None,
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
        expected_identity_path = self.novel_dir / "output" / "campaign_identity.json"
        if campaign_identity_path is None:
            raise AutonomousRunnerError("A1 run requires campaign_identity.json")
        self._campaign_identity_path = Path(campaign_identity_path).resolve()
        if self._campaign_identity_path != expected_identity_path.resolve():
            raise AutonomousRunnerError(
                "campaign identity must be novel/output/campaign_identity.json"
            )
        self.policy = policy
        self.profile = profile
        self._policy_sha256 = canonical_model_sha256(policy)
        self._profile_sha256 = canonical_model_sha256(profile)
        self._campaign_identity = self._validate_campaign_identity()
        self._base_state_hash = base_state_hash
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

    def _validate_campaign_identity(self) -> dict:
        try:
            data = json.loads(
                self._campaign_identity_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise AutonomousRunnerError("campaign identity is missing or invalid") from exc
        required = {
            "schema_version",
            "campaign",
            "genre",
            "base_state_sha256",
            "policy_sha256",
            "profile_sha256",
            "mechanism_source_sha256",
        }
        if not isinstance(data, dict) or set(data) != required:
            raise AutonomousRunnerError(
                "campaign identity must contain exactly the registered fields"
            )
        checks = {
            "schema_version": data["schema_version"] == 1,
            "campaign": data["campaign"] == self.novel_dir.name,
            "genre": isinstance(data["genre"], str) and bool(data["genre"].strip()),
            "base_state_sha256": bool(re.fullmatch(r"[0-9a-f]{64}", str(data["base_state_sha256"]))),
            "policy_sha256": data["policy_sha256"] == self._policy_sha256,
            "profile_sha256": data["profile_sha256"] == self._profile_sha256,
            "mechanism_source_sha256": data["mechanism_source_sha256"]
            == _mechanism_source_sha256(Path(__file__).resolve().parents[2]),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise AutonomousRunnerError(
                "campaign identity mismatch: " + ", ".join(failed)
            )
        return data

    def _validate_base_state_lineage(self, initial_chapter: int) -> None:
        if not self._base_state_hash or not re.fullmatch(
            r"[0-9a-f]{64}", self._base_state_hash
        ):
            raise AutonomousRunnerError("fresh A1 run requires base_state_hash")
        if initial_chapter == 1:
            if self._base_state_hash != self._campaign_identity["base_state_sha256"]:
                raise AutonomousRunnerError(
                    "chapter_1 base state does not match campaign identity"
                )
            return
        expected_previous = initial_chapter - 1
        candidates = []
        for child in (self.novel_dir / "output").iterdir():
            if not child.is_dir() or child.resolve() == self.run_dir:
                continue
            recovery = ChapterCommitBoundary(child, self.chapters_dir).recover()
            manifest = recovery.manifest
            if (
                recovery.recognized
                and manifest is not None
                and manifest.chapter_number == expected_previous
                and manifest.state_after_hash == self._base_state_hash
                and manifest.campaign_identity_hash
                == sha256_file(self._campaign_identity_path)
            ):
                candidates.append(child)
        if len(candidates) != 1:
            raise AutonomousRunnerError(
                "base state must match exactly one recover-recognized previous chapter"
            )

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
        self._validate_base_state_lineage(self._initial_abs)
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

        评审/仲裁输出协议合规失败（ReviewQualityExhaustedError）是单次调用的诚实终态
        （M1：judge/arbitration 只调用一次，解析失败即终态，不重新请求）；按
        provider_error 上报，不附重试次数（不存在重试）。
        """
        error_label = type(exc).__name__
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
        # 获胜正文 Post-Prose + 独立 blind prose final audit + 在线窗口评审。
        return 4 + 4 * pv + tournament_upper

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

    def _judge_call(
        self, role: str, precommit, prose: str, chapter_ref: str
    ) -> list[JudgeClaim]:
        """T6.1：单角色带锚点评审——评审 prompt 只含该候选预承诺 + 正文 + 契约.

        三角色（fact_judge / character_judge / reader_judge）各自独立调用，评审
        上下文彼此隔离（不读生成 prompt/其他候选）。解析器强制锚点与 precommit_id
        绑定（T5.4），generator_source=角色由运行层注入。

        单次调用契约（M1）：只调用一次 provider，随后本地严格解析/校验；解析失败
        （JSON 无法解析/锚点捏造/形状违例）立即抛 ReviewQualityExhaustedError，
        不重新请求 → 显式终态且零状态污染。provider/网络错误从调用侧直接上抛。
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
        text = self._invoke(self._judge_providers[role], prompt)
        try:
            return parse_judge_claims(
                text,
                prose=prose,
                chapter_ref=chapter_ref,
                role=role,
                precommit=precommit,
                require_role_axis=True,
            )
        except ValueError as exc:
            raise ReviewQualityExhaustedError(str(exc)) from exc

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
        单次调用契约（M1）：只调用一次 provider，解析失败即抛
        ReviewQualityExhaustedError，不重新请求。
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
        text = self._invoke(self._tournament_provider, prompt)
        try:
            return parse_anchored_arbitration(
                text,
                pair_id=pair_id,
                anchor_ids_a={
                    content_anchor_id(anchor.excerpt)
                    for claim in claims_x
                    for anchor in claim.anchors
                },
                anchor_ids_b={
                    content_anchor_id(anchor.excerpt)
                    for claim in claims_y
                    for anchor in claim.anchors
                },
            )
        except ValueError as exc:
            raise ReviewQualityExhaustedError(str(exc)) from exc

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
        pair_winner_cache: dict[tuple[str, str], str | None] = {}

        def judge_pair(x: str, y: str) -> tuple[str, str]:
            cache_key = tuple(sorted((x, y)))
            if cache_key not in pair_winner_cache:
                left, right = cache_key
                decision = compare_judge_claims(
                    claims_by_id.get(left, []), claims_by_id.get(right, [])
                )
                if decision == "X":
                    winner = left
                elif decision == "Y":
                    winner = right
                else:
                    canonical_pref = self._arbitrate_pair(
                        claims_by_id.get(left, []),
                        claims_by_id.get(right, []),
                        prose_by_id[left],
                        prose_by_id[right],
                        f"{chapter_ref}:{left}|{right}:canonical",
                    )
                    winner = (
                        left
                        if canonical_pref == "A"
                        else right
                        if canonical_pref == "B"
                        else None
                    )
                pair_winner_cache[cache_key] = winner
            winner = pair_winner_cache[cache_key]
            if winner is None:
                return "no_difference", "no_difference"
            return (
                "A" if winner == x else "B",
                "A" if winner == y else "B",
            )

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

        # 确定性纠偏：线性续写中候选的 input_state_ref 语义上恒等于当前状态，
        # output_state_ref 恒等于候选自带的 new_state；模型把引用抄成不存在的
        # 状态 id 属于转写错误（temperature=0 下 identical prompt 会稳定复现同一
        # 错 id，硬闸空转成 quality_exhausted 死循环）。仅在引用无效时重映射，
        # 有效引用零行为变化；review.py 的存在性硬闸本身保持不变。
        valid_state_ids = {
            obj.state_id for obj in objects if isinstance(obj, NarrativeState)
        }
        for cand_pu, cand_state, _cand_facts, _cand_gaps in plan_tuples:
            if cand_pu.input_state_ref and cand_pu.input_state_ref not in valid_state_ids:
                cand_pu.input_state_ref = narrative_state.state_id
            if (
                cand_pu.output_state_ref
                and cand_pu.output_state_ref
                not in valid_state_ids | {cand_state.state_id}
            ):
                cand_pu.output_state_ref = cand_state.state_id

        existing_fact_ids = {entry.fact_id for entry in facts.entries}
        for _cand_pu, cand_state, cand_facts, _cand_gaps in plan_tuples:
            _remap_historical_fact_id_collisions(
                cand_facts, cand_state, existing_fact_ids, chapter_ref
            )

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
                record.prose_candidate.candidate_id: tuple(
                    claim
                    for claim in record.judge_claims
                    if claim.generator_source == "reader_judge"
                    and claim.axis in SOFT_AXES
                )
                for record in variant_records
                if record.status == "candidate"
            }
            try:
                tournament = self._tournament(
                    prose_by_id, claims_by_id, frontier, chapter_ref
                )
            except Exception as exc:
                return self._stage_failure("tournament", exc)
            if not tournament_position_gate(
                tournament,
                self.policy.evaluation.pairwise_position_consistency_min,
            ):
                best = None
                best_score = None
            elif tournament.winner is not None:
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

        # 获胜正文绝对质量地板：相对 Pareto 只能选出「最不差」，不能证明可提交。
        # 复用既有 Post-Prose Review 的七维正文终审；非 pass 一律耗尽本 run，零状态污染。
        selected_plan = survivors[best.plan_index]
        selected_plotunit, selected_new_state, _selected_facts, _selected_gaps = selected_plan
        post_review_objects = objects + [selected_plotunit, selected_new_state]
        try:
            post_review_prompt = self._review.build_prompt(
                post_review_objects,
                context="a1-post-prose",
                prose_text=best.text,
            )
            post_review_text = self._invoke(
                self._judge_providers["reader_judge"], post_review_prompt
            )
            llm_post_issues, _reminders, post_route = self._review.parse_response(
                post_review_text
            )
            post_issues = self._code_issues(
                selected_plotunit, post_review_objects, objects
            ) + llm_post_issues
            prose_issue_types = {
                "redundancy",
                "emotion_landing",
                "interpretive_space",
                "scene_presence",
                "dialogue_flat",
                "generative_indicia",
                "exposition_heavy",
                "style_drift",
            }
            for issue in llm_post_issues:
                if (
                    issue.issue_type in prose_issue_types
                    and issue.location not in best.text
                ):
                    raise ReviewQualityExhaustedError(
                        f"post-prose issue {issue.issue_id} location is not a verbatim prose anchor"
                    )
            actionable_post_issues = [
                issue for issue in llm_post_issues if issue.severity != "low"
            ] + [
                issue
                for issue in post_issues[: len(post_issues) - len(llm_post_issues)]
                if issue.is_blocking()
            ]
            post_route = self._review.resolve_route(post_issues, post_route)
            if actionable_post_issues and post_route == "pass":
                post_route = "rewrite"
        except Exception as exc:
            return self._stage_failure("post-prose-review", exc)
        post_review_payload = {
            "schema_version": 1,
            "chapter_ref": chapter_ref,
            "route": post_route,
            "issues": [issue.model_dump(mode="json") for issue in post_issues],
        }
        post_review_json = json.dumps(
            post_review_payload, ensure_ascii=False, indent=2
        )
        post_review_evidence_hash = sha256_text(post_review_json)
        (self.run_dir / "post_prose_review.json").write_text(
            post_review_json, encoding="utf-8"
        )
        if post_route != "pass":
            return self._terminal(
                "quality_exhausted",
                f"post-prose absolute quality floor: {post_route}",
            )

        # 独立 blind prose final audit：与 PASS Audit 同 taxonomy/锚点协议，但本次
        # 响应在 commit 前单独生成；warning+ 不提交，low 进入 canonical O。
        blind_unit = PassAuditUnit()
        try:
            blind_text = self._invoke(
                self._judge_providers["reader_judge"],
                blind_unit.build_audit_prompt(best.text, chapter_ref),
            )
            blind_final = blind_unit.parse_audit(blind_text)
        except Exception as exc:
            return self._stage_failure("blind-final-audit", exc)
        blind_review_issues: list[dict] = []
        for index, finding in enumerate(blind_final["findings"], start=1):
            location = finding.get("location")
            if not isinstance(location, str) or location not in best.text:
                return self._stage_failure(
                    "blind-final-audit",
                    ReviewQualityExhaustedError(
                        f"blind finding {index} location is not a verbatim prose anchor"
                    ),
                )
            blind_review_issues.append(
                {
                    "issue_id": f"blind_final_{chapter_ref}_{index:03d}",
                    "issue_type": finding["issue_type"],
                    "severity": finding["severity"],
                    "location": location,
                    "description": finding["evidence"],
                }
            )
        if any(
            finding["severity"] in ("warning", "blocking", "critical")
            for finding in blind_final["findings"]
        ):
            return self._terminal(
                "quality_exhausted",
                "blind prose final audit found actionable defects",
            )

        # chapter3 起在线武装 SerialReader：chapter3/4 用 window=3，chapter5+ 用 window=5；
        # 当前草稿与既往章经12维评审；协议失败/弱项均不得降级为 unarmed pass。
        serial_report = None
        previous_for_serial = load_recent_chapters(self.chapters_dir, n=4)
        if len(previous_for_serial) >= 2:
            serial_window = 5 if len(previous_for_serial) >= 4 else 3
            previous_for_serial = previous_for_serial[-(serial_window - 1):]
            serial_chapters = previous_for_serial + [best.text]
            serial_refs = [
                f"chapter_{chapter_number - len(previous_for_serial) + index}"
                for index in range(len(previous_for_serial))
            ] + [chapter_ref]
            serial_unit = SerialReaderUnit()
            try:
                serial_prompt = serial_unit.build_prompt(
                    serial_chapters,
                    window=serial_window,
                    chapter_refs=serial_refs,
                    review_target=chapter_ref,
                    reader_contract_context=(
                        self._reader_contract.to_prompt_context()
                        if self._reader_contract
                        else ""
                    ),
                )
                serial_text = self._invoke(
                    self._judge_providers["reader_judge"], serial_prompt
                )
                serial_report = serial_unit.merge(
                    serial_unit.parse_response(serial_text),
                    window=serial_window,
                    review_target=chapter_ref,
                    chapter_refs=serial_refs,
                )
            except Exception as exc:
                return self._stage_failure("serial-reader", exc)
        # 提交点读者门禁链（确定性 + 已武装 SerialReader）。
        # P1 长程因果防线（causal_defense）：已提交状态 + 选中计划 → 事件抹除/代价/
        # 成长/制度后果/选择无差异的对象层检测，blocking 即拒绝提交。
        # 历史 PlotUnit 是已提交证据，不是当前草案；若一并送入检测器，会被较晚才
        # 确认的制度事实反向审判并污染当前章。只保留历史状态对象，再追加选中计划。
        causal_context = [obj for obj in objects if not isinstance(obj, PlotUnit)]
        gate_verdict, gate_package, gate_reconcile_issues = evaluate_commit_reader_gate(
            output_dir=self.run_dir,
            chapters_dir=self.chapters_dir,
            draft_text=best.text,
            facts=facts,
            characters=characters,
            time_book=self._time_book,
            reader_contract=self._reader_contract,
            chapter_ref=chapter_ref,
            causal_objects=causal_context + [selected_plotunit, selected_new_state],
            serial_report_override=serial_report,
            require_campaign_evidence=True,
        )
        gate_package_hash = (
            sha256_text(gate_package.model_dump_json())
            if gate_package is not None
            else ""
        )
        gate_hard_violation = (
            f"reader gate: {gate_verdict.route}"
            if gate_verdict.route != "pass"
            else None
        )
        required_axes_armed = {
            claim.generator_source for claim in best.judge_claims
        } == set(self.policy.search.judge_roles)
        decision = resolve_autonomous_decision(
            provider_error=None,
            viability_verdict="continue",
            premise_candidates_remaining=self._premise_candidates_remaining,
            required_axes_armed=required_axes_armed,
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
                selected_plan, best, chapter_ref, gate_verdict,
                gate_package, gate_reconcile_issues,
                post_issues + blind_review_issues,
                blind_final, serial_report, chapter_number,
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
        post_review_issues: list,
        blind_final: dict,
        serial_report,
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
        consumed_frame = ((frame_context or {}).get("current_frame") or {})
        consumed_frame_id = consumed_frame.get("frame_id")
        if consumed_frame_id:
            self._frame_unit.link_plotunit(frames, consumed_frame_id, plotunit.unit_id)
            frame_node = next(
                frame for frame in frames if frame.get("frame_id") == consumed_frame_id
            )
            frame_node["input_state_ref"] = plotunit.input_state_ref
            frame_node["output_state_ref"] = plotunit.output_state_ref
        next_cursor = self._frame_unit.advance_cursor(frames)
        next_frame = (
            next(
                frame
                for frame in frames
                if frame.get("frame_id") == next_cursor["current_frame_id"]
            )
            if next_cursor is not None
            else {}
        )
        frames_json = json.dumps(frames, ensure_ascii=False, indent=2)
        state_json = json.dumps(final_package.model_dump(), ensure_ascii=False, indent=2)

        prov_path = self.run_dir / "chapter_provenance.json"
        prov_existing = (
            json.loads(prov_path.read_text(encoding="utf-8"))
            if prov_path.exists()
            else {"schema_version": 1, "chapters": {}}
        )
        canonical_review_issues = (
            _violated_claim_issues(best.judge_claims) + post_review_issues
        )
        prov_entry = prose_action.build_chapter_provenance_entry(
            chapter_number,
            flow_version="3",
            review_issues=canonical_review_issues,
            final_draft_chars=len("".join((best.text or "").split())),
            active_frame_id=consumed_frame_id,
            active_formula_node=consumed_frame.get("formula_node"),
            next_active_frame_id=next_frame.get("frame_id"),
            next_active_formula_node=next_frame.get("formula_node"),
        )
        prov_entry["review_evidence_hash"] = sha256_text(
            json.dumps(
                prov_entry["review_issues"], ensure_ascii=False, sort_keys=True
            )
        )
        prov_json = json.dumps(
            prose_action.merge_chapter_provenance(prov_existing, prov_entry),
            ensure_ascii=False,
            indent=2,
        )
        gate_package_hash = (
            sha256_text(gate_package.model_dump_json()) if gate_package is not None else ""
        )
        reader_gate_json = json.dumps(
            {
                "schema_version": 1,
                "chapter_ref": chapter_ref,
                "route": gate_verdict.route,
                "axes_armed": dict(gate_verdict.axes_armed),
                "reasons": gate_verdict.reasons,
                "issues": [
                    issue.model_dump(mode="json") for issue in gate_verdict.issues
                ],
                "reconcile_issue_count": len(gate_reconcile_issues),
                "facts_package_hash": gate_package_hash,
            },
            ensure_ascii=False,
            indent=2,
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
            reader_gate_report_json=reader_gate_json,
            blind_final_audit_json=json.dumps(
                {
                    "schema_version": 1,
                    "chapter_ref": chapter_ref,
                    "clean": blind_final["clean"],
                    "findings": blind_final["findings"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            prev_chapter_ref=(
                f"chapter_{chapter_number - 1}" if chapter_number > 1 else None
            ),
            source_text_hash=source_text_hash,
            facts_package_hash=gate_package_hash,
            campaign_identity_path=self._campaign_identity_path,
            serial_reader_report_json=(
                serial_report.model_dump_json(indent=2)
                if serial_report is not None
                else None
            ),
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
