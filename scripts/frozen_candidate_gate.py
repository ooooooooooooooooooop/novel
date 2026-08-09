#!/usr/bin/env python3
"""Frozen Candidate Selection Gate（§9-12）——Generation 与 Selection 因果解耦.

当前生产管线里 Author 主要通过**候选生成注入**影响作品（kernel→proposal prompt），
选择器实际翻转 ≈0（上轮 shadow 0% 分叉）。本 Gate 直接验证 Selection 本身：

  1. 生成并**冻结**候选 A/B/C（内容绝对不变）；
  2. 只换 Author history / AuthorKernel：Initial(空) / History-A / History-B；
  3. 相同 candidates、相同上下文、相同 base model、相同参数；
  4. 多个未见 creative decision（覆盖说破真相/保留误解/爽感vs真实/解释象征/
     戏剧巧合/兑现伏笔/不讨喜真实/市场化hook/保留unresolved/信息权限）。

成功标准（§11）：History A 在多个未见任务上产生可识别偏向；History B 产生
另一种可识别偏向；差异有历史依据；不是固定选 index；不是故意反 Reader。

流程：
  python scripts/frozen_candidate_gate.py baseline   # 关键词选择器基线（预期低分叉）
  python scripts/frozen_candidate_gate.py semantic    # 语义 judge 选择（读 judge 响应）
两个 phase 都写 judge prompt（semantic 用）；operator 填 judge_*.json 后跑 semantic。

隐私：产物含作品语境（候选/理由），存 novels/author-kernel-research/output/research/
（gitignored）。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.object_state.authorkernel import (
    VALUE_VOCAB_DESCRIPTIONS,
    VALUE_VOCAB_PRO_KEYWORDS,
    VALUE_VOCAB_CONTRA_KEYWORDS,
    AuthorKernel,
)
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.object_state.narrativestate import NarrativeState
from src.object_state.plotunit import PlotUnit
from src.object_state.scene_experience import SceneExperience
from src.workflow_action.consolidation import consolidate_ledger
from src.workflow_action.author_selector import (
    AuthorJudge,
    evaluate_candidates,
    select_candidate,
)

TS = "2026-08-09T12:00:00"
OUT = Path("novels/author-kernel-research/output/research/frozen_candidates")
CURRENT_REF = "ns_frozen"


# ---------------------------------------------------------------------------
# 历史构造（真实 ChoiceRecord + Consolidation，非手工 kernel）
# ---------------------------------------------------------------------------
def _pu_text(text: str) -> dict:
    return {
        "unit_id": "pu_x",
        "level": "scene",
        "goal": text,
        "conflict": "冲突",
        "input_state_ref": "ns_in",
        "output_state_ref": "ns_out",
        "consequences": [],
        "released_information": [],
        "is_effective": True,
    }


def history_choice(key: str, direction: str, decision_id: str) -> ChoiceRecord:
    """构造一条历史选择：选中候选命中 key 的 pro/contra 关键词（行为证据）."""
    pro_kw = next((kw for kw in VALUE_VOCAB_PRO_KEYWORDS.get(key, ()) if kw), "")
    contra_kw = next((kw for kw in VALUE_VOCAB_CONTRA_KEYWORDS.get(key, ()) if kw), "")
    sel_text = f"作者选择「{pro_kw}」" if direction == "pro" else f"作者选择了「{contra_kw}」"
    cands = [
        CandidateRecord(
            candidate_id="A", summary="选中",
            plotunit=_pu_text(sel_text), new_state_ref="ns_out",
        ),
        CandidateRecord(
            candidate_id="B", summary="落选",
            plotunit=_pu_text("无关的推进"), new_state_ref="ns_out",
        ),
    ]
    return ChoiceRecord(
        decision_id=decision_id,
        decision_timestamp=TS,
        plot_context="创作决策",
        state_ref="ns_in",
        candidates=cands,
        selected_candidate="A",
        rejected=[RejectedRecord(candidate_id="B", reason="落选")],
        tradeoff="换取 Y",
        value_conflicts=[key],
    )


def build_histories() -> tuple[list[ChoiceRecord], list[ChoiceRecord]]:
    """两条不同创作选择史（各 8 条）→ 归纳出语义不同的两个 kernel."""
    seq_a = [
        history_choice("character_causality_over_plot_convenience", "pro", f"a_{i}")
        for i in range(3)
    ]
    seq_a += [
        history_choice("consequence_visible", "pro", f"a_cv_{i}") for i in range(2)
    ]
    seq_a += [
        history_choice("reader_handholding_prohibited", "pro", f"a_rh_{i}")
        for i in range(2)
    ]
    # 8th: a deliberate attention bias so A is not a "single axis" author
    seq_a += [history_choice("attend_power_dynamics", "pro", "a_ap")]

    seq_b = [
        history_choice("no_unresolved_then_ignore", "pro", f"b_{i}")
        for i in range(3)
    ]
    seq_b += [
        history_choice("autonomy_over_coercion", "pro", f"b_au_{i}") for i in range(2)
    ]
    seq_b += [
        history_choice("no_instant_forgiveness", "pro", f"b_nf_{i}") for i in range(2)
    ]
    seq_b += [history_choice("interpret_via_interest_structure", "pro", "b_ip")]
    return seq_a, seq_b


def consolidate(seq: list[ChoiceRecord]) -> AuthorKernel:
    return consolidate_ledger(
        ChoiceLedgerEntry(choices=list(seq)),
        timestamp=TS,
        min_support=1,
        contested_ratio=0.8,
    ).kernel


def kernel_summary(kernel: AuthorKernel) -> str:
    if not kernel.all_principles():
        return "empty"
    labels = [p.vocab_key for p in kernel.all_principles() if p.status in ("stable", "weak")]
    return f"status={kernel.status} stable/weak={labels}"


# ---------------------------------------------------------------------------
# 未见创作决策（冻结候选；覆盖 §10 要求的维度）
# ---------------------------------------------------------------------------
SCENARIOS: list[dict] = [
    {
        "id": "s1_say_truth",
        "dimension": "人物是否说破真相",
        "situation": "苏观使再度盘问林烬对碑下旧字的了解，逼问越来越近。如何应对？",
        "options": [
            {
                "id": "A", "goal": "当场说出墨痕真相，以坦诚换取信任",
                "conflict": "说出后敬天司会立刻盯上他，暴露改写代价",
                "hook": "苏观使的眼神在他说出口的那一刻变了",
                "consequences": ["信任换取成功", "身份提前暴露"],
                "grounding": "林烬觉得再瞒下去迟早被查穿，不如主动摊牌",
            },
            {
                "id": "B", "goal": "隐瞒墨痕能力，用旁敲侧击与反问引开话题",
                "conflict": "苏观使的追问如影随形，隐瞒越来越难",
                "hook": "苏观使临走那句『你今晚来找我』",
                "consequences": ["信息差保留", "苏观使疑心加重"],
                "grounding": "林烬的执念是查出自己被抹掉的那块碑，不能提前暴露",
            },
        ],
    },
    {
        "id": "s2_misunderstanding",
        "dimension": "是否保留误解",
        "situation": "沈望误以为林烬盗走了碑库钥匙，当面对质。",
        "options": [
            {
                "id": "A", "goal": "当场澄清误会，把钥匙来历说清楚",
                "conflict": "澄清需要解释他为何深夜出现在碑库",
                "hook": "沈望听完仍半信半疑",
                "consequences": ["误会当场消除", "却引出一个更大的问题"],
                "grounding": "林烬不想失去这个唯一肯接济他的旧人",
            },
            {
                "id": "B", "goal": "不澄清，借这个误会让自己留在对方怀疑的目光里",
                "conflict": "让沈望继续防备他，他就有了借力打力的空间",
                "hook": "沈望转身时，钥匙在谁手里只有林烬自己知道",
                "consequences": ["误会被利用为掩护", "沈望心冷了一截"],
                "grounding": "林烬需要这个误会让真正的目标以为他没在查",
            },
        ],
    },
    {
        "id": "s3_instant_vs_real",
        "dimension": "爽感 vs 人物真实性",
        "situation": "主角被逼到绝境，读者正期待他翻盘。",
        "options": [
            {
                "id": "A", "goal": "绝境中忽然领悟碑文奥义，能力跃升反败为胜",
                "conflict": "爽点拉满，但能力来得毫无根基",
                "hook": "碑面在他眼底亮起整片旧字",
                "consequences": ["当场翻盘", "成长显得无来由"],
                "grounding": "剧情需要一个爆点把气氛推上去",
            },
            {
                "id": "B", "goal": "没有顿悟，用此前反复练过的生涩手法硬撑过去",
                "conflict": "过程狼狈，事后才发现这手法恰是伏笔",
                "hook": "他赢了，手上的旧疤裂开一道新口子",
                "consequences": ["保住局面", "靠的是旧日苦功而非天降能力"],
                "grounding": "林烬的能力从来是一笔一画练出来的，不是天授",
            },
        ],
    },
    {
        "id": "s4_symbol",
        "dimension": "是否解释象征",
        "situation": "章末写到被磨平刻痕的第七块碑，月光正好。",
        "options": [
            {
                "id": "A", "goal": "点破石碑象征『被抹去的历史』，替读者总结主题",
                "conflict": "意义交代得清楚，但读者不再需要自己想",
                "hook": "『有些名字，抹掉了就再没人记得』",
                "consequences": ["主题明确", "解读空间关闭"],
                "grounding": "这句总结能强化立意",
            },
            {
                "id": "B", "goal": "只写月光下碑面磨平的痕迹与林烬的沉默，不解释",
                "conflict": "留白给读者，但可能被说看不懂",
                "hook": "林烬伸手，指腹停在那道磨痕上",
                "consequences": ["氛围到位", "象征留在读者手里"],
                "grounding": "碑的意义不需要旁白，字就在那里",
            },
        ],
    },
    {
        "id": "s5_coincidence",
        "dimension": "是否使用戏剧巧合",
        "situation": "查私碑坊线索陷入僵局，需要突破口。",
        "options": [
            {
                "id": "A", "goal": "主角恰好撞见反派深夜密谈，剧情急转直下",
                "conflict": "推进最快，但巧合感重",
                "hook": "窗缝里那张脸，正是他找了三年的抹碑者",
                "consequences": ["突破口瞬间打开", "巧合推进，因果弱"],
                "grounding": "故事需要在这里提速",
            },
            {
                "id": "B", "goal": "主角靠此前埋下的拓片线索逐条排查，找到密谈地点",
                "conflict": "需要两章铺垫，节奏慢但因果完整",
                "hook": "他把两半拓片拼起时，边缘的墨线正好接上",
                "consequences": ["找到地点", "每一步都有迹可循"],
                "grounding": "林烬查案从来是顺藤摸瓜，不信天上掉的线索",
            },
        ],
    },
    {
        "id": "s6_foreshadow",
        "dimension": "是否马上兑现伏笔",
        "situation": "墨痕来源的伏笔吊了很久，读者已在猜。",
        "options": [
            {
                "id": "A", "goal": "本章立即揭晓墨痕真正的来源",
                "conflict": "读者马上得到答案，伏笔快速兑现",
                "hook": "真相落定，新悬念随之而起",
                "consequences": ["旧伏笔兑现", "失去一段发酵空间"],
                "grounding": "吊太久了，该给答案",
            },
            {
                "id": "B", "goal": "继续引而不发，让真相再发酵两章",
                "conflict": "勾着读者，但可能被嫌拖",
                "hook": "墨痕在某处又深了一点",
                "consequences": ["悬念蓄势", "真相仍在路上"],
                "grounding": "墨痕的真相牵动整座城，不能轻易掀开",
            },
        ],
    },
    {
        "id": "s7_unlikable_true",
        "dimension": "是否让人物做不讨喜但真实的选择",
        "situation": "查案进入关键期，一直关照林烬的沈望恰在这时请他帮忙办件私事。",
        "options": [
            {
                "id": "A", "goal": "林烬以查案为重，冷淡拒绝了沈望，选择对旧人无情但忠于执念",
                "conflict": "读者会觉得他凉薄，但这是他此刻真实会做的",
                "hook": "沈望愣住，半晌只说了一个字：好",
                "consequences": ["查案不受干扰", "一段旧情就此搁置"],
                "grounding": "林烬的执念排在一切之前，他就是这样的人",
            },
            {
                "id": "B", "goal": "林烬先放下查案，帮沈望办完私事再走",
                "conflict": "讨喜、有人情味，但偏离了查案节奏",
                "hook": "沈望送他出门时，眼里那点暖意还在",
                "consequences": ["人情保全", "查案被耽搁半日"],
                "grounding": "他欠沈望一碗热粥的情，不想辜负",
            },
        ],
    },
    {
        "id": "s8_market_hook",
        "dimension": "是否使用市场化 hook",
        "situation": "本章结尾，追读数据显示『主角生死未卜』类悬念钩子数据最好。",
        "options": [
            {
                "id": "A", "goal": "章末主角被当街掳走生死未卜，钩子优先",
                "conflict": "追读强，但章内因果链断在这里",
                "hook": "人群散尽，街心只剩一滩墨迹",
                "consequences": ["悬念最抓人", "因果不完整"],
                "grounding": "数据说话，读者爱这个",
            },
            {
                "id": "B", "goal": "章末主角查到关键线索并做了下一步安排，因果完整",
                "conflict": "章内收束得干净，但钩子温和",
                "hook": "他把那半块拓片压进书页，等天亮",
                "consequences": ["章内因果完整", "钩子力度温和"],
                "grounding": "每一步都该有落点，故事不是靠悬念堆的",
            },
        ],
    },
    {
        "id": "s9_unresolved",
        "dimension": "是否保留 unresolved conflict",
        "situation": "章末，林烬与苏观使的对立到了摊牌边缘。",
        "options": [
            {
                "id": "A", "goal": "保留对立，让冲突继续压在两人之间不和解",
                "conflict": "张力延续到下一章，关系悬而未决",
                "hook": "苏观使把刀收回去，也把话咽了回去",
                "consequences": ["张力最大化", "关系保持在未解状态"],
                "grounding": "两人的立场针锋相对，这一句和不了",
            },
            {
                "id": "B", "goal": "各退一步，达成暂时的合作约定",
                "conflict": "冲突软化，但两人都清楚这是权宜",
                "hook": "他们击掌为约，谁也不信谁",
                "consequences": ["眼前局面解开了", "真正的裂隙更深处还在"],
                "grounding": "眼下查碑要紧，暂时同路对两人都有利",
            },
        ],
    },
    {
        "id": "s10_info_permission",
        "dimension": "信息权限",
        "situation": "需要让主角知道下一步该往哪走，编剧在权衡信息的给法。",
        "options": [
            {
                "id": "A", "goal": "主角忽然得知敬天司内部的机密（越权知情推进剧情）",
                "conflict": "推进最顺，但主角凭什么知道",
                "hook": "那封密信的内容，他连最亲近的人都从没说过",
                "consequences": ["方向立刻明确", "信息来得没有来由"],
                "grounding": "剧情需要他此刻知道这件事",
            },
            {
                "id": "B", "goal": "主角只凭已有线索推出有限信息，保持信息差",
                "conflict": "他知道得慢，但每一步都站得住",
                "hook": "他推不出全部，只推出一个名字",
                "consequences": ["信息有据", "真相仍隔着一层"],
                "grounding": "林烬知道的东西，必须是他一步步查出来的",
            },
        ],
    },
]


def _option_package(scenario: dict, opt: dict, idx: int) -> dict:
    sid = scenario["id"]
    oid = opt["id"]
    pu = PlotUnit(
        unit_id=f"pu_{sid}_{oid}",
        level="scene",
        goal=opt["goal"],
        conflict=opt["conflict"],
        participants=["c001", "c003"],
        input_state_ref=CURRENT_REF,
        output_state_ref=f"ns_{sid}_{oid}",
        released_information=[],
        emotional_shift="紧张",
        hook=opt.get("hook"),
        formula_node="scene",
        consequences=opt.get("consequences", []),
        state_change_summary=opt.get("goal"),
        removable_without_loss=False,
        is_effective=True,
        scene_experience=SceneExperience(
            protagonist_sees=opt.get("goal", ""),
            obstacles=[],
            choice_grounding=opt.get("grounding") or opt.get("goal", ""),
            outcome=opt.get("hook", ""),
            cognition_shift=opt.get("grounding") or opt.get("goal", ""),
        ),
    )
    ns = NarrativeState(
        state_id=f"ns_{sid}_{oid}",
        current_time="入夜",
        current_location="青云州",
        current_situation=scenario["situation"],
        primary_goal=opt["goal"],
    )
    return {
        "plotunit": pu,
        "new_state": ns,
        "new_facts": [],
        "confidence_gaps": [],
        "tradeoff_hint": scenario["dimension"],
    }


def build_scenario_packages() -> dict[str, list[dict]]:
    return {
        s["id"]: [_option_package(s, o, i) for i, o in enumerate(s["options"])]
        for s in SCENARIOS
    }


# ---------------------------------------------------------------------------
# 选择跑批
# ---------------------------------------------------------------------------
def run_selection(evals, packages, kernel):
    return select_candidate(packages, evals, kernel=kernel).selected_label


def run_all(judge=None):
    """对每个 kernel 跑全部 10 个未见决策，返回 {kernel_id: {scenario_id: label}}."""
    seq_a, seq_b = build_histories()
    kernels = {
        "initial": None,
        "A": _consolidate_with_id(seq_a, "kernel_auto"),
        "B": _consolidate_with_id(seq_b, "kernel_b"),
    }
    packages_by_scenario = build_scenario_packages()
    base_state = NarrativeState(
        state_id=CURRENT_REF, current_time="入夜", current_location="青云州",
        current_situation="当前局势",
    )
    out: dict[str, dict[str, str]] = {}
    for kid, kernel in kernels.items():
        out[kid] = {}
        for sid, pkgs in packages_by_scenario.items():
            # Consistency Gate 需要 input/output state_ref 都存在于 objects
            objects = [base_state] + [p["new_state"] for p in pkgs]
            evals = evaluate_candidates(
                pkgs, objects,
                kernel=kernel,
                current_state_ref=CURRENT_REF,
                author_judge=judge,
            )
            out[kid][sid] = run_selection(evals, pkgs, kernel)
    return out, kernels


def divergence_report(choices: dict[str, dict[str, str]]) -> dict:
    a, b = choices["A"], choices["B"]
    init = choices["initial"]
    div_ab = sum(1 for s in a if a[s] != b[s]) / len(a)
    div_a_init = sum(1 for s in a if a[s] != init[s]) / len(a)
    div_b_init = sum(1 for s in b if b[s] != init[s]) / len(b)
    # 偏向一致性：A 的选择是否与其历史原则解释一致（由人工在 report 里核）
    return {
        "n_scenarios": len(a),
        "divergence_A_vs_B": round(div_ab, 3),
        "divergence_A_vs_initial": round(div_a_init, 3),
        "divergence_B_vs_initial": round(div_b_init, 3),
    }


# ---------------------------------------------------------------------------
# judge prompt / response（semantic phase）
# ---------------------------------------------------------------------------
def _principle_lines(kernel: Optional[AuthorKernel]) -> str:
    if kernel is None or not kernel.all_principles():
        return "（无原则——初始/冻结作者，任何选择都中性）"
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


def write_judge_prompt(kernels: dict, out: Path) -> Path:
    """写一个给 operator 填的 judge prompt：三作者 × 十决策 × 逐原则方向."""
    p = out / "judge_prompt.txt"
    blocks = []
    for sid in SCENARIOS:
        blocks.append(f"## 决策 {sid['id']}（维度：{sid['dimension']}）")
        blocks.append(f"局势：{sid['situation']}")
        for opt in sid["options"]:
            blocks.append(
                f"- 候选 {opt['id']}：目标『{opt['goal']}』冲突『{opt['conflict']}』"
                f"钩子『{opt.get('hook','')}』后果『{'；'.join(opt.get('consequences',[]))}』"
            )
    scenarios_block = "\n".join(blocks)

    author_blocks = []
    for kid in ("initial", "A", "B"):
        author_blocks.append(
            f"## 作者 {kid}\n{_principle_lines(kernels[kid])}"
        )
    authors_block = "\n\n".join(author_blocks)

    prompt = f"""# 创作选择判断（Frozen Candidate Selection Gate）

你是严格的作者视角判断者。下面是三个「作者」的选择结构（只含中性方法论原则，
**不含任何作品/历史信息**），以及 10 个未见的创作决策，每个决策有 2 个候选方案。

对**每个候选方案**，相对**每个作者**的每条 stable/weak 原则，判断方向：
- pro：该候选表达/保护了这条价值（符合作者会做的）
- contra：该候选违反/牺牲了这条价值
- （不命中就省略该原则）

判断依据是语义（这个候选的实际故事走向），不是字面关键词。不要只看谁「更戏剧」，
只看相对该作者原则的立场。

{scenarios_block}

# 作者选择结构

{authors_block}

# 输出格式（严格 JSON）
{{
  "judgments": {{
    "A": {{
      "s1_say_truth": {{
        "A": {{"character_causality_over_plot_convenience": "pro"}},
        "B": {{"character_causality_over_plot_convenience": "contra"}}
      }},
      "s2_misunderstanding": {{...}}
    }},
    "B": {{...}},
    "initial": {{...}}
  }}
}}
注意：
- 只对判定命中的 (作者, 候选, 原则) 给方向；其余省略。
- 原则键用 vocab_key（如 character_causality_over_plot_convenience）。
- 每个作者块里应覆盖全部 10 个决策、每个决策的 2 个候选。
"""
    p.write_text(prompt, encoding="utf-8")
    return p


def parse_judge_response(path: Path, kernels: dict) -> dict:
    """读 judge 响应，展开成 {kernel_label: {sid: {oid: {vocab_key: dir}}}}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    judgments = data["judgments"]
    expanded: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for kid, kernel in kernels.items():
        expanded[kid] = {}
        kid_judg = judgments.get(kid, {})
        valid = set()
        if kernel is not None:
            valid = {p.vocab_key for p in kernel.all_principles()
                     if p.status in ("stable", "weak")}
        for sid in [s["id"] for s in SCENARIOS]:
            sc = kid_judg.get(sid, {})
            expanded[kid][sid] = {
                oid: {k: v for k, v in sc.get(oid, {}).items() if k in valid}
                for oid in ("A", "B")
            }
    return expanded


class MultiKernelSemanticJudge:
    """把展开的方向表适配成 AuthorJudge 协议（按 kernel.kernel_id 分发）."""

    def __init__(self, directions: dict, id_to_label: Optional[dict] = None):
        self._directions = directions  # {label: {sid: {oid: {vocab_key: dir}}}}
        self._id_to_label = id_to_label or {
            "kernel_auto": "A", "kernel_b": "B"
        }

    def _label(self, kernel: AuthorKernel) -> str:
        if kernel is None or not kernel.all_principles():
            return "initial"
        return self._id_to_label.get(kernel.kernel_id, "initial")

    def judge_candidate(self, kernel, package, candidate_text, context=""):
        label = self._label(kernel)
        pu = package["plotunit"]
        sid = pu.unit_id.removeprefix("pu_").rsplit("_", 1)[0]
        oid = pu.unit_id.rsplit("_", 1)[1]
        return self._directions.get(label, {}).get(sid, {}).get(oid, {})


def _consolidate_with_id(seq, kernel_id):
    res = consolidate_ledger(
        ChoiceLedgerEntry(choices=list(seq)),
        timestamp=TS, min_support=1, contested_ratio=0.8,
    )
    res.kernel.kernel_id = kernel_id
    return res.kernel


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["baseline", "semantic"], default="baseline")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)

    seq_a, seq_b = build_histories()
    kernel_a = _consolidate_with_id(seq_a, "kernel_auto")
    kernel_b = _consolidate_with_id(seq_b, "kernel_b")
    kernels = {"initial": None, "A": kernel_a, "B": kernel_b}

    if args.phase == "baseline":
        # 关键词选择器（生产当前默认，author_judge=None）
        choices, _ = run_all(judge=None)
        report = divergence_report(choices)
        # 记录选择细节
        detail = {
            k: {sid: {"selected": lab} for sid, lab in sc.items()}
            for k, sc in choices.items()
        }
        prompt_path = write_judge_prompt(kernels, OUT)
        (OUT / "baseline_report.json").write_text(
            json.dumps(
                {"metrics": report, "selections": detail,
                 "kernels": {k: kernel_summary(kk) if kk else "None"
                             for k, kk in kernels.items()},
                 "judge_prompt": str(prompt_path)},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"Judge prompt: {prompt_path}")
        print("[WAITING] 填 judge_response.json 后跑 --phase semantic")
        return 0

    if args.phase == "semantic":
        resp_path = OUT / "judge_response.json"
        if not resp_path.exists():
            print(f"missing judge response: {resp_path}")
            return 1
        directions = parse_judge_response(resp_path, kernels)
        judge = MultiKernelSemanticJudge(directions)
        choices, _ = run_all(judge=judge)
        report = divergence_report(choices)

        # ---- stable-only 稳健性（分叉是否由最强原则驱动，防 weak 原则偶然）----
        stable_directions = json.loads(resp_path.read_text(encoding="utf-8"))["judgments"]
        for kid, kernel in kernels.items():
            if kernel is None:
                continue
            stable = {p.vocab_key for p in kernel.all_principles() if p.status == "stable"}
            for sid in [s["id"] for s in SCENARIOS]:
                for oid in ("A", "B"):
                    stable_directions[kid].setdefault(sid, {}).setdefault(oid, {})
                    stable_directions[kid][sid][oid] = {
                        k: v for k, v in stable_directions[kid][sid][oid].items()
                        if k in stable
                    }
        stable_choices, _ = run_all(judge=MultiKernelSemanticJudge(stable_directions))
        stable_report = divergence_report(stable_choices)

        # ---- Gate 判定（§11 Selection 成功标准）----
        min_div = 0.5
        div = report["divergence_A_vs_B"]
        verdict = {
            "gate_pass": div >= min_div,
            "reason": (
                f"A/B 分叉 {div} >= {min_div}（要求多任务可识别偏向）；"
                f"A vs initial {report['divergence_A_vs_initial']}，"
                f"B vs initial {report['divergence_B_vs_initial']}"
            ),
        }

        detail = {
            k: {sid: {"selected": lab} for sid, lab in sc.items()}
            for k, sc in choices.items()
        }
        (OUT / "semantic_report.json").write_text(
            json.dumps(
                {"metrics": report, "stable_only_metrics": stable_report,
                 "selections": detail, "verdict": verdict,
                 "kernels": {k: kernel_summary(kk) if kk else "None"
                             for k, kk in kernels.items()}},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"stable-only: {json.dumps(stable_report, ensure_ascii=False)}")
        print(f"Gate: {'PASS' if verdict['gate_pass'] else 'FAIL'} — {verdict['reason']}")
        print("Semantic selection detail (init/A/B):")
        for s in SCENARIOS:
            sid = s["id"]
            print(f"  {sid}[{s['dimension']}]: init={choices['initial'][sid]} "
                  f"A={choices['A'][sid]} B={choices['B'][sid]}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
