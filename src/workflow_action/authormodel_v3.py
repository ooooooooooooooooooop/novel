"""AuthorModel V3 动作与跨作品验证器 (P5).

实现：
1. 候选作者先验对齐打分 (score_author_prior)：作为候选排序与 tie-break 信号（非硬门禁）。
2. 依据 Hindsight 结果回填反例与支撑样本 (update_author_model_from_hindsight)。
3. 跨作品留一验证 (validate_cross_work_separation)：检测词汇泄漏并计算留出作品选择预测率。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from src.object_state.authorkernel import (
    VALUE_VOCAB,
    VALUE_VOCAB_CONTRA_KEYWORDS,
    VALUE_VOCAB_KEYWORDS,
    VALUE_VOCAB_PRO_KEYWORDS,
    value_direction,
)
from src.object_state.authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CounterexampleSample,
    CrossWorkValidationResult,
    SupportingSample,
)
from src.object_state.choicerecord import ChoiceRecord
from src.object_state.structural_search import StructuralProposal
from src.object_state.workspec import WorkSpec


def score_author_prior(
    proposal: StructuralProposal,
    author_model: Optional[AuthorModelV3],
    work_spec: Optional[WorkSpec] = None,
) -> float:
    """计算结构候选与作者决策先验的对齐度（0.0 ~ 1.0，用于 Pareto 与 tie-break）."""
    if author_model is None or not author_model.principles:
        return 0.5  # 中性默认先验

    score_acc = 0.5
    matched_principles = 0
    text_corpus = (
        f"{proposal.core_choice} {proposal.cost} {proposal.state_change} "
        f"{proposal.summary} {proposal.primary_risk}"
    )

    for principle in author_model.principles:
        # 已废弃或争议极大的原则降低权重或忽略
        if principle.status == "deprecated":
            continue

        weight = principle.confidence
        if principle.status == "stable":
            weight *= 1.2
        elif principle.status == "contested":
            weight *= 0.5

        vocab_key = principle.value_vocab_key
        direction = value_direction(text_corpus, vocab_key)

        # 1. 词汇语义方向对齐
        if direction == "pro":
            score_acc += 0.15 * weight
            matched_principles += 1
        elif direction == "contra":
            score_acc -= 0.2 * weight
            matched_principles += 1

        # 2. 结构化案例支撑与反例权衡 (Case-based / Grounding Evaluation)
        for sup in getattr(principle, "supporting_samples", []):
            if sup.tradeoff_rationale and any(chunk in text_corpus for chunk in sup.tradeoff_rationale.split() if len(chunk) >= 2):
                score_acc += 0.05 * weight
                break
        for contra in getattr(principle, "counterexamples", []):
            if contra.deviation_reason and any(chunk in text_corpus for chunk in contra.deviation_reason.split() if len(chunk) >= 2):
                score_acc -= 0.08 * weight
                break

    return max(0.0, min(1.0, round(score_acc, 3)))


def update_author_model_from_hindsight(
    author_model: AuthorModelV3,
    choice_records: list[ChoiceRecord],
    work_name: str,
) -> int:
    """从已回填 Hindsight 的 ChoiceRecord 更新作者原则（支持样本与反例）."""
    updated_count = 0

    for choice in choice_records:
        if choice.hindsight is None or choice.consequence is None:
            continue

        for conflict_key in choice.value_conflicts:
            # 找到或创建对应原则
            matching_p = next(
                (p for p in author_model.principles if p.value_vocab_key == conflict_key),
                None,
            )

            if matching_p is None:
                if conflict_key in VALUE_VOCAB:
                    matching_p = AuthorPrincipleV3(
                        principle_id=f"ap_{conflict_key}",
                        statement=f"关于 {conflict_key} 的决策原则",
                        value_vocab_key=conflict_key,
                        scope="author_global",
                        confidence=0.5,
                        status="candidate",
                    )
                    author_model.principles.append(matching_p)
                else:
                    continue

            if choice.hindsight in ("overturned", "partial_regret", "complex"):
                # 记录反例
                existing_contra = any(
                    c.decision_id == choice.decision_id for c in matching_p.counterexamples
                )
                if not existing_contra:
                    matching_p.counterexamples.append(
                        CounterexampleSample(
                            decision_id=choice.decision_id,
                            work_name=work_name,
                            chapter_number=choice.chapter_number,
                            hindsight_status=choice.hindsight,
                            observed_consequence=choice.consequence,
                            deviation_reason=choice.hindsight_note or "回看发现负面后果或代价估计失误",
                        )
                    )
                    matching_p.update_status_from_evidence()
                    updated_count += 1
            elif choice.hindsight == "still_supported":
                # 记录支持样本
                existing_sup = any(
                    s.decision_id == choice.decision_id for s in matching_p.supporting_samples
                )
                if not existing_sup:
                    matching_p.supporting_samples.append(
                        SupportingSample(
                            decision_id=choice.decision_id,
                            work_name=work_name,
                            chapter_number=choice.chapter_number,
                            context_summary=choice.plot_context,
                            chosen_action=choice.selected_candidate,
                            rejected_actions=[r.candidate_id for r in choice.rejected],
                            tradeoff_rationale=choice.tradeoff,
                        )
                    )
                    matching_p.update_status_from_evidence()
                    updated_count += 1

    if work_name not in author_model.known_works:
        author_model.known_works.append(work_name)

    return updated_count


def validate_cross_work_separation(
    author_model: AuthorModelV3,
    works_choice_records: dict[str, list[ChoiceRecord]],
    holdout_work: str,
    forbidden_work_entities: Optional[list[str]] = None,
) -> CrossWorkValidationResult:
    """执行留一作品验证 (L1WO)，检测词汇泄漏与选择预测表现."""
    training_works = [w for w in works_choice_records if w != holdout_work]
    holdout_records = works_choice_records.get(holdout_work, [])

    # 1. 词汇泄漏检测：全局原则陈述中不得包含作品专有专有名词
    leaked_terms = []
    forbidden = forbidden_work_entities or []
    for p in author_model.principles:
        if p.scope == "author_global":
            for term in forbidden:
                if term and term in p.statement:
                    leaked_terms.append(term)

    lexical_leakage = len(leaked_terms) > 0

    # 2. 留出作品选择预测准确率评估
    correct_predictions = 0
    evaluable_choices = 0

    for rec in holdout_records:
        if not rec.candidates or not rec.selected_candidate:
            continue
        evaluable_choices += 1

        # 用原则匹配预测哪一个候选最可能被作者选中
        cand_scores = {}
        for c in rec.candidates:
            summary = c.summary
            cand_score = 0.5
            for p in author_model.principles:
                if p.status == "deprecated":
                    continue
                if p.value_vocab_key in rec.value_conflicts:
                    pro_kws = VALUE_VOCAB_PRO_KEYWORDS.get(p.value_vocab_key, ())
                    if any(kw in summary for kw in pro_kws):
                        cand_score += 0.2 * p.confidence
            cand_scores[c.candidate_id] = cand_score

        predicted_winner = max(cand_scores, key=cand_scores.get)
        if predicted_winner == rec.selected_candidate:
            correct_predictions += 1

    accuracy = (
        round(correct_predictions / evaluable_choices, 3)
        if evaluable_choices > 0
        else 0.5
    )

    is_valid = (accuracy > 0.5) and (not lexical_leakage) and (len(training_works) >= 1)

    return CrossWorkValidationResult(
        author_id=author_model.author_id,
        holdout_work=holdout_work,
        training_works=training_works,
        choice_prediction_accuracy=accuracy,
        baseline_accuracy=0.5,
        lexical_leakage_detected=lexical_leakage,
        leaked_terms=leaked_terms,
        is_valid_author_prior=is_valid,
    )


# ---------------------------------------------------------------------------
# 物理持久化 (R5 整改)
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, content: str) -> None:
    """使用临时文件与原子替换写入文件，杜绝写入中断导致数据损坏."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = path.parent
    fd, temp_file = tempfile.mkstemp(prefix=f"{path.stem}_", suffix=".tmp", dir=temp_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_file, path)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass
        raise


def load_author_model_v3(path_or_dir: Path) -> Optional[AuthorModelV3]:
    """从指定路径或目录读取 author_model_v3.json. 损坏文件将显式抛出异常."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "author_model_v3.json"
    if not p.exists():
        return None
    try:
        return AuthorModelV3.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted or invalid author_model_v3 at {p}: {exc}") from exc


def save_author_model_v3(path_or_dir: Path, model: AuthorModelV3) -> Path:
    """原子持久化保存 author_model_v3.json."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "author_model_v3.json"
    _atomic_write_text(p, model.model_dump_json(indent=2))
    return p


def load_qualification_report(path_or_dir: Path) -> Optional[CrossWorkValidationResult]:
    """读取跨作品留一验证资格报告 qualification_report.json. 损坏文件将显式抛出异常."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "qualification_report.json"
    if not p.exists():
        return None
    try:
        return CrossWorkValidationResult.model_validate_json(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted or invalid qualification_report at {p}: {exc}") from exc


def save_qualification_report(path_or_dir: Path, report: CrossWorkValidationResult) -> Path:
    """原子持久化保存 qualification_report.json."""
    p = path_or_dir if path_or_dir.is_file() else path_or_dir / "qualification_report.json"
    _atomic_write_text(p, report.model_dump_json(indent=2))
    return p


def is_author_model_certified_for_production(
    author_model: Optional[AuthorModelV3],
    qualification_report: Optional[CrossWorkValidationResult],
) -> bool:
    """检查 AuthorModel 是否获得 L1WO 跨作品留一资格认证.

    只有在存在资格报告且 is_valid_author_prior=True 且无词汇泄露且准确率超基线时才认证.
    未认证前，任何生产链路必须保持 strict shadow-only 模式，不得改变生产决策.
    """
    if author_model is None or qualification_report is None:
        return False
    if qualification_report.author_id != author_model.author_id:
        return False
    return bool(
        qualification_report.is_valid_author_prior
        and not qualification_report.lexical_leakage_detected
        and qualification_report.choice_prediction_accuracy > qualification_report.baseline_accuracy
    )

