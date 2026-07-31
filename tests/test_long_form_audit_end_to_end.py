"""Long-form audit end-to-end tests without real LLM calls."""

import json
import subprocess
import sys
from pathlib import Path


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
        "worldmodel": {
            "world_facts": ["测试世界成立"],
            "prohibitions": [],
        },
        "charactermodels": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试身份",
                "outer_goal": "完成测试",
                "inner_need": "保持一致",
                "fear": "链路中断",
                "flaw": "信息不足",
                "strength": "稳定执行",
                "stance": "主动",
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "第2章",
            "current_location": "测试地点",
            "current_situation": "长文 audit 重建完成",
            "active_characters": ["c001"],
        },
        "factledger": {
            "entries": [
                {
                    "fact_id": "f001",
                    "statement": "测试主角完成长文 audit 输入解析",
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

_MIN_REVIEW_PASS_RESPONSE = json.dumps(
    {"issues": [], "reminders": [], "route": "pass"},
    ensure_ascii=False,
)

_MIN_REVIEW_REWRITE_RESPONSE = json.dumps(
    {
        "issues": [
            {
                "issue_id": "iss_test_rewrite",
                "issue_type": "weak_progression",
                "severity": "blocking",
                "location": "NarrativeState",
                "scope_of_impact": "测试 rewrite 路径",
                "violated_rule": "测试规则",
                "description": "触发 rewrite 分支以验证 outline trace 保留",
            }
        ],
        "reminders": [],
        "route": "rewrite",
    },
    ensure_ascii=False,
)

_MIN_OUTLINE_RESPONSE = json.dumps(
    {
        "arcs": [
            {
                "arc_id": "arc_001",
                "name": "测试开局",
                "chapter_range": "1-30",
                "purpose": "建立测试主线",
                "key_characters": ["c001"],
                "key_events": ["测试主角出现"],
            }
        ],
        "characters": [
            {
                "character_id": "c001",
                "name": "测试主角",
                "identity": "测试身份",
                "first_appearance": "第1章",
            }
        ],
        "world": {
            "genre": "测试类型",
            "power_system": "测试资源",
            "time_period": "测试时期",
            "key_rules": ["测试规则"],
        },
        "timeline": [
            {
                "timestamp": "测试时间",
                "event": "测试事件",
                "chapters": "1-30",
            }
        ],
    },
    ensure_ascii=False,
)

_OUTLINE_MISSING_CHARACTER_RESPONSE = json.dumps(
    {
        "arcs": [
            {
                "arc_id": "arc_001",
                "name": "测试开局",
                "chapter_range": "1-30",
                "purpose": "建立测试主线",
                "key_characters": ["c999"],
                "key_events": ["测试主角出现"],
            }
        ],
        "characters": [
            {
                "character_id": "c999",
                "name": "缺失角色",
                "identity": "outline only",
                "first_appearance": "第1章",
            }
        ],
        "world": {
            "genre": "测试类型",
            "power_system": "测试资源",
            "time_period": "测试时期",
            "key_rules": ["测试规则"],
        },
        "timeline": [
            {
                "timestamp": "测试时间",
                "event": "测试事件",
                "chapters": "1-30",
            }
        ],
    },
    ensure_ascii=False,
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _thirty_chapter_text() -> str:
    return "\n\n".join(
        f"第{i}章 标题{i}\n" + ("正文" * 100)
        for i in range(1, 31)
    )


def _run_audit_until_report(
    input_path: Path, output_dir: Path, *extra_final_args: str
) -> subprocess.CompletedProcess[str]:
    base_args = [
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--chapter-wise",
    ]

    r1 = _run(base_args)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert (output_dir / "outline_prompt.txt").exists()
    assert "[WAITING]" in r1.stdout
    assert not list(output_dir.glob("batch_*_rebuild_prompt.txt"))

    (output_dir / "outline_response.txt").write_text(
        _MIN_OUTLINE_RESPONSE, encoding="utf-8"
    )

    r2 = _run(base_args)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert (output_dir / "outline_result.json").exists()
    prompt_files = sorted(output_dir.glob("batch_*_rebuild_prompt.txt"))
    assert len(prompt_files) == 1
    assert "arc_001" in prompt_files[0].read_text(encoding="utf-8")
    assert "[WAITING]" in r2.stdout

    rebuild_response = prompt_files[0].with_name(
        prompt_files[0].name.replace("_prompt.txt", "_response.txt")
    )
    rebuild_response.write_text(_MIN_REBUILD_RESPONSE, encoding="utf-8")

    r3 = _run(base_args)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert (output_dir / "review_prompt.txt").exists()
    assert (output_dir / "rebuild_package.json").exists()

    (output_dir / "review_response.txt").write_text(
        _MIN_REVIEW_PASS_RESPONSE, encoding="utf-8"
    )

    return _run([*base_args, *extra_final_args])


def test_long_form_audit_full_chain(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_thirty_chapter_text(), encoding="utf-8")
    output_dir = tmp_path / "audit_run"

    r3 = _run_audit_until_report(input_path, output_dir)
    assert r3.returncode == 0, r3.stdout + r3.stderr

    report_path = output_dir / "audit_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["route"] == "pass"
    assert report["workspec"] is not None
    assert report["narrative_state"] is not None
    assert report["outline_used"] is True
    assert report["outline_arcs_count"] > 0
    assert isinstance(report["issues"], list)
    route_handoff = json.loads(
        (output_dir / "route_handoff.json").read_text(encoding="utf-8")
    )
    assert route_handoff["handoff_header"]["target"] == "ContinueUnit"
    assert route_handoff["next_route"]["review_route"] == "pass"
    assert route_handoff["next_route"]["recommended_workflow"] == "ContinueUnit"


def test_long_form_audit_markdown_output(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_thirty_chapter_text(), encoding="utf-8")
    output_dir = tmp_path / "audit_markdown_run"

    r3 = _run_audit_until_report(
        input_path, output_dir, "--format", "markdown"
    )
    assert r3.returncode == 0, r3.stdout + r3.stderr

    report_path = output_dir / "audit_report.md"
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "# Audit 报告" in report
    assert "## 审查问题" in report


def test_audit_rewrite_preserves_outline_trace(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_thirty_chapter_text(), encoding="utf-8")
    output_dir = tmp_path / "audit_rewrite_run"
    base_args = [
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--chapter-wise",
    ]

    r1 = _run(base_args)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    (output_dir / "outline_response.txt").write_text(
        _MIN_OUTLINE_RESPONSE, encoding="utf-8"
    )

    r2 = _run(base_args)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    prompt_files = sorted(output_dir.glob("batch_*_rebuild_prompt.txt"))
    assert len(prompt_files) == 1
    prompt_files[0].with_name(
        prompt_files[0].name.replace("_prompt.txt", "_response.txt")
    ).write_text(_MIN_REBUILD_RESPONSE, encoding="utf-8")

    r3 = _run(base_args)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    (output_dir / "review_response.txt").write_text(
        _MIN_REVIEW_REWRITE_RESPONSE, encoding="utf-8"
    )

    r4 = _run(base_args)
    assert r4.returncode == 0, r4.stdout + r4.stderr
    assert (output_dir / "audit_rewrite_prompt.txt").exists()
    (output_dir / "audit_rewrite_response.txt").write_text(
        json.dumps(
            [
                {
                    "target_type": "NarrativeState",
                    "field": "current_situation",
                    "action": "replace",
                    "new_value": "rewrite applied",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    r5 = _run(base_args)
    assert r5.returncode == 0, r5.stdout + r5.stderr
    assert (output_dir / "audit_rereview_prompt.txt").exists()
    (output_dir / "audit_rereview_response.txt").write_text(
        _MIN_REVIEW_PASS_RESPONSE, encoding="utf-8"
    )

    r6 = _run(base_args)
    assert r6.returncode == 0, r6.stdout + r6.stderr
    report = json.loads((output_dir / "audit_report.json").read_text(encoding="utf-8"))
    assert report["outline_used"] is True
    assert report["outline_arcs_count"] > 0


def test_long_form_audit_outline_consistency_issue_in_report(tmp_path):
    input_path = tmp_path / "long.txt"
    input_path.write_text(_thirty_chapter_text(), encoding="utf-8")
    output_dir = tmp_path / "audit_outline_issue_run"
    base_args = [
        "src/audit_short_form.py",
        str(input_path),
        "--output-dir",
        str(output_dir),
        "--chapter-wise",
    ]

    r1 = _run(base_args)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    (output_dir / "outline_response.txt").write_text(
        _OUTLINE_MISSING_CHARACTER_RESPONSE, encoding="utf-8"
    )

    r2 = _run(base_args)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    prompt_files = sorted(output_dir.glob("batch_*_rebuild_prompt.txt"))
    assert len(prompt_files) == 1
    prompt_files[0].with_name(
        prompt_files[0].name.replace("_prompt.txt", "_response.txt")
    ).write_text(_MIN_REBUILD_RESPONSE, encoding="utf-8")

    r3 = _run(base_args)
    assert r3.returncode == 0, r3.stdout + r3.stderr
    (output_dir / "review_response.txt").write_text(
        _MIN_REVIEW_PASS_RESPONSE, encoding="utf-8"
    )

    r4 = _run(base_args)
    assert r4.returncode == 0, r4.stdout + r4.stderr
    report = json.loads((output_dir / "audit_report.json").read_text(encoding="utf-8"))
    issue_ids = [issue["issue_id"] for issue in report["issues"]]
    assert any(
        issue_id.startswith("iss_outline_char_missing_") for issue_id in issue_ids
    )
    assert report["outline_used"] is True
    assert report["outline_arcs_count"] > 0
