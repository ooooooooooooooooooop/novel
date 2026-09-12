"""Rebuild boundary conformance — model-emitted list[str] for canonical
Optional[str] WorldModel fields normalizes explicitly; enum violations and
non-string list elements remain explicit rejections (no silent coercion)."""
import json

import pytest

from src.workflow_action.rebuild import RebuildUnit


def _minimal_response(worldmodel=None, fact_type="event"):
    return json.dumps(
        {
            "workspec": {
                "genre": "都市",
                "audience": "成人",
                "theme": "抉择",
                "tone": "克制",
                "pacing": "中速",
            },
            "worldmodel": worldmodel
            or {"world_facts": [], "factions": [], "time_rules": []},
            "charactermodels": [
                {
                    "character_id": "char_a",
                    "name": "甲某",
                    "identity": "公司董事",
                    "outer_goal": "扩张",
                    "inner_need": "证明自己",
                    "fear": "失败",
                    "flaw": "多疑",
                    "strength": "判断力",
                    "stance": "进取",
                }
            ],
            "narrativestate": {
                "state_id": "s1",
                "current_time": "某年春",
                "current_location": "某市",
                "current_situation": "长谈之后",
            },
            "factledger": {
                "entries": [
                    {
                        "fact_id": "f1",
                        "statement": "甲某提出参股条件",
                        "fact_type": fact_type,
                    }
                ]
            },
            "foreshadowgraph": {
                "entries": [
                    {
                        "thread_id": "t1",
                        "setup_point": "ch1",
                        "content": "对手角色现身",
                        "visibility_level": "explicit",
                        "expected_payoff": "对手登场",
                    }
                ]
            },
            "confidence_gaps": ["某配角职务未知"],
        },
        ensure_ascii=False,
    )


def test_worldmodel_scalar_list_normalizes_to_str():
    resp = _minimal_response(
        worldmodel={
            "geography": ["甲市：洪灾发生地", "乙岛：主要发展区域"],
            "power_system": "常规现代背景",
        }
    )
    objects, _gaps = RebuildUnit().parse_response(resp)
    wm = next(o for o in objects if type(o).__name__ == "WorldModel")
    assert wm.geography == "甲市：洪灾发生地; 乙岛：主要发展区域"
    assert wm.power_system == "常规现代背景"


def test_worldmodel_scalar_list_non_str_items_rejected():
    resp = _minimal_response(
        worldmodel={"geography": [{"name": "甲市"}], "factions": []}
    )
    with pytest.raises(Exception, match="must all be strings"):
        RebuildUnit().parse_response(resp)


def test_fact_type_out_of_enum_is_explicit_reject():
    resp = _minimal_response(fact_type="fact")
    with pytest.raises(Exception):
        RebuildUnit().parse_response(resp)


def test_minimal_response_parses_cleanly():
    objects, gaps = RebuildUnit().parse_response(_minimal_response())
    assert len(objects) == 6
    assert gaps == ["某配角职务未知"]
