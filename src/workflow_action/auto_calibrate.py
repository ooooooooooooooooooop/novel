"""AutoCalibrateUnit — 自动评审器校准与 holdout 验证（design §10 / T7.4–T7.6）.

把评审角色（fact_judge / character_judge / reader_judge）校准到冻结的人类偏好基准
（WritingPreferenceBench 中文子集）上：先跑 calibration 划分 → 生成并冻结
QualityThresholds（阈值唯一合法来源是 calibration，禁止从 holdout 生成）→ 再跑
holdout 验证；阈值冻结后不得根据 holdout 调整（T7.6）。

- `load_frozen_preference_bench`：载入基准 + 划分 manifest，校验冻结 SHA-256，
  严格分离 calibration / holdout（prompt_id 零交叉）；
- `build_preference_judge_prompt` / `parse_preference_response`：匿名 A/B 偏好评审
  （绝不泄漏哪份是 chosen）；
- `run_preference_judge` / `compute_accuracy`：预测 + 总体/分类型准确率（Wilson 下界）；
- `freeze_quality_thresholds`：从 calibration 冻结阈值（多 prompt/多标签广度检查）；
- `measure_position_consistency`：A/B 与 B/A 换位稳定率；
- `run_holdout`：只读阈值验证，不调参。
"""

from __future__ import annotations

import hashlib
import hashlib
import json
import math
from pathlib import Path

from src.object_state.autonomous import AutonomousPolicy
from src.object_state.qualitythresholds import (
    AccuracyReport,
    HoldoutReport,
    JudgePreferencePrediction,
    PreferencePair,
    QualityThresholds,
)
from src.workflow_action.preference_review import ReviewQualityExhaustedError

MIN_CALIBRATION_PROMPT_IDS = 10
MIN_CALIBRATION_TAGS = 2

_PREFERENCE_ROLE_AXES = {
    "fact_judge": "事实可信度与一致性：哪个响应更少与既定事实冲突、更可信",
    "character_judge": "人物一致性：哪个响应的人物行为/弧光更符合人物设定与内在逻辑",
    "reader_judge": "读者阅读体验：哪个响应更引人入胜、更有现场感、更少阅读摩擦",
}
_DEFAULT_ROLE_AXIS = "总体写作质量：哪个响应更好地满足了写作要求"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(path: Path, expected: str, label: str) -> None:
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected}, got {actual} ({path})"
        )


# --------------------------------------------------------------------------
# 基准载入与划分（严格分离）
# --------------------------------------------------------------------------

def load_frozen_preference_bench(
    bench_path: Path,
    split_manifest_path: Path,
    *,
    expected_source_sha256: str,
    expected_split_sha256: str,
) -> tuple[list[PreferencePair], list[PreferencePair]]:
    """载入冻结偏好基准，校验哈希，返回 (calibration_pairs, holdout_pairs).

    划分按 manifest 的 row_index → bucket；calibration 与 holdout 按 prompt_id
    零交叉（同一 prompt_id 的所有行只能落在同一个划分）。
    """
    bench_path = Path(bench_path)
    split_manifest_path = Path(split_manifest_path)
    _require_sha256(bench_path, expected_source_sha256, "preference source")
    _require_sha256(
        split_manifest_path, expected_split_sha256, "preference split manifest"
    )

    rows = json.loads(bench_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("preference bench must be a non-empty JSON list")

    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8-sig"))
    calib_buckets = set(manifest["selection"]["calibration_buckets"])
    holdout_buckets = set(manifest["selection"]["holdout_buckets"])
    if calib_buckets & holdout_buckets:
        raise ValueError("calibration and holdout buckets must be disjoint")

    row_to_split: dict[int, str] = {}
    row_to_tag: dict[int, str] = {}
    row_to_prompt_id: dict[int, str] = {}
    for entry in manifest.get("calibration", []):
        row_to_split[entry["row_index"]] = "calibration"
        row_to_tag[entry["row_index"]] = entry["tag"]
        row_to_prompt_id[entry["row_index"]] = entry["prompt_id"]
    for entry in manifest.get("holdout", []):
        row_to_split[entry["row_index"]] = "holdout"
        row_to_tag[entry["row_index"]] = entry["tag"]
        row_to_prompt_id[entry["row_index"]] = entry["prompt_id"]

    calibration: list[PreferencePair] = []
    holdout: list[PreferencePair] = []
    for index, row in enumerate(rows):
        if index not in row_to_split:
            continue  # 不在 manifest 的行不进入任何划分
        chosen = row["chosen"]
        rejected = row["rejected"]
        if isinstance(chosen, dict):
            chosen = chosen.get("response", "")
        if isinstance(rejected, dict):
            rejected = rejected.get("response", "")
        pair = PreferencePair(
            prompt_id=row_to_prompt_id[index],
            tag=row_to_tag[index],
            prompt=row["prompt"],
            chosen=chosen,
            rejected=rejected,
            split=row_to_split[index],
            bucket=0,
        )
        if row_to_split[index] == "calibration":
            calibration.append(pair)
        else:
            holdout.append(pair)

    if not calibration or not holdout:
        raise ValueError("both calibration and holdout splits must be non-empty")
    calib_ids = {p.prompt_id for p in calibration}
    holdout_ids = {p.prompt_id for p in holdout}
    overlap = calib_ids & holdout_ids
    if overlap:
        raise ValueError(
            "calibration and holdout prompt_ids must not overlap: "
            + ", ".join(sorted(overlap))
        )
    return calibration, holdout


# --------------------------------------------------------------------------
# 匿名偏好评审 prompt 与解析
# --------------------------------------------------------------------------

def build_preference_judge_prompt(
    prompt: str,
    response_a: str,
    response_b: str,
    *,
    role: str = "reader_judge",
) -> str:
    """匿名 A/B 偏好评审：两个无标识响应 + 写作要求，绝不泄漏哪份是人类偏好."""
    axis = _PREFERENCE_ROLE_AXES.get(role, _DEFAULT_ROLE_AXIS)
    return f"""【匿名偏好评审】（{role}）
你正在评审两个响应哪个更好地满足了同一条写作要求。请纯粹按{axis}判断。

【写作要求】
{prompt}

【候选甲（匿名）】
{response_a}

【候选乙（匿名）】
{response_b}

【输出格式】严格 JSON（只输出 JSON，不要 Markdown 代码块）：
{{"preferred": "A", "rationale": "<一句话理由>"}}

- "preferred" 只能是 "A"（选候选甲）或 "B"（选候选乙）；若两者实在无法分辨，
  写 "no_difference"，并说明原因。
- "rationale" 必须非空。
- 不要猜测两份响应的来源、作者或任何身份信息；只比较正文本身。
"""


def parse_preference_response(text: str, pair_id: str) -> str:
    """严格解析偏好 JSON → "A" / "B" / "no_difference". 形状错误 raise."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"preference response is not JSON ({pair_id})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"preference response must be a JSON object ({pair_id})")
    allowed = {"preferred", "rationale"}
    if set(data) != allowed:
        raise ValueError(
            f"preference response must contain exactly {sorted(allowed)} "
            f"({pair_id}); got {sorted(data)}"
        )
    preferred = data["preferred"]
    if preferred not in ("A", "B", "no_difference"):
        raise ValueError(
            f"preference response preferred must be A/B/no_difference ({pair_id})"
        )
    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError(f"preference response rationale must be non-blank ({pair_id})")
    return preferred


# --------------------------------------------------------------------------
# 预测 + 准确率
# --------------------------------------------------------------------------

def run_preference_judge(
    pairs: list[PreferencePair],
    role: str,
    judge_fn,
    *,
    on_pair_unreviewable=None,
) -> list[JudgePreferencePrediction]:
    """对每对运行评审（chosen=甲 / rejected=乙），返回带人类标签的预测.

    judge_fn(pair, role) → "A" / "B" / "no_difference"（评审不可见哪份是偏好）。
    正确口径：A=选 chosen（正确），B=选 rejected（错误），no_difference=弃权（错误），
    协议耗尽（ReviewQualityExhaustedError）= 错且计入分母（冻结口径，绝不静默排除）。

    ``on_pair_unreviewable(pair, exc)``：judge_fn 抛 ReviewQualityExhaustedError
    （单候选评审协议合规失败）时调用；回调后该对仍以 ``predicted="unreviewable"``
    记一条 correct=False 的预测（reason 记录原因），与其他预测一起参与 compute_accuracy。
    其余异常（含网络/配置错误）一律上抛，不做静默跳过。
    """
    predictions: list[JudgePreferencePrediction] = []
    for pair in pairs:
        try:
            predicted = judge_fn(pair, role)
        except ReviewQualityExhaustedError as exc:
            if on_pair_unreviewable is None:
                raise
            on_pair_unreviewable(pair, exc)
            predictions.append(
                JudgePreferencePrediction(
                    prompt_id=pair.prompt_id,
                    tag=pair.tag,
                    role=role,
                    predicted="unreviewable",
                    human_label="chosen",  # 真值仍是 chosen；无预测
                    correct=False,
                    reason=str(exc),
                )
            )
            continue
        if predicted == "A":
            correct, human_label = True, "chosen"
        elif predicted == "B":
            correct, human_label = False, "rejected"
        else:
            correct, human_label = False, "rejected"
        predictions.append(
            JudgePreferencePrediction(
                prompt_id=pair.prompt_id,
                tag=pair.tag,
                role=role,
                predicted=predicted,
                human_label=human_label,
                correct=correct,
            )
        )
    return predictions


def _wilson_low(correct: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = correct / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, min(1.0, centre - margin))


def compute_accuracy(predictions: list[JudgePreferencePrediction]) -> AccuracyReport:
    """总体 + 分类型准确率（冻结口径：弃权/耗尽一律计错，分母=全部样本）+ Wilson 95% 下界."""
    n = len(predictions)
    abstain = sum(1 for p in predictions if p.predicted == "no_difference")
    unreviewable = sum(1 for p in predictions if p.predicted == "unreviewable")
    correct = sum(1 for p in predictions if p.correct)
    overall = correct / n if n else 0.0
    per_tag: dict[str, float] = {}
    per_tag_n: dict[str, int] = {}
    by_tag: dict[str, list[JudgePreferencePrediction]] = {}
    for p in predictions:
        by_tag.setdefault(p.tag, []).append(p)
    for tag, group in by_tag.items():
        per_tag[tag] = sum(1 for p in group if p.correct) / len(group)
        per_tag_n[tag] = len(group)
    return AccuracyReport(
        n=n,
        abstain_count=abstain,
        unreviewable_count=unreviewable,
        overall_accuracy=round(overall, 4),
        per_tag_accuracy={tag: round(v, 4) for tag, v in per_tag.items()},
        per_tag_n=per_tag_n,
        wilson_low=round(_wilson_low(correct, n), 4),
    )


# --------------------------------------------------------------------------
# 阈值冻结 + holdout
# --------------------------------------------------------------------------

def freeze_quality_thresholds(
    calibration_pairs: list[PreferencePair],
    calibration_report: AccuracyReport,
    policy: AutonomousPolicy,
    *,
    role: str,
    policy_sha256: str,
    frozen_at: str,
    frozen_by_run: str,
    source_sha256: dict[str, str],
) -> QualityThresholds:
    """从 calibration 冻结阈值（唯一合法来源），并做覆盖广度检查.

    广度约束（design §10：单一读者/单一模型/单一作品不得产生生产阈值）：calibration
    必须覆盖 ≥ MIN_CALIBRATION_PROMPT_IDS 个不同 prompt_id 且 ≥ MIN_CALIBRATION_TAGS
    个不同类型标签。阈值取 policy.evaluation 预注册下界，不从结果调低。
    """
    distinct_prompt_ids = len({p.prompt_id for p in calibration_pairs})
    distinct_tags = len({p.tag for p in calibration_pairs})
    if distinct_prompt_ids < MIN_CALIBRATION_PROMPT_IDS:
        raise ValueError(
            f"calibration span too narrow to freeze production thresholds: "
            f"{distinct_prompt_ids} prompt_ids < {MIN_CALIBRATION_PROMPT_IDS}"
        )
    if distinct_tags < MIN_CALIBRATION_TAGS:
        raise ValueError(
            f"calibration span too narrow to freeze production thresholds: "
            f"{distinct_tags} tags < {MIN_CALIBRATION_TAGS}"
        )

    ev = policy.evaluation
    thresholds_id = (
        hashlib.sha256(
        "|".join(
            (
                policy_sha256,
                role,
                source_sha256.get("preference_source", ""),
                source_sha256.get("preference_split", ""),
                str(calibration_report.overall_accuracy),
            )
        ).encode("utf-8")
        ).hexdigest()[:16]
    )
    return QualityThresholds(
        thresholds_id=thresholds_id,
        role=role,
        policy_id=policy.policy_id,
        policy_sha256=policy_sha256,
        preference_source_sha256=source_sha256.get("preference_source", ""),
        preference_split_manifest_sha256=source_sha256.get("preference_split", ""),
        human_distribution_manifest_sha256=source_sha256.get("human_distribution", ""),
        generated_from="calibration_split",
        frozen_at=frozen_at,
        frozen_by_run=frozen_by_run,
        overall_accuracy_min=ev.holdout_overall_accuracy_min,
        per_tag_accuracy_min=ev.holdout_genre_accuracy_min,
        position_consistency_min=ev.pairwise_position_consistency_min,
        calibration_stats=calibration_report,
        calibration_span={
            "distinct_prompt_ids": distinct_prompt_ids,
            "distinct_tags": distinct_tags,
        },
    )


def _stratified_position_sample(
    pairs: list[PreferencePair], sample: int
) -> list[PreferencePair]:
    """确定性分层采样（按 tag 轮转，保持 tag 内相对顺序）——禁止前缀采样."""
    if sample <= 0 or len(pairs) <= sample:
        return pairs
    by_tag: dict[str, list[PreferencePair]] = {}
    for pair in pairs:
        by_tag.setdefault(pair.tag, []).append(pair)
    selected: list[PreferencePair] = []
    cursor: dict[str, int] = {tag: 0 for tag in sorted(by_tag)}
    while len(selected) < sample:
        progressed = False
        for tag in sorted(by_tag):
            if len(selected) >= sample:
                break
            index = cursor[tag]
            if index < len(by_tag[tag]):
                selected.append(by_tag[tag][index])
                cursor[tag] = index + 1
                progressed = True
        if not progressed:
            break
    return selected


def build_position_ledger(
    pairs: list[PreferencePair],
    judge_fn,
    *,
    role: str = "reader_judge",
    sample: int | None = None,
) -> list[dict]:
    """逐对 AB/BA 台账；协议失败保留在分母并显式标 protocol_valid=false."""
    if sample is not None and sample > 0:
        pairs = _stratified_position_sample(pairs, sample)
    ledger: list[dict] = []
    for pair in pairs:
        row = {
            "prompt_id": pair.prompt_id,
            "tag": pair.tag,
            "chosen_sha256": hashlib.sha256(pair.chosen.encode("utf-8")).hexdigest(),
            "rejected_sha256": hashlib.sha256(pair.rejected.encode("utf-8")).hexdigest(),
            "pref_ab": "unreviewable",
            "pref_ba": "unreviewable",
            "position_consistent": False,
            "protocol_valid": False,
        }
        try:
            row["stage"] = "ab"
            row["pref_ab"] = judge_fn(pair, role)
            swapped_pair = PreferencePair(
                prompt_id=pair.prompt_id,
                tag=pair.tag,
                prompt=pair.prompt,
                chosen=pair.rejected,
                rejected=pair.chosen,
                split=pair.split,
                bucket=pair.bucket,
            )
            row["stage"] = "ba"
            row["pref_ba"] = judge_fn(swapped_pair, role)
            row["stage"] = "complete"
            row["protocol_valid"] = True
            row["position_consistent"] = (row["pref_ab"], row["pref_ba"]) in (
                ("A", "B"),
                ("B", "A"),
            )
        except ReviewQualityExhaustedError as exc:
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)[:240]
        ledger.append(row)
    return ledger


def measure_position_consistency(
    pairs: list[PreferencePair],
    judge_fn,
    *,
    role: str = "reader_judge",
    sample: int | None = None,
    on_pair_unreviewable=None,
) -> float:
    """A/B 与 B/A 换位稳定率：同对换序后评审仍命名同一响应 → 一致.

    call1: chosen=甲/rejected=乙；call2: rejected=甲/chosen=乙。
    (A,B) 与 (B,A) 两轮都选中 chosen → 一致；任一 no_difference 或命名不同 → 不一致。
    协议耗尽（ReviewQualityExhaustedError）：计为「不一致」并计入分母，绝不静默排除。

    ``sample``：0/None = 全部对；>0 时按 tag 确定性分层采样（禁止前缀）。全部对
    均不可评时返回 0.0（空评 ≠ 完美）。

    ``on_pair_unreviewable(pair, exc)``：任一轮评审协议合规耗尽时回调并计入分母；
    缺省回调时异常上抛。
    """
    if sample is not None and sample > 0:
        pairs = _stratified_position_sample(pairs, sample)
    if not pairs:
        return 0.0
    consistent = 0
    total = 0
    for pair in pairs:
        try:
            first = judge_fn(pair, role)          # chosen=甲
        except ReviewQualityExhaustedError as exc:
            if on_pair_unreviewable is None:
                raise
            on_pair_unreviewable(pair, exc)
            total += 1
            continue
        swapped_pair = PreferencePair(
            prompt_id=pair.prompt_id,
            tag=pair.tag,
            prompt=pair.prompt,
            chosen=pair.rejected,
            rejected=pair.chosen,
            split=pair.split,
            bucket=pair.bucket,
        )
        try:
            swapped = judge_fn(swapped_pair, role)  # chosen=乙
        except ReviewQualityExhaustedError as exc:
            if on_pair_unreviewable is None:
                raise
            on_pair_unreviewable(pair, exc)
            total += 1
            continue
        total += 1
        if (first, swapped) in (("A", "B"), ("B", "A")):
            consistent += 1
    if total == 0:
        return 0.0
    return round(consistent / total, 4)


def run_holdout(
    thresholds: QualityThresholds,
    holdout_pairs: list[PreferencePair],
    role: str,
    judge_fn,
    *,
    run_id: str,
    run_at: str,
    position_sample: int | None = None,
    on_pair_unreviewable=None,
) -> HoldoutReport:
    """在 holdout 上验证冻结阈值（只读，不回写阈值；T7.6）."""
    predictions = run_preference_judge(
        holdout_pairs, role, judge_fn, on_pair_unreviewable=on_pair_unreviewable
    )
    report = compute_accuracy(predictions)
    position = measure_position_consistency(
        holdout_pairs, judge_fn, role=role, sample=position_sample,
        on_pair_unreviewable=on_pair_unreviewable,
    )
    overall_met = report.overall_accuracy >= thresholds.overall_accuracy_min
    holdout_tags = {p.tag for p in holdout_pairs}
    missing_tags = sorted(holdout_tags - set(report.per_tag_accuracy))
    if missing_tags:
        per_tag_met = False
    else:
        per_tag_met = all(
            acc >= thresholds.per_tag_accuracy_min
            for acc in report.per_tag_accuracy.values()
        )
    position_met = position >= thresholds.position_consistency_min
    violations: list[str] = []
    if not overall_met:
        violations.append(
            f"overall accuracy {report.overall_accuracy} < "
            f"{thresholds.overall_accuracy_min}"
        )
    if missing_tags:
        violations.append(
            f"per-tag coverage: tags not evaluated {missing_tags}"
        )
    elif per_tag_met is False:
        low_tags = [
            tag for tag, acc in report.per_tag_accuracy.items()
            if acc < thresholds.per_tag_accuracy_min
        ]
        violations.append(
            f"per-tag accuracy below {thresholds.per_tag_accuracy_min}: {low_tags}"
        )
    if not position_met:
        violations.append(
            f"position consistency {position} < {thresholds.position_consistency_min}"
        )
    return HoldoutReport(
        run_id=run_id,
        thresholds_id=thresholds.thresholds_id,
        overall_accuracy=report.overall_accuracy,
        per_tag_accuracy=report.per_tag_accuracy,
        position_consistency=position,
        met=overall_met and per_tag_met and position_met,
        dimension_met={
            "overall": overall_met,
            "per_tag": per_tag_met,
            "position_consistency": position_met,
        },
        violations=violations,
        run_at=run_at,
        abstain_count=report.abstain_count,
        unreviewable_count=report.unreviewable_count,
    )
