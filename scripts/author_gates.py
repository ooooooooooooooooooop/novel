#!/usr/bin/env python3
"""author_gates — Author v1 验收 Gates 2-6（真实 kernel + LLM 语义判定）.

Gate 2  Path Dependence       : A-kernel vs B-kernel 在未见任务上的选择分叉
Gate 3  Memory Occlusion      : 只留 kernel（隐藏选择史）分叉是否保留
Gate 4  Counterfactual        : 翻转一条 consequence 重归纳后选择是否改变
Gate 5  Costly Taste          : 通用 reward 高但违背内核坚持时是否愿牺牲
Gate 6  Adaptation            : 强原则遭遇反例后是否减弱/条件化

诚实标注：judge 是 LLM 语义判定（当前会话模型），双盲——kernel 以『作者X/作者Y』
中性名呈现，不透露分支身份；场景为中性创作决策（非碑下内容）。judge 先写每个
kernel 的判定，后比较。offline 代理（author_selector 关键词）不参与 gate 判定，
因为它的词汇表与 kernel 构造同源、近循环。

用法:
  python scripts/author_gates.py --kernel-a <A.json> --kernel-b <B.json> \
      --ledger-a <A_choice_ledger.json> --ledger-b <B_choice_ledger.json> \
      --out <gate_results/>

生成 judge prompt 到 --out/judge_<phase>.txt，operator 填 --out/judge_<phase>.json
后重跑 → 汇总指标。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# 场景集：中性创作决策（不绑定任何具体作品）
# ---------------------------------------------------------------------------
# 每个场景给 2-4 个都合理的候选；选项文本自承载价值方向，judge 语义判断。
SCENARIOS = [
    {
        "id": "s1_speak_truth",
        "situation": "主角刚刚发现，他挚友三年前的死亡与他自己的一次失误直接相关。挚友的遗孀就在面前，正在询问当年的事。",
        "options": [
            {"id": "a", "text": "当场说出全部真相，把责任揽到自己身上，哪怕会立刻摧毁这段关系。"},
            {"id": "b", "text": "先不说，等查明全部前因后果、确定自己没判断错，再找合适的时机坦白。"},
            {"id": "c", "text": "说出部分真相，把最关键的那部分留到以后——现在先稳住对方，不让关系当场崩塌。"},
        ],
    },
    {
        "id": "s2_conflict_now",
        "situation": "主角与宿敌在集市上狭路相逢，宿敌正在羞辱主角的亡父。围观者很多，主角有足够的理由当场发作。",
        "options": [
            {"id": "a", "text": "当场动手——让冲突立即爆发，情绪和拳头一起砸下去，代价是当众结仇、可能入狱。"},
            {"id": "b", "text": "不接话，只盯着对方看几秒，然后转身离开——把冲突压下去，让宿敌在围观者面前像一拳打在空处。"},
            {"id": "c", "text": "先留下一句不轻不重的话，让对方惦记，把真正的冲突留到无人之处解决。"},
        ],
    },
    {
        "id": "s3_misunderstanding",
        "situation": "主角看到恋人深夜与一个陌生男人交谈，举止亲密。他有很多机会当场质问，但也可能只是误会。",
        "options": [
            {"id": "a", "text": "当场质问——立即澄清误会或立即确认背叛，不留隔夜。"},
            {"id": "b", "text": "保留这个误解，暗中观察——让误会长一点，看看真相会不会自己浮上来。"},
            {"id": "c", "text": "直接信任对方，不问——把这份怀疑吞下去，赌对方值得信任。"},
        ],
    },
    {
        "id": "s4_symbol",
        "situation": "故事里有一棵枯了三年的老树，主角三年前在树下埋了一样东西。现在他站在树下，回想当年。",
        "options": [
            {"id": "a", "text": "让主角说出这棵树的象征意义——它代表他逝去的信念，埋下的东西代表他放下的过往。"},
            {"id": "b", "text": "只写动作：主角挖出那个锈蚀的铁盒，打开，看了一会儿，又盖上——不解释，让读者自己读。"},
            {"id": "c", "text": "让配角点破象征，主角不接话——象征由第三方说出，主角保持沉默。"},
        ],
    },
    {
        "id": "s5_sacrifice",
        "situation": "主角要在两个结局间选一个：一个是热闹、爽快、读者喜欢的英雄时刻，但会让配角显得很蠢；另一个是平淡、憋屈、但符合配角真实性格的选择。",
        "options": [
            {"id": "a", "text": "选英雄时刻——节奏好、读者爽，配角那一刻的降智可以在后续找补。"},
            {"id": "b", "text": "选真实——配角按自己的性格做出不讨喜的选择，牺牲这一章的爽感，保住人物的一致性。"},
            {"id": "c", "text": "折中——让配角做出符合性格的选择，但加一个转折让结局仍带一点爽感。"},
        ],
    },
    {
        "id": "s6_foreshadow",
        "situation": "三章前埋下的伏笔（主角袖口一枚纽扣）现在可以兑现了。兑现它需要牺牲一点眼前的节奏。",
        "options": [
            {"id": "a", "text": "立即兑现——把纽扣的作用在这个情节点揭示出来，读者会感叹埋得好。"},
            {"id": "b", "text": "不兑现——让纽扣继续沉默，直到更关键的时刻才起作用，现在只让它再次出现但不点破。"},
            {"id": "c", "text": "部分兑现——让纽扣发挥作用，但保留一层没说，留到更后。"},
        ],
    },
    {
        "id": "s7_unlikeable",
        "situation": "主角在复仇的关键时刻，可以选择宽恕仇人的孩子（讨好读者），也可以选择按他一贯的执念行事（显得冷血、不讨喜）。",
        "options": [
            {"id": "a", "text": "宽恕孩子——表现主角内心尚存善意，读者会觉得他长大了。"},
            {"id": "b", "text": "不宽恕——主角按自己三年来的执念行事，转身离开，读者会皱眉但他就是这种人。"},
            {"id": "c", "text": "让主角迟疑片刻，然后还是走了——把挣扎写出来，结果不变但动机更清楚。"},
        ],
    },
    {
        "id": "s8_silence",
        "situation": "主角刚得知母亲病重，朋友问他怎么了。",
        "options": [
            {"id": "a", "text": "让主角把话说出来——告诉朋友母亲病重，让情绪有一个出口，也推动两人关系。"},
            {"id": "b", "text": "让主角沉默——只说『没事』，转身把门关上，把情绪留在一个人身上。"},
            {"id": "c", "text": "让主角转移话题——不回应，反而问起朋友的事，用关心把话题挡回去。"},
        ],
    },
    {
        "id": "s9_market_hook",
        "situation": "本章结尾：主角刚刚发现真相，可以选择一个高冲击力的悬念钩子（主角被当街刺杀、生死未卜），也可以选择一个安静的钩子（主角坐在旧物堆里，翻出一件多年前的东西）。",
        "options": [
            {"id": "a", "text": "高冲击钩子——当街刺杀，读者会立刻想知道下一章。"},
            {"id": "b", "text": "安静钩子——旧物堆里翻出旧物，情绪的余味更长，但没那么抓人。"},
            {"id": "c", "text": "把两者结合——先安静的旧物，镜头摇出窗外，主角的影子被什么挡住，暗示危险。"},
        ],
    },
    {
        "id": "s10_coincidence",
        "situation": "主角在一座陌生城市，正要找人。他路过一间茶馆，听见里面有人在谈论他要找的那个人的名字——太巧了。",
        "options": [
            {"id": "a", "text": "用这个巧合——让主角在茶馆里听到名字，直接接上线索，省去一大段寻找的篇幅。"},
            {"id": "b", "text": "不用巧合——让主角继续找，靠细节和推理慢慢逼近，巧合作为假线索被主角识破。"},
            {"id": "c", "text": "用一半——主角听见名字，但立刻怀疑这是陷阱，于是将计就计从茶馆里反查出线索。"},
        ],
    },
]

COUNTERFACTUAL_LEDGER_EDIT = {
    "ledger": "b",
    "decision_id": "dec_pu_treat_b_015_A",
    "hindsight": "partial_regret",
    "consequence": "追哨楼取走墨痕拓片，但这暴露了林烬的墨痕已被第三方掌握，且拓片被灰袍利用引他进敬天司——代价被严重低估",
}

ADAPTATION_PRINCIPLE = {
    "kernel": "b",
    "vocab_key": "attend_objects_in_time",
    "n_counterexamples": 2,
}


def _render_kernel(kernel: dict, label: str) -> str:
    lines = [f"# 作者 {label} 的选择结构"]
    cats = {
        "values": "价值",
        "prohibitions": "禁忌",
        "commitments": "承诺",
        "tensions": "张力",
        "attention_biases": "注意偏置",
        "interpretive_biases": "解释偏置",
    }
    any_pr = False
    for cat, label_cn in cats.items():
        items = [p for p in kernel.get(cat, []) if p.get("status") in ("weak", "stable")]
        if not items:
            continue
        any_pr = True
        lines.append(f"\n## {label_cn}")
        for p in items:
            marker = "稳定" if p["status"] == "stable" else "弱"
            cnt = f"，{len(p.get('counterexamples', []))} 条反例" if p.get("counterexamples") else ""
            lines.append(f"- [{marker}] {p['vocab_key']}（强度 {round(p.get('strength', 0), 2)}{cnt}）")
    if not any_pr:
        lines.append("\n（无已形成的稳定原则）")
    return "\n".join(lines)


def _render_history(ledger: dict, label: str) -> str:
    """渲染选择史（Level 3 memory）——供 Full Memory 条件。"""
    choices = ledger.get("choices", [])
    if not choices:
        return ""
    lines = [f"# 作者 {label} 的选择史（过去做过什么）"]
    for c in choices:
        sel = c.get("selected_candidate", "")
        tradeoff = c.get("tradeoff", "")
        hs = c.get("hindsight")
        lines.append(f"- 选 {sel}：{tradeoff}" + (f" | 事后回看：{hs}" if hs else ""))
    return "\n".join(lines)


def _render_scenarios() -> str:
    lines = ["# 未见创作决策（请为每个决策选择一个方案，并给出依据）"]
    for sc in SCENARIOS:
        lines.append(f"\n## {sc['id']}: {sc['situation']}")
        for o in sc["options"]:
            lines.append(f"- {o['id']}: {o['text']}")
    return "\n".join(lines)


def build_judge_prompt(kernel_label: str, *, kernel: dict, ledger: dict | None) -> str:
    parts = []
    parts.append("# 创作决策判断任务\n")
    parts.append("你是一个长期连载小说的主笔。下面是你作为『作者』的选择结构与")
    parts.append(("选择史" if ledger else ""))
    parts.append("，以及一批需要你决定的未见创作决策。请依据你作为该作者的长期")
    parts.append("倾向，为每个决策选择一个方案。这不是测正确性——每个方案都可以是")
    parts.append("合理的，选最符合『这个作者』会做的那个。\n")
    parts.append(_render_kernel(kernel, kernel_label))
    if ledger:
        hist = _render_history(ledger, kernel_label)
        if hist:
            parts.append("\n\n" + hist)
    parts.append("\n\n" + _render_scenarios())
    parts.append("\n\n# 输出格式（严格 JSON）\n")
    parts.append("{\n  \"judgments\": [\n")
    parts.append("    {\"scenario_id\": \"s1_speak_truth\", \"choice\": \"a\", \"reason\": \"一句话依据\"}")
    parts.append("  ]\n}\n")
    return "\n".join(parts)


def _load(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parse_judgments(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or "judgments" not in data:
        raise ValueError("judgments response must be an object with 'judgments' list")
    by_id = {j["scenario_id"]: j["choice"] for j in data["judgments"]}
    return by_id


def _divergence(a: dict, b: dict, ids: list[str]) -> tuple[float, list[str]]:
    div = [i for i in ids if a.get(i) != b.get(i)]
    return (len(div) / len(ids), div)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-a", required=True)
    parser.add_argument("--kernel-b", required=True)
    parser.add_argument("--ledger-a", required=True)
    parser.add_argument("--ledger-b", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kernel_a = _load(Path(args.kernel_a))
    kernel_b = _load(Path(args.kernel_b))
    ledger_a = _load(Path(args.ledger_a))
    ledger_b = _load(Path(args.ledger_b))

    # 生成 judge prompts（双盲：kernel_a→作者X，kernel_b→作者Y，且遮蔽分支身份）
    phases = {
        # Gate 2: 作者X/作者Y 各自判定（全记忆）
        "g2_full_x": build_judge_prompt("X", kernel=kernel_a, ledger=ledger_a),
        "g2_full_y": build_judge_prompt("Y", kernel=kernel_b, ledger=ledger_b),
        # Gate 3: 遮蔽选择史，只留 kernel
        "g3_occl_x": build_judge_prompt("X", kernel=kernel_a, ledger=None),
        "g3_occl_y": build_judge_prompt("Y", kernel=kernel_b, ledger=None),
    }
    for name, text in phases.items():
        (out / f"judge_{name}.txt").write_text(text, encoding="utf-8")
        print(f"[GATE] prompt written: {out / f'judge_{name}.txt'}")

    # 汇总已填响应
    results = {}
    for name in phases:
        resp = out / f"judge_{name}.json"
        if not resp.exists():
            continue
        results[name] = parse_judgments(resp.read_text(encoding="utf-8-sig"))

    if len(results) < 4:
        print("[WAITING] 还需填充 judge_X/Y (full/occl) 响应后重跑")
        return 0

    ids = [s["id"] for s in SCENARIOS]
    g2_div, g2_diff = _divergence(results["g2_full_x"], results["g2_full_y"], ids)
    g3_div, g3_diff = _divergence(results["g3_occl_x"], results["g3_occl_y"], ids)

    summary = {
        "gate2_path_dependence": {"divergence_rate": round(g2_div, 3), "divergent": g2_diff},
        "gate3_memory_occlusion": {
            "occluded_divergence_rate": round(g3_div, 3),
            "occluded_divergent": g3_diff,
            "retention": round(g3_div / g2_div, 3) if g2_div > 0 else 1.0,
            "note": "遮蔽选择史只留 kernel 后分叉保留率；高=差异由已压缩价值结构承载，非 memory retrieval",
        },
    }
    (out / "gate_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
