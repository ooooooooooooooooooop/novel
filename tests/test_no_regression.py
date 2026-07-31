"""Executable no-regression checks for the Track 1/2/3 locks.

These tests translate the minimum executable slice of
docs/00_project/21_no_regression_acceptance_test_list.md into pytest checks.
"""

import json

import pytest

from src.boundary_control.handoff import HandoffBoundaryUnit, HandoffPacket, NextRoute
from src.boundary_control.serialization import SerializationBoundaryUnit, SerializationPackage
from src.object_state import CharacterModel, FactLedger
from src.workflow_action.rebuild import RebuildUnit
from src.workflow_action.review import ReviewUnit


def _rebuild_objects() -> tuple[list, list[str]]:
    response = json.dumps(
        {
            "workspec": {
                "genre": "悬疑",
                "audience": "青年",
                "theme": "真相与代价",
                "tone": "克制",
                "pacing": "短弧推进",
            },
            "worldmodel": {
                "world_facts": ["潮纹契约会夺走记忆"],
                "prohibitions": ["无授权禁止进入第七层"],
            },
            "charactermodels": [
                {
                    "character_id": "c_shen",
                    "name": "沈青",
                    "identity": "承契者",
                    "outer_goal": "公开真账册",
                    "inner_need": "学习信任同盟",
                    "fear": "再次被制度夺走选择权",
                    "flaw": "习惯独自行动",
                    "strength": "能承受代价",
                    "stance": "合作",
                    "arc_stage": "从独行到共同承担",
                    "self_image": "可以与可信同盟共同承担代价",
                    "knowledge_state": ["白灯只能照见被契约吞走或扭曲的记忆"],
                    "misinformation": ["秦照仍能无代价恢复旧秩序"],
                    "relations": {"c_gu": "稳定互信的同盟"},
                },
                {
                    "character_id": "c_gu",
                    "name": "顾临渊",
                    "identity": "验契司执事",
                    "outer_goal": "公开被调换的证词",
                    "inner_need": "承担制度旧责",
                    "fear": "证词再次无效",
                    "flaw": "过度信任程序",
                    "strength": "熟悉验契规则",
                    "stance": "合作",
                    "knowledge_state": ["秦照调换过三年前证词"],
                    "relations": {"c_shen": "稳定互信的同盟"},
                },
            ],
            "narrativestate": {
                "state_id": "ns_final",
                "current_time": "冬潮退尽后的第一夜",
                "current_location": "潮钟塔第七层门外",
                "active_characters": ["c_shen", "c_gu"],
                "current_situation": "真账册公开，白灯已校准",
                "active_conflicts": ["旧城主残影仍可能有代理人"],
                "public_information": ["沈砚不是伪契者"],
                "hidden_information": ["代理人名单正文未知"],
            },
            "factledger": {
                "entries": [
                    {
                        "fact_id": "f_001",
                        "statement": "白灯被青铜鱼骨校准后不再主动诱导承契者",
                        "fact_type": "event",
                        "involved_entities": ["白灯"],
                        "confirmed": True,
                    }
                ]
            },
            "foreshadowgraph": {
                "entries": [
                    {
                        "thread_id": "th_agent",
                        "setup_point": "第七层门后的残影",
                        "content": "旧城主残影可能仍有代理人",
                        "visibility_level": "implicit",
                        "expected_payoff": "后续追查代理人名单",
                        "current_status": "active",
                    }
                ]
            },
            "confidence_gaps": ["代理人名单正文未知"],
        },
        ensure_ascii=False,
    )
    return RebuildUnit().parse_response(response)


def _only_object(objects: list, object_type: type):
    matches = [obj for obj in objects if isinstance(obj, object_type)]
    assert len(matches) == 1
    return matches[0]


class TestTrack1FactLedger:
    def test_hard_fact_not_degraded(self):
        objects, gaps = _rebuild_objects()
        ledger = _only_object(objects, FactLedger)

        assert ledger.entries
        assert gaps == ["代理人名单正文未知"]
        assert all(entry.confirmed is True for entry in ledger.entries)
        assert all("未知" not in entry.statement for entry in ledger.entries)

    def test_factledger_not_polluted_by_handoff(self):
        objects, gaps = _rebuild_objects()
        package = SerializationBoundaryUnit().build_package(*objects)
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
            input_anchor={"source_text": "mock_input.txt"},
            output_anchor={"state_ref": "ns_final"},
            change_set=[
                {
                    "action": "candidate_fact_delta",
                    "target_owner": "FactLedgerUnit",
                    "target_layer": "stable_memory",
                    "fact_id": "f_candidate",
                }
            ],
            open_items=[{"type": "confidence_gap", "content": gap} for gap in gaps],
            confidence_and_gaps={"gaps": gaps},
            next_route=NextRoute(
                recommended_workflow="ReviewUnit",
                route_reason="reconstruction complete",
            ),
        )

        assert "FactLedger" in package.stable_memory
        assert "FactLedger" not in package.working_set
        assert not SerializationBoundaryUnit().check_separation(package)
        assert packet.change_set[0]["target_owner"] == "FactLedgerUnit"
        assert packet.change_set[0]["target_layer"] == "stable_memory"
        assert "f_candidate" not in {
            entry["fact_id"]
            for ledger in package.stable_memory["FactLedger"]
            for entry in ledger["entries"]
        }


class TestTrack2Rewrite:
    def test_same_packet_local_repair(self):
        issues, reminders, route = ReviewUnit().parse_response(
            json.dumps(
                {
                    "issues": [
                        {
                            "issue_id": "iss_fact_sync",
                            "issue_type": "fact_conflict",
                            "severity": "blocking",
                            "location": "FactLedger",
                            "scope_of_impact": "后续续写依赖该事实",
                            "violated_rule": "same-packet writeback",
                            "description": "修复文本必须同步写回对象层",
                            "suggested_fix": "同包更新 FactLedger",
                            "supporting_facts": ["f_001"],
                        }
                    ],
                    "reminders": [],
                    "route": "rewrite",
                },
                ensure_ascii=False,
            )
        )
        repair_packet = {
            "source_issue": issues[0].issue_id,
            "local_scope": "same_packet",
            "writeback_complete": True,
            "object_writes": [
                {
                    "target_owner": "FactLedgerUnit",
                    "target_layer": "stable_memory",
                    "object_id": "f_001",
                }
            ],
        }

        assert route == "rewrite"
        assert reminders == []
        assert issues[0].is_blocking()
        assert repair_packet["source_issue"] == "iss_fact_sync"
        assert repair_packet["local_scope"] == "same_packet"
        assert repair_packet["writeback_complete"] is True
        assert repair_packet["object_writes"][0]["target_owner"] == "FactLedgerUnit"

    def test_no_cross_handoff_rewrite(self):
        issues, _, route = ReviewUnit().parse_response(
            json.dumps(
                {
                    "issues": [
                        {
                            "issue_id": "iss_rewrite_boundary",
                            "issue_type": "weak_progression",
                            "severity": "warning",
                            "location": "PlotUnit",
                            "scope_of_impact": "当前同包推进",
                            "violated_rule": "bounded runtime-first rewrite",
                            "description": "修复只能作为本地例外，不能靠 handoff prose 推进",
                        }
                    ],
                    "reminders": [],
                    "route": "rewrite",
                },
                ensure_ascii=False,
            )
        )
        packet = HandoffPacket(
            handoff_header={"source": "ReviewUnit", "target": "RewriteUnit"},
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_repair"},
            change_set=[
                {
                    "action": "repair",
                    "target_owner": "PlotUnitUnit",
                    "target_layer": "working_set",
                    "source_issue": issues[0].issue_id,
                }
            ],
            open_items=[
                {
                    "type": "blocked_cross_handoff_rewrite",
                    "content": "handoff prose is not object-layer writeback",
                }
            ],
            confidence_and_gaps={},
            next_route=NextRoute(
                recommended_workflow="RewriteUnit",
                route_reason="formal rewrite required",
                review_route=route,
            ),
        )

        assert packet.next_route.review_route == "rewrite"
        assert packet.next_route.recommended_workflow == "RewriteUnit"
        assert packet.change_set[0]["source_issue"] == "iss_rewrite_boundary"
        assert packet.change_set[0]["target_owner"] == "PlotUnitUnit"
        assert packet.change_set[0]["target_layer"] == "working_set"
        assert packet.open_items[0]["type"] == "blocked_cross_handoff_rewrite"

    def test_string_next_route_is_rejected(self):
        with pytest.raises(ValueError, match="next_route"):
            HandoffPacket(
                handoff_header={"source": "RebuildUnit", "target": "ReviewUnit"},
                input_anchor={"source_text": "mock_input.txt"},
                output_anchor={"state_ref": "ns_final"},
                next_route="ReviewUnit",
            )

    def test_handoff_target_must_match_next_route(self):
        packet = HandoffPacket(
            handoff_header={"source": "ReviewUnit", "target": "ContinueUnit"},
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_review"},
            next_route=NextRoute(
                recommended_workflow="RewriteUnit",
                route_reason="formal rewrite required",
                review_route="rewrite",
            ),
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any("target must match" in violation for violation in violations)

    def test_handoff_reason_must_match_next_route_reason(self):
        packet = HandoffPacket(
            handoff_header={
                "source": "ReviewUnit",
                "target": "ContinueUnit",
                "reason": "header reason",
            },
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_review"},
            next_route=NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="route reason",
                review_route="pass",
            ),
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any("reason must match" in violation for violation in violations)

    def test_handoff_builder_keeps_header_reason_and_route_reason_consistent(self):
        packet = HandoffBoundaryUnit().build_review_route(
            review_target_ref="review_result.json",
            route="pass",
            issues=[],
            reminders=[],
            output_state_ref="ns_final",
            route_reason="review_passed",
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert ok
        assert violations == []
        assert packet.handoff_header["reason"] == packet.next_route.route_reason

    @pytest.mark.parametrize(
        ("review_route", "recommended_workflow"),
        [
            ("rewrite", "ContinueUnit"),
            ("pass", "RewriteUnit"),
            ("block", "ContinueUnit"),
        ],
    )
    def test_review_route_must_match_workflow(
        self, review_route, recommended_workflow
    ):
        packet = HandoffPacket(
            handoff_header={"source": "ReviewUnit", "target": recommended_workflow},
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_review"},
            next_route=NextRoute(
                recommended_workflow=recommended_workflow,
                route_reason="route contract regression",
                review_route=review_route,
            ),
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any("review_route" in violation for violation in violations)

    def test_review_route_requires_reviewunit_source(self):
        packet = HandoffPacket(
            handoff_header={"source": "RebuildUnit", "target": "ContinueUnit"},
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_review"},
            next_route=NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="non-review route spoofing",
                review_route="pass",
            ),
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any("only be emitted by ReviewUnit" in violation for violation in violations)

    def test_reviewunit_handoff_requires_review_route(self):
        packet = HandoffPacket(
            handoff_header={"source": "ReviewUnit", "target": "ContinueUnit"},
            input_anchor={"state_ref": "ns_final"},
            output_anchor={"state_ref": "ns_after_review"},
            next_route=NextRoute(
                recommended_workflow="ContinueUnit",
                route_reason="review route omitted",
            ),
        )

        ok, violations = HandoffBoundaryUnit().verify(packet)

        assert not ok
        assert any("must include review_route" in violation for violation in violations)


class TestTrack3CharacterModel:
    def test_no_evidence_leakback(self):
        objects, _ = _rebuild_objects()
        characters = [obj for obj in objects if isinstance(obj, CharacterModel)]

        assert characters
        for character in characters:
            assert isinstance(character.knowledge_state, list)
            assert all(isinstance(item, str) for item in character.knowledge_state)
            assert all("因为" not in item for item in character.knowledge_state)
            assert all("证据" not in item for item in character.knowledge_state)
            assert all(isinstance(value, str) for value in character.relations.values())

    def test_field_bodies_keep_conclusions_only(self):
        objects, _ = _rebuild_objects()
        package = SerializationBoundaryUnit().build_package(*objects)
        validation_package = SerializationPackage(
            stable_memory=package.stable_memory,
            working_set=package.working_set,
            repair_control=package.repair_control,
            confidence={"gaps": ["代理人名单正文未知"]},
        )

        for character_data in validation_package.stable_memory["CharacterModel"]:
            assert isinstance(character_data["knowledge_state"], list)
            assert isinstance(character_data["relations"], dict)
            assert isinstance(character_data.get("misinformation", []), list)
            assert isinstance(character_data.get("self_image"), (str, type(None)))
            assert isinstance(character_data.get("arc_stage"), (str, type(None)))
            assert len(character_data["knowledge_state"][0]) < 80
            assert all(len(value) < 80 for value in character_data["relations"].values())
        assert "CharacterModel" not in validation_package.working_set
        assert "CharacterModel" not in validation_package.repair_control
