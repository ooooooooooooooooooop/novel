"""Q1 Phase 2 — flow v3 集成：compose/extend 通过事务边界提交章节.

用 mock response 驱动整条 staged 流程（与 test_review_after_prose 同一 harness），
区别：把工作区 .flow_version 显式置 3（模拟已迁移），验证：
- draft → reviewed → committed 状态机随流程推进落盘
- run_manifest.json 产生，recover() 识别为完整提交
- v2 对照：默认工作区不产生 run_manifest（零成本契约）
"""

import json
import subprocess
import sys
from pathlib import Path

from src.boundary_control.chapter_commit import ChapterCommitBoundary

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_input_hash(output_dir: Path, input_path: Path) -> None:
    from src.boundary_control.runtime_identity import file_content_hash

    (output_dir / ".input_hash").write_text(
        file_content_hash(input_path), encoding="utf-8"
    )


def _minimal_rebuild_payload() -> dict:
    return {
        "workspec": {
            "genre": "悬疑",
            "audience": "青年",
            "theme": "真相",
            "tone": "克制",
            "pacing": "短弧推进",
        },
        "worldmodel": {"world_facts": ["世界事实"]},
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
                "relations": {},
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "夜晚",
            "current_location": "案发现场",
            "current_situation": "调查开始",
            "active_characters": ["c001"],
        },
        "factledger": {"entries": []},
        "foreshadowgraph": {"entries": []},
        "confidence_gaps": [],
    }


def _minimal_continue_payload(*, input_state_ref: str = "ns_001") -> dict:
    return {
        "plotunit": {
            "unit_id": "pu_candidate",
            "level": "scene",
            "goal": "推进候选场景",
            "participants": ["c001"],
            "conflict": "候选冲突",
            "input_state_ref": input_state_ref,
            "output_state_ref": "ns_002",
            "released_information": ["候选信息"],
            "consequences": ["候选后果"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": "候选场景的画面",
                "obstacles": ["候选阻碍"],
                "choice_grounding": "候选选择依据：主角基于身份与压力作出判断",
                "outcome": "候选结果：选择产生了可见反馈",
                "cognition_shift": "候选认知变化：从之前怎么想到现在怎么想",
            },
        },
        "new_state": {
            "state_id": "ns_002",
            "current_time": "稍后",
            "current_location": "测试地点",
            "current_situation": "候选推进",
            "active_characters": ["c001"],
        },
        "new_facts": [],
        "confidence_gaps": [],
    }


def _long_prose() -> str:
    return (
        "第一章 开端\n他推开门，屋里的光线斜斜地落在桌上。杯子里剩下半口冷水，"
        "窗缝里有风，把桌角的一张纸吹起又落下。他站在那里，没有动，手停在门框上，"
        "听走廊尽头传来脚步声，越来越近。他想起三天前的事，想起那人临走时说的话。"
        "他原以为不会再回来，此刻却一步也迈不动。他低头，看见自己鞋底沾着刚干的泥，"
        "那是昨天夜里走夜路踩上的。桌上的纸又翻了个面，露出背面的字迹——是那个人的手笔。"
        "他认得那个勾法，认得那个收笔的位置。窗外有鸟叫，他忽然觉得这间屋子空得过分，"
        "连呼吸都有回声。他伸出手，指尖碰到纸边，又缩回来。他不知道自己在怕什么，"
        "只知道这一刻，他不该继续站在这里。脚步声停在了门口。"
    )


def _extend_v3_workspace(tmp_path: Path, output_dir: Path, input_path: Path):
    """建 extend 工作区并推到 flow v3（模拟已迁移）."""
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本，用于驱动 staged 流程。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout, r.stdout + r.stderr
    # 显式迁移到 flow v3（等价 novel migrate 的效果）
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")
    return r


def test_extend_flow_v3_transactional_commit(tmp_path):
    """extend v3 全流程：draft→reviewed→committed，manifest 落盘且 recover 识别."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    chapters = output_dir.parent.parent / "chapters"
    _extend_v3_workspace(tmp_path, output_dir, input_path)

    # Rebuild → Continue
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr

    # Continue → Prose（Pre-Review clear）
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pre-Review clear" in r.stdout
    assert "STEP: PROSE" in r.stdout

    # Prose → draft 状态落盘
    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "draft"
    assert manifest["chapter_number"] == 1

    # Review PASS → committed（事务边界提交）
    _write_json(output_dir / "review_response.txt", {"issues": [], "reminders": [], "route": "pass"})
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout
    assert "Extend complete: PASS" in r.stdout

    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "committed"
    assert manifest["mode"] == "extend"
    assert manifest["chapter_number"] == 1
    assert manifest["artifacts"]["chapters/chapter_1.txt"]
    assert manifest["artifacts"]["output/extend/extend_rebuild_package.json"]
    assert manifest["artifacts"]["output/extend/extend_frames.json"]
    assert manifest["artifacts"]["output/extend/chapter_provenance.json"]
    assert manifest["source_text_hash"]
    assert manifest["state_after_hash"]
    assert manifest["frame_hash"]

    # 重启 recover：完整提交被识别
    boundary = ChapterCommitBoundary(output_dir, chapters)
    report = boundary.recover()
    assert report.recognized is True
    assert report.reason == "committed"
    assert report.orphans == []
    assert (chapters / "chapter_1.txt").read_text(encoding="utf-8") == _long_prose()

    # 状态包确实被事务边界写入
    state = json.loads((output_dir / "extend_rebuild_package.json").read_text(encoding="utf-8"))
    assert state is not None


def test_extend_flow_v2_produces_no_manifest(tmp_path):
    """v2 对照：默认工作区不产生 run_manifest（零成本契约）. """
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本，用于驱动 staged 流程。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)

    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    _write_json(output_dir / "review_response.txt", {"issues": [], "reminders": [], "route": "pass"})
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Extend complete: PASS" in r.stdout
    # v2：无 manifest、无 run_history、无 .flow_version 变更
    assert not (output_dir / "run_manifest.json").exists()
    assert (output_dir / ".flow_version").read_text(encoding="utf-8").strip() == "2"
    # 章节照常提交
    assert (output_dir.parent.parent / "chapters" / "chapter_1.txt").exists()


def test_compose_flow_v3_transactional_commit(tmp_path):
    """compose v3 全流程：committed + manifest + recover 识别."""
    output_dir = tmp_path / "novel" / "output" / "compose"
    chapters = output_dir.parent.parent / "chapters"
    output_dir.mkdir(parents=True)

    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    _write_json(
        output_dir / "compose_continue_response.txt",
        _minimal_continue_payload(input_state_ref="ns_initial"),
    )
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STEP: PROSE" in r.stdout

    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "draft"

    _write_json(
        output_dir / "compose_review_response.txt",
        {"issues": [], "reminders": [], "route": "pass"},
    )
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout
    assert "Compose complete: PASS" in r.stdout

    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "committed"
    assert manifest["mode"] == "compose"
    assert manifest["chapter_number"] == 1
    assert manifest["artifacts"]["chapters/chapter_1.txt"]
    assert manifest["artifacts"]["output/compose/compose_state.json"]
    assert manifest["artifacts"]["output/compose/compose_frames.json"]

    boundary = ChapterCommitBoundary(output_dir, chapters)
    report = boundary.recover()
    assert report.recognized is True
    assert report.orphans == []
