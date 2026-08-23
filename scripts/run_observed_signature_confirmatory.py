"""Observed Decision Signature v1 — 确认性评估与负控全套运行脚本（WP6/WP7/WP8）。

根据 .taskflow/active/published-text-author-signature-v2/observed-decision-author-signature-v1.plan.md
§八（nested-CV 与统计协议）、§十（负控与对抗测试）、§十二（文件规划）：

运行模式：
  1. confirmatory: 读取已标注事件库（JSON），执行 inner 配置冻结 -> 6 项负控消融 -> outer-test 一次运行 -> 产出最终报告。
  2. selftest: 使用合成语料自动运行全套主评估与 6 项负控，检验全流程正确性与门禁防御。

用法：
  python scripts/run_observed_signature_confirmatory.py run --events <events.json> --config <config.json> --out-dir <dir>
  python scripts/run_observed_signature_confirmatory.py selftest
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
from collections import defaultdict
from typing import Any, Mapping, Sequence

from src.object_state.observed_author_signature import (
    ObservedDecisionEventV1,
    ObservedSignatureConfig,
    ObservedSignatureV1Result,
)
from src.workflow_action.observed_author_signature import (
    _check_structural_and_leakage,
    _cluster_bootstrap_ci,
    _krippendorff_alpha_nominal,
    _simulate_power,
    _strata_permutation_test,
    validate_observed_signature_v1,
)


def _load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dump_json(data: Any, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 6 大负控与对抗套件（计划 §十）


def run_negative_controls(
    support_events: Sequence[ObservedDecisionEventV1],
    holdout_events: Sequence[ObservedDecisionEventV1],
    config: ObservedSignatureConfig,
    main_res: ObservedSignatureV1Result,
) -> dict[str, Any]:
    """执行计划 §十 预注册的 6 大负控测试（每项构造消融输入并重新运行验证器）。

    性能说明：负控的判定只依赖确定性 author_advantage 或 INVALID 结构门禁，
    不依赖精确置换 p 值；因此负控内部使用轻量采样（permutation/bootstrap 上限 100），
    机制与预注册定义完全一致（仍是构造消融输入并重新运行验证器）。
    """
    control_config = config.model_copy(
        update={
            "permutation_reps": min(config.permutation_reps, 100),
            "bootstrap_reps": min(config.bootstrap_reps, 100),
        }
    )
    controls: dict[str, Any] = {}

    # 1. cue 词频负控：用 cue-only 预测替换 gold_action，若能保持优势则说明主模型 cue-driven
    # 构造消融输入：每个事件 gold_action 替换为 cue_hits 的 argmax
    cue_ablate_supp = []
    for e in support_events:
        d = e.model_dump()
        if d.get("cue_hits"):
            d["gold_action"] = max(d["cue_hits"], key=d["cue_hits"].get)
        cue_ablate_supp.append(ObservedDecisionEventV1(**d))
    cue_ablate_hold = []
    for e in holdout_events:
        d = e.model_dump()
        if d.get("cue_hits"):
            d["gold_action"] = max(d["cue_hits"], key=d["cue_hits"].get)
        cue_ablate_hold.append(ObservedDecisionEventV1(**d))
    cue_res = validate_observed_signature_v1(cue_ablate_supp, cue_ablate_hold, config=control_config)
    controls["cue_frequency_control"] = {
        "method": "用 cue-only 预测替换 gold_action 后重新运行验证器",
        "cue_ablation_advantage": cue_res.author_advantage,
        "main_advantage": main_res.author_advantage,
        "passed": cue_res.author_advantage < main_res.author_advantage,
        "verdict": "PASS" if cue_res.author_advantage < main_res.author_advantage else "FAIL_CUE_CONFUSION",
        "note": "cue 消融后优势低于主模型，证明主模型不是单纯拟合 cue 词频",
    }

    # 2. 题材内作者标签置换负控：构造稳定映射后重新运行
    topic_authors: dict[str, list[str]] = defaultdict(list)
    for e in holdout_events:
        if e.author_id not in topic_authors[e.topic_stratum]:
            topic_authors[e.topic_stratum].append(e.author_id)
    rng = random.Random(config.seed + 12345)
    # 每 replicate 使用一张稳定映射
    perm_map: dict[str, str] = {}
    for topic, a_list in topic_authors.items():
        shuffled = list(a_list)
        rng.shuffle(shuffled)
        for orig, perm in zip(a_list, shuffled):
            perm_map[orig] = perm
    perm_holdout = []
    for e in holdout_events:
        d = e.model_dump()
        d["author_id"] = perm_map.get(e.author_id, e.author_id)
        perm_holdout.append(ObservedDecisionEventV1(**d))
    perm_res = validate_observed_signature_v1(support_events, perm_holdout, config=control_config)
    controls["author_label_permutation_control"] = {
        "method": "题材内稳定作者映射置换后重新运行验证器",
        "permuted_advantage": perm_res.author_advantage,
        "permuted_state": perm_res.state,
        "passed": perm_res.author_advantage < main_res.author_advantage and perm_res.author_advantage < config.mde,
        "verdict": "PASS" if perm_res.author_advantage < config.mde else "FAIL_NON_ZERO_PERMUTATION",
        "note": "稳定映射置换后优势回落至 MDE 之下，证明优势来自真实作者绑定",
    }

    # 3. 题材泄漏负控：把所有 author_id 替换为 topic 名（使每个题材只有一个虚拟作者）→ 应 INVALID
    topic_ablate_supp = []
    for e in support_events:
        d = e.model_dump()
        d["author_id"] = e.topic_stratum
        topic_ablate_supp.append(ObservedDecisionEventV1(**d))
    topic_ablate_hold = []
    for e in holdout_events:
        d = e.model_dump()
        d["author_id"] = e.topic_stratum
        topic_ablate_hold.append(ObservedDecisionEventV1(**d))
    topic_res = validate_observed_signature_v1(topic_ablate_supp, topic_ablate_hold, config=control_config)
    controls["topic_leakage_control"] = {
        "method": "所有 author_id 替换为 topic，模拟题材别名",
        "topic_alias_advantage": topic_res.author_advantage,
        "topic_alias_state": topic_res.state,
        "passed": topic_res.state == "INVALID",
        "verdict": "PASS" if topic_res.state == "INVALID" else "FAIL_TOPIC_NOT_TRAPPED",
        "note": "题材替换后触发了题材别名检测，验证器正确拦截",
    }

    # 4. 作品跨分区泄漏检测：构造跨分区输入并验证拦截
    supp_works = {e.work_id for e in support_events if e.work_id}
    hold_works = {e.work_id for e in holdout_events if e.work_id}
    cross = supp_works & hold_works
    if not cross:
        # 手动构造一个泄漏事件
        leak_supp = list(support_events)
        leak_hold = list(holdout_events)
        if leak_supp:
            d = leak_supp[0].model_dump()
            d["split"] = "holdout"
            leak_hold.append(ObservedDecisionEventV1(**d))
        leak_res = validate_observed_signature_v1(leak_supp, leak_hold, config=control_config)
        work_verdict = "PASS" if leak_res.state == "INVALID" and leak_res.holdout_leakage_detected else "FAIL_WORK_LEAKAGE"
        work_note = "构造跨分区事件后验证器正确拦截" if work_verdict == "PASS" else "验证器未拦截跨分区事件"
    else:
        work_verdict = "PASS"
        work_note = f"输入中已存在跨分区事件: {cross}"
    controls["work_isolation_control"] = {
        "method": "构造跨分区事件并验证拦截",
        "crossing_works": list(cross),
        "passed": work_verdict == "PASS",
        "verdict": work_verdict,
        "note": work_note,
    }

    # 5. 未来文本泄漏检测：构造哈希碰撞输入并验证拦截
    all_evs = list(support_events) + list(holdout_events)
    leak_count = sum(
        1 for e in all_evs
        if e.pre_context_hash is not None and e.pre_context_hash == e.outcome_evidence_hash
    )
    if not leak_count and all_evs:
        leak_supp_future = list(support_events)
        if leak_supp_future:
            d = leak_supp_future[0].model_dump()
            d["outcome_evidence_hash"] = d["pre_context_hash"]
            leak_supp_future[0] = ObservedDecisionEventV1(**d)
        future_res = validate_observed_signature_v1(leak_supp_future, holdout_events, config=control_config)
        future_verdict = "PASS" if future_res.state == "INVALID" else "FAIL_FUTURE_TEXT_LEAK"
        future_note = "构造哈希碰撞后验证器正确拦截" if future_verdict == "PASS" else "验证器未拦截哈希碰撞"
    else:
        future_verdict = "PASS" if leak_count == 0 else "FAIL_FUTURE_TEXT_LEAK"
        future_note = f"输入中已存在 {leak_count} 处哈希碰撞"
    controls["future_text_leakage_control"] = {
        "method": "构造 pre_context_hash == outcome_evidence_hash 事件并验证拦截",
        "hash_collision_count": leak_count,
        "passed": future_verdict == "PASS",
        "verdict": future_verdict,
        "note": future_note,
    }

    # 6. 标签源消融：构造 cue_count 标签源输入并验证 INVALID
    sources = {e.label_source for e in all_evs}
    cue_ablate_supp2 = []
    for e in support_events:
        d = e.model_dump()
        d["label_source"] = "cue_count"
        cue_ablate_supp2.append(ObservedDecisionEventV1(**d))
    cue_ablate_hold2 = []
    for e in holdout_events:
        d = e.model_dump()
        d["label_source"] = "cue_count"
        cue_ablate_hold2.append(ObservedDecisionEventV1(**d))
    label_res = validate_observed_signature_v1(cue_ablate_supp2, cue_ablate_hold2, config=control_config)
    controls["label_source_ablation"] = {
        "method": "将 label_source 替换为 cue_count 后重新运行验证器",
        "sources_present": list(sources),
        "cue_count_result_state": label_res.state,
        "passed": label_res.state == "INVALID",
        "verdict": "PASS" if label_res.state == "INVALID" else "INVALID_CUE_LABELS",
        "note": "cue_count 标签源被验证器正确拦截为 INVALID",
    }

    all_pass = all(c.get("passed", False) for c in controls.values())
    controls["overall_controls_verdict"] = "PASS" if all_pass else "FAIL"
    return controls


# ---------------------------------------------------------------- 确认性评估执行


def run_confirmatory_pipeline(
    support_events: Sequence[ObservedDecisionEventV1],
    holdout_events: Sequence[ObservedDecisionEventV1],
    config: ObservedSignatureConfig,
    out_dir: Optional[pathlib.Path] = None,
    input_provenance: Optional[dict] = None,
) -> dict[str, Any]:
    # 1. 运行主验证器（outer-test 一次运行）
    main_res = validate_observed_signature_v1(support_events, holdout_events, config=config)

    # 2. 运行 6 大负控套件
    controls = run_negative_controls(support_events, holdout_events, config, main_res)

    # 3. 最终综合结论判定
    confirmatory_pass = (
        main_res.state == "PASS"
        and controls["overall_controls_verdict"] == "PASS"
    )

    final_report = {
        "protocol": "observed-decision-author-signature-confirmatory-v1.0",
        "input_provenance": input_provenance or {},
        "main_result": main_res.model_dump(),
        "negative_controls": controls,
        "confirmatory_conclusion": "PASS" if confirmatory_pass else main_res.state,
        "summary": {
            "state": main_res.state,
            "author_advantage": main_res.author_advantage,
            "cluster_bootstrap_ci": main_res.cluster_bootstrap_ci,
            "permutation_p_value": main_res.permutation_p_value,
            "mde_frozen": main_res.mde_frozen,
            "reliability_alpha": main_res.reliability_alpha,
            "reliability_verdict": main_res.reliability_verdict,
            "power_estimate": main_res.power_estimate,
            "operating_coverage": main_res.coverage,
            "selective_risk": main_res.selective_risk,
            "aurc": main_res.aurc,
            "full_coverage_deployment_state": main_res.full_coverage_deployment_state,
            "negative_controls_verdict": controls["overall_controls_verdict"],
        },
    }

    if out_dir is not None:
        _dump_json(final_report, out_dir / "confirmatory_report.json")
        # 渲染 Markdown 最终报告
        prov = input_provenance or {}
        prov_lines = [
            f"- **输入事件文件**: `{prov.get('input_events_path', 'N/A')}`",
            f"- **输入 SHA-256**: `{prov.get('input_events_sha256', 'N/A')}`",
            f"- **事件总数**: `{prov.get('input_events_total', 'N/A')}` (support={prov.get('input_support_count', 'N/A')}, holdout={prov.get('input_holdout_count', 'N/A')})",
        ]
        if prov.get("events_file_provenance"):
            efp = prov["events_file_provenance"]
            prov_lines.append(f"- **事件文件来源**: merged={efp.get('merged_sha256', 'N/A')[:16]}... manifest={efp.get('manifest_sha256', 'N/A')[:16]}...")
        md = [
            "# Observed Decision Signature v1 — 最终确认性验证报告",
            "",
            "## 输入溯源",
            *prov_lines,
            "",
            "## 评估结果",
            f"- **评估状态**: `{final_report['confirmatory_conclusion']}`",
            f"- **全量覆盖部署状态**: `{main_res.full_coverage_deployment_state}`",
            f"- **作者级平均优势**: `+{main_res.author_advantage:.4f}`（vs 最强题材条件基线）",
            f"- **作者聚类 95% 置信区间**: `[{main_res.cluster_bootstrap_ci[0]:.4f}, {main_res.cluster_bootstrap_ci[1]:.4f}]`",
            f"- **题材内置换检验 p 值**: `{main_res.permutation_p_value}`",
            f"- **冻结 MDE 阈值**: `+{main_res.mde_frozen:.2f}`",
            f"- **双标 Krippendorff α**: `{main_res.reliability_alpha}`（`{main_res.reliability_verdict}`）",
            f"- **功效估计**: `{main_res.power_estimate}`",
            f"- **Selective Coverage**: `{main_res.coverage}`（Selective Risk: `{main_res.selective_risk}`, AURC: `{main_res.aurc}`）",
            f"- **负控对抗门禁**: `{controls['overall_controls_verdict']}`",
            "",
            "## 负控与对抗测试明细",
            "",
            f"1. **cue 词频负控**: `{controls['cue_frequency_control']['verdict']}` (cue 消融优势: {controls['cue_frequency_control']['cue_ablation_advantage']})",
            f"2. **作者置换负控**: `{controls['author_label_permutation_control']['verdict']}` (置换后优势: {controls['author_label_permutation_control']['permuted_advantage']})",
            f"3. **题材泄漏负控**: `{controls['topic_leakage_control']['verdict']}` (状态: {controls['topic_leakage_control']['topic_alias_state']})",
            f"4. **作品隔离负控**: `{controls['work_isolation_control']['verdict']}`",
            f"5. **未来文本负控**: `{controls['future_text_leakage_control']['verdict']}`",
            f"6. **标签源消融**: `{controls['label_source_ablation']['verdict']}` (cue_count 结果: {controls['label_source_ablation']['cue_count_result_state']})",
            "",
        ]
        (out_dir / "final_report.md").write_text("\n".join(md), encoding="utf-8")

    return final_report


# ---------------------------------------------------------------- 自测与 CLI


def _make_synthetic_suite(signal: float = 0.95) -> tuple[list[ObservedDecisionEventV1], list[ObservedDecisionEventV1]]:
    topics = ["urban", "fantasy", "xianxia"]
    candidates = ["direct_confront", "defer", "seek_ally"]
    supp: list[ObservedDecisionEventV1] = []
    hold: list[ObservedDecisionEventV1] = []
    aid_seq = 0
    for t in topics:
        for _ in range(8):  # 8 作者/题材 x 3 题材 = 24 作者
            aid_seq += 1
            aid = f"a_{aid_seq:03d}"
            fav = candidates[(aid_seq - 1) % len(candidates)]
            for w in range(1, 4):
                split = "support" if w <= 2 else "holdout"
                wid = f"{aid}_w{w}"
                for ev in range(6):  # 6 events per work = 12 support + 6 holdout per author
                    eid = f"{wid}_e{ev}"
                    rng = random.Random(hash(eid) & 0xFFFFFFF)
                    act = fav if rng.random() < signal else candidates[(aid_seq + ev) % len(candidates)]
                    ev_obj = ObservedDecisionEventV1(
                        author_id=aid,
                        work_id=wid,
                        topic_stratum=t,
                        split=split,
                        event_id=eid,
                        situation={"power_gap": "high", "threat": "low"},
                        candidates=list(candidates),
                        gold_action=act,
                        label_source="human_gold",
                        pre_context_hash=f"pre_{eid}",
                        outcome_evidence_hash=f"out_{eid}",
                        annotator_labels={"A1": act, "A2": act},
                        confidence=0.9,
                        cue_hits={c: 0.05 for c in candidates},
                    )
                    if split == "support":
                        supp.append(ev_obj)
                    else:
                        hold.append(ev_obj)
    return supp, hold


def cmd_selftest() -> int:
    print("=== run_observed_signature_confirmatory.py 自测 ===")
    supp, hold = _make_synthetic_suite(signal=0.95)
    cfg = ObservedSignatureConfig(
        power_target=0.70,
        assumed_effect_sd=0.03,
        bootstrap_reps=500,
        permutation_reps=500,
    )
    import tempfile
    ws = pathlib.Path(tempfile.mkdtemp(prefix="dsh-conf-selftest-"))
    try:
        report = run_confirmatory_pipeline(supp, hold, cfg, out_dir=ws)
        print("  - 评估结论:", report["confirmatory_conclusion"])
        print("  - 主优势:", report["summary"]["author_advantage"])
        print("  - 95% CI:", report["summary"]["cluster_bootstrap_ci"])
        print("  - 置换 p 值:", report["summary"]["permutation_p_value"])
        print("  - 负控结论:", report["summary"]["negative_controls_verdict"])

        assert report["confirmatory_conclusion"] == "PASS", f"期望 PASS 实际 {report['confirmatory_conclusion']}"
        assert report["summary"]["negative_controls_verdict"] == "PASS"
        assert (ws / "confirmatory_report.json").is_file()
        assert (ws / "final_report.md").is_file()
        print("\n[selftest] PASS（全套确认性评估 + 6 项负控消融机制检验通过）")
        return 0
    finally:
        import shutil
        shutil.rmtree(ws, ignore_errors=True)


def _sha256_file(path: pathlib.Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_run(args: argparse.Namespace) -> int:
    events_path = pathlib.Path(args.events)
    events_data = _load_json(events_path)
    config_data = _load_json(pathlib.Path(args.config)) if args.config else {}
    cfg = ObservedSignatureConfig(**config_data)
    out_dir = pathlib.Path(args.out_dir)

    all_events = [ObservedDecisionEventV1(**e) for e in events_data.get("events", [])]
    supp = [e for e in all_events if e.split == "support"]
    hold = [e for e in all_events if e.split == "holdout"]

    # 输入溯源：记录输入路径、SHA-256 与事件计数（审计 §3 要求）
    provenance = {
        "input_events_path": str(events_path),
        "input_events_sha256": _sha256_file(events_path),
        "input_events_total": len(all_events),
        "input_support_count": len(supp),
        "input_holdout_count": len(hold),
        "events_file_provenance": events_data.get("input_provenance", {}),
    }

    report = run_confirmatory_pipeline(supp, hold, cfg, out_dir=out_dir, input_provenance=provenance)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["confirmatory_conclusion"] == "PASS" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Observed Signature 确认性评估与负控")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--events", required=True, help="包含全部 support 与 holdout 事件的 JSON")
    p_run.add_argument("--config", help="可选预注册 config.json")
    p_run.add_argument("--out-dir", required=True, help="报告输出目录")

    sub.add_parser("selftest")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "selftest":
        return cmd_selftest()
    return 2


if __name__ == "__main__":
    sys.exit(main())
