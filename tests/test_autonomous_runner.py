"""A1 AutonomousRunner 集成测试（doc 48 §6 step 2 / T3–T5）.

用 fake Anthropic Messages HTTP Provider 驱动闭环章节生产（复用
test_provider_adapter.py 的 _Response/_provider_files 模式）。按请求体
max_tokens 路由阶段：plan=200 / prose=300 / judge=400（由冻结策略的
AutonomousChapterPolicy 提供互不相同的值）。plan 阶段现返回多 PlotUnit
候选批次；judge 阶段返回带正文锚点的单轴 JudgeClaim。

覆盖：
- 全新 run 初始化（manifest created、拒绝覆盖非空目录）
- 可信停止 Canary（viability stop → narrative_stopped，零 provider 调用）
- needs_premise（无活跃帧 + 活跃承诺 → premise_exhausted，零生成调用）
- 完整接受周期（多候选：20 次调用，含获胜正文绝对终审 → 提交 chapter_N.txt → usage 记账）
- 拒绝路径（三角色 JudgeClaim blocking → quality_exhausted）
- Provider 错误（只记错误类型，不重试，终止运行）
- 预算不足（投影 30 次调用越限 → 零调用终止）
- 崩溃恢复（failpoint mid-commit → resume 拒绝）
- created 状态续跑（首章提交前崩溃干净恢复）
- 提交吸收（flow 提交完成但 A1 manifest 未推进 → resume 吸收）
"""

import json
import sqlite3
from pathlib import Path

import pytest

from src.object_state.autonomous import (
    AutonomousPolicy,
    ProviderProfile,
    TERMINAL_STATUSES,
    canonical_model_sha256,
)
from src.object_state.run_manifest import sha256_text
from src.provider_adapter import A1_CLOSED_LOOP_ALLOWED, A1_PROVIDER_CALLS_IMPLEMENTED
from src.workflow_action.autonomous_runner import AutonomousRunner, AutonomousRunnerError
from src.workflow_action.frame import NarrativeFrameUnit
from src.domain_layer.rules import get_structure_template


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """隔离进程环境中的 Anthropic 凭据变量（env-first 适配器下走 settings 文件路径）."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _provider_files(tmp_path: Path) -> None:
    """建 fake 用户主目录：settings.json（凭证/端点）+ cc-switch sqlite（Provider 身份）."""
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


def _profile_payload() -> dict:
    return {
        "schema_version": "1.0",
        "profile_id": "provider-a",
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
                "temperature": 0.7 if role == "generation" else 0.0,
            }
            for role in (
                "generation",
                "fact_judge",
                "character_judge",
                "reader_judge",
            )
        },
        "pricing_usd_per_million_tokens": {
            "input": 0.14,
            "output": 0.28,
            "cache_read": 0.0028,
            "cache_creation": 0,
            "source": "pricing-table",
            "frozen_at": "2026-08-11",
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


def _policy_payload(**budget_updates) -> dict:
    budget = {
        "max_total_calls": 100,
        "max_total_input_tokens": 1000000,
        "max_total_output_tokens": 100000,
        "max_total_cost_usd": 10,
        "max_wall_clock_seconds": 1000,
        "max_chapters_per_run": 1,
        "max_canary_runs": 3,
        "max_canary_chapters_total": 3,
    }
    budget.update(budget_updates)
    return {
        "schema_version": "1.0",
        "policy_id": "policy-001",
        "provider_profile_id": "provider-a",
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
            "judge_roles": ["fact_judge", "character_judge", "reader_judge"],
        },
        "chapter": {
            "target_chinese_characters_min": 500,
            "target_chinese_characters_max": 1500,
            "planner_max_output_tokens": 200,
            "prose_max_output_tokens": 300,
            "judge_max_output_tokens": 400,
        },
        "budget": budget,
        "evaluation": {
            "holdout_overall_accuracy_min": 0.6,
            "holdout_genre_accuracy_min": 0.5,
            "pairwise_position_consistency_min": 0.9,
            "hard_fact_conflicts_allowed": 0,
            "manual_routes_allowed": 0,
            "unarmed_required_axes_allowed": 0,
        },
        "benchmarks": {
            "preference_source": "bench/pref.json",
            "preference_source_sha256": "0" * 64,
            "preference_split_manifest": "bench/split.json",
            "preference_split_manifest_sha256": "0" * 64,
            "human_distribution_manifest": "bench/human.json",
            "human_distribution_manifest_sha256": "0" * 64,
        },
        "canary": {
            "genres": ["悬疑", "都市", "仙侠"],
            "chapters_per_genre": 1,
            "long_horizon_checkpoints": [1],
        },
    }


def _policy(**budget_updates) -> AutonomousPolicy:
    return AutonomousPolicy.model_validate(_policy_payload(**budget_updates))


def _profile() -> ProviderProfile:
    return ProviderProfile.model_validate(_profile_payload())


def _base_objects(*, open_thread: bool = False) -> list:
    from src.object_state.charactermodel import CharacterModel
    from src.object_state.factledger import FactLedger
    from src.object_state.foreshadowgraph import ForeshadowGraph
    from src.object_state.narrativestate import NarrativeState
    from src.object_state.workspec import WorkSpec
    from src.object_state.worldmodel import WorldModel

    foreshadow = {"entries": []}
    if open_thread:
        foreshadow = {
            "entries": [
                {
                    "thread_id": "rem_001",
                    "setup_point": "第一章",
                    "content": "神秘来信",
                    "visibility_level": "explicit",
                    "expected_payoff": "回收",
                    "current_status": "active",
                }
            ]
        }
    return [
        WorkSpec(
            genre="悬疑",
            audience="青年",
            theme="真相",
            tone="克制",
            pacing="短弧推进",
        ),
        WorldModel(world_facts=["世界事实"]),
        CharacterModel(
            character_id="c001",
            name="主角",
            identity="侦探",
            outer_goal="破案",
            inner_need="正义",
            fear="失败",
            flaw="固执",
            strength="观察力",
            stance="中立",
            relations={},
        ),
        NarrativeState(
            state_id="ns_001",
            current_time="夜晚",
            current_location="案发现场",
            current_situation="调查开始",
            active_characters=["c001"],
        ),
        FactLedger(entries=[]),
        ForeshadowGraph(**foreshadow),
    ]


def _minimal_continue_payload() -> dict:
    return {
        "plotunit": {
            "unit_id": "pu_candidate",
            "level": "scene",
            "goal": "推进候选场景",
            "participants": ["c001"],
            "conflict": "候选冲突",
            "input_state_ref": "ns_001",
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


def _second_continue_payload() -> dict:
    """第二个 PlotUnit 候选：输出状态变化与首个不同（地点/局势），但释放信息与
    后果保持相同——确保两个候选都能通过确定性证伪（正文含候选信息/候选后果）。"""
    payload = _minimal_continue_payload()
    payload["plotunit"]["unit_id"] = "pu_candidate_b"
    payload["plotunit"]["output_state_ref"] = "ns_002b"
    payload["new_state"]["state_id"] = "ns_002b"
    payload["new_state"]["current_location"] = "测试地点乙"
    payload["new_state"]["current_situation"] = "候选推进之二"
    return payload


_PROSE = (
    "第一章 开端\n"
    "他推开那扇虚掩的门，屋里的油灯被风带了一下，火苗斜斜地伏下去又立起来。"
    "桌角压着一封信，字迹是他认得的——那人走了，把三年前的承诺留在了纸上。"
    "他没有急着拆信，先把手里的刀放回门后，然后走到窗前，把窗户闩上。"
    "夜里的巷子空无一人，只有远处更夫的梆子声一长一短。"
    "他坐下，拆了信。信上说，若他还想知道当年那场火是谁放的，就到城南的茶楼去，"
    "带一壶烧酒，坐东边的位子。他捏着信纸，指节发白。"
    "三年来他查遍案卷，始终差一个名字。这封信，可能就是那个名字。"
    "信里还夹着一页旧纸，上面潦草地写着候选信息，落款处补了一句候选后果。"
    "他吹灭了灯，在黑暗里坐了许久，终于起身，从柜底取出那件旧外衣。"
    "他要去城南。不管信上说的是真是假，他都要去问一句。"
    "风从门缝灌进来，纸上的墨迹在月光下泛着青。他忽然想起那人走的那夜，"
    "也是这样的风，这样的月。他把信叠好，贴身收进里衣，推门走了出去。"
)

# T6 多版正文：每版带「甲/乙/丙/丁方案」标记，供匿名换位评审按内容位置一致地
# 路由（真实系统里换位评审只读正文本身，这里标记是 fake 的确定性判别依据）。
_PROSE_A = _PROSE + "\n甲方案收束。"
_PROSE_B = _PROSE + "\n乙方案收束。"
_PROSE_C = _PROSE + "\n丙方案收束。"
_PROSE_D = _PROSE + "\n丁方案收束。"

# 默认逐版正文：计划 1 的 v1/v2 = 甲/乙，计划 2 的 v1/v2 = 丙/丁。
_DEFAULT_PROSE_TEXTS = [_PROSE_A, _PROSE_B, _PROSE_C, _PROSE_D]

# 第二章用独立正文（不同开头/结尾），避免触发相邻章「开头复述 / 重复闭环」硬闸。
# 正文必须含计划释放的「候选信息 / 候选后果」（确定性证伪硬门禁），但不能含
# 开放承诺 rem_001（神秘来信）——让漂移测试在 ch2 检查点如期望 block。
_PROSE2 = (
    "第二章 追查\n"
    "清晨的城南茶楼还冷清着，小二在擦桌子。他在东边的位子坐下，要了一壶烧酒。"
    "掌柜的说那位客人每月十五才来，让他下回再来。他没有走，就着酒把信又读了一遍，"
    "信里记着的候选信息，他早已逐字背熟。"
    "茶楼后院的狗忽然叫起来，有人从后门进来，脚步很轻。他没有回头，只把酒壶满上。"
    "来人在他对面坐下，一句话也不说。他盯着那人看了很久，终于明白，"
    "当年那场火，不止一个人知道真相——那人低声道出的候选后果印证了他的猜想。"
    "他点了点头，把信折好放进怀里，"
    "又替对面那人斟了一杯。酒是冷的，话也是冷的。茶楼的窗纸被风鼓起又落下，"
    "两个人的影子在晨光里挨得很近，却没有一个人先开口。他记得那人的手——"
    "指节上有旧茧，和当年放火那晚在窗纸上按过的印子，一模一样。"
    "他忽然明白，这人不是来告诉他真相的，是来试探他知道多少的。"
    "他把酒一饮而尽，站起身来。走出茶楼时，晨光已经铺满了整条街。"
)
_PROSE2_A = _PROSE2 + "\n甲方案收束。"
_PROSE2_B = _PROSE2 + "\n乙方案收束。"
_PROSE2_C = _PROSE2 + "\n丙方案收束。"
_PROSE2_D = _PROSE2 + "\n丁方案收束。"


def _success_payload(text: str, model: str = "model-a") -> dict:
    return {
        "type": "message",
        "model": model,
        "content": [
            {"type": "thinking", "thinking": "not persisted"},
            {"type": "text", "text": text},
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 4,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 0,
        },
    }


def _premise_payload(candidate_ids: list[str], obligations: list[str] | None = None) -> dict:
    """有效/无效前提候选载荷。obligations=None → 义务命中活跃承诺 rem_001."""
    return {
        "candidates": [
            {
                "candidate_id": candidate_ids[i],
                "new_external_conflict": "外部势力逼近",
                "new_phase_goal": "追查神秘来信背后的人",
                "boundary_to_closed_arc": "不重开已闭合的情感闭环",
                "obligations_to_old_promises": (
                    (obligations or ["rem_001"]) if i == 0 else ["rem_001"]
                ),
                "new_state_change": "主角获得关键线索",
                "reader_contract_legal": True,
                "reader_contract_reason": "延续契约悬念核心",
            }
            for i in range(len(candidate_ids))
        ]
    }


def _extract_judge_prose(prompt: str) -> str:
    """从评审 prompt 提取被评审正文（【待评审章节正文】与【评审要求】之间）."""
    start = prompt.find("【待评审章节正文】\n")
    end = prompt.find("\n\n【评审要求】")
    if start < 0 or end < 0 or end <= start:
        raise AssertionError("judge prompt missing prose section markers")
    return prompt[start + len("【待评审章节正文】\n"):end]


def _extract_precommit_id(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("- 预承诺ID: "):
            return line[len("- 预承诺ID: "):].strip()
    raise AssertionError("judge prompt missing precommit id line")


def _section(prompt: str, header: str, next_headers: list[str]) -> str:
    """提取 prompt 中 header 之后、任一 next_header 之前的段落."""
    start = prompt.find(header)
    assert start >= 0, f"prompt missing {header!r}"
    body = prompt[start + len(header):]
    for nxt in next_headers:
        pos = body.find("\n" + nxt)
        if pos >= 0:
            return body[:pos].strip()
    return body.strip()


def _evidence_anchor_id(evidence: str) -> str:
    """从证据段复制系统给出的内容地址，不生成自由引文。"""
    marker = "[anc_"
    start = evidence.find(marker)
    assert start >= 0, "arbitration evidence must contain content anchor id"
    end = evidence.find("]", start)
    return evidence[start + 1:end]


def _arbitration_payload(prompt: str, *, slot_biased: bool = False) -> str:
    """证据锚定仲裁响应：decisive_anchor 必须逐字来自候选正文（锚点真实性）.

    content（默认）：偏好「推进轴 satisfied」证据的候选（v1）——锚点取自该候选
    评审证据里的锚点原文；两轮换位命名同一正文 → 位置一致（T6.3）。slot_biased：
    恒命名「甲」并引当前甲槽位证据的锚点 → 两轮命名不同正文 → 位置不一致
    （T6.6 位置偏置夹具，换位测量下必须暴露为不稳定）。
    """
    evidence_a = _section(
        prompt, "【候选甲 评审证据】\n", ["【候选乙 评审证据】"]
    )
    evidence_b = _section(
        prompt, "【候选乙 评审证据】\n", ["【裁定要求】"]
    )
    anchor_a = _evidence_anchor_id(evidence_a)
    anchor_b = _evidence_anchor_id(evidence_b)
    if slot_biased:
        anchor_id = anchor_a
        rationale = "恒甲槽位（位置偏置夹具）。"
    else:
        # 内容基：恰好一个证据块是「推进轴 satisfied」（v1 的判别信号）。
        a_is_v1 = "progression / satisfied" in evidence_a
        b_is_v1 = "progression / satisfied" in evidence_b
        assert a_is_v1 != b_is_v1, "exactly one evidence block must show progression satisfied"
        anchor_id = anchor_a if a_is_v1 else anchor_b
        rationale = "推进证据判别（测试注入）。"
    return json.dumps(
        {
            "decision": "anchor",
            "decisive_anchor_id": anchor_id,
            "rationale": rationale,
        },
        ensure_ascii=False,
    )


def _judge_claims_payload(prompt: str, *, blocking: bool, role: str) -> str:
    prose = _extract_judge_prose(prompt)
    precommit_id = _extract_precommit_id(prompt)
    end = min(40, len(prose))
    if blocking:
        blocking_axis = {
            "fact_judge": "fact_conflict",
            "character_judge": "character_contradiction",
            "reader_judge": "contract_drift",
        }[role]
        claims = [
            {
                "claim_id": "cl_block",
                "precommit_id": precommit_id,
                "axis": blocking_axis,
                "verdict": "violated",
                "severity": "blocking",
                "anchors": [
                    {
                        "position": "start",
                        "excerpt": prose[0:end],
                        "char_start": 0,
                        "char_end": end,
                    }
                ],
                "rationale": "测试注入的阻断硬违例。",
            }
        ]
    elif role == "reader_judge":
        # T6：软轴驱动前沿 + 证据锚定仲裁。计划 1 候选 satisfied——v1（甲方案）
        # 走推进轴、v2（乙方案）走语言轴 → 两版证据互不支配 → 淘汰赛触发仲裁；
        # 计划 2 候选 violated（语言轴 -1，被支配淘汰）。
        # 锚点引正文尾部（含「甲/乙方案」判别标记，逐字真实）——两版正文头 40 字
        # 相同，若锚点引头会两候选同现 → 仲裁误判 no_difference。
        satisfied = precommit_id == "precommit_plan_0001"
        axis = (
            "progression"
            if (satisfied and "甲方案" in prose)
            else "language_distinctiveness"
        )
        tail_len = min(30, len(prose))
        tail_start = len(prose) - tail_len
        claims = [
            {
                "claim_id": "cl_soft",
                "precommit_id": precommit_id,
                "axis": axis,
                "verdict": "satisfied" if satisfied else "violated",
                "severity": "advisory",
                "anchors": [
                    {
                        "position": "start",
                        "excerpt": prose[tail_start:],
                        "char_start": tail_start,
                        "char_end": len(prose),
                    }
                ],
                "rationale": (
                    "计划 1 候选推进有效。" if satisfied else "计划 2 候选推进不足。"
                ),
            }
        ]
    else:
        axis = "fact_conflict" if role == "fact_judge" else "character_fidelity"
        role_tail_len = min(30, len(prose))
        role_tail_start = len(prose) - role_tail_len
        claims = [
            {
                "claim_id": f"cl_{role}",
                "precommit_id": precommit_id,
                "axis": axis,
                "verdict": "satisfied",
                "severity": "advisory",
                "anchors": [
                    {
                        "position": "end",
                        "excerpt": prose[role_tail_start:],
                        "char_start": role_tail_start,
                        "char_end": len(prose),
                    }
                ],
                "rationale": "测试注入的角色轴覆盖。",
            }
        ]
    return json.dumps({"claims": claims})


def _fake_urlopen(
    calls: list,
    *,
    plan_text=None,
    prose_text=None,
    prose_texts=None,
    review_blocking: bool = False,
    post_review_blocking: bool = False,
    premise_text=None,
    fail_max_tokens: set[int] | None = None,
    error: Exception = RuntimeError("simulated provider failure"),
    tournament_position_biased: bool = False,
    judge_text=None,
):
    """按阶段路由：premise/plan=200、prose=300、judge/arbitration=400.

    前提搜索与规划共用 plan provider（max_tokens=200），以「【前提要求】」标记区分。
    评审按三角色独立调用：以「你负责【事实】/【人物】/【读者体验】轴」标记路由；
    证据锚定仲裁以「【证据锚定仲裁】」标记路由（其 prompt 含读者体验轴角色指引，
    必须先于轴判定匹配）。正文按调用次序取 prose_texts（默认逐版标记的甲/乙/丙/丁
    方案）；评审 claims 里 v1=推进满足 / v2=语言满足 互不支配 → 仲裁按「推进满足」
    证据判别返回决定性锚点，两轮命名同一正文（位置一致）。
    """
    _prose_seen: list = []

    def fake(request, timeout):
        assert request.headers["Authorization"] == "Bearer secret-value"
        calls.append(request)
        body = json.loads(request.data.decode("utf-8"))
        max_tokens = body["max_tokens"]
        if fail_max_tokens is not None and max_tokens in fail_max_tokens:
            raise error
        prompt_text = body["messages"][-1]["content"]
        if "【前提要求】" in prompt_text:
            text = (
                premise_text
                if premise_text is not None
                else json.dumps(_premise_payload(["premise-001"]))
            )
        elif max_tokens == 200:
            text = (
                plan_text
                if plan_text is not None
                else json.dumps(
                    {"candidates": [_minimal_continue_payload(), _second_continue_payload()]}
                )
            )
        elif max_tokens == 300:
            if prose_text is not None:
                text = prose_text
            else:
                texts = prose_texts if prose_texts is not None else _DEFAULT_PROSE_TEXTS
                text = texts[len(_prose_seen)]
                _prose_seen.append(text)
        elif "你是一位小说质量评审。下面是一章小说正文" in prompt_text:
            reviewed_prose = _section(
                prompt_text, f"【章节：", ["【审查维度参考】"]
            )
            reviewed_prose = reviewed_prose.split("】\n", 1)[-1].strip()
            anchor = reviewed_prose[:40]
            text = json.dumps(
                {
                    "clean": False,
                    "findings": [
                        {
                            "issue_type": "style_drift",
                            "location": anchor,
                            "severity": "low",
                            "evidence": "测试注入的轻度句式趋同。",
                        }
                    ],
                }
            )
        elif "【审查窗口】window=" in prompt_text:
            text = json.dumps({"findings": [], "overall": "good"})
        elif "【证据锚定仲裁】" in prompt_text:
            text = _arbitration_payload(
                prompt_text, slot_biased=tournament_position_biased
            )
        elif "【审查上下文】a1-post-prose" in prompt_text:
            reviewed_prose = _section(
                prompt_text, "【本章正文】\n", ["【正文层审查维度】"]
            )
            issues = [
                {
                    "issue_id": "iss_post_low_style",
                    "issue_type": "style_drift",
                    "severity": "low",
                    "location": reviewed_prose[:40],
                    "scope_of_impact": "句式辨识度",
                    "violated_rule": "避免模板化句式",
                    "description": "轻度句式趋同，记录但不阻断。",
                    "suggested_fix": "后续章增加句式变化。",
                }
            ]
            route = "pass"
            if post_review_blocking:
                issues = [
                    {
                        "issue_id": "iss_post_quality",
                        "issue_type": "generative_indicia",
                        "severity": "blocking",
                        "location": reviewed_prose[:40],
                        "scope_of_impact": "读者体验",
                        "violated_rule": "Post-Prose 绝对质量地板",
                        "description": "模板化总结过重。",
                        "suggested_fix": "重写正文。",
                    }
                ]
                route = "block"
            text = json.dumps({"issues": issues, "reminders": [], "route": route})
        elif judge_text is not None:
            # M1 单次调用契约回归：judge 阶段返回协议违规（不可解析）响应 → 校验其
            # 恰好调用一次、显式终态、零状态污染（不重请求）。
            text = judge_text
        elif "你负责【事实】轴" in prompt_text:
            text = _judge_claims_payload(prompt_text, blocking=review_blocking, role="fact_judge")
        elif "你负责【人物】轴" in prompt_text:
            text = _judge_claims_payload(prompt_text, blocking=review_blocking, role="character_judge")
        elif "你负责【读者体验】轴" in prompt_text:
            text = _judge_claims_payload(prompt_text, blocking=review_blocking, role="reader_judge")
        else:
            raise AssertionError(f"unexpected provider stage: max_tokens={max_tokens}")
        return _Response(_success_payload(text=text))

    return fake


def _completed_frames() -> list:
    """结构完整但全部 completed 的帧状态 → get_cursor()=None（no_active_frame）."""
    unit = NarrativeFrameUnit()
    frames = unit.build_frame(
        workspec_context="作品类型: 悬疑\n主题: 真相\n",
        structure_template=get_structure_template("eight_node"),
    )
    for frame in frames:
        frame["status"] = "completed"
    return frames


def _crash_at(step_name: str):
    def fail(step: str) -> None:
        if step == step_name:
            raise RuntimeError(f"simulated crash at {step}")

    return fail


def _run_dir(tmp_path: Path) -> Path:
    return (tmp_path / "novels" / "test-novel" / "output" / "a1-run").resolve()


def _make_runner(
    tmp_path: Path,
    *,
    monkeypatch=None,
    install_fake: bool = True,
    frames=None,
    open_thread: bool = False,
    failpoint=None,
    candidates: int = 1,
    flow_mode: str = "compose",
    budget_updates: dict | None = None,
    policy=None,
    premise_text=None,
    prose_text=None,
    prose_texts=None,
    source_text: str = "",
    objects=None,
    judge_text=None,
    plan_text=None,
):
    _provider_files(tmp_path)
    if policy is None:
        policy = _policy(**(budget_updates or {}))
    profile = _profile()
    calls: list = []
    if install_fake:
        assert monkeypatch is not None
        monkeypatch.setattr(
            "src.provider_adapter.urllib.request.urlopen",
            _fake_urlopen(
                calls,
                premise_text=premise_text,
                prose_text=prose_text,
                prose_texts=prose_texts,
                judge_text=judge_text,
                plan_text=plan_text,
            ),
        )
    run_dir = _run_dir(tmp_path)
    identity_path = run_dir.parent / "campaign_identity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    if not identity_path.exists():
        identity_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "campaign": run_dir.parent.parent.name,
                    "genre": "test",
                    "base_state_sha256": "a" * 64,
                    "policy_sha256": canonical_model_sha256(policy),
                    "profile_sha256": canonical_model_sha256(profile),
                    "mechanism_source_sha256": __import__(
                        "src.workflow_action.autonomous_runner", fromlist=["_mechanism_source_sha256"]
                    )._mechanism_source_sha256(Path(__file__).resolve().parents[1]),
                }
            ),
            encoding="utf-8",
        )
    runner = AutonomousRunner(
        run_dir=run_dir,
        policy=policy,
        profile=profile,
        objects=objects if objects is not None else _base_objects(open_thread=open_thread),
        frames=frames,
        user_home=tmp_path,
        failpoint=failpoint,
        initial_candidates_remaining=candidates,
        flow_mode=flow_mode,
        source_text=source_text,
        campaign_identity_path=identity_path,
        base_state_hash="a" * 64,
    )
    return runner, run_dir, policy, profile, calls


def _resume_runner(tmp_path: Path, run_dir: Path, policy, profile):
    return AutonomousRunner(
        run_dir=run_dir,
        policy=policy,
        profile=profile,
        user_home=tmp_path,
        campaign_identity_path=run_dir.parent / "campaign_identity.json",
    )


def test_a1_capability_flags_are_on():
    assert A1_PROVIDER_CALLS_IMPLEMENTED is True
    assert A1_CLOSED_LOOP_ALLOWED is True


def test_fresh_init_creates_manifest_and_refuses_overwrite(tmp_path):
    runner, run_dir, *_ = _make_runner(tmp_path, install_fake=False)
    assert runner.status == "created"
    assert (run_dir / ".flow_version").read_text(encoding="utf-8") == "3"
    assert (run_dir / "initial_chapter").read_text(encoding="utf-8") == "1"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "created"
    assert manifest["committed_chapters"] == 0
    assert (run_dir / "state" / "state_package.json").is_file()
    assert (run_dir / "state" / "frames.json").is_file()

    # 非空但无 manifest 的目录 → 拒绝覆盖
    other = tmp_path / "novels" / "other" / "output" / "stale"
    other.mkdir(parents=True)
    (other / "stray.txt").write_text("x", encoding="utf-8")
    other_policy = _policy()
    other_profile = _profile()
    other_identity = other.parent / "campaign_identity.json"
    other_identity.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign": "other",
                "genre": "test",
                "base_state_sha256": "a" * 64,
                "policy_sha256": canonical_model_sha256(other_policy),
                "profile_sha256": canonical_model_sha256(other_profile),
                "mechanism_source_sha256": __import__(
                    "src.workflow_action.autonomous_runner", fromlist=["_mechanism_source_sha256"]
                )._mechanism_source_sha256(Path(__file__).resolve().parents[1]),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AutonomousRunnerError, match="refuse overwrite"):
        AutonomousRunner(
            run_dir=other,
            policy=other_policy,
            profile=other_profile,
            objects=_base_objects(),
            user_home=tmp_path,
            campaign_identity_path=other_identity,
            base_state_hash="a" * 64,
        )


def test_stop_canary_halts_before_any_provider_call(tmp_path, monkeypatch):
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path, monkeypatch=monkeypatch, frames=_completed_frames()
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "narrative_stopped"
    assert terminal.committed_chapters == 0
    assert calls == []  # stop 先于任何生成调用
    assert terminal.usage.calls == 0
    assert not (run_dir / "calls").exists()
    assert (run_dir / "viability_report.json").is_file()
    report = json.loads(
        (run_dir / "viability_report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "stop"


def test_needs_premise_search_all_invalid_then_premise_exhausted(tmp_path, monkeypatch):
    # no_active_frame（全 completed 帧）+ 活跃承诺 → needs_premise（T4）：
    # 自动前提搜索一次（1 provider 调用），候选验证全部失败 → premise_exhausted。
    # 前提搜索后零生成调用（plan/prose/judge 全不触达）。
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        frames=_completed_frames(),
        open_thread=True,
        premise_text=json.dumps(_premise_payload(["premise-001"], obligations=["虚造承诺"])),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "premise_exhausted"
    assert terminal.committed_chapters == 0
    assert terminal.usage.calls == 1  # 仅前提搜索批
    assert len(calls) == 1
    # 搜索批后无生成调用：唯一调用的 max_tokens 为 planner（200），即前提搜索。
    for request in calls:
        assert json.loads(request.data.decode("utf-8"))["max_tokens"] == 200
    assert (run_dir / "premise_search.json").is_file()
    search = json.loads((run_dir / "premise_search.json").read_text(encoding="utf-8"))
    assert search["searches"][-1]["accepted_id"] is None
    assert (run_dir / "viability_report.json").is_file()


def test_needs_premise_search_finds_premise_then_commits(tmp_path, monkeypatch):
    # T4 成功路径：前提搜索返回命中 rem_001 的有效候选 → 投影新 active 帧 →
    # 重新进入 viability=continue → 规划/成文/审查/读者门禁 → 提交 chapter_1。
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        frames=_completed_frames(),
        open_thread=True,
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    # premise 搜索 1 + plan 批次 1 + 4 版正文 + 12 次评审（三角色）+ 2 次证据锚定仲裁 = 20
    assert terminal.usage.calls == 21
    assert len(calls) == 21
    assert (run_dir / "premise.json").is_file()
    premise = json.loads((run_dir / "premise.json").read_text(encoding="utf-8"))
    assert premise["candidate_id"] == "premise-001"
    assert premise["obligations_to_old_promises"] == ["rem_001"]
    search = json.loads((run_dir / "premise_search.json").read_text(encoding="utf-8"))
    assert search["searches"][-1]["accepted_id"] == "premise-001"
    frames = json.loads((run_dir / "state" / "frames.json").read_text(encoding="utf-8"))
    # 前提候选已投影为新 arc（提交后 cursor 前进，arc 不再 active，但线程绑定必须保留）
    premise_arcs = [
        f
        for f in frames
        if f["level"] == "arc"
        and f["frame_id"] == "arc_002"
        and f["active_thread_ids"] == ["rem_001"]
    ]
    assert premise_arcs, f"premise-projected arc_002 with thread binding missing: {frames}"
    assert (runner.chapters_dir / "chapter_1.txt").is_file()
    # 成功路径非终态：前提搜索后重新进入 continue 并提交，无 terminal viability 报告。
    assert not (run_dir / "viability_report.json").is_file()


def _two_chapter_policy() -> AutonomousPolicy:
    """max_chapters=2 + 检查点 [1,2]：ch1 建基线、ch2 对账漂移判定."""
    payload = _policy_payload(max_chapters_per_run=2, max_canary_chapters_total=6)
    payload["canary"]["chapters_per_genre"] = 2
    payload["canary"]["long_horizon_checkpoints"] = [1, 2]
    return AutonomousPolicy.model_validate(payload)


def test_long_horizon_drift_blocks_second_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.boundary_control.reader_gate._style_drift_issues", lambda *args: []
    )
    # T7.1/T7.2：ch1 检查点建立基线（pass），ch2 检查点正文重建 vs 滚动摘要对账——
    # 开放承诺 rem_001（神秘来信）从未在正文落地 → 漂移超阈值 → quality_exhausted。
    # 每章获胜版（甲方案）均不含「神秘来信」→ 承诺失落地。
    runner, run_dir, _, _, _ = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        open_thread=True,
        prose_texts=[
            _PROSE_A, _PROSE_B, _PROSE_C, _PROSE_D,
            _PROSE2_A, _PROSE2_B, _PROSE2_C, _PROSE2_D,
        ],
        policy=_two_chapter_policy(),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "quality_exhausted"
    assert terminal.committed_chapters == 2
    assert "long-horizon" in terminal.terminal_reason
    # ch1 基线检查点 pass；ch2 漂移检查点 block
    first = json.loads(
        (run_dir / "gates" / "long_horizon_1.json").read_text(encoding="utf-8")
    )
    second = json.loads(
        (run_dir / "gates" / "long_horizon_2.json").read_text(encoding="utf-8")
    )
    assert first["route"] == "pass"
    assert second["route"] == "block"
    assert second["stale_promises"] == ["rem_001"]


def test_long_horizon_grounded_promise_passes_and_continues(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.boundary_control.reader_gate._style_drift_issues", lambda *args: []
    )
    # T7 通过路径：开放承诺在正文落地 → 检查点 pass，滚动摘要以正文刷新，run 继续到
    # 章预算完成。承诺漂移为 false positive 时不应阻断生产。
    grounded = _PROSE2 + "\n神秘来信正是那封旧信。\n甲方案收束。"
    runner, run_dir, _, _, _ = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        open_thread=True,
        prose_texts=[
            _PROSE_A, _PROSE_B, _PROSE_C, _PROSE_D,
            grounded, _PROSE2_B, _PROSE2_C, _PROSE2_D,
        ],
        policy=_two_chapter_policy(),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 2
    second = json.loads(
        (run_dir / "gates" / "long_horizon_2.json").read_text(encoding="utf-8")
    )
    assert second["route"] == "pass"
    assert second["stale_promises"] == []
    # 对账后的滚动摘要持久化（正文落地提及数非零）
    rolling = json.loads(
        (run_dir / "gates" / "rolling_summary.json").read_text(encoding="utf-8")
    )
    assert rolling["last_checkpoint"] == 2
    assert rolling["summary"]["promise_mentions"].get("rem_001", 0) > 0


def test_long_horizon_checkpoint_not_fired_outside_checkpoints(tmp_path, monkeypatch):
    # 未落在冻结检查点（[3] 且 max_chapters=1，committed=1 ∉ [3]）→ 无 gates 产物.
    payload = _policy_payload(
        max_chapters_per_run=1, max_canary_runs=9, max_canary_chapters_total=9
    )
    payload["canary"]["chapters_per_genre"] = 3
    payload["canary"]["long_horizon_checkpoints"] = [3]
    runner, run_dir, _, _, _ = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        policy=AutonomousPolicy.model_validate(payload),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    assert not (run_dir / "gates").exists()


def test_seam_event_replay_blocks_chapter(tmp_path, monkeypatch):
    # T5：上章末事件在章首原样重演 → 语义接缝硬闸阻断（零 LLM）。
    # plan 批次 1 次 + 4 版正文后被 seam 拦截，省去评审调用；
    # 全部正文候选 rejected → quality_exhausted，零提交。
    from src.object_state.charactermodel import CharacterModel

    objects = _base_objects() + [
        CharacterModel(
            character_id="c_lin",
            name="林越",
            identity="主角",
            outer_goal="追查真相",
            inner_need="释怀",
            fear="再次失去",
            flaw="固执",
            strength="观察力",
            stance="中立",
            relations={},
        ),
        CharacterModel(
            character_id="c_qing",
            name="乔晚",
            identity="故人",
            outer_goal="离开",
            inner_need="自由",
            fear="被找到",
            flaw="犹豫",
            strength="敏锐",
            stance="回避",
            relations={},
        ),
    ]
    # 上章末以「林越接到电话，得知乔晚去了远方」结束；本章首原样重演。
    source_text = "（前文省略）\n\n林越接到电话，得知乔晚去了远方。"
    prose_text = (
        "第一章 电话\n"
        "他又接到电话，得知乔晚去了远方。夜色里他攥紧了手机，久久没有说话。"
        "听筒那头只剩忙音，一遍一遍地响。他想起三年前她也是这样不辞而别，"
        "只留一封信，信上写着别再找她。他始终没弄明白那一夜发生了什么，"
        "如今她又一次离开，他连告别都没能说出口。窗外下起小雨，雨丝斜斜地"
        "打在玻璃上，像那年她撑伞走过巷口的样子。他把手机放进口袋，关掉"
        "屋里的灯，在黑暗里坐了很久。天快亮的时候他起身收拾行李，决定这次"
        "无论如何也要找到她，问清楚那些年所有的沉默。雨一直下，他背上行囊"
        "推门走进了清晨的街道。"
    )
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        objects=objects,
        source_text=source_text,
        prose_text=prose_text,
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "quality_exhausted"
    assert terminal.committed_chapters == 0
    # plan 批次 1 + 4 版正文 = 5，接缝在评审前拦截
    assert terminal.usage.calls == 5
    assert len(calls) == 5
    assert not (runner.chapters_dir / "chapter_1.txt").exists()
    seam = json.loads((run_dir / "seam_findings.json").read_text(encoding="utf-8"))
    assert seam["findings"], "semantic seam should have recorded the replay finding"
    assert seam["findings"][-1]["issue_type"] == "seam_event_replay"
    # 阻断走 reject_candidate 而非提交：seam 是硬闸，不接受任何正文。
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["committed_chapters"] == 0


def test_full_accept_cycle_commits_chapter_and_records_usage(
    tmp_path, monkeypatch
):
    from src.boundary_control.reader_gate import (
        evaluate_commit_reader_gate as real_commit_reader_gate,
    )
    from src.object_state.factledger import FactEntry, FactLedger
    from src.object_state.narrativestate import NarrativeState
    from src.object_state.plotunit import PlotUnit

    historical_payload = _minimal_continue_payload()["plotunit"]
    historical_payload["unit_id"] = "pu_historical"
    historical_payload["output_state_ref"] = "ns_001"
    historical = PlotUnit.model_validate(historical_payload)
    historical_fact_id = "f_historical"
    objects = _base_objects() + [historical]
    facts = next(obj for obj in objects if isinstance(obj, FactLedger))
    facts.add_fact(
        FactEntry(
            fact_id=historical_fact_id,
            statement="历史已提交事实",
            fact_type="event",
            confirmed=True,
        )
    )
    first_plan = _minimal_continue_payload()
    first_plan["new_facts"] = [
        {
            "fact_id": historical_fact_id,
            "statement": "本章新增且内容不同的事实",
            "fact_type": "event",
            "confirmed": True,
        }
    ]
    first_plan["new_state"]["current_facts_in_scope"] = [historical_fact_id]
    plan_text = json.dumps(
        {"candidates": [first_plan, _second_continue_payload()]}
    )
    captured_plotunits: list[str] = []

    def capture_commit_reader_gate(**kwargs):
        captured_plotunits.extend(
            obj.unit_id
            for obj in kwargs.get("causal_objects", [])
            if isinstance(obj, PlotUnit)
        )
        return real_commit_reader_gate(**kwargs)

    monkeypatch.setattr(
        "src.workflow_action.autonomous_runner.evaluate_commit_reader_gate",
        capture_commit_reader_gate,
    )
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        objects=objects,
        plan_text=plan_text,
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    # plan 批次 1 + 4 版正文 + 12 次评审（三角色）+ 2 次证据锚定仲裁 = 19
    assert terminal.usage.calls == 20
    assert len(calls) == 20
    assert (runner.chapters_dir / "chapter_1.txt").is_file()
    assert (run_dir / "terminal.json").is_file()
    assert (run_dir / "run_manifest.json").is_file()
    assert (run_dir / "reader_gate_report.json").is_file()
    from src.boundary_control.chapter_commit import ChapterCommitBoundary
    from src.object_state.run_manifest import sha256_file

    identity_path = run_dir.parent / "campaign_identity.json"
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    identity_rel = "output/campaign_identity.json"
    assert manifest["campaign_identity_hash"] == sha256_file(identity_path)
    assert manifest["artifacts"][identity_rel] == sha256_file(identity_path)
    assert ChapterCommitBoundary(run_dir, runner.chapters_dir).recover().recognized
    # 提交正文与获胜候选（甲方案）draft 一致
    committed = (runner.chapters_dir / "chapter_1.txt").read_text(encoding="utf-8")
    assert committed.strip() == _PROSE_A.strip()
    # 提交门禁只能审查最终选中计划；历史 PU 与候选循环末项均不得污染当前章。
    assert captured_plotunits == ["pu_candidate"]
    state = runner._serializer.load(run_dir / "state" / "state_package.json")
    state_objects = runner._serializer.deserialize_package(state)
    committed_facts = next(
        obj for obj in state_objects if isinstance(obj, FactLedger)
    )
    fact_ids = [entry.fact_id for entry in committed_facts.entries]
    remapped_fact_id = f"{historical_fact_id}__chapter_1"
    assert fact_ids.count(historical_fact_id) == 1
    assert remapped_fact_id in fact_ids
    committed_state = next(
        obj
        for obj in state_objects
        if isinstance(obj, NarrativeState) and obj.state_id == "ns_002"
    )
    assert committed_state.current_facts_in_scope == [remapped_fact_id]
    frames = json.loads((run_dir / "state" / "frames.json").read_text(encoding="utf-8"))
    consumed = next(frame for frame in frames if frame["frame_id"] == "scene_001")
    assert consumed["target_plotunit_ids"] == ["pu_candidate"]
    assert consumed["input_state_ref"] == "ns_001"
    assert consumed["output_state_ref"] == "ns_002"
    provenance = json.loads(
        (run_dir / "chapter_provenance.json").read_text(encoding="utf-8")
    )["chapters"]["chapter_1"]
    assert provenance["active_frame_id"] == "scene_001"
    assert provenance["next_active_frame_id"] == "scene_002"
    assert provenance["next_active_formula_node"] == "inciting_incident"
    assert provenance["review_evidence_hash"] == sha256_text(
        json.dumps(
            provenance["review_issues"], ensure_ascii=False, sort_keys=True
        )
    )
    from src.experiment.pass_audit import classify_chapter

    style_issue = next(
        issue for issue in provenance["review_issues"]
        if issue["issue_type"] == "style_drift"
    )
    classified = classify_chapter(
        provenance["review_issues"],
        [
            {
                "issue_type": "style_drift",
                "location": style_issue["location"],
                "severity": "low",
                "evidence": "独立盲审复现同一轻度句式问题。",
            }
        ],
    )
    assert len(classified["matched"]) == 1
    assert classified["missed"] == []

    # 审计：只存 SHA-256 与计数，绝不落正文/凭证/思维块
    audits = sorted((run_dir / "calls").glob("call_*.json"))
    assert len(audits) == 20
    role_counts = {}
    for path in audits:
        audit = json.loads(path.read_text(encoding="utf-8"))
        assert audit["status"] == "success"
        assert audit["prompt_sha256"]
        assert audit["response_sha256"]
        for forbidden in ("prompt", "response", "thinking", "credential", "content"):
            assert forbidden not in audit, f"audit must not contain {forbidden}"
        assert audit["input_tokens"] == 12
        assert audit["output_tokens"] == 4
        # T6.1：请求模型与实际响应模型逐调用一致且等于冻结模型（别名≠多样性）。
        assert audit["request_model"] == "model-a"
        assert audit["actual_model"] == "model-a"
        role_counts[audit["role"]] = role_counts.get(audit["role"], 0) + 1
    # 三个评审角色各自独立调用；换位评审走 reader_judge 实例。
    assert role_counts["generation"] == 5  # plan 批次 1 + 正文 4
    assert role_counts["fact_judge"] == 4
    assert role_counts["character_judge"] == 4
    assert role_counts["reader_judge"] == 7  # 候选4 + canonical1 + Post-Prose1 + blind-final1

    # T6.1/T6.3/T6.4 选择证据：前沿 + 证据锚定仲裁 + 位置一致率落盘。
    selection = json.loads(
        (run_dir / "candidate_selection.json").read_text(encoding="utf-8")
    )["chapters"]["chapter_1"]
    assert selection["selected"] == "prose_pu_candidate_v1"
    # 计划 1 的两版（v1 推进满足 / v2 语言满足）互不支配 → 构成前沿；计划 2 的两版
    # （violated）被支配淘汰。
    assert set(selection["frontier"]) == {"prose_pu_candidate_v1", "prose_pu_candidate_v2"}
    assert set(selection["soft_dominated"]) == {
        "prose_pu_candidate_b_v1",
        "prose_pu_candidate_b_v2",
    }
    assert "A/B + B/A" in selection["selection_rule"]
    tournament = json.loads(
        (run_dir / "tournament.json").read_text(encoding="utf-8")
    )["chapters"]["chapter_1"]
    assert tournament["stable_winner"] == "prose_pu_candidate_v1"
    assert tournament["position_consistency_rate"] == 1.0
    assert tournament["pairs"][0]["pref_ab"] == "A"
    assert tournament["pairs"][0]["pref_ba"] == "B"
    assert tournament["pairs"][0]["winner"] == "prose_pu_candidate_v1"


def test_plan_invalid_state_refs_remapped_before_plan_gate(tmp_path, monkeypatch):
    # 回归（S6 canary ch9 实测死锁）：temperature=0 下模型把全部候选的
    # input_state_ref/output_state_ref 稳定抄成不存在的 id，计划硬闸（存在性
    # 校验）反复全灭 → quality_exhausted 死循环。runner 必须在硬闸前把无效
    # 引用确定性重映射到当前状态/候选新状态 id，候选照常过闸、流程与调用数
    # 与正常路径完全一致。
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path, monkeypatch=monkeypatch, install_fake=False
    )
    bad_a = _minimal_continue_payload()
    bad_a["plotunit"]["input_state_ref"] = "ns_999_missing"
    bad_a["plotunit"]["output_state_ref"] = "ns_998_missing"
    bad_b = _second_continue_payload()
    bad_b["plotunit"]["input_state_ref"] = "ns_999_missing"
    bad_b["plotunit"]["output_state_ref"] = "ns_998_missing"
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls, plan_text=json.dumps({"candidates": [bad_a, bad_b]})),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    assert terminal.usage.calls == 20
    assert (runner.chapters_dir / "chapter_1.txt").is_file()


def test_reject_path_quality_exhausted(tmp_path, monkeypatch):
    # JudgeClaim 返回 blocking 硬违例（带正文锚点）→ 全部正文候选 rejected →
    # quality_exhausted（硬分数不能由软轴抵消）。
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path, monkeypatch=monkeypatch, install_fake=False
    )
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls, review_blocking=True),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "quality_exhausted"
    assert terminal.committed_chapters == 0
    # plan 批次 1 + 4 版正文 + 12 次评审（三角色全部 blocking）= 17
    assert terminal.usage.calls == 17
    assert not (runner.chapters_dir / "chapter_1.txt").exists()
    assert not (run_dir / "run_manifest.json").exists()

    # 同一拒绝测试覆盖获胜正文绝对质量地板，不新增收集项。
    floor_dir = tmp_path / "post-floor"
    floor_dir.mkdir()
    runner2, run_dir2, _, _, calls2 = _make_runner(
        floor_dir, monkeypatch=monkeypatch, install_fake=False
    )
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls2, post_review_blocking=True),
    )
    terminal2 = runner2.run_until_terminal()
    assert terminal2.status == "quality_exhausted"
    assert terminal2.terminal_reason == "post-prose absolute quality floor: block"
    assert terminal2.committed_chapters == 0
    assert not (runner2.chapters_dir / "chapter_1.txt").exists()
    report = json.loads(
        (run_dir2 / "post_prose_review.json").read_text(encoding="utf-8")
    )
    assert report["route"] == "block"
    assert "generative_indicia" in {
        issue["issue_type"] for issue in report["issues"]
    }


def test_tournament_position_bias_quality_exhausted(tmp_path, monkeypatch):
    # 底层仲裁恒选展示槽位甲；runner 只按正文 hash 做一次 canonical-order 仲裁，
    # 再本地映射 AB/BA，因此槽位行为固定到同一内容而不能制造换位漂移。
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path, monkeypatch=monkeypatch, install_fake=False
    )
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls, tournament_position_biased=True),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    # plan1 + 正文4 + 评审12 + canonical仲裁1 + Post-Prose1 = 19
    assert terminal.usage.calls == 20
    assert (runner.chapters_dir / "chapter_1.txt").exists()
    tournament = json.loads(
        (run_dir / "tournament.json").read_text(encoding="utf-8")
    )["chapters"]["chapter_1"]
    assert tournament["stable_winner"] is not None
    assert tournament["position_consistency_rate"] == 1.0
    assert tournament["pairs"][0]["position_consistent"] is True
    assert tournament["pairs"][0]["discriminator_rounds"] == 1
    selection = json.loads(
        (run_dir / "candidate_selection.json").read_text(encoding="utf-8")
    )["chapters"]["chapter_1"]
    assert selection["selected"] == tournament["stable_winner"]
    assert selection["frontier"]
    assert (run_dir / "run_manifest.json").exists()


def test_provider_error_records_type_only_and_stops(tmp_path, monkeypatch):
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path, monkeypatch=monkeypatch, install_fake=False
    )
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen",
        _fake_urlopen(calls, fail_max_tokens={200}),
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "execution_failed"
    assert terminal.committed_chapters == 0
    assert len(calls) == 1  # 单次 attempt，无重试
    audit = json.loads(
        (run_dir / "calls" / "call_000001.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "failed"
    assert audit["error_type"] == "RuntimeError"
    assert audit["response_sha256"] is None
    for forbidden in ("prompt", "response", "thinking", "credential"):
        assert forbidden not in audit


def test_m1_judge_protocol_violation_single_call_terminal_no_pollution(tmp_path, monkeypatch):
    """M1 生产调用链回归：真实 AutonomousRunner 走 judge 阶段，fake provider 返回协议违规
    （不可解析）评审响应 → 对应逻辑任务 Provider 调用**恰好 1 次**、显式终态失败、
    零章节/零状态污染。锁死「评审协议合规失败立即抛 ReviewQualityExhaustedError，不重新请求」。
    """
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        judge_text="THIS IS NOT A VALID JUDGE JSON{{{",
    )
    terminal = runner.run_until_terminal()
    # 显式终态失败（provider/schema 证据错误，不降级、不静默放行）
    assert terminal.status == "execution_failed"
    assert terminal.terminal_reason == (
        "provider/schema/evidence error: judge failed: ReviewQualityExhaustedError"
    )
    assert terminal.committed_chapters == 0
    # 该逻辑任务（judge）Provider 调用恰好 1 次：plan 1 + prose 4 + judge 1 = 6，无重请求
    assert len(calls) == 6
    judge_calls = [
        c for c in calls
        if json.loads(c.data.decode("utf-8"))["max_tokens"] == 400
    ]
    assert len(judge_calls) == 1
    # 零状态污染：无章节落盘、无 accepted 候选证据
    assert not (runner.chapters_dir / "chapter_1.txt").is_file()
    assert not (run_dir / "state" / "accepted_candidate.json").exists()


def test_budget_exhaustion_halts_before_generation(tmp_path, monkeypatch):
    # 投影 30 calls（plan 1 + 正文 4 + 候选评审 12 + 淘汰赛上界 12 + Post-Prose 1）；
    # budget 只有 2 → 零调用终止
    runner, run_dir, _, _, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        budget_updates={"max_total_calls": 2},
    )
    terminal = runner.run_until_terminal()
    assert terminal.status == "quality_exhausted"
    assert terminal.committed_chapters == 0
    assert calls == []
    assert terminal.usage.calls == 0


def test_crash_mid_commit_refuses_resume(tmp_path, monkeypatch):
    runner, run_dir, policy, profile, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        failpoint=_crash_at("state"),
        budget_updates={"max_chapters_per_run": 3, "max_canary_runs": 1},
    )
    with pytest.raises(RuntimeError, match="simulated crash at state"):
        runner.step()
    # 正文已写，但 A1 manifest 仍是上一状态（running/0），flow manifest 未落盘
    assert (runner.chapters_dir / "chapter_1.txt").is_file()
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "running"
    assert manifest["committed_chapters"] == 0
    assert not (run_dir / "run_manifest.json").exists()
    # 重启必须拒绝进入后续上下文（孤儿章 + 无完整提交）
    with pytest.raises(AutonomousRunnerError, match="refuse to resume"):
        _resume_runner(tmp_path, run_dir, policy, profile)


def test_created_run_resumes_cleanly_and_continues(tmp_path, monkeypatch):
    runner1, run_dir, policy, profile, _ = _make_runner(
        tmp_path, monkeypatch=monkeypatch, install_fake=False
    )
    assert runner1.status == "created"
    # 模拟崩溃：尚未 step，磁盘上只有 created 状态 → 干净续跑
    calls: list = []
    monkeypatch.setattr(
        "src.provider_adapter.urllib.request.urlopen", _fake_urlopen(calls)
    )
    runner2 = _resume_runner(tmp_path, run_dir, policy, profile)
    assert runner2.status == "created"
    terminal = runner2.run_until_terminal()
    assert terminal.status == "completed"
    assert terminal.committed_chapters == 1
    assert terminal.usage.calls == 20


def test_absorb_commit_on_resume(tmp_path, monkeypatch):
    """flow 提交完整成功但 A1 manifest 未推进 → resume 吸收该提交."""
    runner, run_dir, policy, profile, calls = _make_runner(
        tmp_path,
        monkeypatch=monkeypatch,
        budget_updates={"max_chapters_per_run": 3, "max_canary_runs": 1},
    )
    decision = runner.step()
    assert decision.route == "accepted"
    assert runner.status == "running"
    assert runner._run.committed_chapters == 1
    assert (runner.chapters_dir / "chapter_1.txt").is_file()

    # 模拟崩溃：flow manifest 已提交，但 A1 manifest 停在 committed_chapters=0
    manifest_path = run_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["committed_chapters"] = 0
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    resumed = _resume_runner(tmp_path, run_dir, policy, profile)
    assert resumed.status == "running"
    assert resumed._run.committed_chapters == 1  # 吸收
    assert (run_dir / "manifest.json").is_file()


def test_terminal_run_cannot_be_reopened(tmp_path, monkeypatch):
    runner, run_dir, policy, profile, _ = _make_runner(
        tmp_path, monkeypatch=monkeypatch
    )
    terminal = runner.run_until_terminal()
    assert terminal.status in TERMINAL_STATUSES
    with pytest.raises(AutonomousRunnerError, match="refuse to reopen terminal"):
        _resume_runner(tmp_path, run_dir, policy, profile)
