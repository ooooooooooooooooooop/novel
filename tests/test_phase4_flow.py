"""Q1 Phase 4 — flow 集成：提交点读者门禁链.

在 extend/compose 真实脚本层面验证（复用 test_phase2_flow_v3 的 staged harness）：
- v3 + 纯氛围草稿 → 门禁阻断，不提交章节（无 chapter_*.txt），run 状态 rejected
- v3 + 干净草稿 → 门禁 pass，事务提交，manifest 含 facts_package_hash
- v2 → 零成本：不产 reader_gate_report.json、无 manifest
"""

import json
import subprocess
import sys
from pathlib import Path

from tests.test_phase2_flow_v3 import (
    _extend_v3_workspace,
    _long_prose,
    _minimal_continue_payload,
    _minimal_rebuild_payload,
    _write_input_hash,
    _write_json,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _ambient_prose() -> str:
    """纯氛围草稿（无事件/选择/顿悟/对白）——应被 _check_no_state_change 阻断.

    长度须 ≥ prose 最小 200 字符，且全程只有坐/看/喝/叹等氛围动词。
    """
    return (
        "他坐在窗前，看着外面的雨，喝了一口水。杯子放下，又端起来。"
        "他叹了口气，换了个姿势，继续坐着。窗外的雨还在下，屋檐滴着水。"
        "他把手放在窗沿上，指节凉凉的。他又喝了口水，水已经凉透了。"
        "他望着雨里模糊的街角，什么都没有想，又好像想了很久。"
        "杯子里的水映着灰蒙蒙的天。他坐着，听着雨声，一直到天彻底暗下来。"
        "他数着雨滴，数到一半又忘了。灯没有开，屋里只有雨声，"
        "他慢慢地、慢慢地靠在椅背上，眼睛望着天花板，一动不动。"
    )


def _loop_chapter_one_prose() -> str:
    """第一章（含顿悟核心 + 推进信号）：提交通过门禁."""
    return (
        "第一章 开端\n他推开门，决定去追查那份旧卷宗。结果在书架夹层里发现了线索，"
        "是一张发黄的纸条。他对照笔迹，忽然明白了真相就在眼前，那个署名是伪造的。"
        "他深吸一口气，把纸条收进怀里，关上门。雨还在下，他沿着来路往回走，"
        "鞋底在湿滑的石板路上留下深深的印子。他决定明天一早就去对质。"
        "此刻他终于明白，这些年他一直追错了方向，而真正的答案，"
        "已经被他亲手放回了一旁。他握紧纸条，指节发白，雨水顺着领口往下淌，"
        "他全然不觉，只想着那纸条上的落款到底是谁。"
    )


def _loop_chapter_two_prose() -> str:
    """第二章：与第一章**同一顿悟核心**（重复闭环第二次）→ 应被门禁阻断."""
    return (
        "第二章 追踪\n他又推开门，决定再查一遍那份旧卷宗。结果还是同样的纸条，"
        "同样的字迹。他对着灯端详，忽然明白了真相就在眼前，那个署名是伪造的。"
        "他再次把纸条收进怀里，关上门。雨还在下，他沿着同样的路往回走，"
        "鞋底印着同样的泥。他决定明天再去对质一次。此刻他终于明白，"
        "真相就在眼前，和昨天他明白的完全一样。他站在雨里，"
        "把那张纸条展开又折起，折起又展开，直到纸边都起了毛。"
        "路灯把雨丝照成一根根细线，他数着这些细线，数到第七根时停下来，"
        "又低头看了一眼纸条，还是那个署名，还是那行他认得的字迹。"
        "他忽然明白，那个署名是伪造的，这句话他昨天就明白过。"
    )


def _drive_to_prose(output_dir: Path, input_path: Path, prose: str):
    """Rebuild → Continue → Prose，使流程停在 review 前（draft 落盘）."""
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    (output_dir / "prose_response.txt").write_text(prose, encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout


def _review_pass(output_dir: Path, input_path: Path):
    _write_json(output_dir / "review_response.txt", {"issues": [], "reminders": [], "route": "pass"})
    return _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))


def test_extend_v3_ambient_draft_blocked_no_commit(tmp_path):
    """v3 + 纯氛围草稿 → 读者门禁阻断，不提交章节，run 状态 rejected."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    chapters = output_dir.parent.parent / "chapters"
    _extend_v3_workspace(tmp_path, output_dir, input_path)

    _drive_to_prose(output_dir, input_path, _ambient_prose())

    r = _review_pass(output_dir, input_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Reader gate block" in r.stdout, r.stdout + r.stderr
    assert "本章不提交" in r.stdout
    assert not (chapters / "chapter_1.txt").exists(), "阻断后不得落盘章节"

    gate = json.loads((output_dir / "reader_gate_report.json").read_text(encoding="utf-8"))
    assert gate["route"] == "block"
    assert gate["chapter_ref"] == "chapter_1"
    assert gate["facts_package_hash"], "门禁报告应记录事实包哈希"
    # 确定性轴始终武装（hard_consistency=True）
    assert gate["axes_armed"]["hard_consistency"] is True

    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "rejected"


def test_extend_v3_clean_draft_commits_with_facts_hash(tmp_path):
    """v3 + 干净草稿 → 门禁 pass，事务提交，manifest 含 facts_package_hash."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    chapters = output_dir.parent.parent / "chapters"
    _extend_v3_workspace(tmp_path, output_dir, input_path)

    _drive_to_prose(output_dir, input_path, _long_prose())

    r = _review_pass(output_dir, input_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Reader gate pass" in r.stdout, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout

    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "committed"
    assert manifest["facts_package_hash"], "committed manifest 必须带 facts_package_hash"

    gate = json.loads((output_dir / "reader_gate_report.json").read_text(encoding="utf-8"))
    assert gate["route"] == "pass"
    assert gate["facts_package_hash"] == manifest["facts_package_hash"]
    # 首章窗口轴 unarmed（无前章），其余轴如实记录
    assert gate["axes_armed"]["window"] is False


def test_extend_v3_repeated_loop_second_blocks(tmp_path):
    """v3 + 与上一章同一顿悟核心 → 重复闭环第二次阻断，不提交."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    chapters = output_dir.parent.parent / "chapters"
    _extend_v3_workspace(tmp_path, output_dir, input_path)

    # 第一章（带顿悟核心）干净提交
    _drive_to_prose(output_dir, input_path, _loop_chapter_one_prose())
    r = _review_pass(output_dir, input_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (chapters / "chapter_1.txt").exists()

    # 重跑第二章（沿用已提交的 chapter_1），草稿与第一章同一顿悟核心。
    # 提交后 reset_consumed_responses 已清掉响应文件，直接写新响应即可。
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    # Continue → 第二版 prose（同一顿悟核心，含推进信号以免被 no_state_change 抢先）
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    (output_dir / "prose_response.txt").write_text(
        _loop_chapter_two_prose(), encoding="utf-8"
    )
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout

    r = _review_pass(output_dir, input_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Reader gate block" in r.stdout, r.stdout + r.stderr
    assert not (chapters / "chapter_2.txt").exists(), "重复闭环阻断后不得提交第二章"


def test_extend_v2_no_reader_gate_artifacts(tmp_path):
    """v2 零成本：不产 reader_gate_report.json、无 run_manifest."""
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

    assert not (output_dir / "reader_gate_report.json").exists(), "v2 不产门禁报告"
    assert not (output_dir / "run_manifest.json").exists(), "v2 不产 run_manifest（零成本契约）"
