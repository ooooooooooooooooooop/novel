#!/usr/bin/env python3
"""style_drift_short_form — Style Drift 测量（measurement-only，不自动纠正）.

从小说工作区产出 drift 报告：
1. AI 章 vs 人类原文 baseline 的『AI 化 drift』（他意识到/身体反应/解释收尾/不是而是…）。
2. 同一章的 Draft vs Committed（用 output/prose_history/draft_chapter_N.txt）——
   判断 Review 修订是否在制造 homogenization（Draft 有变化、Committed 更统一）。

用法：
    python src/style_drift_short_form.py --output-dir <dir> --chapters-dir <dir> --baseline <file>
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.experiment.style_drift import compare_draft_committed, drift_report, measure_text


def _chapter_num(path: Path) -> int:
    try:
        return int(path.stem[len("chapter_"):])
    except ValueError:
        return 10**9


def _load_frame_meta(output_dir: Path) -> dict[str, str]:
    """从 output/extend_frames.json 提取 scene→formula_node 映射（供 drift 按叙事阶段分组）.

    scene_i ↔ chapter_i（当前单章=单场景的创作形态）；读不到返回空映射。
    """
    meta: dict[str, str] = {}
    for name in ("extend_frames.json", "compose_frames.json"):
        path = output_dir / name
        if not path.exists():
            continue
        try:
            frames = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        scenes = [f for f in frames if f.get("level") == "scene"]
        for i, s in enumerate(scenes, start=1):
            node = s.get("formula_node") or s.get("title") or ""
            meta[f"chapter_{i:02d}"] = node
            meta[f"chapter_{i}"] = node
    return meta


def _load_provenance(output_dir: Path) -> dict:
    """读 output/chapter_provenance.json（无则返回空）."""
    path = output_dir / "chapter_provenance.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("chapters", {})


def main() -> int:
    parser = argparse.ArgumentParser(description="Style Drift 测量")
    parser.add_argument("--output-dir", default="output", help="工作区 output 目录")
    parser.add_argument("--chapters-dir", default="", help="chapters/ 目录")
    parser.add_argument("--baseline", default="", help="人类原文 baseline 文件")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    chapters_dir = Path(args.chapters_dir) if args.chapters_dir else output_dir.parent.parent / "chapters"
    baseline_path = Path(args.baseline) if args.baseline else output_dir.parent.parent / "input.txt"

    if not baseline_path.exists():
        print(f"Error: baseline not found: {baseline_path}")
        return 1
    baseline = baseline_path.read_text(encoding="utf-8")

    chapters = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    if not chapters:
        print(f"Error: no chapters in {chapters_dir}")
        return 1

    report: dict = {
        "schema_version": 2,
        "baseline_metrics": measure_text(baseline),
        "chapters": [],
        "draft_vs_committed": [],
        "note": (
            "measurement-only：不自动纠正。AI 化 drift 上升 ≠ 变差，需人工判断；"
            "draft_vs_committed 的 positive 信号 = Review 修订后更统一（homogenization 风险）。"
            "formula_node 标注叙事阶段，便于『控制阶段后看时间是否仍解释 drift』。"
        ),
    }

    frame_meta = _load_frame_meta(output_dir)
    provenance = _load_provenance(output_dir)

    for ch in chapters:
        text = ch.read_text(encoding="utf-8")
        meta = provenance.get(ch.stem, {})
        report["chapters"].append({
            "chapter": ch.stem,
            "formula_node": frame_meta.get(ch.stem, ""),
            "flow_version": meta.get("flow_version", ""),
            "review_version": meta.get("review_version", ""),
            "prose_review_enabled": meta.get("prose_review_enabled", False),
            "metrics": measure_text(text),
        })

    # Draft vs Committed（homogenization 检查）
    for ch in chapters:
        num = _chapter_num(ch)
        draft_path = output_dir / "prose_history" / f"draft_chapter_{num}.txt"
        if not draft_path.exists():
            continue
        committed = ch.read_text(encoding="utf-8")
        draft = draft_path.read_text(encoding="utf-8")
        report["draft_vs_committed"].append({
            "chapter": ch.stem,
            **compare_draft_committed(draft, committed),
        })

    drift = drift_report(
        [(ch.stem, ch.read_text(encoding="utf-8")) for ch in chapters],
        baseline,
    )
    report["ai_drift_deltas"] = {
        "realization_per_1k": [c["delta"]["realization_per_1k"] for c in drift["chapters"]],
        "body_reaction_per_1k": [c["delta"]["body_reaction_per_1k"] for c in drift["chapters"]],
        "explanatory_per_1k": [c["delta"]["explanatory_per_1k"] for c in drift["chapters"]],
        "not_a_but_b_per_1k": [c["delta"]["not_a_but_b_per_1k"] for c in drift["chapters"]],
        "metaphor_per_1k": [c["delta"]["metaphor_per_1k"] for c in drift["chapters"]],
        "sentence_len_delta": [c["delta"]["sentence_len"] for c in drift["chapters"]],
    }

    out_dir = output_dir / "drift"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "drift_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Style drift report: {report_path}")
    print(f"  chapters measured: {len(report['chapters'])}")
    print(f"  draft-vs-committed pairs: {len(report['draft_vs_committed'])}")
    print("  AI drift deltas (vs baseline):")
    for k, v in report["ai_drift_deltas"].items():
        print(f"    {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
