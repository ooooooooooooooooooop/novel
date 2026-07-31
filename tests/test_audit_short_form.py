"""测试 audit_short_form slice 的基础功能."""

import json
import subprocess
import sys
from pathlib import Path

from src.boundary_control.handoff import HandoffBoundaryUnit
from src.boundary_control.serialization import SerializationBoundaryUnit
from src.boundary_control.validation import NoRegressionValidationUnit
from src.object_state import (
    CharacterModel,
    FactEntry,
    FactLedger,
    WorkSpec,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _complete_rebuild_response() -> str:
    return json.dumps(
        {
            "workspec": {
                "genre": "悬疑",
                "audience": "青年",
                "theme": "真相",
                "tone": "克制",
                "pacing": "短弧推进",
            },
            "worldmodel": {
                "world_facts": ["世界事实"],
                "prohibitions": ["禁止事项"],
            },
            "charactermodels": [
                {
                    "character_id": "c001",
                    "name": "主角",
                    "identity": "侦探",
                    "outer_goal": "破案",
                    "inner_need": "正义",
                    "fear": "失败",
                    "flaw": "固执",
                    "strength": "观察力",
                    "stance": "中立",
                }
            ],
            "narrativestate": {
                "state_id": "ns_001",
                "current_time": "夜晚",
                "current_location": "案发现场",
                "current_situation": "调查开始",
                "active_characters": ["c001"],
            },
            "factledger": {
                "entries": [
                    {
                        "fact_id": "f001",
                        "statement": "门被撬开",
                        "fact_type": "event",
                        "involved_entities": [],
                        "confirmed": True,
                    }
                ]
            },
            "foreshadowgraph": {"entries": []},
            "confidence_gaps": [],
        },
        ensure_ascii=False,
    )


def test_workspec_creation():
    ws = WorkSpec(
        genre="仙侠",
        audience="青年",
        theme="成长",
        tone="克制",
        pacing="前快中稳后爆",
    )
    assert ws.genre == "仙侠"


def test_worldmodel_validation():
    from src.object_state import WorldModel

    wm = WorldModel(prohibitions=["王城内禁止斗法"])
    valid, _ = wm.validate_event("在王城内斗法")
    assert valid is False


def test_character_model_no_overlap():
    cm = CharacterModel(
        character_id="c001",
        name="沈青",
        identity="被逐弟子",
        outer_goal="回宗",
        inner_need="被接纳",
        fear="再次被弃",
        flaw="独扛",
        strength="坚韧",
        stance="隐忍",
        knowledge_state=["令牌在手"],
        misinformation=["旧案已结案"],
    )
    assert "令牌在手" not in cm.misinformation


def test_factledger_confirm():
    fl = FactLedger(
        entries=[
            FactEntry(
                fact_id="f001",
                statement="测试",
                fact_type="event",
                confirmed=False,
            )
        ]
    )
    assert fl.confirm_fact("f001")
    assert fl.get_confirmed()[0].confirmed


def test_serialization_roundtrip():
    ser = SerializationBoundaryUnit()
    ws = WorkSpec(
        genre="测试",
        audience="测试读者",
        theme="测试主题",
        tone="测试调性",
        pacing="测试节奏",
    )
    pkg = ser.build_package(ws)
    assert "WorkSpec" in pkg.stable_memory

    path = Path("tests/__test_output.json")
    ser.save(pkg, path)
    loaded = ser.load(path)
    assert "WorkSpec" in loaded.stable_memory
    path.unlink(missing_ok=True)


def test_handoff_verify():
    hb = HandoffBoundaryUnit()
    packet = hb.build_rebuild_to_review(
        source_text_ref="test.txt",
        reconstructed_objects={"WorkSpec": {}},
        confidence_gaps=["不确定"],
    )
    ok, violations = hb.verify(packet)
    assert ok
    assert violations == []
    assert packet.next_route.recommended_workflow == "ReviewUnit"
    assert packet.next_route.route_reason == "reconstruction_complete"
    assert packet.next_route.must_read_first == ("test.txt",)
    assert packet.next_route.model_dump()["must_read_first"] == ["test.txt"]


def test_no_regression_pass():
    ser = SerializationBoundaryUnit()
    ws = WorkSpec(
        genre="测试",
        audience="测试读者",
        theme="测试主题",
        tone="测试调性",
        pacing="测试节奏",
    )
    fl = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="确认",
                fact_type="event",
                confirmed=True,
            )
        ]
    )
    pkg = ser.build_package(ws, fl)

    val = NoRegressionValidationUnit()
    violations = val.run(pkg)
    assert violations == []


def test_no_regression_fail_unconfirmed_fact():
    ser = SerializationBoundaryUnit()
    fl = FactLedger(
        entries=[
            FactEntry(
                fact_id="f1",
                statement="未确认",
                fact_type="event",
                confirmed=False,
            )
        ]
    )
    pkg = ser.build_package(fl)

    val = NoRegressionValidationUnit()
    violations = val.run(pkg)
    assert any("unconfirmed" in v for v in violations)


def test_rebuild_parses_complete_novel():
    """完整作品重建：RebuildUnit 解析完整 JSON 输出全部对象."""
    from src.workflow_action.rebuild import RebuildUnit

    objects, gaps = RebuildUnit().parse_response(_complete_rebuild_response())

    assert len(objects) == 6
    assert gaps == []


def test_rebuild_preserves_gaps():
    """碎片化作品重建：confidence_gaps 被保留."""
    from src.workflow_action.rebuild import RebuildUnit

    response = json.dumps(
        {
            "workspec": {
                "genre": "仙侠",
                "audience": "青年",
                "theme": "成长",
                "tone": "克制",
                "pacing": "前快中稳后爆",
            },
            "worldmodel": {"world_facts": [], "prohibitions": []},
            "charactermodels": [],
            "narrativestate": {
                "state_id": "ns_001",
                "current_time": "初始",
                "current_location": "待定",
                "current_situation": "待定",
            },
            "factledger": {"entries": []},
            "foreshadowgraph": {"entries": []},
            "confidence_gaps": ["时间线矛盾", "角色动机不明", "势力关系未交代"],
        },
        ensure_ascii=False,
    )

    objects, gaps = RebuildUnit().parse_response(response)

    assert len(gaps) == 3
    assert "时间线矛盾" in gaps


def test_audit_entry_treats_utf8_bom_as_encoding_marker(tmp_path):
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "output"
    input_path.write_bytes(b"\xef\xbb\xbf" + "短篇正文".encode("utf-8"))

    result = subprocess.run(
        [
            sys.executable,
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "rebuild_prompt.txt").read_text(encoding="utf-8")
    assert "\ufeff" not in prompt
    assert "短篇正文" in prompt


def test_audit_entry_treats_utf8_bom_response_as_encoding_marker(tmp_path):
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "output"
    input_path.write_text("短篇正文", encoding="utf-8")

    first = subprocess.run(
        [
            sys.executable,
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stdout + first.stderr

    response_path = output_dir / "rebuild_response.txt"
    response_path.write_bytes(
        b"\xef\xbb\xbf" + _complete_rebuild_response().encode("utf-8")
    )

    second = subprocess.run(
        [
            sys.executable,
            "src/audit_short_form.py",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert second.returncode == 0, second.stdout + second.stderr
    assert "Rebuilt 6 objects" in second.stdout
    assert (output_dir / "review_prompt.txt").exists()


def test_review_audit_detects_character_overlap():
    """问题作品审查：Review 检测 knowledge/misinformation 重叠."""
    from src.object_state import CharacterModel
    from src.workflow_action.review import ReviewUnit

    char = CharacterModel(
        character_id="c001",
        name="沈青",
        identity="被逐弟子",
        outer_goal="回宗",
        inner_need="被接纳",
        fear="再次被弃",
        flaw="独扛",
        strength="坚韧",
        stance="隐忍",
        knowledge_state=["令牌在手", "旧案已结案"],
        misinformation=["令牌在手"],
    )

    review = ReviewUnit()
    issues = review._hard_rules([char])

    assert any(i.issue_type == "character_distortion" for i in issues)
    assert any("令牌在手" in i.description for i in issues)
