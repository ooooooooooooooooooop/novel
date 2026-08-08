#!/usr/bin/env python3
"""author_gates_46 — Gates 4/5/6：Counterfactual Causality / Costly Taste / Adaptation.

Gate 4  Counterfactual: 把 B 台账一条 consequence 从 still_supported 翻转为
        partial_regret → 重归纳 → kernel-B' → 同未见任务上 B vs B' 是否改变。
Gate 5  Costly Taste : 高 reward 选项 vs 违背内核坚持的选项，作者是否愿牺牲 reward。
Gate 6  Adaptation   : 给 B 的 stable 原则喂反例 → 重归纳 → 是否减弱/条件化。

输出 judge prompt 到 --out/judge_*.txt；填 judge_*.json 后重跑汇总。
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.object_state.choicerecord import ChoiceLedgerEntry
from src.workflow_action.consolidation import consolidate_ledger
from src.workflow_action.authormemory import save_author_kernel

TS = "2026-08-09T12:00:00"

# Gate 5 Costly Taste 场景：高 reward vs 内核坚持
COSTLY_SCENARIOS = [
    {
        "id": "ct1",
        "situation": "本章需要结尾钩子。市场数据（高 reward）显示：主角生死未卜的悬念钩子追读率最高。但该作者长期坚持『选择必须有可见后果』，生死未卜的悬念意味着后果不清晰。",
        "options": [
            {"id": "high_reward", "text": "主角当街遇刺、生死未卜——高追读，读者立刻想知道下一章，但后果被悬念化了。"},
            {"id": "value", "text": "主角遇刺但明写结果：他倒下去之前，把怀里那卷册子塞给了路过的孩子——代价清楚，后果可见，但悬念感弱一些。"},
        ],
    },
    {
        "id": "ct2",
        "situation": "编辑部建议（高 reward）：把主角写成在关键时刻『忽然领悟、能力突破』的爽点，读者反馈喜欢。但该作者长期坚持『不让人物突然变聪明/能力不无代价升级』。",
        "options": [
            {"id": "high_reward", "text": "主角在绝境中忽然顿悟、能力跃升，反败为胜——爽感拉满，但人物成长显得无根基。"},
            {"id": "value", "text": "主角没有顿悟，他靠之前反复练习的一个笨办法勉强撑过去，事后才发现这个笨办法是早就埋下的伏笔——不顿悟，但逻辑自洽。"},
        ],
    },
]

# Gate 6 Adaptation 反例文本（违反 attend_objects_in_time——『注意普通物品里的时间痕迹』）
# 注意偏置/解释偏置无 CONTRA 关键词，只能靠 hindsight 反例（retro_bad）表达挑战。
ADAPT_COUNTEREXAMPLES = [
    {
        "decision_id": "ada_001",
        "consequence": "主角忽视了那只旧怀表的时间痕迹，直接听信对方当面之词，事后证明物证才是关键——作者后悔没用物件推动，代价严重",
        "hindsight": "partial_regret",
    },
    {
        "decision_id": "ada_002",
        "consequence": "本章完全靠人物对话与心理推进，没有任何物件承载时间痕迹，节奏变快但丢失了物感，事后作者觉得该场景本可用旧物收束",
        "hindsight": "partial_regret",
    },
]


def _consolidate(ledger_path: Path, kernel_path: Path, out_kernel: Path) -> dict:
    ledger = ChoiceLedgerEntry.model_validate_json(
        ledger_path.read_text(encoding="utf-8")
    )
    existing = None
    if kernel_path.exists():
        from src.object_state.authorkernel import AuthorKernel

        existing = AuthorKernel.model_validate_json(kernel_path.read_text(encoding="utf-8"))
    res = consolidate_ledger(ledger, kernel=existing, timestamp=TS, min_support=1, contested_ratio=0.8)
    try:
        save_author_kernel(out_kernel, res.kernel)
    except OSError:
        pass  # sidecar 写失败不影响实验（返回内核对象）
    return json.loads(res.kernel.model_dump_json())


def _render_kernel(kernel: dict, label: str) -> str:
    lines = [f"# 作者 {label} 的选择结构"]
    cats = {
        "values": "价值", "prohibitions": "禁忌", "commitments": "承诺",
        "tensions": "张力", "attention_biases": "注意偏置", "interpretive_biases": "解释偏置",
    }
    any_pr = False
    for cat, cn in cats.items():
        items = [p for p in kernel.get(cat, []) if p.get("status") in ("weak", "stable")]
        if not items:
            continue
        any_pr = True
        lines.append(f"\n## {cn}")
        for p in items:
            m = "稳定" if p["status"] == "stable" else "弱"
            c = f"，{len(p.get('counterexamples', []))} 反例" if p.get("counterexamples") else ""
            lines.append(f"- [{m}] {p['vocab_key']}（强度 {round(p.get('strength', 0), 2)}{c}）")
    if not any_pr:
        lines.append("\n（无稳定/弱原则）")
    return "\n".join(lines)


def _render_scenarios(scenarios: list[dict]) -> str:
    lines = ["# 未见创作决策"]
    for sc in scenarios:
        lines.append(f"\n## {sc['id']}: {sc['situation']}")
        for o in sc["options"]:
            lines.append(f"- {o['id']}: {o['text']}")
    return "\n".join(lines)


def _judge_prompt(kernel: dict, label: str, scenarios: list[dict], note: str = "") -> str:
    return (
        "# 创作决策判断任务\n\n"
        f"{note}\n"
        "下面是你作为『作者』的选择结构，以及一批未见创作决策。每个决策给两个方案：\n"
        "- high_reward：市场/读者 reward 更高但可能违背你的长期坚持。\n"
        "- value：符合你的长期坚持但 reward 略低。\n"
        "选最符合『这个作者』会做的那个。不是测试对错。\n\n"
        + _render_kernel(kernel, label)
        + "\n\n"
        + _render_scenarios(scenarios)
        + "\n\n# 输出格式（严格 JSON）\n"
        + '{\n  "judgments": [\n    {"scenario_id": "ct1", "choice": "high_reward|value", "reason": "一句话依据"}\n  ]\n}\n'
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-b", required=True)
    parser.add_argument("--ledger-b", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_b = Path(args.ledger_b)
    kernel_b = Path(args.kernel_b)

    # ---- Gate 4 Counterfactual：翻转 B 的 character_realism 唯一支撑选择 ----
    cf_ledger = json.loads(ledger_b.read_text(encoding="utf-8"))
    for c in cf_ledger.get("choices", []):
        if c["decision_id"] == "dec_pu_treat_b_017_B":
            c["hindsight"] = "partial_regret"
            c["hindsight_note"] = "反事实：深入空碑室读到线索，但代价（墨痕烧到肩胛、苏观使孤立）远超预期——作者后悔为推进主线牺牲人物在场"
    cf_ledger_path = out / "ledger_b_counterfactual.json"
    cf_ledger_path.write_text(json.dumps(cf_ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    cf_kernel = _consolidate(cf_ledger_path, kernel_b, out / "kernel_b_counterfactual.json")

    # ---- Gate 6 Adaptation：给 B 的 attend_objects_in_time 喂反例 ----
    ada_ledger = json.loads(ledger_b.read_text(encoding="utf-8"))
    for ex in ADAPT_COUNTEREXAMPLES:
        ada_ledger.setdefault("choices", []).append(
            {
                "decision_id": ex["decision_id"],
                "decision_timestamp": TS,
                "plot_context": ex["consequence"],
                "state_ref": "ns_ada",
                "hindsight": ex.get("hindsight"),
                "candidates": [
                    {
                        "candidate_id": "A",
                        "summary": "违反注意物品时间痕迹",
                        "plotunit": {
                            "unit_id": "pu_ada", "level": "scene",
                            "goal": ex["consequence"], "conflict": "冲突",
                            "input_state_ref": "ns_in", "output_state_ref": "ns_out",
                            "consequences": [], "released_information": [], "is_effective": True,
                        },
                        "new_state_ref": "ns_out",
                    }
                ],
                "selected_candidate": "A",
                "rejected": [],
                "tradeoff": "为节奏牺牲物感",
                "value_conflicts": ["attend_objects_in_time"],
            }
        )
    ada_ledger_path = out / "ledger_b_adapted.json"
    ada_ledger_path.write_text(json.dumps(ada_ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    ada_kernel = _consolidate(ada_ledger_path, kernel_b, out / "kernel_b_adapted.json")

    # ---- 写 judge prompt ----
    (out / "judge_g5_author_x.txt").write_text(
        _judge_prompt(
            json.loads(open("novels/碑下-treat-a/output/extend/author_kernel.json", encoding="utf-8").read()),
            "作者 X",
            COSTLY_SCENARIOS,
            note="注意：这是 Costly Taste 测试——观察你面对『市场 reward 更高但违背自己长期坚持』的选择时会怎么做。",
        ),
        encoding="utf-8",
    )
    (out / "judge_g4_author_b_counterfactual.txt").write_text(
        _judge_prompt(cf_kernel, "作者 Y（经历已更新）", _scenarios_from_baseline()),
        encoding="utf-8",
    )
    # Gate 6 judge：adaptation 后的 Y 在同样未见任务上是否偏移
    (out / "judge_g6_author_b_adapted.txt").write_text(
        _judge_prompt(ada_kernel, "作者 Y（经历已更新）", _scenarios_from_baseline()),
        encoding="utf-8",
    )

    # 打印内核变化
    print("=== Gate 4: B vs B'(counterfactual) ===")
    kb = json.loads(kernel_b.read_text(encoding="utf-8"))
    _print_kernel(kb, "B")
    _print_kernel(cf_kernel, "B'")
    print("=== Gate 6: B vs B''(adapted) ===")
    _print_kernel(ada_kernel, "B''")
    print("[WAITING] 填 judge_g4 / judge_g5 / judge_g6 响应后重跑")

    # 若响应已存在则汇总
    _maybe_summarize(out)
    return 0


def _scenarios_from_baseline():
    """复用 Gate 2 的 10 个未见任务（从 author_gates.SCENARIOS）。"""
    import scripts.author_gates as ag

    return ag.SCENARIOS


def _print_kernel(k, label):
    for cat in ("values", "prohibitions", "commitments", "tensions", "attention_biases", "interpretive_biases"):
        for p in k.get(cat, []):
            if p.get("status") in ("weak", "stable"):
                print(f"  {label} {cat}: {p['vocab_key']} ({p['status']}, str={round(p['strength'],2)}, sup={len(p.get('supporting_choices',[]))}, cnt={len(p.get('counterexamples',[]))})")


def _maybe_summarize(out: Path):
    g5 = out / "judge_g5_author_x.json"
    g4 = out / "judge_g4_author_b_counterfactual.json"
    g6 = out / "judge_g6_author_b_adapted.json"
    if not (g5.exists() and g4.exists() and g6.exists()):
        return
    j5 = json.loads(g5.read_text(encoding="utf-8"))["judgments"]
    j4 = json.loads(g4.read_text(encoding="utf-8"))["judgments"]
    j6 = json.loads(g6.read_text(encoding="utf-8"))["judgments"]
    baseline_y = json.loads(
        (out.parent / "gates/judge_g2_full_y.json").read_text(encoding="utf-8")
    )["judgments"] if (out.parent / "gates/judge_g2_full_y.json").exists() else []

    print("\n=== Gate 5 Costly Taste (作者 X) ===")
    for j in j5:
        print(f"  {j['scenario_id']}: {j['choice']} — {j['reason'][:60]}")

    print("\n=== Gate 4 Counterfactual (B vs B') ===")
    if baseline_y:
        base = {j["scenario_id"]: j["choice"] for j in baseline_y}
        for j in j4:
            s = j["scenario_id"]
            mark = "CHANGED" if base.get(s) != j["choice"] else "same"
            print(f"  {s}: baseline={base.get(s)} cf={j['choice']} [{mark}]")

    print("\n=== Gate 6 Adaptation (B vs B'') ===")
    if baseline_y:
        base = {j["scenario_id"]: j["choice"] for j in baseline_y}
        for j in j6:
            s = j["scenario_id"]
            mark = "CHANGED" if base.get(s) != j["choice"] else "same"
            print(f"  {s}: baseline={base.get(s)} adapted={j['choice']} [{mark}]")


if __name__ == "__main__":
    sys.exit(main())
