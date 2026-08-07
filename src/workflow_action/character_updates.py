"""CharacterUpdate 写回工作流（作者性 Phase A：Task 2）.

定位：Continue 解析出 PlotUnit/new_state/new_facts 之后，新增一个可选的
【角色变更提案】阶段。把本 PlotUnit 的 consequence 翻译成受控的角色变更
提案（CharacterUpdate），默认只落 sidecar 记录；`--character-update on`
时才 apply 到 CharacterModel 的动态字段（current_pressure / change_trajectory /
fear / outer_goal / self_image / relations），记 before/after。

镜像 admit_new_facts（continuation.py:22）的写回形态：
- validate 原始 dict → CharacterUpdate(**data)（extra=forbid 拒绝未知键）
- admit 时自动填充 trigger=source_plotunit
- 未知 character_id → ValueError 硬失败（不静默吞）
- apply=False 时纯 sidecar 记录（零状态机污染，不进 stable serialization）

与 Continue parse_response 严格 4 字段 schema 分离——不往 Continue 响应里加键，
避免破坏既有回归。sidecar 产物 `output/character_updates.json` 与
`*_prompt.txt`/`*_response.txt` 平行，`discover_pending_slots` 会自动发现
`character_update_prompt.txt` 槽位（response_file.py 无文件名白名单）。
"""

import json
from pathlib import Path
from typing import Optional

from src.object_state import (
    CharacterModel,
    NarrativeState,
    PlotUnit,
)
from src.object_state.characterupdate import CharacterUpdate

CHARACTER_UPDATES_LEDGER = "character_updates.json"


def apply_update_to_character(
    character: CharacterModel,
    update: CharacterUpdate,
) -> Optional[str]:
    """把一条变更提案 apply 到角色动态字段，返回记录的 before（None=仅记录维度）.

    affected_dimension 决定落点：
    - pressure    : current_pressure 追加 proposed_after（去重）
    - trajectory  : change_trajectory 追加 proposed_after（去重）
    - fear        : 替换 character.fear（记 before）
    - goal        : 替换 character.outer_goal（记 before）
    - self_image  : 替换 character.self_image（记 before）
    - relation    : 仅记录（relations / relation_behaviors 不进本提案自动写——
                    关系变化依赖对方角色的上下文，属手写区，只落 sidecar）

    update.before 被就地填充，供 admit 后 model_dump 序列化。
    """
    before: Optional[str] = None
    dim = update.affected_dimension
    if dim == "pressure":
        before = (
            "; ".join(character.current_pressure) if character.current_pressure else None
        )
        if update.proposed_after not in character.current_pressure:
            character.current_pressure = character.current_pressure + [update.proposed_after]
    elif dim == "trajectory":
        before = (
            "; ".join(character.change_trajectory)
            if character.change_trajectory
            else None
        )
        if update.proposed_after not in character.change_trajectory:
            character.change_trajectory = character.change_trajectory + [update.proposed_after]
    elif dim == "fear":
        before = character.fear
        character.fear = update.proposed_after
    elif dim == "goal":
        before = character.outer_goal
        character.outer_goal = update.proposed_after
    elif dim == "self_image":
        before = character.self_image
        character.self_image = update.proposed_after
    elif dim == "relation":
        before = None  # record-only
    update.before = before
    return before


def admit_character_updates(
    characters: list[CharacterModel],
    updates: list[dict],
    source_plotunit: str,
    *,
    apply: bool = False,
) -> list[dict]:
    """Admit CharacterUpdate 提案：validate → 填充 trigger → 解析角色 → 可选 apply.

    Mirrors admit_new_facts 的校验强度：非 list / 非 dict 项 / 未知键 /
    未知 character_id 一律 ValueError 硬失败（不静默吞），保证 sidecar 数据
    可被 CharacterUpdate(**data) 原样重建。返回已接受提案的 JSON-safe list。
    """
    if not isinstance(updates, list):
        raise ValueError("updates must be a list")
    by_id = {c.character_id: c for c in characters}
    admitted: list[dict] = []
    for raw in updates:
        if not isinstance(raw, dict):
            raise ValueError("updates entries must be JSON objects")
        data = dict(raw)
        data["trigger"] = source_plotunit  # admit 时自动填充来源 unit_id
        update = CharacterUpdate(**data)  # extra=forbid 拒绝未知键
        character = by_id.get(update.character_id)
        if character is None:
            raise ValueError(
                f"unknown character_id in character update: {update.character_id}"
            )
        if apply:
            apply_update_to_character(character, update)
        admitted.append(update.model_dump(mode="json"))
    return admitted


def build_character_update_prompt(
    characters: list[CharacterModel],
    plotunit: PlotUnit,
    new_state: NarrativeState,
) -> str:
    """生成【角色变更提案】阶段 prompt（Continue 之后、Review 之前注入）.

    核心约束（纲领 §7 五种变化 / §47 禁项）：
    - 不是每个事件都必须改变人物——无变化输出空数组，是合法答案
    - unresolved 是合法状态（事情发生了，人物尚不知道含义），不是敷衍
    - 变化必须能被 PlotUnit 后果支撑，禁止『事件→必然成长』的流水线
    """
    lines = [
        "【任务：角色变更提案】",
        "",
        "阅读下面 PlotUnit 的后果（结果 / 后果 / 认知变化），判断哪些角色因此",
        "而受影响。每个受影响角色输出一条 CharacterUpdate 提案；无角色受影响的",
        "场景输出空数组 character_updates: []（不是每个事件都必须改变人物）。",
        "",
        "字段约束（严格遵循，额外键会被拒绝）：",
        "- character_id: 必须来自下方角色列表的 角色ID",
        "- observed_consequence: 实际发生了什么（一句话，来自 PlotUnit）",
        "- affected_dimension: fear|goal|relation|self_image|pressure|trajectory",
        "- update_type（五种，单选）:",
        "    reinforce   = 原有信念被加强（信任朋友后再遭利用 → 『不能信人』更强）",
        "    shift       = 方向性变化（只能靠自己 → 开始有限度托付）",
        "    destabilize = 信念动摇但无新答案",
        "    unresolved  = 事情发生了，人物目前不知道这意味着什么（合法！）",
        "    misinterpret= 人物得出错误结论（错误理解本身可成为后续发展）",
        "- proposed_after: 候选新状态（具体描述；unresolved 写『暂不改变』类的状态说明）",
        "- evidence: 支撑证据（可选）",
        "- permanence: transient|medium|long",
        "- confidence: 0-1",
        "",
        "不要输出 trigger/before/status 字段（系统自动填充）。",
        "输出为 JSON 对象：{\"character_updates\": [...]}",
        "",
        "======== PlotUnit ========",
        plotunit.to_prompt_context(),
        "",
        "======== 新状态 ========",
        new_state.to_prompt_context(),
        "",
        "======== 角色 ========",
    ]
    for c in characters:
        lines.append("")
        lines.append(c.to_prompt_context())
    return "\n".join(lines)


def parse_character_updates_response(response: str) -> list[dict]:
    """严格解析【角色变更提案】响应.

    顶层只允许 character_updates 一个键（extra=forbid 语义，防止混入其他字段）。
    条目类型/字段校验交给 CharacterUpdate(**entry)（admit 时执行）。
    """
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError("character update response must be a JSON object")
    extra = sorted(set(data) - {"character_updates"})
    if extra:
        raise ValueError(
            "character update response has unexpected field(s): "
            + ", ".join(extra)
        )
    if "character_updates" not in data:
        raise ValueError(
            "character update response missing required field: character_updates"
        )
    updates = data["character_updates"]
    if not isinstance(updates, list):
        raise ValueError(
            "character update response field character_updates must be a list"
        )
    if not all(isinstance(u, dict) for u in updates):
        raise ValueError("character_updates entries must be JSON objects")
    return updates


def load_character_updates(output_dir: Path) -> dict:
    """读 sidecar 台账（无则返回空台账）."""
    path = output_dir / CHARACTER_UPDATES_LEDGER
    if not path.exists():
        return {"schema_version": 1, "updates": []}
    return json.loads(path.read_text(encoding="utf-8"))


def append_character_updates(output_dir: Path, admitted: list[dict]) -> Path:
    """追加已接受提案到 sidecar 台账并落盘."""
    ledger = load_character_updates(output_dir)
    ledger["updates"].extend(admitted)
    path = output_dir / CHARACTER_UPDATES_LEDGER
    path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
