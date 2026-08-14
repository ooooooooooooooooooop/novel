#!/usr/bin/env python3
"""Rebuild the deepseek_active provider bundle (privacy-safe, cross-device handoff).

为什么需要本脚本：`runtime/refs/deepseek_active/*` 与 `.taskflow/*` 均被 .gitignore 排除
（Provider 配置/证据不入 GitHub），不能单独作为 GitHub 接力交付。本脚本是一个**可跟踪、
隐私安全的重建入口**：只写 Provider/model/环境变量**名**和确定性政策，**不写**凭证值、
私有端点、机器路径、小说名/正文。在其他设备设置获准环境变量（ANTHROPIC_BASE_URL /
ANTHROPIC_AUTH_TOKEN / CC_SWITCH_DB）后，可重建同结构的本地 bundle。

本 bundle 登记的是 switchboard 72606eb9 传达的「用户直接确认：deepseek-v4-flash 唯一
默认生产模型」决定。**诚实警示（冻结门不降）**：deepseek-v4-flash 自有证据无法通过冻结
G7 阈值（评审 holdout overall 0.6129<0.65、生成 4/4 冒烟失败）；M1 已删除评审协议合规
重请求。因此本 bundle 是活动配置登记，不构成能通过 G7/G8 的可执行路径；任何实际运行
会在资格门显式失败并保留证据。k3 冻结 G0/哈希/证据（runtime/refs/t8_canary/*、
g0_report.json、calibrate-kimi-k3-full/calls/）一律不改写。

不变式（本脚本以断言锁死，防漂移）：
- 冻结阈值 holdout_overall_accuracy_min=0.65 / holdout_genre_accuracy_min=0.5 /
  pairwise_position_consistency_min=0.9，**不得降低**。
- preference split 用**无交叉 v2 划分** `split_manifest_v2.json`（c45cd6ad，103 cal / 35
  holdout，文学非虚构 tag）；旧污染划分 `split_manifest.json`（20864f82，165 cal / 43
  holdout，叙事 tag，被 A1 早期轮次用于协议调参）已废弃——**不得**把干净哈希配到该文件。
  `main()` 运行时用实际文件字节校验 v2 SHA，防漂移/错配。
- 输出 JSON 确定性幂等（sort_keys + 固定 indent），重跑字节不变。
- 输出（gitignored runtime 本地证据）唯一含 URL 的字段是 provider_audit.upstream_url，
  由执行时 `ANTHROPIC_BASE_URL` env 注入**实际值**（缺失即显式失败、值不打印）；tracked
  模板/文档不含任何凭证值 / URL / 机器绝对路径 / 小说名或正文。ProviderAdapter 调用前
  校验已加载 base_url 与 profile 的 upstream_url 一致（规范化尾斜杠）。

用法：python scripts/build_deepseek_active_bundle.py
产物：runtime/refs/deepseek_active/（active_provider.json + provider_profile_*.json +
      canary_policy_*.json + setup_manifest.json；均 gitignored 本地冻结证据）
"""

import hashlib
import json
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "runtime/refs/deepseek_active"

# ---- 公共常量（只含 Provider/model/环境变量名/确定性政策；无凭证值、无私有端点 URL）----

# Provider 身份（公共事实）
PROVIDER_ID = "deepseek_v4_flash"
PROVIDER_NAME = "OpenCode"
PROVIDER_CATEGORY = "third_party"
MODEL = "deepseek-v4-flash"
PROFILE_ID = "ccswitch-opencode-go-deepseek-v4-flash-20260811"

# 环境变量**名**（凭据/端点值由获准环境在目标设备运行时注入，本脚本永不读取/打印）
ENV_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
ENV_CC_SWITCH_DB = "CC_SWITCH_DB"

# 冻结阈值（不得降低）
THRESHOLD_OVERALL = 0.65
THRESHOLD_GENRE = 0.5
THRESHOLD_POSITION = 0.9

# 冻结基准哈希（与 k3 冻结 G0 同源；**split 用无交叉 v2 划分**，见模块 docstring）
SPLIT_MANIFEST_PATH = (
    "reference_texts/a1_benchmark/sources/writing_preference_bench/split_manifest_v2.json"
)
SPLIT_MANIFEST_SHA256 = "c45cd6ad1640fb9688aba6bdb65973bc886237ca3f3b7d7555c9d86390f9ac01"
SOURCE_SHA256 = "fd9c8faf85b7f4ae4b48f938c9fd608e5ed2011f726789130b37c1588f2ab6e0"
HUMAN_SHA256 = "96c8dffbe12238f9a4823da2b3e2aca204d411bf927ce8f140924c9c05042ebf"

# 活动 bundle 元数据
EVIDENCE_VERSION = "deepseek-active-v20260814-m1b"
RUN_ID_NAMESPACE = "canary-deepseek-active-<seq>"
DECISION_SOURCE = "switchboard 72606eb9（声称用户决定已直接确认）"

# 隐私守卫：不得出现在任何输出中的凭证值/私有端点模式（测试亦复用）
FORBIDDEN_PATTERNS = [
    r"(?i)sk-[a-z0-9]{8,}",           # API key 形态
    r"Bearer [A-Za-z0-9._~+/=-]{8,}",  # Authorization 头
    r"https?://[^\s\"']*",            # 任何私有/公开 URL（端点一律走 env 变量名）
    r"[A-Za-z]:\\\\Users\\\\[^\"']+",  # Windows 用户绝对路径
    r"/home/[^\s\"']*",               # Unix 用户绝对路径
]

GENRES = ["contemporary_officialdom", "mythic_fantasy", "historical_strategy"]


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _assert_no_secrets(text: str) -> None:
    for pat in FORBIDDEN_PATTERNS:
        assert not re.search(pat, text), f"forbidden pattern leaked: {pat}"


def _assert_split_manifest_bytes() -> None:
    """用实际文件字节校验 v2 split 哈希：干净哈希绝不配到错误/陈旧/缺失文件."""
    path = REPO_ROOT / SPLIT_MANIFEST_PATH
    assert path.is_file(), f"v2 split manifest missing: {path}"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == SPLIT_MANIFEST_SHA256, (
        f"v2 split manifest SHA drift: expected {SPLIT_MANIFEST_SHA256}, got {actual} "
        f"({path})"
    )


def _load_env_base_url() -> str:
    """读取 ANTHROPIC_BASE_URL **实际值**，注入 gitignored runtime profile 的 upstream_url.

    缺失/空白即显式失败——runtime profile 的 upstream_url 必须是实际上游身份，不能回落到
    描述性假值或 env 符号名。值本身绝不打印、绝不进入 tracked 字节（GitHub 只看 tracked）。
    """
    value = os.environ.get(ENV_BASE_URL, "").strip().rstrip("/")
    if not value:
        raise RuntimeError(
            f"{ENV_BASE_URL} is required to rebuild the runtime profile "
            "(actual upstream URL is injected into the gitignored runtime profile; "
            "never printed or committed)"
        )
    return value


def _active_provider() -> dict:
    return {
        "schema_version": "1.0",
        "active_provider": PROVIDER_ID,
        "status": "active",
        "evidence_version": EVIDENCE_VERSION,
        "run_id_namespace": RUN_ID_NAMESPACE,
        "decision_source": DECISION_SOURCE,
        "provider_eligibility": {
            "production_only": "OpenCode deepseek-v4-flash (deepseek_v4_flash)",
            "future_m2_candidate": "CPA Gemini（仅作 M2 待资格候选，未资格化前不启用）",
            "disabled": ["kimi k3（K3 禁用 2026-08-14；冻结证据只读保留）"],
        },
        "active_policy": {
            "policy_id": "a1-q2a-canary-deepseek-v4-flash-m1",
            "file": "runtime/refs/deepseek_active/canary_policy_deepseek_v4_flash.json",
            "split_manifest_sha256": SPLIT_MANIFEST_SHA256,
            "note": "使用无交叉 v2 划分 split_manifest_v2.json（103 cal / 35 holdout）；"
                    "旧污染划分 split_manifest.json/20864f82 已废弃",
        },
        "credential_model": {
            "base_url": f"env:{ENV_BASE_URL}",
            "auth_token": f"env:{ENV_AUTH_TOKEN}",
            "cc_switch_db": f"env:{ENV_CC_SWITCH_DB}",
            "note": "凭据/端点值由获准环境变量在目标设备注入；本 bundle 不保存任何值",
        },
        "honest_caveat": [
            "deepseek-v4-flash 自有证据无法通过冻结门：评审 holdout overall 0.6129<0.65；生成 4/4 冒烟失败。",
            "M1（2026-08-14）删除评审协议合规重请求：单次真实能力只会更诚实失败。",
            "本 bundle 是活动配置登记（按传达决定），不构成能通过 G7/G8 的可执行路径；实际运行在资格门显式失败并保留证据。",
            "preference split 用无交叉 v2 划分（split_manifest_v2.json/c45cd6ad，103 cal/35 holdout）；"
            "旧污染划分 split_manifest.json/20864f82（165 cal/43 holdout，被 A1 早期调参）已废弃。",
            "upstream_url 是实际上游身份：tracked 模板只保存 env 变量名（env:ANTHROPIC_BASE_URL），"
            "执行时从 ANTHROPIC_BASE_URL 注入实际值到 gitignored runtime profile（缺失即失败、不打印值）；"
            "ProviderAdapter 调用前校验 base_url 与 upstream_url 一致。",
            "K3 禁用（2026-08-14）；CPA Gemini 仅作 M2 待资格候选。",
            "k3 冻结 G0/哈希/证据不改写（其 split=20864f82 为污染划分，只读保留并视为失效，待 v2 重冻结）。",
        ],
        "k3_frozen_not_rewritten": [
            "runtime/refs/t8_canary/kimi_k3_canary_policy.json (92a6bbcd)",
            "runtime/refs/t8_canary/kimi_k3_calibrate_policy.json (7025a022)",
            ".taskflow/active/autonomous-high-quality-production/runtime/g0_report.json (k3 profile 8fa66f1f)",
            "novels/a1-calibrate/output/calibrate-kimi-k3-full/calls/ (73 calls, run ID 退休不复用)",
        ],
    }


def _profile() -> dict:
    """Provider 档案**模板**：端点/凭证经 env 变量**名**引用；数据库走既有跨设备合同
    ``~/.cc-switch/cc-switch.db``（ProviderAdapter 以 ``user_home / 该路径`` 打开，
    不解析 env 值，故不得写 ``env:CC_SWITCH_DB``）。``upstream_url`` 在模板中是
    ``env:ANTHROPIC_BASE_URL`` 符号名（不落任何端点值）；``main()`` 执行时从
    ANTHROPIC_BASE_URL 读取**实际值**写入 gitignored runtime profile（缺失即显式失败、
    不打印值）。ProviderAdapter 调用前校验已加载 base_url 与 profile upstream_url 一致。"""
    return {
        "schema_version": "1.0",
        "profile_id": PROFILE_ID,
        "transport": "anthropic_messages_http",
        "endpoint": {
            "settings_path_from_user_home": ".claude/settings.json",
            "base_url_json_path": f"env.{ENV_BASE_URL}",
            "credential_json_path": f"env.{ENV_AUTH_TOKEN}",
            "messages_path": "/v1/messages",
            "auth_scheme": "bearer",
            "anthropic_version": "2023-06-01",
            "user_agent": "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT; Windows NT 10.0; zh-CN)",
            "timeout_seconds": 300,
            "max_attempts": 1,
        },
        "provider_audit": {
            "provider_id": PROVIDER_ID,
            "provider_name": PROVIDER_NAME,
            "provider_category": PROVIDER_CATEGORY,
            "database_path_from_user_home": ".cc-switch/cc-switch.db",
            "upstream_url": f"env:{ENV_BASE_URL}",
            "expected_actual_model": MODEL,
            "failover_allowed": False,
        },
        "roles": {
            "generation": {"request_model": MODEL, "expected_actual_model": MODEL, "temperature": 0.0},
            "fact_judge": {"request_model": MODEL, "expected_actual_model": MODEL, "temperature": 0.0},
            "character_judge": {"request_model": MODEL, "expected_actual_model": MODEL, "temperature": 0.0},
            "reader_judge": {"request_model": MODEL, "expected_actual_model": MODEL, "temperature": 0.0},
        },
        "pricing_usd_per_million_tokens": {
            "input": 0.14, "output": 0.28, "cache_read": 0.0028, "cache_creation": 0.0,
            "source": ".cc-switch/cc-switch.db:model_pricing", "frozen_at": "2026-08-11",
        },
        "smoke_evidence": {
            "request_model": MODEL, "actual_model": MODEL,
            "input_tokens": 103, "output_tokens": 18, "cost_usd": 0.00001946, "status_code": 200,
        },
    }


def _policy() -> dict:
    # 只含 AutonomousPolicy 模型可载入的字段（模型 extra=forbid）：
    # evidence_version 等 bundle 元数据放 active_provider / setup_manifest，不入 policy。
    return {
        "schema_version": "1.0",
        "policy_id": "a1-q2a-canary-deepseek-v4-flash-m1",
        "provider_profile_id": PROFILE_ID,
        "runtime": {
            "manual_allowed": False,
            "waiting_allowed": False,
            "provider_fallback_allowed": False,
            "network_retry_allowed": False,
            "max_provider_attempts_per_call": 1,
            "resume_may_skip_gate": False,
        },
        "search": {
            "premise_candidates": 4,
            "plot_candidates": 2,
            "prose_variants_per_plot": 2,
            "max_decision_rounds": 2,
            "pairwise_orderings": ["A/B", "B/A"],
            "judge_roles": ["fact_judge", "character_judge", "reader_judge"],
        },
        "chapter": {
            "target_chinese_characters_min": 2500,
            "target_chinese_characters_max": 5000,
            "planner_max_output_tokens": 8000,
            "prose_max_output_tokens": 10000,
            "judge_max_output_tokens": 5000,
        },
        "budget": {
            "max_total_calls": 1500,
            "max_total_input_tokens": 20000000,
            "max_total_output_tokens": 10000000,
            "max_total_cost_usd": "25.0",
            "max_wall_clock_seconds": 36000,
            "max_chapters_per_run": 30,
            "max_canary_runs": 3,
            "max_canary_chapters_total": 90,
        },
        "evaluation": {
            "holdout_overall_accuracy_min": THRESHOLD_OVERALL,
            "holdout_genre_accuracy_min": THRESHOLD_GENRE,
            "pairwise_position_consistency_min": THRESHOLD_POSITION,
            "hard_fact_conflicts_allowed": 0,
            "manual_routes_allowed": 0,
            "unarmed_required_axes_allowed": 0,
        },
        "benchmarks": {
            "preference_source": "reference_texts/a1_benchmark/sources/writing_preference_bench/WP_bench_chinese.json",
            "preference_source_sha256": SOURCE_SHA256,
            "preference_split_manifest": SPLIT_MANIFEST_PATH,
            "preference_split_manifest_sha256": SPLIT_MANIFEST_SHA256,
            "human_distribution_manifest": "reference_texts/a1_benchmark/sources/wikisource/source_manifest.json",
            "human_distribution_manifest_sha256": HUMAN_SHA256,
        },
        "canary": {
            "genres": GENRES,
            "chapters_per_genre": 30,
            "long_horizon_checkpoints": [1, 30],
        },
    }


def _setup_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "bundle": "deepseek_active",
        "evidence_version": EVIDENCE_VERSION,
        "status": "active_selector_deepseek_v4_flash",
        "purpose": "switchboard 72606eb9 传达的直接确认登记（非破坏性；k3 冻结证据不改写）。",
        "files": {
            "active_provider.json": "活动选择器声明",
            "provider_profile_deepseek_v4_flash.json": "Provider 档案（端点/凭证经 env 变量名引用）",
            "canary_policy_deepseek_v4_flash.json": "活动 canary 策略（阈值冻结不降；split=split_manifest_v2.json c45cd6ad，无交叉 v2 划分）",
            "setup_manifest.json": "本清单",
        },
        "fresh_run_id_namespace": RUN_ID_NAMESPACE,
        "reserved_run_id_note": "必须以全新 run 目录 novels/<genre>/output/canary-deepseek-active-<seq>/ 运行；不得复用/覆盖任何退休 run ID。",
        "launcher": {
            "entry": "novel auto <novel>",
            "args": {
                "--run-name": "<canary-deepseek-active-<seq>>",
                "--policy": "runtime/refs/deepseek_active/canary_policy_deepseek_v4_flash.json",
                "--profile": "runtime/refs/deepseek_active/provider_profile_deepseek_v4_flash.json",
                "--base-state": "runtime/refs/t8_canary/<genre>/base_state_package.json",
                "--base-frames": "runtime/refs/t8_canary/<genre>/base_frames.json",
                "--flow-mode": "compose",
            },
            "note": "base-state/base-frames 沿用 t8_canary 冻结的三类型起始状态（与 provider 无关）。",
        },
        "cross_device": (
            "在其他设备 clone 本仓库后，设置获准环境变量 "
            f"{ENV_BASE_URL} / {ENV_AUTH_TOKEN} / {ENV_CC_SWITCH_DB}，重跑本脚本即可重建同结构 bundle。"
        ),
        "honest_caveat": [
            "deepseek-v4-flash 自有证据无法通过冻结门（评审 0.6129<0.65；生成 4/4 冒烟失败）。",
            "M1 删除评审协议合规重请求后只会更诚实失败。",
            "本 bundle 不构成能通过 G7/G8 的可执行路径；实际运行在资格门显式失败并保留证据。",
            "split 用无交叉 v2 划分（c45cd6ad）；旧污染 20864f82 已废弃，只读保留并标注失效。",
            "upstream_url 由执行时 ANTHROPIC_BASE_URL 注入 runtime profile（实际上游身份，"
            "gitignored 本地证据；缺失即失败，值不落 tracked 字节）。",
            "未发起任何外部调用；未生成任何 deepseek G0 新证据。",
        ],
    }


def main(output_dir: Path | None = None) -> bool:
    """重建 deepseek_active bundle。``output_dir`` 缺省为仓库内 runtime/refs/deepseek_active/.

    ``output_dir`` 可覆盖（测试用临时目录）；写出的文件结构与默认目录完全相同。
    执行时从 ``ANTHROPIC_BASE_URL`` 读取**实际值**注入 runtime profile 的 upstream_url
    （gitignored 本地证据；缺失即显式失败、值不打印、不进 tracked 字节）。
    """
    out = Path(output_dir) if output_dir is not None else BUNDLE_DIR
    # 冻结阈值不变式（不得降低）
    assert THRESHOLD_OVERALL == 0.65
    assert THRESHOLD_GENRE == 0.5
    assert THRESHOLD_POSITION == 0.9
    # 无交叉 v2 划分不变式（不得用旧污染 20864f82/split_manifest.json）
    assert SPLIT_MANIFEST_SHA256 == "c45cd6ad1640fb9688aba6bdb65973bc886237ca3f3b7d7555c9d86390f9ac01"
    _assert_split_manifest_bytes()

    base_url = _load_env_base_url()
    profile = _profile()
    profile["provider_audit"]["upstream_url"] = base_url  # 实际上游身份注入 runtime profile

    files = {
        "active_provider.json": _active_provider(),
        "provider_profile_deepseek_v4_flash.json": profile,
        "canary_policy_deepseek_v4_flash.json": _policy(),
        "setup_manifest.json": _setup_manifest(),
    }

    out.mkdir(parents=True, exist_ok=True)
    for name, obj in files.items():
        text = _dump(obj)
        # 隐私闸：唯一合法 URL 是 env 注入的 upstream_url 值；掩码后任何其他 URL/凭证/
        # 机器路径/小说内容即断言失败（tracked 模板本身零 URL，见 _profile 的 env 符号名）。
        masked = text.replace(base_url, "<upstream-url-redacted>")
        _assert_no_secrets(masked)
        (out / name).write_text(text, encoding="utf-8")
        print(f"wrote {out / name}")
    print(f"bundle rebuilt: {out} (evidence_version={EVIDENCE_VERSION})")
    return True


if __name__ == "__main__":
    main()
