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
                    "character_id": "zhang_ke",
                    "name": "张恪",
                    "identity": "锦湖商事董事",
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
                "current_time": "1998年春",
                "current_location": "金山",
                "current_situation": "叔侄长谈后",
            },
            "factledger": {
                "entries": [
                    {
                        "fact_id": "f1",
                        "statement": "张恪提出参股条件",
                        "fact_type": fact_type,
                    }
                ]
            },
            "foreshadowgraph": {
                "entries": [
                    {
                        "thread_id": "t1",
                        "setup_point": "ch1",
                        "content": "谢剑南现身金山",
                        "visibility_level": "explicit",
                        "expected_payoff": "对手登场",
                    }
                ]
            },
            "confidence_gaps": ["梁伟法职务未知"],
        },
        ensure_ascii=False,
    )


def test_worldmodel_scalar_list_normalizes_to_str():
    resp = _minimal_response(
        worldmodel={
            "geography": ["金山市：洪灾发生地", "东山岛：主要发展区域"],
            "power_system": "常规现代背景",
        }
    )
    objects, _gaps = RebuildUnit().parse_response(resp)
    wm = next(o for o in objects if type(o).__name__ == "WorldModel")
    assert wm.geography == "金山市：洪灾发生地; 东山岛：主要发展区域"
    assert wm.power_system == "常规现代背景"


def test_worldmodel_scalar_list_non_str_items_rejected():
    resp = _minimal_response(
        worldmodel={"geography": [{"name": "金山"}], "factions": []}
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
    assert gaps == ["梁伟法职务未知"]
