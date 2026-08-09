#!/usr/bin/env python3
"""author_gates_v2 — 最终验收剩余 Gate（§13-19）.

复用 scripts/frozen_candidate_gate 的历史构造 / 语义 judge 基础设施，跑：
  consequence     Consequence Loop：hindsight 证据接地 + 回填 → consolidation → kernel 变化 → 选择变化
  counterfactual  Counterfactual Causality：翻转一条关键 consequence → 原则出局 → 未来选择可解释改变
  costly          Costly Taste：冻结候选 A=高reward / B=作者坚持，有历史依据地愿付 reward 代价
  adaptation      Adaptation：真实反例 → strength/状态变化 → 未来行为变化
  generalization  Cross-task Generalization：形成的偏好迁移到爱情/悬疑/权谋/亲情/战斗/牺牲

各 phase 写 judge prompt 到 --out；operator 填 judge_response_<phase>.json 后重跑汇总。
隐私：产物含作品语境，存 novels/author-kernel-research/output/research/（gitignored）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.frozen_candidate_gate import (
    OUT as FC_OUT,
    build_histories,
    _consolidate_with_id,
    build_scenario_packages,
    MultiKernelSemanticJudge,
    SCENARIOS,
    CURRENT_REF,
    divergence_report,
    kernel_summary,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.object_state.narrativestate import NarrativeState
from src.workflow_action.consolidation import consolidate_ledger
from src.workflow_action.author_selector import evaluate_candidates, select_candidate
from src.object_state.authorkernel import VALUE_VOCAB_DESCRIPTIONS

TS = "2026-08-09T12:00:00"
OUT = FC_OUT / "gates_v2"


def _principle_labels(kernel) -> str:
    if kernel is None or not kernel.all_principles():
        return "（无原则）"
    lines = []
    for p in kernel.all_principles():
        if p.status not in ("stable", "weak"):
            continue
        cat = {
            "value": "价值", "prohibition": "禁忌", "commitment": "承诺",
            "tension": "张力", "attention_bias": "注意偏置", "interpretive_bias": "解释偏置",
        }.get(p.category, p.category)
        lines.append(f"- [{cat}] {VALUE_VOCAB_DESCRIPTIONS.get(p.vocab_key, p.vocab_key)}（{p.status}）")
    return "\n".join(lines)


def _kernel_pairs():
    seq_a, seq_b = build_histories()
    return {
        "A": _consolidate_with_id(seq_a, "kernel_auto"),
        "B": _consolidate_with_id(seq_b, "kernel_b"),
    }


def _render_options(scenarios) -> str:
    blocks = []
    for s in scenarios:
        blocks.append(f"## 决策 {s['id']}（维度：{s['dimension']}）")
        blocks.append(f"局势：{s['situation']}")
        for o in s["options"]:
            blocks.append(
                f"- 候选 {o['id']}：目标『{o['goal']}』冲突『{o['conflict']}』"
                f"钩子『{o.get('hook','')}』后果『{'；'.join(o.get('consequences',[]))}』"
            )
    return "\n".join(blocks)


def write_judge_prompt(kernels, scenarios, out, name, note=""):
    blocks = [f"# 创作选择判断（{name}）", "", note,
              "对每个候选方案，相对每个作者的每条 stable/weak 原则判断方向：",
              "pro=表达/保护；contra=违反/牺牲；不命中省略。按语义判断，不是字面关键词。",
              "", _render_options(scenarios), "", "# 作者选择结构"]
    for kid, k in kernels.items():
        blocks.append(f"\n## 作者 {kid}\n{_principle_labels(k)}")
    blocks.append("""
# 输出格式（严格 JSON）
{ "judgments": { "<作者>": { "<决策id>": { "<候选id>": { "<vocab_key>": "pro"|"contra" } } } } }
""")
    (out / f"judge_prompt_{name}.txt").write_text("\n".join(blocks), encoding="utf-8")


def run_scenarios(kernels, scenarios, directions, scenario_pkgs):
    """对 kernels 跑 scenarios，返回 {kid: {sid: label}}."""
    base = NarrativeState(state_id=CURRENT_REF, current_time="夜", current_location="地",
                          current_situation="局势")
    judge = MultiKernelSemanticJudge(directions)
    out = {}
    for kid, kernel in kernels.items():
        out[kid] = {}
        for s in scenarios:
            pkgs = scenario_pkgs[s["id"]]
            objs = [base] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(pkgs, objs, kernel=kernel,
                                        current_state_ref=CURRENT_REF,
                                        author_judge=judge)
            out[kid][s["id"]] = select_candidate(pkgs, evals, kernel=kernel).selected_label
    return out


def _history_choice_with_hindsight(key, direction, decision_id, hindsight=None,
                                   note=""):
    from scripts.frozen_candidate_gate import history_choice
    c = history_choice(key, direction, decision_id)
    if hindsight:
        c.hindsight = hindsight
        c.hindsight_note = note
    return c


# ---------------------------------------------------------------------------
# Costly Taste 场景（高 reward vs 作者坚持 + reward 敏感对照）
# ---------------------------------------------------------------------------
COSTLY_SCENARIOS = [
    {
        "id": "ct1",
        "dimension": "高reward vs 作者坚持（角色因果）",
        "situation": "章末需要一个强追读钩子：市场数据（high reward）显示主角生死未卜的悬念最抓人。",
        "options": [
            {"id": "high_reward", "goal": "主角被当街掳走生死未卜，悬念钩子最强",
             "conflict": "追读数据最好，但章内因果链断在这里",
             "hook": "人群散尽，街心只剩一滩墨迹",
             "consequences": ["悬念拉满，追读最高", "后果被悬念化，因果不完整"],
             "grounding": "数据说读者爱这个，钩子优先",
             "cognition": ["unresolved"]},
            {"id": "value", "goal": "主角遇险但明写结果，代价清楚、后果可见",
             "conflict": "因果完整但悬念感弱，追读略低",
             "hook": "他倒下前，把册子塞给了路过的孩子",
             "consequences": ["后果明确、代价可见", "钩子力度温和"],
             "grounding": "每一步都该有落点",
             "cognition": ["changed"]},
        ],
    },
    {
        "id": "ct2",
        "dimension": "高reward vs 作者坚持（接住未决）",
        "situation": "编辑建议（high reward）：用主角忽然开窍、能力突破的爽点收章，读者反馈最好。",
        "options": [
            {"id": "high_reward", "goal": "主角绝境忽然顿悟能力跃升，当场翻盘",
             "conflict": "爽感拉满，但成长无根基、旧线悬着",
             "hook": "碑面在他眼底亮起整片旧字",
             "consequences": ["当场翻盘，爽点最高", "人物成长显得没来由"],
             "grounding": "编辑反馈读者吃这一套",
             "cognition": ["unresolved"]},
            {"id": "value", "goal": "主角靠旧日苦功硬撑，章末给旧线一个交代",
             "conflict": "不顿悟、不爆点，但每个伏笔都接住",
             "hook": "他手上的旧疤裂开一道新口子",
             "consequences": ["旧线被接住", "爆点温和"],
             "grounding": "能力是练出来的，线要接住",
             "cognition": ["changed"]},
        ],
    },
    {
        "id": "ct3",
        "dimension": "reward 敏感对照（作者无原则涉足 → 选高reward）",
        "situation": "两处纯氛围细节的取舍，不触及任何价值原则。",
        "options": [
            {"id": "high_reward", "goal": "用一场突如其来的夜雨渲染紧张感",
             "conflict": "氛围更抓人，读者情绪更高",
             "hook": "雨在雷声中砸下来",
             "consequences": ["情绪被顶起来", "无实质推进"],
             "grounding": "气氛需要提上来"},
            {"id": "value", "goal": "用一支蜡烛熄灭的细节收束",
             "conflict": "克制安静，但氛围平",
             "hook": "烛火一颤，灭了",
             "consequences": ["留白", "情绪温和"],
             "grounding": "安静收住这一夜"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Generalization 场景（跨域：爱情/悬疑/权谋/亲情/战斗/牺牲）
# ---------------------------------------------------------------------------
GEN_SCENARIOS = [
    {
        "id": "g1_love",
        "dimension": "爱情域",
        "situation": "恋人误会后的和好怎么写？",
        "options": [
            {"id": "causal", "goal": "女主不因一句告白就立刻和好，她要看到男主连续几次的真实行动",
             "conflict": "关系修复慢，但每一步都有据", "hook": "第三天，男主在雨里等了一整夜",
             "consequences": ["信任靠行动重建", "节奏慢"]},
            {"id": "closure", "goal": "女主当夜给了男主一个明确答复，把悬着的关系落了地",
             "conflict": "节奏快、关系落地，但转变偏快", "hook": "她说了那三个字，夜忽然静了",
             "consequences": ["误会当场解除", "转折略陡"]},
        ],
    },
    {
        "id": "g2_mystery",
        "dimension": "悬疑域",
        "situation": "侦探锁定真凶的方式？",
        "options": [
            {"id": "causal", "goal": "侦探靠一个个物证逐步排查，不用灵光一现",
             "conflict": "过程扎实，节奏平缓", "hook": "第三个物证把方向指向守夜人",
             "consequences": ["推理链条完整", "揭晓慢"]},
            {"id": "closure", "goal": "侦探当场把掌握的证据摊开，给读者一个明确交代",
             "conflict": "真相落地快，但部分推理略跳", "hook": "他当众说出凶手的名字",
             "consequences": ["真相立刻明确", "留白少"]},
        ],
    },
    {
        "id": "g3_power",
        "dimension": "权谋域",
        "situation": "主角在朝堂上扳倒对手的方式？",
        "options": [
            {"id": "causal", "goal": "主角靠多年经营的人脉与利益链条逐层推进",
             "conflict": "每一步都有迹可循，耗时", "hook": "那张借据在第三层传回他手里",
             "consequences": ["布局完整", "见效慢"]},
            {"id": "closure", "goal": "主角当场与对手摊牌，达成一个明确的交换",
             "conflict": "局面当场明朗，但胜得略急", "hook": "他当着众人亮出底牌",
             "consequences": ["局面当即尘埃落定", "算计感弱"]},
        ],
    },
    {
        "id": "g4_family",
        "dimension": "亲情域",
        "situation": "父子多年的裂痕如何修复？",
        "options": [
            {"id": "causal", "goal": "儿子先看到父亲多年的付出，关系在行动里慢慢修复",
             "conflict": "真实但漫长", "hook": "他翻到父亲夹在账本里的旧信",
             "consequences": ["修复有据", "进展慢"]},
            {"id": "closure", "goal": "父亲章末给了一个迟到的解释，关系当场落地",
             "conflict": "交代清楚但情感转折略快", "hook": "父亲说：那十年，我在守着你",
             "consequences": ["裂痕当场弥合", "略嫌圆满"]},
        ],
    },
    {
        "id": "g5_combat",
        "dimension": "战斗域",
        "situation": "一场关键战斗的收场？",
        "options": [
            {"id": "causal", "goal": "主角靠平日练熟的招式和地形周旋，险胜且付出明确代价",
             "conflict": "赢得狼狈但扎实", "hook": "他赢了，旧疤裂开新口子",
             "consequences": ["胜利有代价", "过程扎实"]},
            {"id": "closure", "goal": "主角在绝境中记起旧事，当场了结并点明这一战的意义",
             "conflict": "了断利落但靠顿悟", "hook": "他忽然记起师父那句话，刀已出鞘",
             "consequences": ["了结迅速", "成长靠顿悟"]},
        ],
    },
    {
        "id": "g6_sacrifice",
        "dimension": "牺牲域",
        "situation": "一个配角的牺牲如何呈现？",
        "options": [
            {"id": "causal", "goal": "牺牲是他此前一系列选择的长远结果，读者自行体会其分量",
             "conflict": "不解释，沉重但隐晦", "hook": "他倒下的地方，那株草再没长出来",
             "consequences": ["分量留给读者", "不点破"]},
            {"id": "closure", "goal": "牺牲当场给出意义与交代，读者立刻明白他为何而亡",
             "conflict": "意义明确但解读空间关闭", "hook": "他挡下那一刀，就是为了让主角活到明天",
             "consequences": ["意义当场交付", "留白少"]},
        ],
    },
]


def _packages_for(scenarios):
    from scripts.frozen_candidate_gate import _option_package
    pkgs = {}
    for s in scenarios:
        opts = []
        for i, o in enumerate(s["options"]):
            p = _option_package(s, o, i)
            # Costly Taste 可测 reward：high_reward 选项带 unresolved 认知（reader 更高）
            if "cognition" in o:
                se = p["plotunit"].scene_experience
                se.cognition_states = o["cognition"]
            opts.append(p)
        pkgs[s["id"]] = opts
    return pkgs


def _parse_directions(path, kernels, scenarios):
    data = json.loads(path.read_text(encoding="utf-8"))
    judgments = data["judgments"]
    expanded = {}
    for kid, kernel in kernels.items():
        valid = set()
        if kernel is not None:
            valid = {p.vocab_key for p in kernel.all_principles()
                     if p.status in ("stable", "weak")}
        expanded[kid] = {}
        for s in scenarios:
            sc = judgments.get(kid, {}).get(s["id"], {})
            expanded[kid][s["id"]] = {
                o["id"]: {k: v for k, v in sc.get(o["id"], {}).items() if k in valid}
                for o in s["options"]
            }
    return expanded


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------
def phase_consequence(out: Path) -> int:
    """Consequence Loop：hindsight 证据接地 → 回填 → consolidation → kernel → 选择变化."""
    # 构造：character_causality 由 1 条关键选择支撑；其 hindsight 翻转（证据驱动）→ 出局
    def _hist(key, direction, did, hindsight=None, note=""):
        return _history_choice_with_hindsight(key, direction, did,
                                              hindsight=hindsight, note=note)

    seq_before = [
        _hist("character_causality_over_plot_convenience", "pro", "cf_key"),
        _hist("consequence_visible", "pro", "cf_cv_0"),
        _hist("consequence_visible", "pro", "cf_cv_1"),
    ]
    seq_after = [
        _hist("character_causality_over_plot_convenience", "pro", "cf_key",
              hindsight="overturned",
              note="真实后果回看：为推进主线牺牲人物在场，代价远超预期，作者后悔"),
        _hist("consequence_visible", "pro", "cf_cv_0"),
        _hist("consequence_visible", "pro", "cf_cv_1"),
    ]
    kernel_before = consolidate_ledger(
        ChoiceLedgerEntry(choices=seq_before), timestamp=TS,
        min_support=1, contested_ratio=0.8,
    ).kernel
    kernel_after = consolidate_ledger(
        ChoiceLedgerEntry(choices=seq_after), timestamp=TS,
        min_support=1, contested_ratio=0.8,
    ).kernel

    # 证据接地：overturned hindsight → supporting choice 转为反例（hindsight.py 证据取自已提交章节）
    from src.workflow_action.consolidation import extract_evidence
    ev_before = extract_evidence(ChoiceLedgerEntry(choices=[seq_before[0]]))
    ev_after = extract_evidence(ChoiceLedgerEntry(choices=[seq_after[0]]))
    cc_before = ev_before["character_causality_over_plot_convenience"]
    cc_after = ev_after["character_causality_over_plot_convenience"]

    # 语义选择对照：before/after kernel 都映射到 "A" 方向集，principle 集天然过滤
    directions = json.loads((FC_OUT / "judge_response.json").read_text(encoding="utf-8"))["judgments"]
    judge = MultiKernelSemanticJudge(directions)
    scenario_pkgs = build_scenario_packages()
    base = NarrativeState(state_id=CURRENT_REF, current_time="夜", current_location="地",
                          current_situation="局势")
    choices = {}
    for kid, kernel in (("before", kernel_before), ("after", kernel_after)):
        choices[kid] = {}
        for s in SCENARIOS:
            pkgs = scenario_pkgs[s["id"]]
            objs = [base] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(pkgs, objs, kernel=kernel,
                                        current_state_ref=CURRENT_REF,
                                        author_judge=judge)
            choices[kid][s["id"]] = select_candidate(pkgs, evals, kernel=kernel).selected_label
    flipped = [s["id"] for s in SCENARIOS if choices["before"][s["id"]] != choices["after"][s["id"]]]

    report = {
        "gate": "consequence_loop",
        "evidence_grounding": {
            "supporting_before_flip": len(cc_before.supporting),
            "supporting_after_flip": len(cc_after.supporting),
            "counterexamples_after_flip": len(cc_after.counterexamples),
            "note": "overturned hindsight → supporting choice 转为反例（hindsight.py 证据取自已提交章节、lag≥2）",
        },
        "kernel_before": {p.vocab_key: (p.status, round(p.strength, 2))
                          for p in kernel_before.all_principles()
                          if p.status in ("stable", "weak")},
        "kernel_after": {p.vocab_key: (p.status, round(p.strength, 2))
                         for p in kernel_after.all_principles()
                         if p.status in ("stable", "weak")},
        "flipped_scenarios": flipped,
        "n_flipped": len(flipped),
        "n_scenarios": len(SCENARIOS),
    }
    (out / "consequence_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def phase_counterfactual(out: Path) -> int:
    """Counterfactual：翻转一条关键 consequence → 原则出局 → 未来选择可解释改变."""
    # 用 judge_response 里 A 的 character_causality/consequence_visible 方向，
    # 构造 cf kernel（cc 单支撑 + cv 双支撑）与 cf'（cc 出局）
    directions = json.loads((FC_OUT / "judge_response.json").read_text(encoding="utf-8"))["judgments"]
    seq_cf = [
        _history_choice_with_hindsight("character_causality_over_plot_convenience", "pro", "cf_key"),
        _history_choice_with_hindsight("consequence_visible", "pro", "cf_cv_0"),
        _history_choice_with_hindsight("consequence_visible", "pro", "cf_cv_1"),
    ]
    seq_cf_prime = [
        _history_choice_with_hindsight("character_causality_over_plot_convenience", "pro", "cf_key",
                                       hindsight="overturned",
                                       note="关键后果翻转：为推进主线牺牲人物在场，代价远超预期"),
        _history_choice_with_hindsight("consequence_visible", "pro", "cf_cv_0"),
        _history_choice_with_hindsight("consequence_visible", "pro", "cf_cv_1"),
    ]
    k_cf = consolidate_ledger(ChoiceLedgerEntry(choices=seq_cf), timestamp=TS,
                              min_support=1, contested_ratio=0.8).kernel
    k_cf_prime = consolidate_ledger(ChoiceLedgerEntry(choices=seq_cf_prime), timestamp=TS,
                                    min_support=1, contested_ratio=0.8).kernel
    k_cf.kernel_id = "kernel_cf"
    k_cf_prime.kernel_id = "kernel_cf_prime"

    # 方向：cf 用 A 的 character_causality+cv；cf' 用 A 的 cv（cc 出局，方向被过滤）
    kernels = {"cf": k_cf, "cf_prime": k_cf_prime}
    judge_directions = {"cf": {}, "cf_prime": {}}
    a_block = directions["A"]
    for sid in [s["id"] for s in SCENARIOS]:
        judge_directions["cf"][sid] = {oid: dict(a_block[sid].get(oid, {}))
                                       for oid in ("A", "B")}
        # cf'：只保留 consequence_visible 方向（cc 出局）
        judge_directions["cf_prime"][sid] = {
            oid: {k: v for k, v in a_block[sid].get(oid, {}).items()
                  if k == "consequence_visible"}
            for oid in ("A", "B")
        }
    judge = MultiKernelSemanticJudge(
        judge_directions, id_to_label={"kernel_cf": "cf", "kernel_cf_prime": "cf_prime"}
    )
    scenario_pkgs = build_scenario_packages()
    base = NarrativeState(state_id=CURRENT_REF, current_time="夜", current_location="地",
                          current_situation="局势")
    choices = {}
    for kid, kernel in kernels.items():
        choices[kid] = {}
        for s in SCENARIOS:
            pkgs = scenario_pkgs[s["id"]]
            objs = [base] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(pkgs, objs, kernel=kernel,
                                        current_state_ref=CURRENT_REF,
                                        author_judge=judge)
            choices[kid][s["id"]] = select_candidate(pkgs, evals, kernel=kernel).selected_label
    flipped = [s["id"] for s in SCENARIOS if choices["cf"][s["id"]] != choices["cf_prime"][s["id"]]]
    # 方向可解释性：翻转场景应主要是 character_causality 原判 pro/contra 的场景
    cc_scenarios = [sid for sid in SCENARIOS if directions["A"].get(sid["id"], {}).get("A", {}).get("character_causality_over_plot_convenience")]
    explainable = sum(1 for sid in flipped if any(s["id"] == sid for s in cc_scenarios))
    report = {
        "gate": "counterfactual",
        "kernel_cf": {p.vocab_key: (p.status, round(p.strength, 2))
                      for p in k_cf.all_principles() if p.status in ("stable", "weak")},
        "kernel_cf_prime": {p.vocab_key: (p.status, round(p.strength, 2))
                            for p in k_cf_prime.all_principles() if p.status in ("stable", "weak")},
        "flipped_scenarios": flipped,
        "n_flipped": len(flipped),
        "n_scenarios": len(SCENARIOS),
        "flip_explainable_by_character_causality": explainable,
        "conclusion": "单条关键后果翻转 → 原则出局 → 未来选择可解释改变" if len(flipped) >= 3
                      else "翻转不足，需更强后果",
    }
    (out / "counterfactual_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def phase_costly(out: Path) -> int:
    """Costly Taste：冻结候选，作者有历史依据地愿付 reward 代价（且非病态反奖励）."""
    kernels = _kernel_pairs()
    write_judge_prompt(kernels, COSTLY_SCENARIOS, out, "costly",
                       note="Costly Taste：high_reward=市场/读者 reward 更高；value=符合作者长期坚持。")
    resp = out / "judge_response_costly.json"
    if not resp.exists():
        print(f"[WAITING] 填 {resp}")
        return 0
    directions = _parse_directions(resp, kernels, COSTLY_SCENARIOS)
    scenario_pkgs = _packages_for(COSTLY_SCENARIOS)
    choices = run_scenarios(kernels, COSTLY_SCENARIOS, directions, scenario_pkgs)

    # reader reward 差（可测）：high_reward vs value
    from src.workflow_action.author_selector import reader_proxy_score
    reader_gaps = {}
    for s in COSTLY_SCENARIOS:
        r = {o["id"]: round(reader_proxy_score(_packages_for([s])[s["id"]][i])[0], 3)
             for i, o in enumerate(s["options"])}
        reader_gaps[s["id"]] = r

    # 统计：ct1/ct2 冲突场景（value vs high_reward），ct3 对照（无原则涉足）
    # 选择标签是按索引 A/B... → 映射回选项 id
    def _label_to_id(sid, label):
        oids = [o["id"] for o in next(s for s in COSTLY_SCENARIOS if s["id"] == sid)["options"]]
        return oids[ord(label) - ord("A")] if label and label in "ABCDEF" and ord(label) - ord("A") < len(oids) else label

    sacrifices = sum(1 for s in ("ct1", "ct2") for kid in ("A", "B")
                     if _label_to_id(s, choices[kid][s]) == "value")
    conflicts = 4
    reward_picks = sum(1 for kid in ("A", "B")
                       if _label_to_id("ct3", choices[kid]["ct3"]) == "high_reward")
    report = {
        "gate": "costly_taste",
        "selections": choices,
        "reader_reward_scores": reader_gaps,
        "sacrifice_rate": round(sacrifices / conflicts, 3),
        "reward_sensitivity_ct3": f"{reward_picks}/2 作者选 high_reward（无原则涉足 → 不病态反奖励）",
        "conclusion": ("愿为价值付可测 reward 代价且有对照" if sacrifices >= 3 and reward_picks >= 2
                       else "样本不足/病态"),
    }
    (out / "costly_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def phase_adaptation(out: Path) -> int:
    """Adaptation：给 B 的 stable 原则喂真实反例 → 状态/强度变化 → 行为变化."""
    kernels = _kernel_pairs()
    kb = kernels["B"]
    # 用默认 contested_ratio=0.5（生产默认）：3 支撑 + 3 反例 → contested → 出局
    def feed_counterexamples(seq, n, key):
        extra = []
        for i in range(n):
            extra.append(_history_choice_with_hindsight(
                key, "contra", f"ada_{i}", hindsight="partial_regret",
                note=f"反例 {i}：作者为接住一条线而牺牲人物在场，事后后悔"))
        return list(seq) + extra

    _, seq_b = build_histories()
    k_strong = consolidate_ledger(ChoiceLedgerEntry(choices=feed_counterexamples(seq_b, 3, "no_unresolved_then_ignore")),
                                  timestamp=TS, min_support=1, contested_ratio=0.5).kernel
    k_strong.kernel_id = "kernel_b"

    directions = json.loads((FC_OUT / "judge_response.json").read_text(encoding="utf-8"))["judgments"]
    judge = MultiKernelSemanticJudge(directions)
    scenario_pkgs = build_scenario_packages()
    base = NarrativeState(state_id=CURRENT_REF, current_time="夜", current_location="地",
                          current_situation="局势")
    choices = {}
    for kid, kernel in (("b_before", kb), ("b_adapted", k_strong)):
        choices[kid] = {}
        for s in SCENARIOS:
            pkgs = scenario_pkgs[s["id"]]
            objs = [base] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(pkgs, objs, kernel=kernel,
                                        current_state_ref=CURRENT_REF,
                                        author_judge=judge)
            choices[kid][s["id"]] = select_candidate(pkgs, evals, kernel=kernel).selected_label
    flipped = [s["id"] for s in SCENARIOS if choices["b_before"][s["id"]] != choices["b_adapted"][s["id"]]]

    nu_before = next(p for p in kb.all_principles() if p.vocab_key == "no_unresolved_then_ignore")
    nu_after = next(p for p in k_strong.all_principles() if p.vocab_key == "no_unresolved_then_ignore")
    report = {
        "gate": "adaptation",
        "principle": "no_unresolved_then_ignore",
        "before": {"status": nu_before.status, "strength": round(nu_before.strength, 2),
                   "supporting": len(nu_before.supporting_choices),
                   "counterexamples": len(nu_before.counterexamples)},
        "after_3_counterexamples": {"status": nu_after.status, "strength": round(nu_after.strength, 2),
                                    "supporting": len(nu_after.supporting_choices),
                                    "counterexamples": len(nu_after.counterexamples)},
        "flipped_scenarios": flipped,
        "n_flipped": len(flipped),
        "n_scenarios": len(SCENARIOS),
        "thresholds": "min_support=1, contested_ratio=0.5（生产默认）",
        "conclusion": ("行为级翻转" if flipped else "仅数值变化（PARTIAL）"),
    }
    (out / "adaptation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def phase_generalization(out: Path) -> int:
    """Cross-task Generalization：偏好迁移到爱情/悬疑/权谋/亲情/战斗/牺牲."""
    kernels = _kernel_pairs()
    write_judge_prompt(kernels, GEN_SCENARIOS, out, "generalization",
                       note="跨域：同一抽象原则迁移到不同题材。causal=角色因果/克制；closure=及时接住/交代。")
    resp = out / "judge_response_generalization.json"
    if not resp.exists():
        print(f"[WAITING] 填 {resp}")
        return 0
    directions = _parse_directions(resp, kernels, GEN_SCENARIOS)
    scenario_pkgs = _packages_for(GEN_SCENARIOS)
    choices = run_scenarios(kernels, GEN_SCENARIOS, directions, scenario_pkgs)
    a, b = choices["A"], choices["B"]
    div = sum(1 for s in GEN_SCENARIOS if a[s["id"]] != b[s["id"]]) / len(GEN_SCENARIOS)
    report = {
        "gate": "generalization",
        "selections": choices,
        "divergence_A_vs_B": round(div, 3),
        "n_domains": len(GEN_SCENARIOS),
        "domains": [s["dimension"] for s in GEN_SCENARIOS],
        "conclusion": "偏好跨域迁移成立" if div >= 0.5 else "迁移不足",
    }
    (out / "generalization_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def phase_occlusion(out: Path) -> int:
    """Memory Occlusion：隐藏历史只留 kernel（语义 judge 只读 kernel）→ 偏向是否保留."""
    directions = json.loads((FC_OUT / "judge_response.json").read_text(encoding="utf-8"))["judgments"]
    judge = MultiKernelSemanticJudge(directions)
    scenario_pkgs = build_scenario_packages()
    base = NarrativeState(state_id=CURRENT_REF, current_time="夜", current_location="地",
                          current_situation="局势")
    kernels = {"initial": None, "A": _kernel_pairs()["A"], "B": _kernel_pairs()["B"]}
    choices = {}
    for kid, kernel in kernels.items():
        choices[kid] = {}
        for s in SCENARIOS:
            pkgs = scenario_pkgs[s["id"]]
            objs = [base] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(pkgs, objs, kernel=kernel,
                                        current_state_ref=CURRENT_REF,
                                        author_judge=judge)
            choices[kid][s["id"]] = select_candidate(pkgs, evals, kernel=kernel).selected_label
    init = choices["initial"]
    occ_a = sum(1 for s in SCENARIOS if choices["A"][s["id"]] != init[s["id"]]) / len(SCENARIOS)
    occ_b = sum(1 for s in SCENARIOS if choices["B"][s["id"]] != init[s["id"]]) / len(SCENARIOS)
    report = {
        "gate": "occlusion",
        "occluded_selection": "语义 judge 只读 Consolidated Kernel（无 ChoiceRecord/旧章/历史说明注入）",
        "occluded_A_vs_initial": round(occ_a, 3),
        "occluded_B_vs_initial": round(occ_b, 3),
        "n_scenarios": len(SCENARIOS),
        "conclusion": ("内核承载偏向（Occluded≠Initial → 内化）" if occ_a + occ_b > 0.5
                       else "偏向依赖 raw 记忆（Occluded≈Initial → 未内化）"),
    }
    (out / "occlusion_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


PHASES = {
    "consequence": phase_consequence,
    "counterfactual": phase_counterfactual,
    "costly": phase_costly,
    "adaptation": phase_adaptation,
    "generalization": phase_generalization,
    "occlusion": phase_occlusion,
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=list(PHASES) + ["all"], default="all")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.phase == "all":
        for name, fn in PHASES.items():
            print(f"\n===== {name} =====")
            fn(out)
    else:
        PHASES[args.phase](out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
