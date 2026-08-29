"""A1 T5/T6 — 评审委员会：带正文锚点的单轴 JudgeClaim 生成与严格解析.

T5.5/T5.6：JudgeClaim 必须携带正文锚点与单轴结论；生成器与评审器上下文隔离——
评审 prompt 只含「本章正文 + 预承诺预期值 + ReaderContract」，**不含**生成 prompt、
其他候选正文、holdout 或对抗夹具。

``parse_judge_claims`` 做两道不可绕过核验：
1. 形状核验——缺字段/多余字段/非对象一律拒绝（schema 错误 → execution_failed）。
2. **锚点真实性核验**——每个 excerpt 必须与被评审正文的 [char_start, char_end)
   区间在规范化后全等；评审器伪造引文（paraphrase 冒充原文、越界偏移）即整批拒绝。
   这是 G5「无证据结论不能进入门禁」的落地：没有真实正文锚点的 claim 构造即失败。

T6 将扩展为三个上下文隔离角色（fact_judge / character_judge / reader_judge）；
本模块已按 ``role`` 参数化，T5 先以单角色（reader_judge）驱动，锚点核验通用。
"""

from __future__ import annotations

import json

from src.object_state.judge_claim import JudgeClaim, ProseAnchor
from src.object_state.evaluator_precommit import EvaluatorPrecommit
from src.workflow_action.json_repair import parse_json
from src.workflow_action.plan_search import compact_text
# 锚点重定位（位置映射）：评审模型在长正文上算 [char_start, char_end) 偏移经常偏差，
# 但引用必须逐字真实——与 G7 校准路径（preference_review._locate_excerpt）同一套折叠
# 检索语义，保证生产评审与校准评审对「锚点真实性」口径一致（无依赖环：preference_review
# 不反向导入本模块）。
from src.workflow_action.preference_review import _locate_excerpt

# 软质量轴（design §7：推进 / 人物 / 契约 / 阅读摩擦 / 语言辨识度 / 建设性歧义）。
SOFT_AXES = (
    "progression",
    "character_fidelity",
    "contract_fulfillment",
    "friction",
    "language_distinctiveness",
    "constructive_ambiguity",
)
# 评审可声明的硬轴（blocking 违例 → 候选淘汰，软分数不能抵消）。
HARD_AXES = (
    "fact_conflict",
    "contract_drift",
    "character_contradiction",
    "plotunit_expected_change",
    "state_necessity",
)
ROLE_AXES = {
    "fact_judge": {"fact_conflict"},
    "character_judge": {"character_fidelity", "character_contradiction"},
    "reader_judge": set(SOFT_AXES) | {"contract_drift"},
}


def _derive_anchor_position(char_start: int, prose_len: int) -> str:
    """按锚点**核验后**的真实起始位置推导描述性标签（start/middle/end）。

    评审模型自报的 position（core/mid/primary/…）在长正文上不可靠，且该标签
    不参与任何门禁逻辑（仅描述锚点在正文中的大致位置）——故由系统从核验后的
    真实偏移确定性推导，而不是信任模型值。证据强度完全由 excerpt + char 区间
    的真实性核验承担，标签不降低任何标准。
    """
    if prose_len <= 0:
        return "middle"
    third = prose_len // 3
    if char_start < third:
        return "start"
    if char_start < third * 2:
        return "middle"
    return "end"


def build_judge_claim_prompt(
    precommit: EvaluatorPrecommit,
    prose: str,
    reader_contract_context: str = "",
    role: str = "reader_judge",
) -> str:
    """评审 prompt：单轴、必带正文锚点（评审上下文与生成器隔离）.

    评审能看到的：本章完整正文、该候选的预承诺预期值（正文前冻结）、ReaderContract。
    评审不能看到：生成 prompt、其他候选正文、生成参数、holdout/对抗夹具。
    """
    role_lines = {
        "fact_judge": "你负责【事实】轴：正文与可信事实是否冲突、确定性与文学歧义是否分离。",
        "character_judge": "你负责【人物】轴：角色行为是否符合其驱动力/恐惧/缺陷，是否可交换。",
        "reader_judge": "你负责【读者体验】轴：推进/阅读摩擦/契约/语言辨识度/建设性歧义。",
    }
    axis_guide = role_lines.get(role, role_lines["reader_judge"])
    allowed_axes = sorted(ROLE_AXES.get(role, ROLE_AXES["reader_judge"]))
    contract_section = (
        f"\n【读者契约】\n{reader_contract_context}" if reader_contract_context else ""
    )
    return f"""你是一位章节评审。请对给定章节正文作出**单轴**判断，每条判断必须引用**正文原文锚点**。

{axis_guide}

【候选预承诺（评审正文前已冻结，不可修改）】
- 预承诺ID: {precommit.precommit_id}
- 候选 PlotUnit: {precommit.plotunit_id}
- 输入状态: {precommit.input_state_id} → 输出状态: {precommit.output_state_id}
- 预期输出地点: {precommit.expected_output_location}
- 预期输出局势: {precommit.expected_output_situation}
- 预期释放信息: {'；'.join(precommit.expected_released_information) or '（无）'}
- 预期后果: {'；'.join(precommit.expected_consequences) or '（无）'}
- 关键单元（须有正文证据）: {'是' if precommit.effective else '否'}
- 本预承诺将执行的证伪检查: {'；'.join(precommit.check_list)}{contract_section}

【待评审章节正文】
{prose}

【评审要求】
1. axis 只能取：{' / '.join(allowed_axes)}。必须至少输出一条 claim；没有发现违例时，
   对最有把握的允许轴输出 satisfied，不得返回空 claims 或自造轴名。
2. 每条 claim 必须带 ≥1 个**正文锚点**：直接引用本章正文中的连续原文片段，给出
   它在正文中的 [char_start, char_end) 偏移（0 起始，excerpt 必须与正文该区间逐字一致）。
3. 结论必须是单轴（axis 只能填一个轴）；verdict = satisfied / violated / inconclusive。
4. severity 只填 blocking（硬违例：与可信事实/契约/角色驱动力直接矛盾，或关键单元
   缺正文证据）或 advisory（软质量问题）。不确定时给 advisory + inconclusive。
5. 禁止捏造锚点、禁止引用正文之外的文本。

【输出格式】严格 JSON：
{{
  "claims": [
    {{
      "claim_id": "cl_001",
      "precommit_id": "{precommit.precommit_id}",
      "axis": "progression",
      "verdict": "satisfied",
      "severity": "advisory",
      "anchors": [
        {{"position": "start", "excerpt": "…正文连续原文…", "char_start": 0, "char_end": 40}}
      ],
      "rationale": "…依据…"
    }}
  ]
}}

注意：anchors 不含 chapter_ref（系统注入）；excerpt 必须与正文 [char_start, char_end)
逐字一致（去空白比较）。claims 不得为空数组。
"""


def parse_judge_claims(
    response: str,
    *,
    prose: str,
    chapter_ref: str,
    role: str,
    precommit: EvaluatorPrecommit,
    require_role_axis: bool = False,
) -> list[JudgeClaim]:
    """严格解析评审响应，核验锚点真实性与预承诺归属.

    Raises:
        ValueError: 形状违例 / 锚点越界 / excerpt 与正文区间不一致 / precommit 不匹配
            / 非唯一 claims 键 / 多余字段 —— 由 runner 记为 schema/证据错误 →
            execution_failed（不重试、不吞异常）。
    """
    data = parse_json(response)
    if not isinstance(data, dict) or set(data) != {"claims"}:
        raise ValueError("judge response must be a JSON object with only 'claims'")
    claims = data["claims"]
    if not isinstance(claims, list):
        raise ValueError("judge response 'claims' must be a list")
    allowed_axes = ROLE_AXES.get(role)
    if require_role_axis and not claims:
        raise ValueError(f"{role} must return at least one registered-axis claim")
    parsed: list[JudgeClaim] = []
    for index, item in enumerate(claims):
        if not isinstance(item, dict):
            raise ValueError(f"judge claim {index} must be a JSON object")
        required = {
            "claim_id",
            "precommit_id",
            "axis",
            "verdict",
            "severity",
            "anchors",
            "rationale",
        }
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required)
        if missing or extra:
            raise ValueError(
                f"judge claim {index} missing field(s) {missing} and/or extra field(s) {extra}"
            )
        if item["precommit_id"] != precommit.precommit_id:
            raise ValueError(
                f"judge claim {index} references wrong precommit {item['precommit_id']}"
            )
        if require_role_axis and (
            allowed_axes is None or item["axis"] not in allowed_axes
        ):
            raise ValueError(
                f"judge claim {index} axis {item['axis']!r} is not allowed for {role}"
            )
        if not isinstance(item["anchors"], list) or not item["anchors"]:
            raise ValueError(f"judge claim {index} anchors must be a non-empty list")
        anchors: list[ProseAnchor] = []
        for anchor_index, anchor in enumerate(item["anchors"]):
            if not isinstance(anchor, dict):
                raise ValueError(
                    f"judge claim {index} anchor {anchor_index} must be a JSON object"
                )
            anchor_required = {"position", "excerpt", "char_start", "char_end"}
            if set(anchor) != anchor_required:
                raise ValueError(
                    f"judge claim {index} anchor {anchor_index} must have exactly "
                    f"{sorted(anchor_required)}"
                )
            char_start = anchor["char_start"]
            char_end = anchor["char_end"]
            excerpt = anchor["excerpt"]
            if not isinstance(excerpt, str) or not excerpt.strip():
                raise ValueError(f"judge claim {index} anchor {anchor_index} excerpt must be non-empty")
            if not isinstance(char_start, int) or not isinstance(char_end, int):
                raise ValueError(
                    f"judge claim {index} anchor {anchor_index} char_start/char_end must be integers"
                )
            # 锚点真实性核验：excerpt 必须逐字来自被评审正文。
            # 快速路径：模型声称偏移的区间在规范化后与 excerpt 全等 → 直接用。
            # 兜底路径：模型算偏移偏差（长正文常见）且区间不匹配或越界（char_end
            # 超出正文长度）——在正文内检索 excerpt（折叠空白/标点/引号字形差异），
            # 命中则把锚点重映射到真实偏移；检索不到才是伪造（paraphrase 冒充原文
            # / 越界引用），整批拒绝。与 G7 校准路径 preference_review 的锚点口径一致。
            if not (
                char_start >= 0
                and char_start < char_end
                and char_end <= len(prose)
                and compact_text(prose[char_start:char_end]) == compact_text(excerpt)
            ):
                located = _locate_excerpt(prose, excerpt)
                if located is None:
                    raise ValueError(
                        f"judge claim {index} anchor {anchor_index} excerpt not found "
                        f"in prose — fabricated anchor"
                    )
                char_start, char_end = located
            anchors.append(
                ProseAnchor(
                    chapter_ref=chapter_ref,
                    position=_derive_anchor_position(char_start, len(prose)),
                    excerpt=prose[char_start:char_end],
                    char_start=char_start,
                    char_end=char_end,
                )
            )
        parsed.append(
            JudgeClaim(
                claim_id=item["claim_id"],
                precommit_id=precommit.precommit_id,
                axis=item["axis"],
                verdict=item["verdict"],
                severity=item["severity"],
                anchors=tuple(anchors),
                rationale=item["rationale"],
                generator_source=role,  # 由运行层按评审角色注入，评审无法自报身份
            )
        )
    return parsed
