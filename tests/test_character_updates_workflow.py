"""CharacterUpdate 写回工作流 tests — 作者性 Phase A Task 2.

覆盖：
- apply_update_to_character：pressure/trajectory 追加去重、fear/goal/self_image
  替换记 before、relation 仅记录
- admit_character_updates：validate 硬失败（非 list/非 dict/未知键/未知角色）、
  trigger 自动填充、apply=False 纯记录不污染角色
- sidecar 台账 load/append 落盘
- build_character_update_prompt：含角色与 PlotUnit 上下文，五态说明在场
- parse_character_updates_response：严格键校验
- 零成本契约：空角色列表仍生成合法 prompt；台账缺省空结构
"""

import json
import subprocess
import sys

import pytest

from src.object_state import CharacterModel, NarrativeState, PlotUnit
from src.object_state.characterupdate import CharacterUpdate
from src.workflow_action.character_updates import (
    CHARACTER_UPDATES_LEDGER,
    admit_character_updates,
    append_character_updates,
    apply_update_to_character,
    build_character_update_prompt,
    load_character_updates,
    parse_character_updates_response,
)


def _mk_character(**overrides) -> CharacterModel:
    base = dict(
        character_id="c1",
        name="沈望",
        identity="被逐出宗门的少女",
        outer_goal="为师父洗刷冤屈",
        inner_need="被认可",
        fear="重蹈被逐的覆辙",
        flaw="不肯求助",
        strength="韧性",
        stance="中立",
    )
    base.update(overrides)
    return CharacterModel(**base)


def _mk_plotunit() -> PlotUnit:
    return PlotUnit(
        unit_id="pu_001",
        level="scene",
        goal="改写规则救沈望",
        conflict="改写暴露风险",
        input_state_ref="ns_in",
        output_state_ref="ns_out",
        is_effective=True,
    )


def _mk_state() -> NarrativeState:
    return NarrativeState(
        state_id="ns_out",
        current_time="故事起始",
        current_location="观碑台",
        current_situation="改写生效",
        active_characters=["c1"],
        primary_goal="救沈望",
    )


def _mk_update(**overrides) -> dict:
    base = dict(
        character_id="c1",
        trigger="pu_001",  # admit 时会用 source_plotunit 覆盖
        observed_consequence="处决文书被改写",
        affected_dimension="pressure",
        update_type="shift",
        proposed_after="处决期限成为当前压力",
    )
    base.update(overrides)
    return base


# ---- apply_update_to_character ----


def test_apply_pressure_appends_dedupe():
    c = _mk_character(current_pressure=["家族施压"])
    u = CharacterUpdate(**_mk_update(proposed_after="处决期限成为当前压力"))
    before = apply_update_to_character(c, u)
    assert before == "家族施压"
    assert c.current_pressure == ["家族施压", "处决期限成为当前压力"]
    assert u.before == "家族施压"


def test_apply_pressure_dedupes_existing():
    c = _mk_character(current_pressure=["处决期限成为当前压力"])
    u = CharacterUpdate(**_mk_update(proposed_after="处决期限成为当前压力"))
    before = apply_update_to_character(c, u)
    assert c.current_pressure == ["处决期限成为当前压力"]
    assert before == "处决期限成为当前压力"


def test_apply_trajectory_appends():
    c = _mk_character(change_trajectory=["从独行到愿意托付"])
    u = CharacterUpdate(
        **_mk_update(
            affected_dimension="trajectory",
            proposed_after="从不敢反抗到处决前孤注一掷",
        )
    )
    before = apply_update_to_character(c, u)
    assert before == "从独行到愿意托付"
    assert c.change_trajectory == ["从独行到愿意托付", "从不敢反抗到处决前孤注一掷"]


def test_apply_replace_records_before():
    c = _mk_character(fear="重蹈被逐的覆辙")
    u = CharacterUpdate(
        **_mk_update(
            affected_dimension="fear",
            proposed_after="改写真相对方识破",
        )
    )
    before = apply_update_to_character(c, u)
    assert before == "重蹈被逐的覆辙"
    assert c.fear == "改写真相对方识破"


def test_apply_goal_and_self_image_replace():
    c = _mk_character(outer_goal="为师父洗刷冤屈", self_image="必须独自承担")
    g = CharacterUpdate(
        **_mk_update(affected_dimension="goal", proposed_after="先保全自己再图复仇")
    )
    s = CharacterUpdate(
        **_mk_update(affected_dimension="self_image", proposed_after="可以有限度求助")
    )
    assert apply_update_to_character(c, g) == "为师父洗刷冤屈"
    assert apply_update_to_character(c, s) == "必须独自承担"
    assert c.outer_goal == "先保全自己再图复仇"
    assert c.self_image == "可以有限度求助"


def test_apply_relation_record_only():
    c = _mk_character()
    u = CharacterUpdate(
        **_mk_update(affected_dimension="relation", proposed_after="对盟友开始信任")
    )
    before = apply_update_to_character(c, u)
    assert before is None
    assert u.before is None
    # 仅记录维度不改任何角色字段
    assert c.relations == {}


# ---- admit_character_updates ----


def test_admit_fills_trigger_and_dumps():
    chars = [_mk_character()]
    admitted = admit_character_updates(chars, [_mk_update()], "pu_001", apply=False)
    assert len(admitted) == 1
    assert admitted[0]["trigger"] == "pu_001"
    assert admitted[0]["character_id"] == "c1"
    assert admitted[0]["status"] == "proposed"  # 默认安全
    # 未 apply：角色动态字段不被污染
    assert chars[0].current_pressure == []


def test_admit_apply_mutates_character():
    chars = [_mk_character()]
    admitted = admit_character_updates(chars, [_mk_update()], "pu_001", apply=True)
    assert admitted[0]["before"] is None  # pressure 空 → before None
    assert chars[0].current_pressure == ["处决期限成为当前压力"]


def test_admit_requires_list():
    with pytest.raises(ValueError):
        admit_character_updates([_mk_character()], "not-a-list", "pu_001")


def test_admit_requires_dict_entries():
    with pytest.raises(ValueError):
        admit_character_updates([_mk_character()], ["nope"], "pu_001")


def test_admit_rejects_unknown_key():
    bad = _mk_update(unknown_field="x")
    with pytest.raises(ValueError):
        admit_character_updates([_mk_character()], [bad], "pu_001")


def test_admit_rejects_unknown_character():
    bad = _mk_update(character_id="ghost")
    with pytest.raises(ValueError):
        admit_character_updates([_mk_character()], [bad], "pu_001")


def test_admit_empty_list_noop():
    chars = [_mk_character()]
    admitted = admit_character_updates(chars, [], "pu_001", apply=True)
    assert admitted == []
    assert chars[0].current_pressure == []


# ---- sidecar ledger ----


def test_ledger_default_empty(tmp_path):
    ledger = load_character_updates(tmp_path)
    assert ledger == {"schema_version": 1, "updates": []}


def test_append_ledger_persists(tmp_path):
    chars = [_mk_character()]
    admitted = admit_character_updates(chars, [_mk_update()], "pu_001", apply=True)
    path = append_character_updates(tmp_path, admitted)
    assert path.name == CHARACTER_UPDATES_LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert len(ledger["updates"]) == 1
    assert ledger["updates"][0]["trigger"] == "pu_001"


def test_append_accumulates(tmp_path):
    chars = [_mk_character()]
    a = admit_character_updates(chars, [_mk_update()], "pu_001", apply=True)
    b = admit_character_updates(chars, [_mk_update()], "pu_002", apply=True)
    append_character_updates(tmp_path, a)
    append_character_updates(tmp_path, b)
    ledger = load_character_updates(tmp_path)
    assert [u["trigger"] for u in ledger["updates"]] == ["pu_001", "pu_002"]


# ---- prompt / parse ----


def test_prompt_contains_context_and_five_states():
    chars = [_mk_character()]
    prompt = build_character_update_prompt(chars, _mk_plotunit(), _mk_state())
    assert "【任务：角色变更提案】" in prompt
    assert "character_id" in prompt
    assert "reinforce" in prompt
    assert "misinterpret" in prompt
    assert "不是每个事件都必须改变人物" in prompt
    assert "【角色: 沈望】" in prompt
    assert "【PlotUnit: pu_001" in prompt


def test_prompt_empty_characters_still_valid():
    prompt = build_character_update_prompt([], _mk_plotunit(), _mk_state())
    assert "======== 角色 ========" in prompt


def test_parse_ok():
    response = json.dumps({"character_updates": [_mk_update()]})
    updates = parse_character_updates_response(response)
    assert updates == [_mk_update()]


def test_parse_empty_ok():
    updates = parse_character_updates_response('{"character_updates": []}')
    assert updates == []


def test_parse_rejects_top_level_extra():
    with pytest.raises(ValueError):
        parse_character_updates_response('{"character_updates": [], "x": 1}')


def test_parse_rejects_missing_key():
    with pytest.raises(ValueError):
        parse_character_updates_response("{}")


def test_parse_rejects_non_list():
    with pytest.raises(ValueError):
        parse_character_updates_response('{"character_updates": "nope"}')


def test_parse_rejects_non_dict_entries():
    with pytest.raises(ValueError):
        parse_character_updates_response('{"character_updates": [1, 2]}')


def test_parse_rejects_non_object():
    with pytest.raises(ValueError):
        parse_character_updates_response("[1, 2]")


# ---- CLI 合约：--character-update 默认 off（零成本） ----


def _build_parser():
    from src.novel_cli import build_parser

    return build_parser(emit_json_errors=False)


def test_cli_parser_defaults_off():
    """extend / compose 的 --character-update 默认 off（零成本契约）."""
    parser = _build_parser()
    ext = parser.parse_args(["extend", "x"])
    comp = parser.parse_args(["compose", "x"])
    assert ext.character_update == "off"
    assert comp.character_update == "off"


def test_cli_parser_accepts_on():
    parser = _build_parser()
    ext = parser.parse_args(["extend", "x", "--character-update", "on"])
    comp = parser.parse_args(["compose", "x", "--character-update", "on"])
    assert ext.character_update == "on"
    assert comp.character_update == "on"


def test_short_form_help_exposes_flag():
    """两个短表单入口都暴露 --character-update（argparse 接受）."""
    for script in ("src/compose_short_form.py", "src/extend_short_form.py"):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, script
        assert "--character-update" in result.stdout, script

