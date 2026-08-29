#!/usr/bin/env python3
"""pass_audit_short_form — PASS Blind Audit（测 Review 漏检率，measurement-only）.

抽样 route=pass 的 committed chapter，交给独立 Blind Audit 自由找缺陷
（不透露这是 PASS 样本、不给原 Review 结果），估算 Review 的漏检率。

用法（Codex 循环）：
    python src/pass_audit_short_form.py --chapters-dir <dir> --output-dir <dir>
    1. 第一次运行：为每章写 pa_<i>_prompt.txt 后 [WAITING]。
    2. 把每章交给独立 Judge 自由审查，把判定 JSON 保存到 pa_<i>_response.txt。
    3. 重跑：解析 → 写 results → 汇总 output/pass_audit/pass_audit_summary.json。
"""

import argparse
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.chapter_commit import ChapterCommitBoundary
from src.experiment.pass_audit import PassAuditUnit, load_pass_audit_results, summarize_pass_audit


def _chapter_num(path: Path) -> int:
    try:
        return int(path.stem[len("chapter_"):])
    except ValueError:
        return 10**9


def main() -> int:
    parser = argparse.ArgumentParser(description="PASS Blind Audit（测漏检率）")
    parser.add_argument("--chapters-dir", required=True, help="chapters/ 目录（committed 章）")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--limit", type=int, default=0, help="只审前 N 章（0=全部）")
    parser.add_argument("--sample", type=int, default=0, help="随机抽 N 章（0=全部）")
    parser.add_argument("--force", action="store_true", help="覆盖已有响应重新物化")
    args = parser.parse_args()

    chapters_dir = Path(args.chapters_dir)
    output_dir = Path(args.output_dir)
    audit_dir = output_dir / "pass_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    chapters = sorted(chapters_dir.glob("chapter_*.txt"), key=_chapter_num)
    if args.limit:
        chapters = chapters[: args.limit]
    if args.sample:
        chapters = sorted(
            random.Random(0).sample(chapters, min(args.sample, len(chapters))),
            key=_chapter_num,
        )
    if not chapters:
        print(f"Error: no chapters in {chapters_dir}")
        return 1

    unit = PassAuditUnit()

    # 检查是否有已物化的响应
    responses: dict[int, str] = {}
    missing: list[Path] = []
    for i, ch in enumerate(chapters):
        prompt_path = audit_dir / f"pa_{i:03d}_prompt.txt"
        resp_path = audit_dir / f"pa_{i:03d}_response.txt"
        if resp_path.exists() and not args.force:
            responses[i] = resp_path.read_text(encoding="utf-8")
        else:
            if not prompt_path.exists() or args.force:
                label = ch.stem
                prompt_path.write_text(
                    unit.build_audit_prompt(ch.read_text(encoding="utf-8"), label),
                    encoding="utf-8",
                )
            missing.append(prompt_path)

    if missing:
        print(f"[STEP: PASS AUDIT] {len(missing)} chapter(s) to audit, prompt saved:")
        for p in missing:
            print(f"  {p}")
        print(f"[WAITING] 请交给独立 Judge（不告诉它是 PASS 样本）自由找缺陷，"
              f"填写 pa_<i>_response.txt（JSON），然后重跑。")
        return 0

    # 解析响应，写结果（附审核世代 provenance，供 cohort 分组），汇总
    provenance = _load_provenance(output_dir)
    results = []
    for i, ch in enumerate(chapters):
        try:
            parsed = unit.parse_audit(responses[i])
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"Error parsing pa_{i:03d}_response.txt: {exc}")
            return 1
        meta = provenance.get(ch.stem, {})
        results.append({
            "chapter_label": ch.stem,
            "original_review_route": "pass",  # committed ⇒ PASS（Draft/Commit）
            "prose_review_enabled": bool(meta.get("prose_review_enabled", True)),
            "review_version": meta.get("review_version", "post-prose-v1"),
            "review_issues": meta.get("review_issues", []),  # O：原 Review 报的问题
            "clean": parsed["clean"],
            "findings": parsed["findings"],
        })

    results_path = audit_dir / "pass_audit_results.json"
    results_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = summarize_pass_audit(results)
    summary_path = audit_dir / "pass_audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"PASS audit results: {results_path}")
    print(f"Summary: {summary_path}")
    _print_summary(summary)
    return 0


def _load_provenance(output_dir: Path) -> dict:
    """只读取 recover 认可、review_route=pass、artifact hash 完整的提交 provenance."""
    output_dir = Path(output_dir)

    def accepted(run_dir: Path) -> tuple[int, dict] | None:
        boundary = ChapterCommitBoundary(run_dir)
        recovery = boundary.recover()
        manifest = recovery.manifest
        if (
            not recovery.recognized
            or manifest is None
            or manifest.review_route != "pass"
            or manifest.chapter_number is None
        ):
            return None
        path = run_dir / "chapter_provenance.json"
        rel = boundary._rel(path)
        if rel not in manifest.artifacts or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8")).get("chapters", {})
        key = f"chapter_{manifest.chapter_number}"
        if key not in data:
            return None
        entry = data[key]
        expected_review_hash = __import__("hashlib").sha256(
            json.dumps(
                entry.get("review_issues", []),
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if entry.get("review_evidence_hash") != expected_review_hash:
            return None
        return manifest.chapter_number, {key: entry}

    by_number: dict[int, dict] = {}
    candidate_dirs = []
    if (output_dir / "run_manifest.json").is_file():
        candidate_dirs.append(output_dir)
    candidate_dirs.extend(
        sorted(path for path in output_dir.iterdir() if path.is_dir())
    )
    for run_dir in candidate_dirs:
        item = accepted(run_dir)
        if item is None:
            continue
        number, chapter = item
        if number in by_number:
            raise ValueError(f"multiple recover-recognized PASS runs for chapter_{number}")
        by_number[number] = chapter
    chapters: dict = {}
    for number in sorted(by_number):
        chapters.update(by_number[number])
    return chapters


def _print_summary(summary: dict) -> None:
    o = summary["overall"]
    print(f"  chapters audited: {o['n_chapters']} | clean: {o['clean']} | has_issues: {o['has_issues']}")
    print(f"  audit_finding_rate: {o['audit_finding_rate']}")
    print(f"  true_miss_rate: {o['true_miss_rate']}")
    print(f"  actionable_true_miss_rate: {o['actionable_true_miss_rate']}")
    print(f"  blocking_true_miss_rate: {o['blocking_true_miss_rate']}")
    print(f"  severity_disagreement_rate: {o['severity_disagreement_rate']}")
    print("  by_cohort（不同审核世代分算，不混 cohort）:")
    for cohort, s in sorted(summary.get("by_cohort", {}).items()):
        print(f"    [{cohort}] n={s['n_chapters']} "
              f"finding={s['audit_finding_rate']} true_miss={s['true_miss_rate']} "
              f"actionable_miss={s['actionable_true_miss_rate']} "
              f"blocking_miss={s['blocking_true_miss_rate']}")
    for t, st in sorted(o.get("by_issue_type", {}).items()):
        print(f"    {t}: {st['count']} (blocking/critical: "
              f"{st['severity_counts']['blocking'] + st['severity_counts']['critical']})")


if __name__ == "__main__":
    sys.exit(main())
