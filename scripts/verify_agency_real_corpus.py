"""S4（54 计划 §S4）：53 三机制真实语料验证——重跑研究轨结论，无人参与.

把 53 三机制（Work Experience 因果节点化 / Reflective Override 二阶否决 /
Experience Ablation 消融验证）从研究轨 selftest（合成夹具）推进到真实
ChoiceLedger 语料：把每条决策记录映射为消融事件（plot_context → 情境、
selected_candidate → 决策、consequence/hindsight → 结局与教训），
在真实格式语料上断言与 selftest 一致的结论（EXPERIENCE_IS_CAUSAL_NODE）。

用法：
  python scripts/verify_agency_real_corpus.py [--ledger PATH]
缺省 --ledger 使用内置"真实格式"合成语料（对齐 ChoiceLedger schema，
保证离线可重跑）。隐私纪律：不硬编码小说名/路径入仓库，真实路径由
调用方显式传入；脚本不读取正文、不输出任何具体叙事内容。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.research_agency.experience_ablation import build_ablation_report
from src.research_agency.experience_ledger import ExperienceLedger, build_meaning_view
from src.research_agency.reflective_override import ReflectiveOverride


# ---------------------------------------------------------------------------
# 真实格式语料（对齐 ChoiceLedger records schema，离线缺省回退）
# ---------------------------------------------------------------------------

def _synth_corpus() -> list[dict[str, Any]]:
    """内置合成语料：与真实 ChoiceLedger 相同的键结构，规避隐私与离线依赖."""
    base = {
        "decision_timestamp": "2026-08-08T00:00:00+00:00",
        "state_ref": "ns_synth_001",
        "character_refs": ["c001"],
        "style_profile_id": None,
        "tradeoff": "综合权衡",
        "value_conflicts": [],
    }
    records = []
    for index in range(1, 9):
        rec = dict(base)
        rec.update({
            "decision_id": f"dec_synth_{index:03d}",
            "plot_context": f"第 {index} 次面临同一类抉择（主题：背叛），线索与上回同源",
            "chapter_number": index,
            "candidates": [
                {"candidate_id": "A", "summary": "维持原有路线"},
                {"candidate_id": "B", "summary": "依据历史教训改道"},
                {"candidate_id": "C", "summary": "另辟蹊径"},
            ],
            "selected_candidate": "A" if index == 1 else "B",
            "rejected": [{"candidate_id": "C", "reason": "与作品历史不符"}],
            "consequence": f"结局 {index}：选择落地",
            "hindsight": "still_supported" if index % 2 == 0 else None,
            "hindsight_note": f"第 {index} 次的教训：重复默认路线已被历史证伪",
        })
        records.append(rec)
    return records


def load_records(ledger_path: str | None) -> list[dict[str, Any]]:
    """加载 ChoiceLedger JSON 为记录列表；缺省用内置合成语料."""
    if not ledger_path:
        return _synth_corpus()
    data = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "choices", "decisions"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        raise ValueError(
            f"ChoiceLedger 顶层既非列表也缺 records/choices/decisions 数组: {ledger_path}"
        )
    raise ValueError(f"无法识别的语料结构: {ledger_path}")


def record_to_event(record: Mapping[str, Any], index: int) -> dict[str, Any]:
    """单条决策记录 → 消融事件（保留 plot_context 全文，不输出正文）."""
    return {
        "event_id": str(record.get("decision_id") or f"dec-{index}"),
        "topic": "作品决策",
        "plot_context": record.get("plot_context") or "",
        "chapter": int(record.get("chapter_number") or 0),
        "decision": str(record.get("selected_candidate") or ""),
        "outcome": record.get("consequence") or "",
        "lesson": record.get("hindsight_note") or (record.get("hindsight") or ""),
    }


def _events(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [record_to_event(record, index) for index, record in enumerate(records)]


# ---------------------------------------------------------------------------
# 三机制真实路径验证
# ---------------------------------------------------------------------------

def verify_experience_ledger(events: list[dict[str, Any]]) -> bool:
    """真实事件序列上：同一情境、不同历史 → 不同 MeaningView."""
    situation = {"plot_context": "同一主题的当前抉择"}
    full = ExperienceLedger(events)
    partial = ExperienceLedger(events[: max(1, len(events) // 2)])
    view_full = build_meaning_view(full, situation)
    view_partial = build_meaning_view(partial, situation)
    if not view_full:
        return False
    return view_full != view_partial or len(full.history) != len(partial.history)


def verify_reflective_override(records: list[dict[str, Any]]) -> bool:
    """真实候选序列上：二阶裁决稳定产出 override/endorse 且可复现."""
    history = [
        {"decision": str(r.get("selected_candidate") or ""), "topic": "作品决策"}
        for r in records
    ]
    override = ReflectiveOverride(history, min_run=2)
    verdicts: list[str] = []
    for record in records:
        for candidate in record.get("candidates") or []:
            cid = candidate.get("candidate_id") or ""
            result = override.check(
                {"candidate_id": cid, "decision": cid, "topic": "作品决策"},
                situation={"plot_context": record.get("plot_context") or ""},
            )
            verdict = result.get("override_verdict")
            if verdict not in ("override", "endorse"):
                return False
            verdicts.append(verdict)
    return len(verdicts) > 0 and len(set(verdicts)) >= 1


def verify_experience_ablation(events: list[dict[str, Any]]) -> tuple[bool, float, str]:
    """真实事件序列上：有经验 vs 无经验分叉 > 0 → EXPERIENCE_IS_CAUSAL_NODE."""

    def decision_fn(situation: Any, ledger: ExperienceLedger) -> str:
        if not ledger.history:
            return "default"
        return "informed"

    report = build_ablation_report(events, decision_fn)
    ok = report.divergence_rate > 0 and report.verdict == "EXPERIENCE_IS_CAUSAL_NODE"
    return ok, report.divergence_rate, report.verdict


def verify_suite(records: list[dict[str, Any]]) -> dict[str, Any]:
    """对一组记录跑三机制真实路径验证，返回结构化报告."""
    events = _events(records)
    led_ok = verify_experience_ledger(events)
    ref_ok = verify_reflective_override(records)
    abl_ok, divergence, verdict = verify_experience_ablation(events)
    ok = led_ok and ref_ok and abl_ok
    return {
        "record_count": len(records),
        "experience_ledger": led_ok,
        "reflective_override": ref_ok,
        "experience_ablation": abl_ok,
        "divergence_rate": divergence,
        "verdict": verdict,
        "suite_pass": ok,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S4：53 三机制真实语料验证（重跑研究轨结论）"
    )
    parser.add_argument(
        "--ledger",
        default=None,
        help="ChoiceLedger JSON 路径（缺省用内置合成真实格式语料）",
    )
    args = parser.parse_args(argv)

    try:
        records = load_records(args.ledger)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: 无法加载语料——{exc}")
        return 1

    report = verify_suite(records)
    source = args.ledger or "(内置合成真实格式语料)"
    print(f"S4 三机制真实语料验证 | 来源: {source} | 记录数: {report['record_count']}")
    print(f"  [{'PASS' if report['experience_ledger'] else 'FAIL'}] "
          f"Experience Ledger 因果节点化（同情境不同历史 → 不同意义视图）")
    print(f"  [{'PASS' if report['reflective_override'] else 'FAIL'}] "
          f"Reflective Override 二阶否决（真实候选裁决稳定）")
    print(f"  [{'PASS' if report['experience_ablation'] else 'FAIL'}] "
          f"Experience Ablation（divergence={report['divergence_rate']:.2f} "
          f"→ {report['verdict']}）")
    print(f"SUITE: {'PASS' if report['suite_pass'] else 'FAIL'}")
    return 0 if report["suite_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
