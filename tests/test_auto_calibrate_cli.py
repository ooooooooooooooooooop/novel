"""auto_calibrate_short_form CLI 测试（design §10 / T7.4–T7.6）.

calibration 冻结阈值（唯一来源）+ holdout 只读验证 + 凭证无关审计 + 隐私红线
（产物不含正文/提示词）+ 退出码（holdout 未达标 → 1，禁止据 holdout 调低阈值）.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from src.auto_calibrate_short_form import main as calibrate_main
from src.object_state.autonomous import AutonomousPolicy, ProviderProfile

# 合成基准：chosen 恒含「甲文」标记，rejected 恒含「乙文」标记——fake 评审按
# 内容稳定偏好「甲文」，既正确（选 chosen）又换位稳定（两轮命名同一内容）。
_CALIBRATION = 12  # 12 个不同 prompt_id ≥ MIN_CALIBRATION_PROMPT_IDS(10)
_HOLDOUT = 4


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """隔离进程环境中的 Anthropic 凭据变量（env-first 适配器下走 settings 文件路径）."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def _bench_row(prompt_id: str, tag: str, split: str) -> dict:
    marker = "甲文" if split == "calibration" else "甲文"
    return {
        "prompt_id": prompt_id,
        "tag": tag,
        "prompt": "写一个故事",
        "chosen": {"response": f"{marker}-{prompt_id}-优选"},
        "rejected": {"response": f"乙文-{prompt_id}-次选"},
    }


def _tags_for(index: int) -> str:
    return "悬疑-推理故事" if index % 2 == 0 else "仙侠小说"


def _write_bench(tmp_path: Path):
    rows = []
    calibration_rows: list[dict] = []
    holdout_rows: list[dict] = []
    for index in range(_CALIBRATION + _HOLDOUT):
        is_calib = index < _CALIBRATION
        prompt_id = f"prompt-{index:04d}"
        tag = _tags_for(index)
        row = _bench_row(prompt_id, tag, "calibration" if is_calib else "holdout")
        rows.append(row)
        (calibration_rows if is_calib else holdout_rows).append(
            {"row_index": index, "prompt_id": prompt_id, "tag": tag, "bucket": 0 if is_calib else 1}
        )
    bench_path = tmp_path / "bench.json"
    bench_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "selection": {
            "calibration_buckets": [0],
            "holdout_buckets": [1],
        },
        "calibration": calibration_rows,
        "holdout": holdout_rows,
    }
    split_path = tmp_path / "split.json"
    split_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return bench_path, split_path


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _policy_payload(bench_path: Path, split_path: Path) -> dict:
    return {
        "schema_version": "1.0",
        "policy_id": "policy-calib-test",
        "provider_profile_id": "profile-calib-test",
        "runtime": {
            "manual_allowed": False,
            "waiting_allowed": False,
            "provider_fallback_allowed": False,
            "network_retry_allowed": False,
            "max_provider_attempts_per_call": 1,
            "resume_may_skip_gate": False,
        },
        "search": {
            "premise_candidates": 1,
            "plot_candidates": 2,
            "prose_variants_per_plot": 2,
            "max_decision_rounds": 1,
            "pairwise_orderings": ["A/B", "B/A"],
            "judge_roles": ["reader_judge", "fact_judge", "character_judge"],
        },
        "chapter": {
            "target_chinese_characters_min": 100,
            "target_chinese_characters_max": 2000,
            "planner_max_output_tokens": 100,
            "prose_max_output_tokens": 100,
            "judge_max_output_tokens": 500,
        },
        "budget": {
            "max_total_calls": 200,
            "max_total_input_tokens": 1000000,
            "max_total_output_tokens": 100000,
            "max_total_cost_usd": 10,
            "max_wall_clock_seconds": 1000,
            "max_chapters_per_run": 1,
            "max_canary_runs": 3,
            "max_canary_chapters_total": 3,
        },
        "evaluation": {
            "holdout_overall_accuracy_min": 0.65,
            "holdout_genre_accuracy_min": 0.5,
            "pairwise_position_consistency_min": 0.9,
            "hard_fact_conflicts_allowed": 0,
            "manual_routes_allowed": 0,
            "unarmed_required_axes_allowed": 0,
        },
        "benchmarks": {
            "preference_source": str(bench_path),
            "preference_source_sha256": _sha256_file(bench_path),
            "preference_split_manifest": str(split_path),
            "preference_split_manifest_sha256": _sha256_file(split_path),
            "human_distribution_manifest": "human.json",
            "human_distribution_manifest_sha256": "c" * 64,
        },
        "canary": {
            "genres": ["悬疑", "仙侠", "都市"],
            "chapters_per_genre": 1,
            "long_horizon_checkpoints": [1],
        },
    }


def _profile_payload() -> dict:
    return {
        "schema_version": "1.0",
        "profile_id": "profile-calib-test",
        "transport": "anthropic_messages_http",
        "endpoint": {
            "settings_path_from_user_home": ".claude/settings.json",
            "base_url_json_path": "env.ANTHROPIC_BASE_URL",
            "credential_json_path": "env.ANTHROPIC_AUTH_TOKEN",
            "messages_path": "/v1/messages",
            "auth_scheme": "bearer",
            "anthropic_version": "2023-06-01",
            "user_agent": "AutomaticNovelNarrativeSystem/0.1",
            "timeout_seconds": 10,
            "max_attempts": 1,
        },
        "provider_audit": {
            "database_path_from_user_home": ".cc-switch/cc-switch.db",
            "provider_id": "provider-id",
            "provider_name": "provider-name",
            "provider_category": "third_party",
            "upstream_url": "http://127.0.0.1:15721",
            "expected_actual_model": "model-a",
            "failover_allowed": False,
        },
        "roles": {
            role: {
                "request_model": "model-a",
                "expected_actual_model": "model-a",
                "temperature": 0.0 if role != "generation" else 0.7,
            }
            for role in ("generation", "fact_judge", "character_judge", "reader_judge")
        },
        "pricing_usd_per_million_tokens": {
            "input": 0.14,
            "output": 0.28,
            "cache_read": 0.0028,
            "cache_creation": 0,
            "source": "pricing-table",
            "frozen_at": "2026-08-12",
        },
        "smoke_evidence": {
            "request_model": "model-a",
            "actual_model": "model-a",
            "input_tokens": 10,
            "output_tokens": 2,
            "cost_usd": 0.000002,
            "status_code": 200,
        },
    }


def _provider_files(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://127.0.0.1:15721",
                    "ANTHROPIC_AUTH_TOKEN": "secret-value",
                }
            }
        ),
        encoding="utf-8",
    )
    import sqlite3

    db_dir = tmp_path / ".cc-switch"
    db_dir.mkdir()
    with sqlite3.connect(db_dir / "cc-switch.db") as connection:
        connection.execute(
            """
            CREATE TABLE providers (
                id TEXT, app_type TEXT, name TEXT, in_failover_queue INTEGER,
                settings_config TEXT, is_current INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO providers VALUES (?, 'claude', 'provider-name', 0, ?, 1)",
            (
                "provider-id",
                json.dumps({"env": {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "model-a"}}),
            ),
        )


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _success_payload(text: str, model: str = "model-a") -> dict:
    return {
        "type": "message",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 4,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _fake_urlopen(calls: list, *, prefer_marker: str = "甲文"):
    """按 G7 内容无关协议模拟 provider：单候选评审 + 证据锚定仲裁（内容稳定）.

    评审按候选正文是否含 prefer_marker 给 satisfied/violated（内容决定，与展示顺序
    无关）；锚点逐字取自候选正文 → 锚点真实性必然通过。需要仲裁时引用被选候选评审
    证据里的「锚点原文」，同样逐字存在于其正文。
    """

    def fake(request, timeout=None):
        calls.append(request)
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][-1]["content"]
        if "【单候选评审】" in prompt:
            return _fake_review_response(prompt, prefer_marker)
        if "【证据锚定仲裁】" in prompt:
            return _fake_arbitration_response(prompt, prefer_marker)
        raise AssertionError("unknown prompt type in fake provider")

    return fake


def _fake_review_response(prompt: str, prefer_marker: str):
    start_marker = "【待评审候选】\n"
    start = prompt.find(start_marker)
    assert start >= 0, "single-review prompt must contain 【待评审候选】"
    prose = prompt[start + len(start_marker):]
    end_marker = "\n\n【评审要求】"
    end = prose.find(end_marker)
    assert end > 0, "single-review prompt must end before 【评审要求】"
    prose = prose[:end].rstrip()
    assert prose, "candidate prose empty"
    excerpt = prose[:12]  # 逐字取自候选正文 → 锚点真实
    verdict = "satisfied" if prefer_marker in prose else "violated"
    payload = {
        "content_digest": (
            f"含{prefer_marker}的候选" if verdict == "satisfied"
            else f"不含{prefer_marker}的候选"
        ),
        "claims": [
            {
                "claim_id": "c1",
                "axis": "推进",
                "verdict": verdict,
                "severity": "advisory",
                "anchors": [
                    {"excerpt": excerpt, "char_start": 0, "char_end": len(excerpt)}
                ],
                "confidence": 0.9,
                "rationale": "测试注入。",
            }
        ],
        "experience_rating": 4 if verdict == "satisfied" else 1,
        "overall_confidence": 0.8,
        "abstain": False,
        "abstain_reason": "",
    }
    return _Response(_success_payload(json.dumps(payload, ensure_ascii=False)))


def _section(prompt: str, header: str, next_headers: list[str]) -> str:
    start = prompt.find(header)
    assert start >= 0, f"prompt missing {header!r}"
    body = prompt[start + len(header):]
    for nxt in next_headers:
        pos = body.find("\n" + nxt)
        if pos >= 0:
            return body[:pos].strip()
    return body.strip()


def _fake_arbitration_response(prompt: str, prefer_marker: str):
    digest_a = _section(prompt, "【候选甲 内容摘要】\n", ["【候选甲 评审证据】"])
    digest_b = _section(prompt, "【候选乙 内容摘要】\n", ["【候选乙 评审证据】"])
    preferred = "A" if prefer_marker in digest_a else "B"
    evidence_header = f"【候选{'甲' if preferred == 'A' else '乙'} 评审证据】\n"
    evidence = _section(
        prompt, evidence_header, ["【候选甲 内容摘要】", "【候选乙 内容摘要】"]
    )
    match = re.search(r"\[(anc_[0-9a-f]+)\]", evidence)
    assert match, "arbitration evidence must contain content anchor id"
    payload = {
        "decision": "anchor",
        "decisive_anchor_id": match.group(1),
        "rationale": "测试注入仲裁。",
    }
    return _Response(_success_payload(json.dumps(payload, ensure_ascii=False)))


def _run_cli(tmp_path: Path, monkeypatch, *, prefer_marker="甲文", **kwargs):
    bench_path, split_path = _write_bench(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(_policy_payload(bench_path, split_path), ensure_ascii=False),
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(_profile_payload(), ensure_ascii=False), encoding="utf-8"
    )
    _provider_files(tmp_path)
    output_dir = tmp_path / "out"
    calls: list = []
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls, prefer_marker=prefer_marker),
    )
    argv = [
        "auto_calibrate_short_form.py",
        "--output-dir", str(output_dir),
        "--policy", str(policy_path),
        "--profile", str(profile_path),
        "--role", "reader_judge",
        "--user-home", str(tmp_path),
        "--position-sample", "2",
    ]
    for key, value in kwargs.items():
        argv.extend([f"--{key}", str(value)])
    monkeypatch.setattr(sys, "argv", argv)
    return calibrate_main(), output_dir, calls


def test_calibrate_met_freeze_thresholds_and_holdout(tmp_path, monkeypatch):
    # 内容稳定正确评审 → calibration 冻结阈值 + holdout 只读达标 → exit 0.
    rc, output_dir, calls = _run_cli(tmp_path, monkeypatch)
    assert rc == 0
    result = json.loads(
        (output_dir / "calibration_result.json").read_text(encoding="utf-8")
    )
    assert result["route"] == "pass"
    assert result["holdout"]["met"] is True
    thresholds = json.loads(
        (output_dir / "thresholds.json").read_text(encoding="utf-8")
    )
    assert thresholds["generated_from"] == "calibration_split"
    assert thresholds["role"] == "reader_judge"
    assert thresholds["overall_accuracy_min"] == 0.65
    # 唯一来源 = calibration：阈值冻结证据记录 calibration 跨度
    assert thresholds["calibration_span"]["distinct_prompt_ids"] == _CALIBRATION
    assert thresholds["calibration_span"]["distinct_tags"] == 2
    # holdout 只读：不回写阈值
    holdout = json.loads(
        (output_dir / "holdout_report.json").read_text(encoding="utf-8")
    )
    assert holdout["thresholds_id"] == thresholds["thresholds_id"]
    assert holdout["dimension_met"]["overall"] is True
    assert holdout["dimension_met"]["position_consistency"] is True
    # 逐调用凭证无关审计存在（prompt 只记 SHA-256）
    audits = sorted((output_dir / "calls").glob("call_*.json"))
    assert audits
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert audit["status"] == "success"
    assert audit["request_model"] == "model-a"
    assert len(audit["prompt_sha256"]) == 64
    assert "prose" not in audit


def test_calibrate_no_prose_leak_in_artifacts(tmp_path, monkeypatch):
    # 隐私红线：所有产物（含审计）不含正文内容/提示词，只含哈希与元数据.
    rc, output_dir, _ = _run_cli(tmp_path, monkeypatch)
    assert rc == 0
    for name in (
        "calibration_result.json",
        "calibration_report.json",
        "thresholds.json",
        "holdout_report.json",
    ):
        text = (output_dir / name).read_text(encoding="utf-8")
        assert "甲文-" not in text, name  # 正文内容绝不进入产物
        assert "写一个故事" not in text, name  # 提示词不进入产物
    for audit_path in (output_dir / "calls").glob("call_*.json"):
        text = audit_path.read_text(encoding="utf-8")
        assert "甲文-" not in text


def test_calibrate_fail_when_holdout_unmet(tmp_path, monkeypatch):
    # 恒偏好「乙文」（错误 + 换位不稳定）→ 准确率/位置一致性全不达标 → exit 1.
    rc, output_dir, _ = _run_cli(
        tmp_path, monkeypatch, prefer_marker="乙文"
    )
    assert rc == 1
    result = json.loads(
        (output_dir / "calibration_result.json").read_text(encoding="utf-8")
    )
    assert result["route"] == "fail"
    assert result["holdout"]["met"] is False
    assert result["holdout"]["violations"]
    # 阈值仍冻结（holdout 未回写阈值）
    assert (output_dir / "thresholds.json").is_file()


def test_calibrate_rejects_bench_sha_mismatch(tmp_path, monkeypatch):
    # 冻结 SHA-256 不匹配 → 拒绝载入，exit 1，零 provider 调用.
    bench_path, split_path = _write_bench(tmp_path)
    # 篡改 bench 内容后其哈希与 policy.benchmarks 记录不一致
    bench_path.write_text(
        bench_path.read_text(encoding="utf-8") + "\ntampered",
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(_policy_payload(bench_path, split_path), ensure_ascii=False),
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(_profile_payload(), ensure_ascii=False), encoding="utf-8"
    )
    _provider_files(tmp_path)
    output_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", [
        "auto_calibrate_short_form.py",
        "--output-dir", str(output_dir),
        "--policy", str(policy_path),
        "--profile", str(profile_path),
        "--user-home", str(tmp_path),
    ])
    rc = calibrate_main()
    assert rc == 1
    assert not (output_dir / "calls").exists()


def test_policy_provider_mismatch_rejected(tmp_path, monkeypatch):
    # policy.provider_profile_id != profile.profile_id → 拒绝，exit 1.
    bench_path, split_path = _write_bench(tmp_path)
    policy = _policy_payload(bench_path, split_path)
    policy["provider_profile_id"] = "other-profile"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(_profile_payload(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "argv", [
        "auto_calibrate_short_form.py",
        "--output-dir", str(tmp_path / "out"),
        "--policy", str(policy_path),
        "--profile", str(profile_path),
        "--user-home", str(tmp_path),
    ])
    assert calibrate_main() == 1


def test_policy_and_profile_models_valid():
    # 合成 policy/profile 本身能通过冻结模型校验（结构契约）。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        b, s = _write_bench(Path(tmp))
        payload = _policy_payload(b, s)
        AutonomousPolicy.model_validate(payload)
        ProviderProfile.model_validate(_profile_payload())
