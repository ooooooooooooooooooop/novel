"""Tests for the deepseek_active bundle rebuild entry (scripts/build_deepseek_active_bundle.py).

锁死跨设备接力契约（消息 321a4259 验收；split 事实纠正 35a5fda0）：
* builder 恰好写出 4 个 bundle 文件（active_provider / profile / canary_policy / setup_manifest）。
* 输出字节稳定幂等（重跑 diff 为空）。
* 输出不含凭证值 / 私有端点 URL / 机器绝对路径 / 小说名或正文（复用脚本内隐私闸）。
* 冻结 G7 阈值 0.65/0.5/0.9 不得降低；split 用**无交叉 v2 划分**
  `split_manifest_v2.json`（c45cd6ad，103 cal / 35 holdout），**非**旧污染
  `split_manifest.json`（20864f82，165 cal / 43 holdout，被 A1 早期调参）。
  测试用实际文件字节计算 v2 SHA 并断言与 policy 声明一致（干净哈希绝不配到错文件）。
* 生成 profile/policy 必须通过真实 `ProviderProfile` / `AutonomousPolicy` Pydantic 校验
  （provider_audit.database_path_from_user_home=`.cc-switch/cc-switch.db` 既有跨设备合同，
  非 env 假值）。
* 端点/凭证经 env 变量**名**引用（env.ANTHROPIC_BASE_URL 等），不落任何值；唯一含 URL 的
  输出字段是 runtime profile 的 provider_audit.upstream_url（执行时从 ANTHROPIC_BASE_URL
  注入**实际值**，缺失即显式失败，值不打印）；其余输出无 URL/凭证/机器路径/小说内容。
* provider_audit 的 id/name/expected_actual_model 由执行时从 cc-switch **当前 claude
  provider** 冻结（`CC_SWITCH_DB` env 指向的 DB，测试注入夹具 DB，与真实 DB/凭据隔离）——
  非 stylized 标签（ProviderAdapter 构造时以相同查询核对）；当前 provider 非生产允许模型
  deepseek-v4-flash 或处于 failover 即显式失败。settings_config 中的凭证值绝不读取打印。

无 provider/LLM 调用；纯确定性文件生成。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.object_state.autonomous import AutonomousPolicy, ProviderProfile

REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "build_deepseek_active_bundle", REPO_ROOT / "scripts" / "build_deepseek_active_bundle.py"
)
bd = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(bd)

EXPECTED_FILES = [
    "active_provider.json",
    "provider_profile_deepseek_v4_flash.json",
    "canary_policy_deepseek_v4_flash.json",
    "setup_manifest.json",
]

# 无交叉 v2 划分（build_split_manifest_v2.py 生成，1024 字节校验）
SPLIT_V2_PATH = (
    "reference_texts/a1_benchmark/sources/writing_preference_bench/split_manifest_v2.json"
)
SPLIT_V2_SHA256 = "c45cd6ad1640fb9688aba6bdb65973bc886237ca3f3b7d7555c9d86390f9ac01"


def _actual_split_sha256() -> str:
    """计算仓库内 split_manifest_v2.json 的实际字节 SHA（校准 loader 的同一来源）。"""
    return hashlib.sha256((REPO_ROOT / SPLIT_V2_PATH).read_bytes()).hexdigest()


def _write_fixture_db(
    tmp_path: Path,
    *,
    provider_id: str = "fixture-deepseek-id",
    provider_name: str = "Fixture DeepSeek",
    model: str = "deepseek-v4-flash",
    in_failover: int = 0,
    is_current: int = 1,
) -> Path:
    """写一个夹具 cc-switch DB（当前 claude provider 行）；与真实 DB/凭据完全隔离."""
    db_path = tmp_path / "db" / "cc-switch.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE IF EXISTS providers")
    con.execute(
        "CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, "
        "in_failover_queue INTEGER, settings_config TEXT, is_current INTEGER)"
    )
    con.execute(
        "INSERT INTO providers VALUES (?, 'claude', ?, ?, ?, ?)",
        (
            provider_id,
            provider_name,
            in_failover,
            json.dumps({"env": {"ANTHROPIC_DEFAULT_HAIKU_MODEL": model}}),
            is_current,
        ),
    )
    con.commit()
    con.close()
    return db_path


@pytest.fixture(autouse=True)
def _deepseek_env(monkeypatch, tmp_path_factory):
    """builder main() 执行时从 ANTHROPIC_BASE_URL 注入实际上游 URL；测试注入不冲突的
    显式值（https://provider.invalid），与真实凭据/端点完全隔离；cc-switch DB 指向夹具
    DB（当前 claude provider = deepseek-v4-flash，放在测试 tmp_path 之外，不污染
    output_dir 计数），与真实 DB/凭据隔离。"""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://provider.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")
    db_dir = tmp_path_factory.mktemp("fixture_db")
    monkeypatch.setenv("CC_SWITCH_DB", str(_write_fixture_db(db_dir)))
    yield


def _run(tmp_path: Path):
    assert bd.main(output_dir=tmp_path)
    return {name: (tmp_path / name).read_text(encoding="utf-8") for name in EXPECTED_FILES}


def test_build_produces_exactly_four_bundle_files(tmp_path):
    contents = _run(tmp_path)
    assert set(contents) == set(EXPECTED_FILES)
    assert len(list(tmp_path.iterdir())) == 4


def test_build_is_idempotent_byte_stable(tmp_path):
    _run(tmp_path)
    first = {(name): (tmp_path / name).read_bytes() for name in EXPECTED_FILES}
    _run(tmp_path)  # 重跑
    for name in EXPECTED_FILES:
        assert (tmp_path / name).read_bytes() == first[name], f"{name} 字节漂移"


def test_build_output_has_no_forbidden_secrets(tmp_path):
    contents = _run(tmp_path)
    upstream = os.environ["ANTHROPIC_BASE_URL"].rstrip("/")
    for name, text in contents.items():
        # 唯一合法 URL：runtime profile 的 provider_audit.upstream_url（env 注入的实际上游
        # 身份）。掩码后任何其他 URL/凭证/机器路径/小说内容即断言失败。
        masked = text.replace(upstream, "<upstream-url-redacted>")
        bd._assert_no_secrets(masked)
        low = masked.lower()
        assert "sk-" not in low
        assert "bearer " not in low
        assert "https://" not in low and "http://" not in low
        assert "/users/" not in low and ":\\users\\" not in low
    profile = json.loads(contents["provider_profile_deepseek_v4_flash.json"])
    assert profile["provider_audit"]["upstream_url"] == upstream
    # 端点/凭证引用仍是 env 变量**名**而非值（profile 用 dot 记法，与既有 Provider 档案一致）
    assert "env.ANTHROPIC_BASE_URL" in contents["provider_profile_deepseek_v4_flash.json"]
    assert "env.ANTHROPIC_AUTH_TOKEN" in contents["provider_profile_deepseek_v4_flash.json"]


def test_build_template_upstream_url_is_env_name_not_value():
    """tracked 模板的 upstream_url 是 env 符号名（env:ANTHROPIC_BASE_URL），绝不落端点值；
    实际值只由 main() 在写 gitignored runtime profile 时从 env 注入。"""
    profile = bd._profile()
    assert profile["provider_audit"]["upstream_url"] == "env:ANTHROPIC_BASE_URL"
    # 模板本身通过完整隐私闸（env 符号名不是 URL；模板含任何 URL/凭证/路径即断言失败）
    bd._assert_no_secrets(bd._dump(profile))


def test_build_requires_base_url_env(tmp_path, monkeypatch):
    """ANTHROPIC_BASE_URL 缺失 → 显式失败，不产出任何 bundle 文件（不回落描述性假值）。"""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_BASE_URL"):
        bd.main(output_dir=tmp_path)
    assert not (tmp_path / "provider_profile_deepseek_v4_flash.json").exists()
    assert not (tmp_path / "active_provider.json").exists()


def test_build_derives_provider_identity_from_live_db(tmp_path):
    """provider_audit 的 id/name/expected_actual_model 冻结自 cc-switch 当前 claude
    provider（夹具 DB）——非 stylized 标签；与 ProviderAdapter 构造时同查询核对逐字一致。"""
    contents = _run(tmp_path)
    profile = json.loads(contents["provider_profile_deepseek_v4_flash.json"])
    pa = profile["provider_audit"]
    assert pa["provider_id"] == "fixture-deepseek-id"
    assert pa["provider_name"] == "Fixture DeepSeek"
    assert pa["expected_actual_model"] == "deepseek-v4-flash"
    assert pa["failover_allowed"] is False
    # active selector 仍是模型标签声明（与 provider 行身份分离的公共事实）
    active = json.loads(contents["active_provider.json"])
    assert active["active_provider"] == "deepseek_v4_flash"


def test_build_refuses_non_deepseek_current_provider(tmp_path, monkeypatch):
    """当前 claude provider 非生产允许模型 deepseek-v4-flash → 显式失败，不写任何文件。"""
    monkeypatch.setenv(
        "CC_SWITCH_DB", str(_write_fixture_db(tmp_path, model="kimi-k2.6"))
    )
    with pytest.raises(RuntimeError, match="deepseek-v4-flash"):
        bd.main(output_dir=tmp_path)
    assert not (tmp_path / "provider_profile_deepseek_v4_flash.json").exists()


def test_build_refuses_failover_current_provider(tmp_path, monkeypatch):
    """当前 provider 处于 failover 队列 → 显式失败（禁止冻结 failover provider）。"""
    monkeypatch.setenv(
        "CC_SWITCH_DB", str(_write_fixture_db(tmp_path, in_failover=1))
    )
    with pytest.raises(RuntimeError, match="failover"):
        bd.main(output_dir=tmp_path)
    assert not (tmp_path / "active_provider.json").exists()


def test_build_frozen_thresholds_and_uncontaminated_split(tmp_path):
    contents = _run(tmp_path)
    policy = json.loads(contents["canary_policy_deepseek_v4_flash.json"])
    ev = policy["evaluation"]
    assert ev["holdout_overall_accuracy_min"] == 0.65
    assert ev["holdout_genre_accuracy_min"] == 0.5
    assert ev["pairwise_position_consistency_min"] == 0.9
    assert policy["runtime"]["network_retry_allowed"] is False
    assert policy["runtime"]["provider_fallback_allowed"] is False
    # split 用无交叉 v2 划分：路径指向 split_manifest_v2.json，且声明哈希 == 实际文件字节 SHA
    assert policy["benchmarks"]["preference_split_manifest"] == SPLIT_V2_PATH
    assert policy["benchmarks"]["preference_split_manifest_sha256"] == SPLIT_V2_SHA256
    assert _actual_split_sha256() == SPLIT_V2_SHA256
    # 不得回落到旧污染划分 split_manifest.json / 20864f82
    assert "split_manifest.json" != Path(
        policy["benchmarks"]["preference_split_manifest"]
    ).name
    # v2 manifest 实际内容：103 cal / 35 holdout、文学非虚构 tag、cal/holdout 零交叉
    v2 = json.loads((REPO_ROOT / SPLIT_V2_PATH).read_text(encoding="utf-8-sig"))
    assert len(v2["calibration"]) == 103 and len(v2["holdout"]) == 35
    calib_ids = {e["prompt_id"] for e in v2["calibration"]}
    holdout_ids = {e["prompt_id"] for e in v2["holdout"]}
    assert not (calib_ids & holdout_ids)
    assert policy["budget"]["max_total_cost_usd"] == "25.0"


def test_build_profile_passes_provider_profile_validation(tmp_path):
    """生成 profile 必须通过真实 ProviderProfile 校验，且 DB 走既有跨设备合同
    ``.cc-switch/cc-switch.db``（ProviderAdapter 做 ``user_home / 该路径``，不解析 env 值）。
    """
    contents = _run(tmp_path)
    profile = ProviderProfile.model_validate(
        json.loads(contents["provider_profile_deepseek_v4_flash.json"])
    )
    assert profile.provider_audit.database_path_from_user_home == ".cc-switch/cc-switch.db"
    assert profile.endpoint.settings_path_from_user_home == ".claude/settings.json"
    assert profile.endpoint.base_url_json_path == "env.ANTHROPIC_BASE_URL"
    assert profile.endpoint.credential_json_path == "env.ANTHROPIC_AUTH_TOKEN"
    # 模型级 validator 已冻结：所有 role 的 expected_actual_model 与 smoke/audit 一致
    assert profile.provider_audit.expected_actual_model == bd.MODEL
    assert profile.smoke_evidence.actual_model == bd.MODEL


def test_build_policy_passes_autonomous_policy_validation(tmp_path):
    """生成 policy 必须通过真实 AutonomousPolicy 校验，且声明 split 哈希与实际文件字节一致
    （干净哈希绝不配到错文件——旧污染 20864f82/split_manifest.json 的错配会在此失败）。
    """
    contents = _run(tmp_path)
    policy = AutonomousPolicy.model_validate(
        json.loads(contents["canary_policy_deepseek_v4_flash.json"])
    )
    assert policy.benchmarks.preference_split_manifest_sha256 == _actual_split_sha256()
    assert policy.benchmarks.preference_split_manifest == SPLIT_V2_PATH
    assert policy.benchmarks.preference_split_manifest_sha256 == SPLIT_V2_SHA256
    assert policy.evaluation.holdout_overall_accuracy_min == 0.65
    assert policy.budget.max_total_cost_usd > 0


def test_build_judge_roles_disable_thinking(tmp_path):
    """deepseek-v4-flash 是 thinking-native provider：judge 角色必须发
    ``thinking: {"type": "disabled"}``，否则隐藏思考 token 耗尽 judge 输出预算、
    JSON text 块被截断（ProviderSchemaError）。生成角色不强制（M2 只用 judge）。"""
    contents = _run(tmp_path)
    profile = ProviderProfile.model_validate(
        json.loads(contents["provider_profile_deepseek_v4_flash.json"])
    )
    for name in ("fact_judge", "character_judge", "reader_judge"):
        assert getattr(profile.roles, name).thinking_disabled is True, name
    assert profile.roles.generation.thinking_disabled is False


def test_build_active_selector_points_only_deepseek(tmp_path):
    contents = _run(tmp_path)
    active = json.loads(contents["active_provider.json"])
    assert active["active_provider"] == "deepseek_v4_flash"
    assert active["run_id_namespace"] == "canary-deepseek-active-<seq>"
    assert active["credential_model"]["cc_switch_db"] == "env:CC_SWITCH_DB"
    manifest = json.loads(contents["setup_manifest.json"])
    assert manifest["launcher"]["args"]["--flow-mode"] == "compose"
    assert "--policy" in manifest["launcher"]["args"]
