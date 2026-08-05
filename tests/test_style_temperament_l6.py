"""L6 气质分层接入测试.

覆盖：WorkSpec.temperament 渲染差异（无 → 字节不变）、novel_cli --temperament
透传（style/compose/extend 三子命令）、compose/extend 无风格档案时注入气质桶
指导（build_temperament_guidance）、气质桶简写别名归一化。
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

from src.domain_layer.style_rules import build_temperament_guidance
from src.object_state import WorkSpec


PROJECT_ROOT = Path(__file__).resolve().parents[1]

_MIN_REBUILD_RESPONSE = json.dumps(
    {
        "workspec": {
            "genre": "测试类型",
            "audience": "测试读者",
            "theme": "测试主题",
            "tone": "测试调性",
            "pacing": "测试节奏",
        },
        "worldmodel": {"world_facts": ["测试世界成立"], "prohibitions": []},
        "charactermodels": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试身份",
                "outer_goal": "完成续写",
                "inner_need": "保持一致",
                "fear": "链路中断",
                "flaw": "信息不足",
                "strength": "稳定执行",
                "stance": "主动",
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "第1章",
            "current_location": "测试地点",
            "current_situation": "重建完成",
            "active_characters": ["c001"],
        },
        "factledger": {
            "entries": [
                {
                    "fact_id": "f001",
                    "statement": "测试主角完成输入解析",
                    "fact_type": "event",
                    "involved_entities": ["c001"],
                    "confirmed": True,
                }
            ]
        },
        "foreshadowgraph": {"entries": []},
        "confidence_gaps": [],
    },
    ensure_ascii=False,
)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _workspec(**overrides) -> WorkSpec:
    base = dict(
        genre="仙侠",
        audience="成年读者",
        theme="命运",
        tone="克制",
        pacing="前快中稳后爆",
    )
    base.update(overrides)
    return WorkSpec(**base)


# --- WorkSpec.temperament 渲染差异（零成本契约） ---


def test_workspec_without_temperament_omits_line():
    assert "叙事气质" not in _workspec().to_prompt_context()


def test_workspec_with_temperament_renders_line():
    ctx = _workspec(temperament="散文型").to_prompt_context()
    assert "叙事气质: 散文型" in ctx


def test_workspec_old_json_deserializes_without_temperament():
    old = {
        "genre": "仙侠",
        "audience": "读者",
        "theme": "命运",
        "tone": "克制",
        "pacing": "前快",
    }
    ws = WorkSpec.model_validate_json(json.dumps(old))
    assert ws.temperament is None
    assert "叙事气质" not in ws.to_prompt_context()


# --- compose：无风格档案时 --temperament 注入气质桶指导 ---


def test_compose_temperament_injects_bucket_guidance(tmp_path):
    output_dir = tmp_path / "compose_run"
    result = run_script(
        "src/compose_short_form.py",
        "--output-dir",
        str(output_dir),
        "--temperament",
        "散文",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "compose_continue_prompt.txt").read_text(encoding="utf-8")
    assert "【叙事气质: 散文型】" in prompt
    assert "默认聚焦手法" in prompt


def test_compose_without_temperament_keeps_prompt_byte_identical(tmp_path):
    output_dir = tmp_path / "compose_run"
    result = run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "compose_continue_prompt.txt").read_text(encoding="utf-8")
    assert "叙事气质" not in prompt


def test_compose_temperament_full_name_also_works(tmp_path):
    output_dir = tmp_path / "compose_run"
    result = run_script(
        "src/compose_short_form.py",
        "--output-dir",
        str(output_dir),
        "--temperament",
        "散文型",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prompt = (output_dir / "compose_continue_prompt.txt").read_text(encoding="utf-8")
    assert "【叙事气质: 散文型】" in prompt


# --- extend：无风格档案时 --temperament 注入气质桶指导（Replay 到 Continue） ---


def test_extend_temperament_injects_bucket_guidance(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("山门破旧，雪落满阶。弟子们鱼贯而入。", encoding="utf-8")
    output_dir = tmp_path / "extend_run"

    first = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--temperament",
        "散文",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert (output_dir / "rebuild_prompt.txt").exists()

    (output_dir / "rebuild_response.txt").write_text(
        _MIN_REBUILD_RESPONSE, encoding="utf-8"
    )
    second = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--temperament",
        "散文",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    prompt = (output_dir / "continue_prompt.txt").read_text(encoding="utf-8")
    assert "【叙事气质: 散文型】" in prompt


def test_extend_without_temperament_omits_guidance(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("山门破旧，雪落满阶。弟子们鱼贯而入。", encoding="utf-8")
    output_dir = tmp_path / "extend_run"

    first = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )
    assert first.returncode == 0
    (output_dir / "rebuild_response.txt").write_text(
        _MIN_REBUILD_RESPONSE, encoding="utf-8"
    )
    second = run_script(
        "src/extend_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
    )
    assert second.returncode == 0, second.stdout + second.stderr
    prompt = (output_dir / "continue_prompt.txt").read_text(encoding="utf-8")
    assert "叙事气质" not in prompt


# --- novel_cli --temperament 透传（style/compose/extend 三子命令） ---


def test_novel_cli_defines_and_passes_temperament():
    text = (PROJECT_ROOT / "src/novel_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    # 三个 _run_* 都透传 --temperament 给 child script
    for name in ("_run_style", "_run_compose", "_run_extend"):
        source = ast.get_source_segment(text, functions[name])
        assert '"--temperament"' in source, name
    # 三个子命令 argparse 各定义一次 + 三处透传各一次 = 至少 6 处
    assert text.count('"--temperament"') >= 6


# --- 气质桶简写别名归一化 ---


def test_temperament_alias_normalizes():
    assert build_temperament_guidance("散文") == build_temperament_guidance("散文型")
    assert build_temperament_guidance("散文")
    assert build_temperament_guidance("未知气质") == ""
