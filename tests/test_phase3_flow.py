"""Q1 Phase 3 — flow 集成：续写可行性门禁 + 读者契约注入 + SceneExperience 强制.

在 extend/compose 真实脚本层面验证：
- v3 + 契约 → Continue prompt 注入【读者契约】（零成本：v2/无契约不注入，字节不变）
- resume + 全 completed 帧（no active frame）→ 确定性 stop / needs_premise，
  跳过 Continue 不生成下一章（viability_report.json 落盘）
- v3 Continue 响应缺 scene_experience → Pre-Review 代码闸阻断 → 对象层 rewrite
"""

import json
import subprocess
import sys
from pathlib import Path

from tests.test_phase2_flow_v3 import (
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


def _contract_json() -> dict:
    return {
        "contract_id": "flow-test-001",
        "audience": "测试读者",
        "core_pleasures": ["围绕「真相」的张力推进", "每章新状态", "类型期待"],
        "follow_reason": "主角在代价下做选择",
        "core_tension": "「真相」驱动下的持续对抗",
        "chapter_pacing": "每章推进一个量级",
        "must_keep": ["克制叙事声音"],
        "forbidden_drifts": ["超能力", "穿越"],
        "valid_hooks": ["cliffhanger", "reveal", "promise", "emotional_peak"],
        "ending_conditions": ["真相揭开后所有承诺回收"],
        "opening_minimum_promise": "首章主角必须做出定义性选择并承担代价",
    }


def _write_contract(output_dir: Path) -> None:
    (output_dir / "reader_contract.json").write_text(
        json.dumps(_contract_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _all_completed_frames() -> list[dict]:
    """整个结构 completed——合法的终止态（frame.validate_frame_state 明示允许）."""
    return [
        {
            "frame_id": "book_001",
            "level": "book",
            "title": "测试书",
            "purpose": "容器",
            "position": "start",
            "status": "completed",
        },
        {
            "frame_id": "arc_001",
            "level": "arc",
            "title": "测试弧",
            "purpose": "主线",
            "position": "middle",
            "status": "completed",
            "parent_id": "book_001",
            "order_index": 0,
        },
        {
            "frame_id": "chapter_001",
            "level": "chapter",
            "title": "测试章",
            "purpose": "推进",
            "position": "middle",
            "status": "completed",
            "parent_id": "arc_001",
            "order_index": 0,
        },
        {
            "frame_id": "scene_001",
            "level": "scene",
            "title": "测试场景",
            "purpose": "落点",
            "position": "end",
            "status": "completed",
            "parent_id": "chapter_001",
            "order_index": 0,
        },
    ]


def _extend_workspace(tmp_path: Path, output_dir: Path, input_path: Path) -> None:
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本，用于驱动 staged 流程。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout, r.stdout + r.stderr
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")


def test_v3_contract_injected_into_continue_prompt(tmp_path):
    """v3 + 契约 → Continue prompt 注入【读者契约】段."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    _extend_workspace(tmp_path, output_dir, input_path)
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    # 无契约时 prompt 无【读者契约】
    prompt_no_contract = (output_dir / "continue_prompt.txt").read_text(encoding="utf-8")
    assert "【读者契约】" not in prompt_no_contract

    _write_contract(output_dir)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    prompt = (output_dir / "continue_prompt.txt").read_text(encoding="utf-8")
    assert "【读者契约】" in prompt
    assert "「真相」驱动下的持续对抗" in prompt
    # 可行性分析产物落盘（v3 每轮）
    assert (output_dir / "viability_analysis.json").exists()


def test_v2_contract_not_injected_zero_cost(tmp_path):
    """v2 流程即使存在契约文件也不注入【读者契约】（零成本契约：字节不变）."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert "STEP: CONTINUE" in r.stdout
    _write_contract(output_dir)  # 即使契约存在
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert "STEP: CONTINUE" in r.stdout
    prompt = (output_dir / "continue_prompt.txt").read_text(encoding="utf-8")
    assert "【读者契约】" not in prompt
    # v2 不产生可行性分析产物
    assert not (output_dir / "viability_analysis.json").exists()


def test_v3_viability_stop_skips_continue(tmp_path):
    """no active frame + 无承诺 → stop，跳过 Continue，不生成下一章."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    _extend_workspace(tmp_path, output_dir, input_path)
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout
    # 结构闭合：写全 completed 帧并 resume
    (output_dir / "extend_frames.json").write_text(
        json.dumps(_all_completed_frames(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    r = _run_script(
        "src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir), "--resume"
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ContinuationViability: stop" in r.stdout
    assert "不生成下一章" in r.stdout
    report = json.loads((output_dir / "viability_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "stop"
    assert report["deterministic"] is True
    # 不产生 Continue 响应槽（未到 Step 2）
    assert not (output_dir / "continue_response.txt").exists()


def test_v3_viability_needs_premise_with_open_promises(tmp_path):
    """no active frame + 活跃承诺 → needs_premise，给出 required_premise."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    _extend_workspace(tmp_path, output_dir, input_path)
    payload = _minimal_rebuild_payload()
    payload["foreshadowgraph"] = {
        "entries": [
            {
                "thread_id": "th_001",
                "setup_point": "第1章",
                "content": "主角身世之谜未解",
                "visibility_level": "explicit",
                "expected_payoff": "回收",
                "current_status": "active",
            }
        ]
    }
    _write_json(output_dir / "rebuild_response.txt", payload)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout
    (output_dir / "extend_frames.json").write_text(
        json.dumps(_all_completed_frames(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    r = _run_script(
        "src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir), "--resume"
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ContinuationViability: needs_premise" in r.stdout
    report = json.loads((output_dir / "viability_report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "needs_premise"
    assert report["required_premise"]


def test_v3_scene_experience_guard_blocks_prose(tmp_path):
    """v3 Continue 响应缺 scene_experience → Pre-Review 代码闸阻断 → 对象层 rewrite."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    _extend_workspace(tmp_path, output_dir, input_path)
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout
    # Continue 响应缺 scene_experience（关键单元：conflict/released_information 非空）
    payload = _minimal_continue_payload()
    del payload["plotunit"]["scene_experience"]
    _write_json(output_dir / "continue_response.txt", payload)
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pre-Review blocked" in r.stdout
    assert "STEP: PROSE" not in r.stdout
    assert (output_dir / "extend_pre_rewrite_prompt.txt").exists()
    # 闸的 issue 确实进入 pre_review_result（blocking + SceneExperience 规则）
    pre = json.loads((output_dir / "pre_review_result.json").read_text(encoding="utf-8"))
    se_issues = [i for i in pre["blocking"] if "SceneExperience" in i["violated_rule"]]
    assert se_issues, [i["violated_rule"] for i in pre["blocking"]]


def test_v3_contract_injected_into_compose_continue_prompt(tmp_path):
    """compose v3 + 契约 → compose_continue_prompt 注入【读者契约】."""
    output_dir = tmp_path / "novel" / "output" / "compose"
    output_dir.mkdir(parents=True)
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")
    prompt_no_contract = (output_dir / "compose_continue_prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "【读者契约】" not in prompt_no_contract

    _write_contract(output_dir)
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    prompt = (output_dir / "compose_continue_prompt.txt").read_text(encoding="utf-8")
    assert "【读者契约】" in prompt
    assert "「真相」驱动下的持续对抗" in prompt


def test_v3_contract_gate_opening_payload_still_passes(tmp_path):
    """完整 v3 流程（带契约）依旧走通：contract 注入不破坏现有 staged 流."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    _extend_workspace(tmp_path, output_dir, input_path)
    _write_contract(output_dir)
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pre-Review clear" in r.stdout
    assert "STEP: PROSE" in r.stdout
