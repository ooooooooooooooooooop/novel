#!/usr/bin/env python3
"""auto_calibrate_short_form — A1 自动评审器校准 CLI 入口（design §10 / T7.4–T7.6）.

把评审角色（缺省 reader_judge）校准到冻结的人类偏好基准上：

1. 载入冻结 policy/profile（A1 冻结证据），校验 provider_profile_id 一致性；
2. 载入冻结偏好基准 + 划分 manifest（校验 SHA-256），严格分离 calibration/holdout；
3. 在 calibration 划分上运行匿名 A/B 偏好评审（单次 provider 调用，无重试/无回退）
   → 计算准确率 → 冻结 QualityThresholds（唯一来源 = calibration）；
4. 在 holdout 划分上只读验证（总体/分类型/位置一致性），**禁止据 holdout 调阈值**。

产物（output-dir）：
    calls/                    逐调用凭证无关审计（prompt 只记 SHA-256，不落正文）
    calibration_predictions.json / calibration_report.json
    thresholds.json           （冻结阈值，含冻结证据）
    holdout_report.json       （只读验证结果）
    calibration_result.json   （汇总：met/violations/route）

退出码：holdout 达标 → 0；未达标或任何错误 → 1（G7：holdout 必须达到预注册阈值）。

用法:
    python src/auto_calibrate_short_form.py --output-dir <dir> \
        --policy <autonomous_policy.json> --profile <provider_profile.json> \
        [--role reader_judge] [--bench <WP_bench_chinese.json>] [--split <split_manifest.json>] \
        [--max-calibration-pairs N] [--max-holdout-pairs N] [--position-sample N]
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_interface import DirectAPIInterface
from src.object_state.autonomous import AutonomousPolicy, ProviderProfile
from src.provider_adapter import AnthropicMessagesProvider, AutonomousBudgetLedger
from src.workflow_action.auto_calibrate import (
    compute_accuracy,
    freeze_quality_thresholds,
    load_frozen_preference_bench,
    run_holdout,
    run_preference_judge,
)
from src.workflow_action.preference_review import (
    ReviewQualityExhaustedError,
    build_anchored_arbitration_prompt,
    build_single_review_prompt,
    make_review_judge,
    parse_anchored_arbitration,
    parse_single_review,
    parse_with_quality_retry,
)

DEFAULT_ROLE = "reader_judge"


def _load_json_model(path: str, model):
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_bench_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="A1 自动评审器校准：calibration 冻结阈值 + holdout 只读验证"
    )
    parser.add_argument("--output-dir", required=True, help="校准产物目录")
    parser.add_argument("--policy", required=True, help="冻结策略 JSON（AutonomousPolicy）")
    parser.add_argument("--profile", required=True, help="冻结 Provider 档案 JSON（ProviderProfile）")
    parser.add_argument("--role", default=DEFAULT_ROLE, help="校准的评审角色（缺省 reader_judge）")
    parser.add_argument("--bench", default="", help="偏好基准 JSON（缺省取 policy.benchmarks）")
    parser.add_argument("--split", default="", help="划分 manifest JSON（缺省取 policy.benchmarks）")
    parser.add_argument("--max-calibration-pairs", type=int, default=0, help="calibration 上限（0=全部）")
    parser.add_argument("--max-holdout-pairs", type=int, default=0, help="holdout 上限（0=全部）")
    parser.add_argument("--position-sample", type=int, default=20, help="位置一致性抽样对（0=全部）")
    parser.add_argument(
        "--user-home", default="", help="Provider 凭证/身份目录（缺省 Path.home()）"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        policy = _load_json_model(args.policy, AutonomousPolicy)
        profile = _load_json_model(args.profile, ProviderProfile)
    except Exception as exc:
        print(f"Error: 无法载入冻结 policy/profile: {type(exc).__name__}")
        return 1
    if policy.provider_profile_id != profile.profile_id:
        print(
            f"Error: policy.provider_profile_id ({policy.provider_profile_id}) "
            f"!= profile.profile_id ({profile.profile_id})"
        )
        return 1

    # 基准来源：显式覆盖优先，否则取冻结 policy.benchmarks。
    bench = _resolve_bench_path(args.bench or policy.benchmarks.preference_source)
    split = _resolve_bench_path(
        args.split or policy.benchmarks.preference_split_manifest
    )
    source_sha256 = {
        "preference_source": policy.benchmarks.preference_source_sha256,
        "preference_split": policy.benchmarks.preference_split_manifest_sha256,
        "human_distribution": policy.benchmarks.human_distribution_manifest_sha256,
    }

    try:
        calibration_pairs, holdout_pairs = load_frozen_preference_bench(
            bench, split,
            expected_source_sha256=source_sha256["preference_source"],
            expected_split_sha256=source_sha256["preference_split"],
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    if args.max_calibration_pairs:
        calibration_pairs = calibration_pairs[: args.max_calibration_pairs]
    if args.max_holdout_pairs:
        holdout_pairs = holdout_pairs[: args.max_holdout_pairs]

    # 单次 provider 调用：同一冻结 profile 的评审角色实例，逐调用凭证无关审计。
    ledger = AutonomousBudgetLedger(
        budget=policy.budget,
        pricing=profile.pricing_usd_per_million_tokens,
    )
    try:
        judge_provider = AnthropicMessagesProvider(
            profile=profile,
            role=args.role,
            max_output_tokens=policy.chapter.judge_max_output_tokens,
            audit_dir=output_dir / "calls",
            ledger=ledger,
            user_home=Path(args.user_home) if args.user_home else None,
        )
    except Exception as exc:
        print(f"Error: provider 初始化失败: {type(exc).__name__}")
        return 1

    def review_candidate(prompt, response, role: str, candidate_ref: str):
        """单候选内容无关评审：一次调用只评一个文本，不见槽位/另一候选（G7 协议）.

        协议合规失败（锚点捏造/形状违例）做有界重请求（只重请求、不重试网络）；
        每次重请求是独立全新调用，由调用方记录次数。
        """
        role_config = getattr(profile.roles, role)
        review_prompt = build_single_review_prompt(prompt, response, role=role)
        interface = DirectAPIInterface(
            model=role_config.request_model,
            provider_call=judge_provider,
            expected_response_model=role_config.expected_actual_model,
        )
        return parse_with_quality_retry(
            lambda: interface.call(review_prompt),
            lambda text: parse_single_review(
                text, candidate_ref=candidate_ref, response=response, role=role
            ),
            on_retry=lambda _attempt: record_quality_retry(),
        )

    def arbitrate(prompt, r_chosen, r_rejected, response_chosen, response_rejected, role: str):
        """证据锚定仲裁：仅确定性比较无法分出高下时调用；锚点映射到实际包含它的候选."""
        role_config = getattr(profile.roles, role)
        arb_prompt = build_anchored_arbitration_prompt(
            prompt, r_chosen, r_rejected, role=role
        )
        interface = DirectAPIInterface(
            model=role_config.request_model,
            provider_call=judge_provider,
            expected_response_model=role_config.expected_actual_model,
        )
        return parse_with_quality_retry(
            lambda: interface.call(arb_prompt),
            lambda text: parse_anchored_arbitration(
                text,
                pair_id=r_chosen.review_id,
                response_a=response_chosen,
                response_b=response_rejected,
            ),
            on_retry=lambda _attempt: record_quality_retry(),
        )

    # 质量台账：协议合规重请求次数 + 有界重请求后仍不可评审的对（诚实上报，不静默吞）。
    quality_retries = 0
    unreviewable_pairs: list[dict[str, str]] = []

    def record_quality_retry() -> None:
        nonlocal quality_retries
        quality_retries += 1

    def record_unreviewable(pair, exc: Exception) -> None:
        unreviewable_pairs.append(
            {
                "prompt_id": pair.prompt_id,
                "tag": pair.tag,
                "error_type": type(exc).__name__,
            }
        )

    judge_pair = make_review_judge(review_candidate, arbitrate)

    # ---- 1. calibration：跑评审 → 准确率 → 冻结阈值（唯一来源 = calibration）。
    try:
        calib_predictions = run_preference_judge(
            calibration_pairs,
            args.role,
            judge_pair,
            on_pair_unreviewable=record_unreviewable,
        )
        calib_report = compute_accuracy(calib_predictions)
    except Exception as exc:
        print(f"Error: calibration 失败: {type(exc).__name__}")
        return 1

    run_id = f"auto-calibrate-{args.role}-{_utc_now()}"
    policy_sha256 = _sha256_file(Path(args.policy))
    try:
        thresholds = freeze_quality_thresholds(
            calibration_pairs,
            calib_report,
            policy,
            role=args.role,
            policy_sha256=policy_sha256,
            frozen_at=_utc_now(),
            frozen_by_run=run_id,
            source_sha256=source_sha256,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    # ---- 2. holdout：只读验证冻结阈值（禁止据 holdout 调阈值，T7.6）。
    try:
        holdout_report = run_holdout(
            thresholds,
            holdout_pairs,
            args.role,
            judge_pair,
            run_id=run_id,
            run_at=_utc_now(),
            position_sample=args.position_sample or None,
            on_pair_unreviewable=record_unreviewable,
        )
    except Exception as exc:
        print(f"Error: holdout 失败: {type(exc).__name__}")
        return 1

    # ---- 3. 落盘（全部凭证无关，无正文）。
    output_dir.joinpath("calibration_predictions.json").write_text(
        json.dumps(
            [p.model_dump(mode="json") for p in calib_predictions],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    output_dir.joinpath("calibration_report.json").write_text(
        json.dumps(calib_report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_dir.joinpath("thresholds.json").write_text(
        json.dumps(thresholds.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_dir.joinpath("holdout_report.json").write_text(
        json.dumps(holdout_report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "role": args.role,
        "policy_id": policy.policy_id,
        "policy_sha256": policy_sha256,
        "benchmarks": source_sha256,
        "calibration": {
            "pairs": len(calibration_pairs),
            "overall_accuracy": calib_report.overall_accuracy,
            "abstain_count": calib_report.abstain_count,
            "per_tag_n": calib_report.per_tag_n,
            "wilson_low": calib_report.wilson_low,
        },
        "thresholds_id": thresholds.thresholds_id,
        "holdout": {
            "pairs": len(holdout_pairs),
            "overall_accuracy": holdout_report.overall_accuracy,
            "position_consistency": holdout_report.position_consistency,
            "met": holdout_report.met,
            "violations": holdout_report.violations,
        },
        "route": "pass" if holdout_report.met else "fail",
        "quality": {
            "review_quality_retries": quality_retries,
            "unreviewable_pairs": unreviewable_pairs,
        },
        "frozen_by_run": run_id,
    }
    output_dir.joinpath("calibration_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 56)
    print("A1 auto-calibrate report")
    print("=" * 56)
    print(f"  role:                  {args.role}")
    print(f"  calibration pairs:     {len(calibration_pairs)}")
    print(f"  calibration accuracy:  {calib_report.overall_accuracy}"
          f" (wilson_low={calib_report.wilson_low})")
    print(f"  thresholds_id:         {thresholds.thresholds_id}")
    print(f"  holdout pairs:         {len(holdout_pairs)}")
    print(f"  holdout accuracy:      {holdout_report.overall_accuracy}"
          f" (>= {thresholds.overall_accuracy_min})")
    print(f"  position consistency:  {holdout_report.position_consistency}"
          f" (>= {thresholds.position_consistency_min})")
    print(f"  holdout met:           {holdout_report.met}")
    if holdout_report.violations:
        for violation in holdout_report.violations:
            print(f"    violation: {violation}")
    print(f"  usage:                 {ledger.usage.calls} calls / "
          f"${ledger.usage.cost_usd}")
    print(f"  quality retries:       {quality_retries}")
    if unreviewable_pairs:
        print(f"  unreviewable pairs:    {len(unreviewable_pairs)}")
        for u in unreviewable_pairs:
            print(f"    - {u['prompt_id']} ({u['tag']}): {u['error_type']}")
    print(f"  thresholds:            {output_dir / 'thresholds.json'}")
    if holdout_report.met:
        return 0
    print("\nG7: holdout 未达到预注册阈值（阈值已冻结，禁止据 holdout 调低）→ 失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
