#!/usr/bin/env python3
"""blind_eval_short_form — Post-Prose Review 的 A/B 盲评 staged CLI.

测量 Post-Prose Review 的净效果（measurement-only，不改 Review 规则）：
从工作区 A/B 台账（output/prose_revision_ledger.json）取尚未评审的修订对，
以 staged 方式物化盲评 prompt（Judge 看不到哪个是原文、看不到 Review issue），
operator/独立 Judge 填响应后重跑 → 写回偏好并产出分层统计
（Revision Gain / Detection Precision / net_rate / Wilson CI）。

用法（Codex 循环）：
    python src/blind_eval_short_form.py --output-dir <dir>
    1. 第一次运行：为每个待评审修订对写 ab_judge_<i>_prompt.txt 后 [WAITING]。
    2. 把每个 prompt 交给独立 Judge（不展示 issue / 哪个是原文），
       把判断 JSON 保存到对应 ab_judge_<i>_response.txt。
    3. 重跑：解析响应 → 写回台账 → 产出 output/blind_eval_summary.json。

--detection 模式：只跑 Detection Precision pass（Judge 判断原文是否确有被标记缺陷）。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiment.blind_eval import (
    BlindEvalUnit,
    load_ledger,
    summarize,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B 盲评（Post-Prose Review 测量）")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument(
        "--detection",
        action="store_true",
        help="只跑 Detection Precision pass（原文是否确有被标记缺陷）",
    )
    parser.add_argument(
        "--judge",
        default="judge_1",
        help="本次 Judge 标识（默认 judge_1；多 Judge 用 judge_1/judge_2/judge_3 区分，"
        "汇总支持 3/3、2/3、split）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ledger_path = output_dir / "prose_revision_ledger.json"
    if not ledger_path.exists():
        print(f"Error: no A/B ledger at {ledger_path}")
        return 1

    entries = load_ledger(output_dir)
    if not entries:
        print("A/B ledger is empty.")
        return 1

    unit = BlindEvalUnit()
    if args.detection:
        pending = [
            e for e in entries
            if (e.get("detection") or {}).get("original_has_flaw") is None
        ]
        field = "detection"
    else:
        pending = [
            e for e in entries
            if (e.get("revision_gain") or {}).get("preference") is None
        ]
        field = "revision_gain"

    if not pending:
        # 全部已评审 → 汇总
        summary = summarize(entries)
        summary_path = output_dir / "blind_eval_summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"All {len(entries)} pairs judged. Summary: {summary_path}")
        _print_summary(summary)
        return 0

    # 物化 / 读取 judge 响应（revision 与 detection 用不同前缀，避免互相踩响应槽）
    prefix = "ab_detect" if args.detection else "ab_judge"
    responses: dict[int, str] = {}
    missing: list[Path] = []
    for i, entry in enumerate(pending):
        prompt_path = output_dir / f"{prefix}_{i:03d}_prompt.txt"
        resp_path = output_dir / f"{prefix}_{i:03d}_response.txt"
        if resp_path.exists():
            responses[i] = resp_path.read_text(encoding="utf-8")
        else:
            if not prompt_path.exists():
                if args.detection:
                    prompt_text = unit.build_detection_prompt(entry)
                else:
                    prompt_text = unit.build_revision_gain_prompt(entry)
                prompt_path.write_text(prompt_text, encoding="utf-8")
            missing.append(prompt_path)

    if missing:
        mode = "DETECTION" if args.detection else "REVISION GAIN"
        print(f"[STEP: BLIND {mode}] {len(missing)} judge prompt(s) saved.")
        for p in missing:
            print(f"  {p}")
        print(f"[WAITING] 请交给独立 Judge（不展示 issue / 哪个是原文）填写对应 "
              f"ab_judge_<i>_response.txt（JSON），然后重跑。")
        return 0

    # 应用响应，写回台账（追加 judgment + 聚合）
    from src.experiment.blind_eval import _majority_flaw, _majority_preference

    for i, entry in enumerate(pending):
        try:
            if args.detection:
                result = unit.parse_detection(responses[i])
                det = entry.setdefault("detection", {})
                det.setdefault("judgments", []).append({
                    "judge_id": args.judge,
                    "flaw_present": result["flaw_present"],
                    "confidence": result["confidence"],
                })
                det["original_has_flaw"] = _majority_flaw(det["judgments"])
            else:
                result = unit.parse_revision_gain(responses[i])
                rg = entry.setdefault("revision_gain", {})
                rg.setdefault("judgments", []).append({
                    "judge_id": args.judge,
                    "preference": result["preference"],
                    "confidence": result["confidence"],
                })
                rg["preference"] = _majority_preference(rg["judgments"])
                rg["confidence"] = max(
                    j.get("confidence", 0.0) for j in rg["judgments"]
                )
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"Error parsing ab_judge_{i:03d}_response.txt: {exc}")
            return 1

    ledger = {"schema_version": 2, "revisions": entries}
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = summarize(entries)
    summary_path = output_dir / "blind_eval_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Judged {len(pending)} pair(s). Summary: {summary_path}")
    _print_summary(summary)
    return 0


def _print_summary(summary: dict) -> None:
    rows = [("issue_type", "better", "worse", "no_diff", "uncertain", "net", "better_rate", "95%CI")]
    items = [("overall", summary["overall"])] + sorted(
        summary.get("by_issue_type", {}).items()
    )
    for name, s in items:
        ci = s.get("better_rate_ci")
        ci_txt = f"[{ci[0]:.2f}, {ci[1]:.2f}]" if ci else "-"
        br = f"{s['better_rate']:.2f}" if s["better_rate"] is not None else "-"
        rows.append((
            name, str(s["better"]), str(s["worse"]), str(s["no_diff"]),
            str(s["uncertain"]), f"{s['net_rate']:+.2f}", br, ci_txt,
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(r, widths)))
    det = summary["overall"].get("detection_precision")
    if det is not None:
        print(f"  Detection precision: {det:.2f} (n={summary['overall']['detection_n']})")


if __name__ == "__main__":
    sys.exit(main())
