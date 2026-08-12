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
from src.workflow_action.plan_search import compact_text

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
1. 只对你有把握的轴给出判断；没有证据的轴**不要**输出 claim（宁缺毋滥）。
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
逐字一致（去空白比较）。claims 可为空数组。
"""


def parse_judge_claims(
    response: str,
    *,
    prose: str,
    chapter_ref: str,
    role: str,
    precommit: EvaluatorPrecommit,
) -> list[JudgeClaim]:
    """严格解析评审响应，核验锚点真实性与预承诺归属.

    Raises:
        ValueError: 形状违例 / 锚点越界 / excerpt 与正文区间不一致 / precommit 不匹配
            / 非唯一 claims 键 / 多余字段 —— 由 runner 记为 schema/证据错误 →
            execution_failed（不重试、不吞异常）。
    """
    data = json.loads(response)
    if not isinstance(data, dict) or set(data) != {"claims"}:
        raise ValueError("judge response must be a JSON object with only 'claims'")
    claims = data["claims"]
    if not isinstance(claims, list):
        raise ValueError("judge response 'claims' must be a list")
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
            if (
                not isinstance(char_start, int)
                or not isinstance(char_end, int)
                or char_start < 0
                or char_start >= char_end
                or char_end > len(prose)
            ):
                raise ValueError(
                    f"judge claim {index} anchor {anchor_index} has invalid char bounds"
                )
            # 锚点真实性核验：excerpt 必须与正文该区间规范化后逐字全等。
            if compact_text(prose[char_start:char_end]) != compact_text(excerpt):
                raise ValueError(
                    f"judge claim {index} anchor {anchor_index} excerpt does not match prose "
                    f"at [{char_start},{char_end}) — fabricated anchor"
                )
            anchors.append(
                ProseAnchor(
                    chapter_ref=chapter_ref,
                    position=anchor["position"],
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
