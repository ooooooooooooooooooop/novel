"""ReaderContract 构建/注入/合规检查（Q1 R3）.

- compose：从 WorkSpec 建立初始契约（确定性默认，操作者可通过 staged 编辑覆盖）；
- extend：从真实原文提取并由操作者批准（staged：写 prompt → 操作者填 response）；
- 注入：Continue/Prose prompt 的【读者契约】段（无契约零成本，字节不变）；
- 合规：candidate PlotUnit ↔ forbidden_drifts 的确定性子串检查。

契约侧车文件：`output/<mode>/reader_contract.json`（同 author_kernel /
choice_ledger 的 sidecar 模式，不进 serialization.py 状态机层）。
"""

import json
from pathlib import Path
from typing import Optional

from src.object_state.readercontract import ReaderContract
from src.object_state.reviewissue import ReviewIssue

CONTRACT_FILENAME = "reader_contract.json"


def build_initial_contract(
    *,
    contract_id: str = "default",
    workspec=None,
    audience: str = "",
    theme: str = "",
    tone: str = "",
    genre: str = "",
    pacing: str = "",
) -> ReaderContract:
    """从 WorkSpec（compose）或显式参数建立初始读者契约.

    只做确定性默认；`novel contract` staged 流程让操作者在此基础上批准/改写。
    契约永不包含作品名/作者名等隐私信息。
    """
    workspec_audience = getattr(workspec, "audience", "") or ""
    workspec_theme = getattr(workspec, "theme", "") or ""
    workspec_tone = getattr(workspec, "tone", "") or ""
    workspec_genre = getattr(workspec, "genre", "") or ""
    workspec_pacing = getattr(workspec, "pacing", "") or ""
    eff_audience = audience or workspec_audience or "大众网文读者"
    eff_theme = theme or workspec_theme or "核心矛盾"
    eff_tone = tone or workspec_tone or ""
    eff_genre = genre or workspec_genre or ""
    eff_pacing = pacing or workspec_pacing or "短弧推进"

    pleasures = [f"围绕「{eff_theme}」的张力推进", "每章产生可感知的新状态变化"]
    if eff_genre:
        pleasures.insert(1, f"{eff_genre}题材的类型期待（悬念/爽点/情感）")

    core_tension = f"「{eff_theme}」驱动下的持续对抗与未兑现选择"
    follow_reason = f"主角在「{eff_theme}」压力下做出代价明确的选择，读者想看他如何承担"
    pacing_line = f"每章推进{eff_pacing}一个量级的事件，章末留下可等待的具体问题"

    opening_promise = (
        "首章主角必须做出一个定义人物的主动选择，该选择立即产生可见代价；"
        "至少一个细节具备本作独特性；不能主要用于解释设定"
    )

    return ReaderContract(
        contract_id=contract_id,
        audience=eff_audience,
        core_pleasures=pleasures,
        follow_reason=follow_reason,
        core_tension=core_tension,
        chapter_pacing=pacing_line,
        must_keep=[],
        forbidden_drifts=[],
        valid_hooks=["cliffhanger", "reveal", "promise", "emotional_peak"],
        ending_conditions=[],
        opening_minimum_promise=opening_promise,
    )


def load_reader_contract(output_dir: Path) -> Optional[ReaderContract]:
    """读侧车契约；无文件/损坏返回 None（零成本：不注入、不检查）。"""
    path = output_dir / CONTRACT_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReaderContract(**data)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_reader_contract(output_dir: Path, contract: ReaderContract) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / CONTRACT_FILENAME
    path.write_text(
        json.dumps(contract.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def contract_violations(plotunit, contract: ReaderContract) -> list[str]:
    """candidate PlotUnit ↔ forbidden_drifts 的确定性检查.

    把禁例短语在 plotunit.goal / conflict / 场景体验选择依据 中做子串命中。
    命中即 violation（禁止漂移）。无 contract → []（零成本）。
    """
    if contract is None or not contract.forbidden_drifts:
        return []
    haystack = " / ".join(
        [
            plotunit.goal or "",
            plotunit.conflict or "",
        ]
    )
    se = getattr(plotunit, "scene_experience", None)
    if se is not None:
        haystack += " / " + (getattr(se, "choice_grounding", "") or "")
    return [drift for drift in contract.forbidden_drifts if drift and drift in haystack]


def evaluate_opening_compliance(plotunit, contract: ReaderContract) -> dict:
    """新开首章的最小承诺合规评估（确定性部分）.

    返回：
    - has_choice: 主角是否作出定义性选择（scene_experience.choice_grounding 非空）
    - has_cost: 选择是否有可见代价（scene_experience.outcome 非空，或 PlotUnit consequences 非空）
    - has_follow_alignment: 目标与契约核心张力是否有可观察关联（保守：主题词命中）
    - q1_ready: 三项是否全部满足
    独特跟随理由是质性判断，归操作者/LLM 复核，不在此硬断。
    """
    se = getattr(plotunit, "scene_experience", None)
    choice = ""
    outcome = ""
    if se is not None:
        choice = getattr(se, "choice_grounding", "") or ""
        outcome = getattr(se, "outcome", "") or ""
    has_choice = bool(choice.strip())
    has_cost = bool(outcome.strip()) or bool(getattr(plotunit, "consequences", None))
    # 保守对齐：契约核心张力主题词在目标/冲突中出现
    theme_tokens = [
        tok for tok in (contract.core_tension or "").replace("「", "").replace("」", "").split("的")
        if len(tok.strip()) >= 2
    ]
    hay = (plotunit.goal or "") + (plotunit.conflict or "")
    has_follow_alignment = any(tok in hay for tok in theme_tokens[:3])
    return {
        "has_choice": has_choice,
        "has_cost": has_cost,
        "has_follow_alignment": has_follow_alignment,
        "q1_ready": has_choice and has_cost and has_follow_alignment,
    }


def scene_experience_guard_issues(plotunit) -> list[str]:
    """v3 强制：产生主动选择的 PlotUnit 必须携带选择依据与可见后果（SceneExperience）.

    只约束「关键单元」：conflict 或 released_information 非空（即确实发生事件/选择）
    的有效单元。纯过渡/氛围单元不强制。返回 issue 描述列表，空=通过。
    """
    if plotunit is None or getattr(plotunit, "is_effective", True) is False:
        return []
    is_key_unit = bool(getattr(plotunit, "conflict", None)) or bool(
        getattr(plotunit, "released_information", None)
    )
    if not is_key_unit:
        return []
    se = getattr(plotunit, "scene_experience", None)
    if se is None:
        return [
            "PlotUnit 缺少 scene_experience：关键单元必须提供【选择依据/结果/认知变化】"
        ]
    issues = []
    if not (getattr(se, "choice_grounding", "") or "").strip():
        issues.append("scene_experience.choice_grounding（选择依据）不能为空")
    if not (getattr(se, "outcome", "") or "").strip():
        issues.append("scene_experience.outcome（结果/可见后果）不能为空")
    return issues


def scene_experience_guard_review_issues(plotunit) -> list[ReviewIssue]:
    """v3 Pre-Review 闸：把 scene_experience_guard_issues 的串行描述映射为 blocking ReviewIssue.

    缺失整体 → missing_consequence；缺选择依据 → motivation_gap；缺可见后果 →
    missing_consequence。blocking 级 -> 进入对象层 rewrite（Pre-Review 代码闸，零 LLM）。
    """
    descriptions = scene_experience_guard_issues(plotunit)
    issues: list[ReviewIssue] = []
    for desc in descriptions:
        if "缺少 scene_experience" in desc:
            itype, rule = "missing_consequence", "关键单元必须携带 SceneExperience（选择依据/结果/认知变化）"
        elif "choice_grounding" in desc:
            itype, rule = "motivation_gap", "选择必须有依据（scene_experience.choice_grounding）"
        else:
            itype, rule = "missing_consequence", "选择必须有可见后果（scene_experience.outcome）"
        issues.append(
            ReviewIssue(
                issue_id=f"iss_v3_se_{plotunit.unit_id}_{len(issues)}",
                issue_type=itype,
                severity="blocking",
                location=f"PlotUnit {plotunit.unit_id}",
                scope_of_impact="读者体验五维（选择依据/结果）",
                violated_rule=rule,
                description=desc,
            )
        )
    return issues


class ReaderContractUnit:
    """Staged 契约建立/编辑：写 prompt → 操作者填 response → 解析保存."""

    def build_prompt(
        self,
        *,
        mode: str,
        workspec_context: str = "",
        original_style_context: str = "",
        initial_contract: ReaderContract | None = None,
    ) -> str:
        draft_section = ""
        if initial_contract is not None:
            draft_section = f"\n【初始草稿（可由你修改）】\n{initial_contract.to_prompt_context()}\n"
        return f"""为一部{mode}作品建立【读者契约】——读者为什么选择这本书，而不是另一本书。

写成中性机制而非作者模仿（如：伤感必须被粗粝笑料和具体生活细节抵消；商业主角必须通过
具体判断和行动展现聪明；「代价」必须由人物选择触发，不能只作为设定说明）。禁止包含
作品名、作者笔名、机器路径等隐私信息。

{draft_section}
【作品约束】
{workspec_context}

【输出格式】严格输出 JSON（只输出 JSON）：
{{
  "contract_id": "作名代号",
  "audience": "目标读者",
  "core_pleasures": ["快感1", "快感2", "快感3"],
  "follow_reason": "主角值得持续跟随的理由",
  "core_tension": "作品核心张力",
  "chapter_pacing": "合理章节推进速度",
  "must_keep": ["必须保留的叙事声音/关系动力"],
  "forbidden_drifts": ["禁止出现的漂移1", "禁止出现的漂移2"],
  "valid_hooks": ["cliffhanger", "reveal", "promise", "emotional_peak"],
  "ending_conditions": ["哪些情形意味着故事应结束"],
  "opening_minimum_promise": "新开首章必须交付的最小承诺"
}}
"""

    def parse_response(self, response: str) -> ReaderContract:
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("ReaderContract response must be a JSON object")
        return ReaderContract(**data)
