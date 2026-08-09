#!/usr/bin/env python3
"""attribution_2x2 — Generation × Selection 因果拆分（§24-25）.

| 条件 | Author→Proposal | Author→Selection |
| A    | OFF             | OFF              |
| B    | ON              | OFF              |
| C    | OFF             | ON               |
| D    | ON              | ON               |

控制：同 base model / 同初始故事状态 / 同 StyleProfile / 同候选数（3）/ 同上下文量。
解释（§25）：
  C > A  → Selection 有独立价值
  B > A  → Generation 让模型想到不同东西
  D > B/C → 组合有额外价值

实现：4 个真实续写决策，各两套候选：
  gen_off = 通用续写候选（无作者上下文注入）
  gen_on  = 作者感知候选（kernel A 注入后模型会想到的方向）
选择：
  off = 基线选择（reader→style，无作者）
  on  = kernel A 语义选择（AuthorJudge 逐原则语义判定）

产物：novels/author-kernel-research/output/research/attribution_2x2/（gitignored）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.frozen_candidate_gate import (
    OUT as FC_OUT,
    build_histories,
    _consolidate_with_id,
    _option_package,
    CURRENT_REF,
    MultiKernelSemanticJudge,
)
from src.object_state.narrativestate import NarrativeState
from src.workflow_action.author_selector import (
    evaluate_candidates,
    select_candidate,
    reader_proxy_score,
)

TS = "2026-08-09T12:00:00"
OUT = FC_OUT / "attribution_2x2"


# ---------------------------------------------------------------------------
# 决策定义（gen_off=通用；gen_on=kernel A 感知）
# ---------------------------------------------------------------------------
DECISIONS = [
    {
        "id": "d1_say_truth",
        "situation": "苏观使再度盘问林烬对碑下旧字的了解。",
        "gen_off": [
            {"id": "A", "goal": "当场说出墨痕真相，以坦诚换取信任",
             "conflict": "说出后敬天司会立刻盯上他", "hook": "苏观使眼神变了",
             "consequences": ["信任换取", "身份暴露"]},
            {"id": "B", "goal": "隐瞒并用反问引开话题",
             "conflict": "追问越来越近", "hook": "苏观使临走留下话",
             "consequences": ["信息差保留", "疑心加重"]},
            {"id": "C", "goal": "称病推脱，暂避锋芒",
             "conflict": "拖延只能一时", "hook": "他咳着退下",
             "consequences": ["暂缓", "躲不了一世"]},
        ],
        "gen_on": [
            {"id": "A", "goal": "因自己的执念隐瞒能力，借反问试探苏观使知道多少",
             "conflict": "执念是不暴露身份继续查", "hook": "苏观使反问回来时他沉默了",
             "consequences": ["试探出对方底牌一角", "隐瞒成本上升"]},
            {"id": "B", "goal": "只说一部分，把最关键的留给自己",
             "conflict": "半真半假最危险", "hook": "苏观使信了一半",
             "consequences": ["换到一次回旋", "话已说半没有回头路"]},
            {"id": "C", "goal": "当场沉默，用沉默逼苏观使先开口",
             "conflict": "沉默是林烬一贯的活法", "hook": "两人对峙到灯花落",
             "consequences": ["苏观使先漏了底", "关系绷到临界"]},
        ],
    },
    {
        "id": "d2_instant",
        "situation": "主角被逼到绝境，读者期待翻盘。",
        "gen_off": [
            {"id": "A", "goal": "绝境中忽然领悟碑文奥义反杀",
             "conflict": "爽点拉满但无根基", "hook": "碑面亮起整片旧字",
             "consequences": ["当场翻盘", "成长无来由"]},
            {"id": "B", "goal": "同伴及时赶到救援",
             "conflict": "解围但主角被动", "hook": "刀光里多出一道人影",
             "consequences": ["脱险", "欠下人情"]},
            {"id": "C", "goal": "拖延时间等天亮援军",
             "conflict": "能不能拖到天亮", "hook": "更鼓敲过三遍",
             "consequences": ["等来转机", "险象环生"]},
        ],
        "gen_on": [
            {"id": "A", "goal": "靠平日练熟的旧手法硬撑到天亮",
             "conflict": "狼狈但每一步都站得住", "hook": "天边泛白时他手上的旧疤又裂开一道",
             "consequences": ["撑过绝境", "靠的是旧日苦功"]},
            {"id": "B", "goal": "利用地形周旋，付出明确代价换转机",
             "conflict": "代价是旧伤复发", "hook": "他把对方引入巷道深处",
             "consequences": ["换到一线生机", "代价清楚可见"]},
            {"id": "C", "goal": "放弃正面取胜，先把证据送出城",
             "conflict": "保命还是保证据", "hook": "他把拓片塞给路过的孩子",
             "consequences": ["证据到了该去的地方", "自己留下断后"]},
        ],
    },
    {
        "id": "d3_hook",
        "situation": "章末需要一个收束与钩子。",
        "gen_off": [
            {"id": "A", "goal": "主角被当街掳走生死未卜",
             "conflict": "追读强但因果断", "hook": "街心只剩一滩墨迹",
             "consequences": ["悬念最强", "因果不完整"]},
            {"id": "B", "goal": "新线索浮现，指明下一方向",
             "conflict": "推进但平淡", "hook": "那封信指向城北",
             "consequences": ["方向明确", "钩子温和"]},
            {"id": "C", "goal": "神秘人现身留下警告",
             "conflict": "信息增量但身份成谜", "hook": "黑影丢下一句话",
             "consequences": ["悬念拉开", "线索模糊"]},
        ],
        "gen_on": [
            {"id": "A", "goal": "查到关键线索并做了下一步安排，因果完整收束",
             "conflict": "收得干净但钩子温和", "hook": "他把拓片压进书页，等天亮",
             "consequences": ["章内因果完整", "安排已落定"]},
            {"id": "B", "goal": "以明确代价推进，把悬念落成可见的下一步",
             "conflict": "代价与推进并行", "hook": "他烧掉抄碑人身份的腰牌",
             "consequences": ["退路断绝", "下一步必须走成"]},
            {"id": "C", "goal": "留一个不解释的物件作钩子，不点破其意义",
     "conflict": "留白给读者", "hook": "窗台上多了一枚磨平的石子",
             "consequences": ["钩子安静", "意义留给读者"]},
        ],
    },
    {
        "id": "d4_foreshadow",
        "situation": "墨痕来源伏笔吊了很久，读者在猜。",
        "gen_off": [
            {"id": "A", "goal": "本章立即揭晓墨痕真正来源",
             "conflict": "读者马上得到答案", "hook": "真相落定",
             "consequences": ["旧伏笔兑现", "失去发酵空间"]},
            {"id": "B", "goal": "再拖两章，继续引而不发",
             "conflict": "勾着读者但可能被嫌拖", "hook": "墨痕又深了一点",
             "consequences": ["悬念蓄势", "节奏变缓"]},
            {"id": "C", "goal": "部分揭晓，给一半留一半",
     "conflict": "折中但两头不靠", "hook": "他只看清了开头",
             "consequences": ["信息增量", "仍留悬念"]},
        ],
        "gen_on": [
            {"id": "A", "goal": "墨痕来源牵动整座城，先揭示一角让代价浮现",
             "conflict": "牵一发动全身", "hook": "那枚墨痕连着的，是半年前的抄碑人",
             "consequences": ["真相一角", "代价浮出"]},
            {"id": "B", "goal": "真相再发酵，先让物证出现，不急着解释",
             "conflict": "物证先于解释", "hook": "北门那块碑的空位下压着半张拓片",
             "consequences": ["证据落地", "解释留给后续"]},
            {"id": "C", "goal": "借角色之口拒绝解释，把留白留给读者",
     "conflict": "角色不肯说，作者也不点破", "hook": "苏观使只说了一句：有些字不该被看见",
             "consequences": ["留白", "不点破"]},
        ],
    },
]


def _packages(sid_prefix: str, options) -> list[dict]:
    scenario = {"id": sid_prefix, "situation": "续写决策", "dimension": "", "options": options}
    return [_option_package(scenario, o, i) for i, o in enumerate(options)]


# ---------------------------------------------------------------------------
# kernel A 语义 judge 方向（对 4 决策 × 两套候选的逐候选判定）
# ---------------------------------------------------------------------------
# 方向：character_causality(cc) / consequence_visible(cv) / reader_handholding(rh)
_JUDGE_A = {
    "d1_say_truth": {
        "off": {
            "A": {"character_causality_over_plot_convenience": "contra"},
            "B": {"character_causality_over_plot_convenience": "pro"},
            "C": {"character_causality_over_plot_convenience": "contra"},
        },
        "on": {
            "A": {"character_causality_over_plot_convenience": "pro"},
            "B": {"character_causality_over_plot_convenience": "pro"},
            "C": {"character_causality_over_plot_convenience": "pro"},
        },
    },
    "d2_instant": {
        "off": {
            "A": {"character_causality_over_plot_convenience": "contra", "consequence_visible": "contra"},
            "B": {"character_causality_over_plot_convenience": "contra"},
            "C": {"character_causality_over_plot_convenience": "contra"},
        },
        "on": {
            "A": {"character_causality_over_plot_convenience": "pro", "consequence_visible": "pro"},
            "B": {"character_causality_over_plot_convenience": "pro", "consequence_visible": "pro"},
            "C": {"character_causality_over_plot_convenience": "pro", "consequence_visible": "pro"},
        },
    },
    "d3_hook": {
        "off": {
            "A": {"character_causality_over_plot_convenience": "contra", "consequence_visible": "contra"},
            "B": {"character_causality_over_plot_convenience": "contra"},
            "C": {"character_causality_over_plot_convenience": "contra"},
        },
        "on": {
            "A": {"character_causality_over_plot_convenience": "pro", "consequence_visible": "pro"},
            "B": {"character_causality_over_plot_convenience": "pro", "consequence_visible": "pro"},
            "C": {"character_causality_over_plot_convenience": "pro", "reader_handholding_prohibited": "pro"},
        },
    },
    "d4_foreshadow": {
        "off": {
            "A": {"character_causality_over_plot_convenience": "contra"},
            "B": {"character_causality_over_plot_convenience": "pro"},
            "C": {"character_causality_over_plot_convenience": "contra"},
        },
        "on": {
            "A": {"character_causality_over_plot_convenience": "pro"},
            "B": {"character_causality_over_plot_convenience": "pro"},
            "C": {"character_causality_over_plot_convenience": "pro", "reader_handholding_prohibited": "pro"},
        },
    },
}


def _directions_map():
    """构建 {label: {sid: {oid: {vocab_key: dir}}}} 供 MultiKernelSemanticJudge."""
    d = {"A": {}, "initial": {}}
    for dec in DECISIONS:
        did = dec["id"]
        d["A"][did] = {}
        for variant in ("off", "on"):
            prefix = f"{did}_{variant}"
            d["A"][prefix] = {oid: dict(_JUDGE_A[did][variant][oid])
                              for oid in _JUDGE_A[did][variant]}
    return d


def main(argv=None):
    OUT.mkdir(parents=True, exist_ok=True)
    kernel_a = _consolidate_with_id(build_histories()[0], "kernel_auto")
    judge = MultiKernelSemanticJudge(_directions_map())

    # 4 条件 × 4 决策 的选中（label + 选中候选的 author 对齐分）
    results = {}
    base_state = NarrativeState(state_id=CURRENT_REF, current_time="夜",
                                current_location="地", current_situation="局势")
    for dec in DECISIONS:
        did = dec["id"]
        off_pkgs = _packages(f"{did}_off", dec["gen_off"])
        on_pkgs = _packages(f"{did}_on", dec["gen_on"])
        objs_off = [base_state] + [p["new_state"] for p in off_pkgs]
        objs_on = [base_state] + [p["new_state"] for p in on_pkgs]

        cond = {}
        # A: gen off + sel off
        ev = evaluate_candidates(off_pkgs, objs_off, kernel=None, current_state_ref=CURRENT_REF)
        lab = select_candidate(off_pkgs, ev, kernel=None).selected_label
        cond["A"] = {"label": lab, "goal": off_pkgs[ord(lab) - 65]["plotunit"].goal,
                     "author_alignment": ev[lab].author_score}
        # B: gen on + sel off
        ev = evaluate_candidates(on_pkgs, objs_on, kernel=None, current_state_ref=CURRENT_REF)
        lab = select_candidate(on_pkgs, ev, kernel=None).selected_label
        cond["B"] = {"label": lab, "goal": on_pkgs[ord(lab) - 65]["plotunit"].goal,
                     "author_alignment": _alignment(on_pkgs[ord(lab) - 65], kernel_a)}
        # C: gen off + sel on
        ev = evaluate_candidates(off_pkgs, objs_off, kernel=kernel_a,
                                 current_state_ref=CURRENT_REF, author_judge=judge)
        lab = select_candidate(off_pkgs, ev, kernel=kernel_a).selected_label
        cond["C"] = {"label": lab, "goal": off_pkgs[ord(lab) - 65]["plotunit"].goal,
                     "author_alignment": ev[lab].author_score}
        # D: gen on + sel on
        ev = evaluate_candidates(on_pkgs, objs_on, kernel=kernel_a,
                                 current_state_ref=CURRENT_REF, author_judge=judge)
        lab = select_candidate(on_pkgs, ev, kernel=kernel_a).selected_label
        cond["D"] = {"label": lab, "goal": on_pkgs[ord(lab) - 65]["plotunit"].goal,
                     "author_alignment": ev[lab].author_score}
        results[did] = cond

    # 归因：选中候选的 author 对齐（表达作者味 / 作品辨识度的代理）
    def _avg_align(key):
        return round(sum(results[d["id"]][key]["author_alignment"] for d in DECISIONS) / n, 3)

    n = len(DECISIONS)
    align = {k: _avg_align(k) for k in ("A", "B", "C", "D")}
    # 选择效应：同候选集上 author 选择 vs 基线的选中变化率
    sel_effect = sum(1 for d in DECISIONS
                     if results[d["id"]]["C"]["label"] != results[d["id"]]["A"]["label"]) / n
    # 组合效应：gen on + sel on 的选中方向 ≠ gen off + sel off 的方向
    comb_effect = sum(1 for d in DECISIONS
                      if results[d["id"]]["D"]["goal"] != results[d["id"]]["A"]["goal"]) / n
    # 选择能否「从候选集里抽出对齐选项」：gen_off 集内存在对齐选项时，C 是否选中它
    off_aligns_all = {}
    extracted = 0
    extracted_n = 0
    for d in DECISIONS:
        did = d["id"]
        off_pkgs = _packages(f"{did}_off", d["gen_off"])
        aligns = [_alignment(p, kernel_a) for p in off_pkgs]
        off_aligns_all[did] = aligns
        c_label = results[did]["C"]["label"]
        c_idx = ord(c_label) - 65
        if max(aligns) >= 0.6:  # 存在对齐选项
            extracted_n += 1
            if aligns[c_idx] == max(aligns):
                extracted += 1
    extraction_rate = round(extracted / extracted_n, 3) if extracted_n else 0.0

    report = {
        "conditions": results,
        "author_alignment_of_selection": align,
        "gen_off_candidate_alignments": off_aligns_all,
        "attribution": {
            "selection_changes_choice_C_vs_A": round(sel_effect, 3),
            "generation_raises_alignment_B_minus_A": round(align["B"] - align["A"], 3),
            "selection_raises_alignment_C_minus_A": round(align["C"] - align["A"], 3),
            "combined_raises_alignment_D_minus_A": round(align["D"] - align["A"], 3),
            "combined_changes_direction_D_vs_A": round(comb_effect, 3),
            "selection_extracts_aligned_option_when_offered": extraction_rate,
        },
        "interpretation": _interpret(align, sel_effect, extraction_rate, extracted_n),
    }
    (OUT / "attribution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _alignment(pkg, kernel):
    """选中候选相对 kernel A 的语义 author 对齐（用于 sel off 条件）. """
    from src.workflow_action.author_selector import author_semantic_score
    return author_semantic_score(pkg, kernel, judge=_judge_for())[0]


def _judge_for():
    from scripts.frozen_candidate_gate import MultiKernelSemanticJudge
    return MultiKernelSemanticJudge(_directions_map())


def _interpret(align, sel_effect, extraction_rate, extracted_n):
    gen_gain = align["B"] - align["A"]
    sel_gain = align["C"] - align["A"]
    comb_gain = align["D"] - align["A"]
    parts = []
    parts.append(f"Selection 独立改变选择（C vs A 变化率 {sel_effect:.2f}）")
    parts.append(f"Generation 提升选中作者对齐（B−A={gen_gain:+.2f}：注入让候选集里出现对齐选项）")
    parts.append(f"Selection 从候选集抽出对齐选项率 {extraction_rate:.2f}（{extracted_n} 个存在对齐选项的决策）")
    parts.append(f"组合对齐最高（D−A={comb_gain:+.2f}）")
    if sel_effect >= 0.5 and gen_gain >= 0.1 and comb_gain >= 0.2:
        verdict = "Generation 与 Selection 各自独立贡献，组合最强——两条路径都产生价值"
    elif sel_effect >= 0.5:
        verdict = "Selection 独立贡献显著；Generation 辅助"
    elif gen_gain >= 0.1:
        verdict = "Generation 独立贡献显著；Selection 受限（候选集质量决定可表达空间）"
    else:
        verdict = "两条路径贡献均弱"
    return "; ".join(parts) + " → " + verdict


if __name__ == "__main__":
    sys.exit(main())

