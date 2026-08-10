"""Proposal Generator — 多候选 PlotUnit 生成（作者性第二工作包 §9-10）.

Continue 从「生成一个 PlotUnit」→「生成 N 个 PlotUnit candidate」（**非 prose**，
省成本——PlotUnit 已含 goal/conflict/participants/hook/consequences/
SceneExperience，没必要生成五份正文）。

**候选必须有真实决策差异，不是 style variation**（§10）。错误：
`A愤怒离开 / B冷冷离开 / C沉默离开`。正确：
`A直接摊牌 / B隐瞒并继续调查 / C故意给错误信息试探 / D离开关系 / E装不知`
——不同的故事选择。

CLI `--proposals N`（默认 1，零成本）：N=1 时 prompt/输出字节不变
（compose/extend 走原有 Continue 路径，本模块完全不参与）；N>1 时才启用
本模块。

零成本契约：N=1 不调用 build_proposal_prompt / parse_proposals_response，
字节与旧版逐字节相同（回归测试锁死）。
"""

import json
from typing import Optional

from src.object_state import NarrativeState, PlotUnit
from src.workflow_action.continuation import ContinueUnit

_CANDIDATE_LABELS = ("A", "B", "C", "D", "E", "F", "G")


def build_proposal_prompt(
    continue_unit: ContinueUnit,
    n: int,
    state: NarrativeState,
    characters,
    facts,
    foreshadows,
    *,
    workspec_context: str = "",
    frame_context: Optional[dict] = None,
    structure_template: Optional[str] = None,
    platform: Optional[str] = None,
    genre: Optional[str] = None,
    style_context: str = "",
    retrieval_context: str = "",
    timeline_context: str = "",
    time_context: str = "",
    excerpt_context: str = "",
    original_style_context: str = "",
    nsfw_context: str = "",
    author_context: str = "",
    contract_context: str = "",
    viability_note: str = "",
) -> str:
    """构建 N 候选续写 prompt.

    前段（作品约束/当前状态/角色/事实/伏笔/续写要求）复用 Continue 的构建
    结果，保证单候选语境与旧版一致；在【输出格式】处换成多候选格式。
    author_context 为作者感知注入（§29/§30：render_kernel_context +
    render_memory_context 的产物，Level 3+4 记忆）；空串时输出与旧版逐字节
    相同（零成本契约）。
    """
    if n < 2:
        raise ValueError("build_proposal_prompt requires n >= 2 (N=1 走原 Continue)")
    base = continue_unit.build_prompt(
        state=state,
        characters=characters,
        facts=facts,
        foreshadows=foreshadows,
        workspec_context=workspec_context,
        frame_context=frame_context,
        structure_template=structure_template,
        platform=platform,
        genre=genre,
        style_context=style_context,
        retrieval_context=retrieval_context,
        timeline_context=timeline_context,
        time_context=time_context,
        excerpt_context=excerpt_context,
        original_style_context=original_style_context,
        nsfw_context=nsfw_context,
        contract_context=contract_context,
        viability_note=viability_note,
    )
    marker = "【输出格式】"
    if marker not in base:
        raise ValueError("Continue prompt layout changed; proposal builder out of sync")
    head = base.split(marker, 1)[0]
    if author_context.strip():
        return head + "\n\n" + author_context.strip() + "\n\n" + _multi_candidate_output_section(n)
    return head + _multi_candidate_output_section(n)


def _multi_candidate_output_section(n: int) -> str:
    labels = ", ".join(f"{_CANDIDATE_LABELS[i]}={_CANDIDATE_LABELS[i]}方案" for i in range(n))
    return f"""【多候选要求】

必须生成 {n} 个 PlotUnit 候选（候选标签：{labels}）。
- 每个候选代表一条**真正不同的故事走向**，不是同一情节的措辞/风格变体。
  正确示例：直接摊牌 / 隐瞒并继续调查 / 故意给错误信息试探 / 离开关系 / 装不知。
- 候选之间在 goal、conflict、hook、consequences、参与角色上必须有实质差异。
- 每个候选都必须满足【续写要求】的全部约束（结构有效推进 / 角色行为符合
  CharacterModel 驱动力 / 信息释放服务伏笔推进 / 世界规则代价 / 情绪有据 /
  忠于已发生事件）。
- 各候选彼此独立自洽，不得互相假设另一个候选已发生。
- 若某一故事走向会破坏信息权限 / 让角色突然变聪明 / 让道歉瞬间修复长期创伤，
  它仍可作为一个候选出现，但请如实标注其 tradeoff（放弃什么换取什么）。

【输出格式】
严格输出 JSON:
{{
  "proposals": [
    {{
      "plotunit": {{
        "unit_id": "pu_xxx_A",
        "level": "scene",
        "goal": "候选A的本单元目标",
        "participants": ["角色ID"],
        "conflict": "候选A的核心冲突",
        "input_state_ref": "ns_xxx",
        "output_state_ref": "新状态ID_A",
        "released_information": ["新释放给读者的信息"],
        "emotional_shift": "情绪变化",
        "hook": "钩子",
        "hook_type": "钩子类型（显式枚举，见【层级钩子类型】；可省略）",
        "formula_node": "当前结构节点名",
        "consequences": ["后果"],
        "is_effective": true,
        "scene_experience": {{
          "protagonist_sees": "主角看见了什么",
          "obstacles": ["阻碍"],
          "choice_grounding": "为什么作出选择",
          "outcome": "选择产生了什么结果",
          "cognition_shift": "情绪和认知如何变化"
        }}
      }},
      "new_state": {{
        "state_id": "新状态ID_A",
        "current_time": "新时间",
        "current_location": "新地点",
        "active_characters": ["角色ID"],
        "current_situation": "新局势",
        "active_conflicts": ["新冲突"],
        "public_information": ["新公开信息"],
        "hidden_information": ["新隐藏信息"]
      }},
      "new_facts": [
        {{
          "fact_id": "f_xxx_A",
          "statement": "新确认事实",
          "fact_type": "event",
          "involved_entities": [],
          "confirmed": true
        }}
      ],
      "confidence_gaps": ["不确定的信息"],
      "tradeoff_hint": "该候选相比其他候选，放弃什么换取什么（用于选择理由）"
    }}
  ]
}}

注意：
- proposals 数组长度必须恰好为 {n}
- 每个候选的 unit_id / new_state.state_id / fact_id 必须唯一（前缀 A/B/C...）
- 每个候选的 new_facts 只写已确认的 hard facts，不确定的放入 confidence_gaps
"""


def parse_proposals_response(response: str, n: int) -> list[dict]:
    """解析多候选响应，返回 N 个候选包.

    Each package: {"plotunit": PlotUnit, "new_state": NarrativeState,
                   "new_facts": list, "confidence_gaps": list}
    """
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError("proposals response must be a JSON object")
    extra = sorted(set(data) - {"proposals"})
    if extra:
        raise ValueError(f"proposals response has unexpected field(s): {', '.join(extra)}")
    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("proposals must be a list")
    if len(proposals) != n:
        raise ValueError(f"expected {n} proposals, got {len(proposals)}")

    parsed: list[dict] = []
    seen_unit_ids: set[str] = set()
    seen_state_ids: set[str] = set()
    for i, cand in enumerate(proposals):
        if not isinstance(cand, dict):
            raise ValueError(f"proposal {i} must be a JSON object")
        required = ("plotunit", "new_state", "new_facts", "confidence_gaps")
        missing = [f for f in required if f not in cand]
        if missing:
            raise ValueError(
                f"proposal {i} missing required field(s): {', '.join(missing)}"
            )
        extra_fields = sorted(set(cand) - set(required) - {"tradeoff_hint"})
        if extra_fields:
            raise ValueError(
                f"proposal {i} has unexpected field(s): {', '.join(extra_fields)}"
            )
        if not isinstance(cand["new_facts"], list):
            raise ValueError(f"proposal {i} new_facts must be a list")
        if not isinstance(cand["confidence_gaps"], list):
            raise ValueError(f"proposal {i} confidence_gaps must be a list")
        if not all(isinstance(gap, str) for gap in cand["confidence_gaps"]):
            raise ValueError(f"proposal {i} confidence_gaps must be strings")

        plotunit = PlotUnit(**cand["plotunit"])
        new_state = NarrativeState(**cand["new_state"])
        if plotunit.unit_id in seen_unit_ids:
            raise ValueError(f"duplicate unit_id across proposals: {plotunit.unit_id}")
        if new_state.state_id in seen_state_ids:
            raise ValueError(f"duplicate state_id across proposals: {new_state.state_id}")
        seen_unit_ids.add(plotunit.unit_id)
        seen_state_ids.add(new_state.state_id)

        parsed.append(
            {
                "plotunit": plotunit,
                "new_state": new_state,
                "new_facts": cand["new_facts"],
                "confidence_gaps": cand["confidence_gaps"],
                "tradeoff_hint": cand.get("tradeoff_hint", ""),
            }
        )
    return parsed


def candidate_label(index: int) -> str:
    """候选标签 A/B/C...（超出 7 个则回退编号）."""
    if index < len(_CANDIDATE_LABELS):
        return _CANDIDATE_LABELS[index]
    return f"C{index}"
