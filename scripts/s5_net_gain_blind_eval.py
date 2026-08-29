"""S5（54 计划 §S5）作者先验生成注入净收益盲评——真实 provider 执行。

协议（对齐 54 计划 S5 完成判据「注入净收益 > 0（CI 下界 > 0）」）：
1. 同一状态点构造 ON（作者 kernel + 选择史注入）与 OFF（无注入）两版续写 prompt，
   除作者注入段外逐字节相同。
2. 用真实 provider（generation role）分别生成正文。
3. 盲评：A/B 顺序随机化、隐藏哪版是 ON，judge 只读正文判 better/worse/no_difference/uncertain。
4. 统计 ON 相对 OFF 的 net_rate = (better - worse) / n 与 Wilson 95% CI 下界。

用法：
  python scripts/s5_net_gain_blind_eval.py [--pairs N] [--workspace DIR] [--seed S]

隐私：默认只用内置中性合成语料；不触碰任何真实小说工作区。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

from src.object_state.authorkernel import AuthorKernel, AuthorPrinciple
from src.object_state.autonomous import AutonomousPolicy, ProviderProfile
from src.object_state.choicerecord import (
    CandidateRecord,
    ChoiceLedgerEntry,
    ChoiceRecord,
    RejectedRecord,
)
from src.provider_adapter import AnthropicMessagesProvider, AutonomousBudgetLedger
from src.workflow_action.author_selection import build_author_prompt_context
from src.workflow_action.taste_stack import compute_wilson_ci

BASE_CONTEXT = (
    "他站在办公室门口，手里攥着那封举报信。走廊尽头的脚步声越来越近。"
    "这一刻他必须决定：是退回办公室装作无事发生，还是迎上去当面质问。"
)

# 状态点池（中性合成，覆盖不同决策语境）
STATE_POINTS = [
    "对峙现场：他当众坦白，选择以持续行动换取信任（需要决定如何推进）",
    "关键会议前夜：他犹豫是否提交那份得罪人的整改方案（需要决定是否冒险）",
    "朋友求助：旧识登门借钱，他想起对方曾出卖过自己（需要决定是否帮助）",
    "功成之日：项目落地，领导暗示他揽功，他却想起同事的付出（需要决定如何表态）",
    "深夜独处：他发现抽屉里的旧照片，想起被遗忘的承诺（需要决定是否兑现）",
]


def _principle() -> AuthorPrinciple:
    return AuthorPrinciple(
        principle_id="val_trust_earned",
        category="value",
        vocab_key="trust_earned_over_time",
        description="信任必须随时间与代价挣得，不能因一次道歉即刻恢复",
        status="stable",
        supporting_choices=["d_001"],
        counterexamples=[],
        first_formed_at="t",
        strength=0.8,
    )


def _kernel() -> AuthorKernel:
    p = _principle()
    return AuthorKernel(
        kernel_id="k_s5", values=[p], prohibitions=[], commitments=[],
        tensions=[], attention_biases=[], interpretive_biases=[],
    )


def _ledger() -> ChoiceLedgerEntry:
    def _candidate(cid: str, summary: str) -> CandidateRecord:
        return CandidateRecord(
            candidate_id=cid, summary=summary,
            plotunit={"unit_id": f"pu_{cid}", "level": "scene"},
            new_state_ref=f"ns_{cid}",
        )

    def _choice(did: str, context: str, selected: str, tradeoff: str) -> ChoiceRecord:
        return ChoiceRecord(
            decision_id=did,
            decision_timestamp="2026-08-24T00:00:00+00:00",
            plot_context=context,
            state_ref="ns_in",
            candidates=[_candidate("A", "当众摊牌"), _candidate("C", "即刻原谅")],
            selected_candidate=selected,
            rejected=[RejectedRecord(candidate_id="C", reason="人物当前不会这样")],
            tradeoff=tradeoff,
            value_conflicts=["trust_earned_over_time"],
        )

    return ChoiceLedgerEntry(choices=[
        _choice("d_001", "他当众摊牌，换来背叛者的坦诚", "A", "信任以风险换取真实"),
        _choice("d_002", "他再次原谅，代价被一笔带过", "C", "信任被廉价消费"),
    ])


def _write_workspace(root: Path) -> None:
    (root / "author_kernel.json").write_text(
        _kernel().model_dump_json(indent=2), encoding="utf-8")
    (root / "choice_ledger.json").write_text(
        _ledger().model_dump_json(indent=2), encoding="utf-8")


def _build_prompt(state_point: str, injection: str) -> str:
    base = (
        "续写以下小说片段（约 400-600 字，中文，保持现有叙事语气）：\n\n"
        f"【情境】{BASE_CONTEXT}\n\n"
        f"【决策点】{state_point}\n\n"
        "请写出这段续写正文，直接输出正文内容，不要任何解释或标记。"
    )
    if injection:
        base += f"\n\n{injection}"
    return base


JUDGE_PROMPT = (
    "你是小说质量评审。以下是同一片段的两版续写（A 与 B），顺序随机，"
    "你不知道哪版来自何种写作设定。请仅从读者体验出发，判断哪版更好。\n\n"
    "评审维度：人物行为可信度、情绪落地、场景在场感、信息展开、语言质地。\n\n"
    "【A 版】\n{text_a}\n\n【B 版】\n{text_b}\n\n"
    '只输出一个词：better_a / better_b / no_difference / uncertain。'
)


def _load_policy_profile(policy_path: Path, profile_path: Path):
    policy = AutonomousPolicy.model_validate_json(policy_path.read_text(encoding="utf-8"))
    profile = ProviderProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    return policy, profile


def _call_with_retry(provider, request, retries: int = 8, base_delay: float = 10.0):
    """429 限流时指数退避重试；其他错误直接抛（不吞异常，对齐 M1 单次调用契约）.

    provider 是 M1 单次调用契约：失败会写 failed 审计。429 重试前必须删除
    本次调用刚写入的 failed 审计（call_{usage.calls+1}.json），否则重试成功后
    FileExistsError。这是 harness 层修复，不改 provider 语义。
    """
    import urllib.error
    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return provider(request)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == retries:
                raise
            # 删除本次 failed 审计（provider 内部已写入）
            call_number = provider.ledger.usage.calls + 1
            audit_path = Path(provider.audit_dir) / f"call_{call_number:06d}.json"
            if audit_path.exists():
                audit_path.unlink()
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--policy", default="runtime/refs/bai_active/canary_policy_bai_smoke.json")
    parser.add_argument("--profile", default="runtime/refs/bai_active/provider_profile_bai.json")
    parser.add_argument("--out", default="runtime/refs/bai_active/s5_net_gain_report.json")
    args = parser.parse_args(argv)

    if not os.environ.get("ANTHROPIC_BASE_URL") or not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("Error: 需要环境变量 ANTHROPIC_BASE_URL 与 ANTHROPIC_AUTH_TOKEN")
        return 2

    rng = random.Random(args.seed)
    policy, profile = _load_policy_profile(Path(args.policy), Path(args.profile))

    ledger = AutonomousBudgetLedger(
        budget=policy.budget, pricing=profile.pricing_usd_per_million_tokens)
    # 每次运行用独立审计目录（避免跨运行 call 编号冲突）
    audit_dir = Path("runtime/refs/bai_active") / f"calls_s5_{int(time.time())}"
    audit_dir.mkdir(parents=True, exist_ok=True)
    gen = AnthropicMessagesProvider(
        profile=profile, role="generation",
        max_output_tokens=2000,
        audit_dir=audit_dir,
        ledger=ledger,
    )
    judge = AnthropicMessagesProvider(
        profile=profile, role="reader_judge",
        max_output_tokens=800,
        audit_dir=audit_dir,
        ledger=ledger,
    )

    from src.llm_interface import DirectAPIRequest
    req_model = profile.roles.generation.request_model

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_workspace(root)
        injection = build_author_prompt_context(root, STATE_POINTS[0])

    print(f"S5 作者先验注入净收益盲评（真实 provider, pairs={args.pairs}）")
    print(f"  注入段长度: {len(injection)} chars; ON 非空: {bool(injection)}")
    if not injection:
        print("Error: 注入段为空，无法盲评")
        return 1

    # 断点续跑：读已完成的中间进度
    progress_path = Path("runtime/refs/bai_active/s5_pairs_progress.json")
    done_pairs: dict[int, dict] = {}
    if progress_path.exists():
        try:
            done_pairs = {
                int(p["pair"]): p
                for p in json.loads(progress_path.read_text(encoding="utf-8"))
            }
        except Exception:
            done_pairs = {}
    results: list[dict] = [done_pairs[i + 1] for i in range(len(done_pairs))] if done_pairs else []
    start = len(results)
    for i in range(start, args.pairs):
        state_point = STATE_POINTS[i % len(STATE_POINTS)]
        prompt_on = _build_prompt(state_point, injection)
        prompt_off = _build_prompt(state_point, "")

        # 生成
        on_text = _call_with_retry(
            gen, DirectAPIRequest(model=req_model, prompt=prompt_on)).text
        time.sleep(2)
        off_text = _call_with_retry(
            gen, DirectAPIRequest(model=req_model, prompt=prompt_off)).text
        time.sleep(2)

        # 盲评（A/B 随机顺序）
        if rng.random() < 0.5:
            judge_text = JUDGE_PROMPT.format(text_a=on_text, text_b=off_text)
            a_is_on = True
        else:
            judge_text = JUDGE_PROMPT.format(text_a=off_text, text_b=on_text)
            a_is_on = False
        verdict = _call_with_retry(
            judge, DirectAPIRequest(model=req_model, prompt=judge_text)).text.strip().lower()
        time.sleep(2)

        # 归一化 verdict → ON 是否更好
        if verdict.startswith("better_a"):
            on_better = a_is_on
        elif verdict.startswith("better_b"):
            on_better = not a_is_on
        elif verdict.startswith("no_difference"):
            on_better = None
        else:
            on_better = None  # uncertain / 解析失败按弃权

        results.append({
            "pair": i + 1,
            "state_point": state_point,
            "verdict_raw": verdict,
            "a_is_on": a_is_on,
            "on_better": on_better,
        })
        # 每对完成后立即固化进度（断点续跑）
        try:
            progress_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        tag = {True: "ON+", False: "ON-", None: "eq/?"}[on_better]
        print(f"  pair {i + 1}: verdict={verdict} -> {tag}")

    better = sum(1 for r in results if r["on_better"] is True)
    worse = sum(1 for r in results if r["on_better"] is False)
    no_diff = sum(1 for r in results if r["on_better"] is None)
    n = len(results)
    decided = better + worse
    net_rate = (better - worse) / n if n else 0.0
    better_rate = better / decided if decided else None
    # 净收益 > 0 ⟺ ON 赢率 > 0.5（在有明确判断的对子上）；Wilson CI 用 decided 作分母
    if decided:
        wilson_low, wilson_high = compute_wilson_ci(better, decided)
    else:
        wilson_low, wilson_high = (0.0, 0.0)
    # 判据：better_rate 的 Wilson 95% 下界 > 0.5（即净收益 CI 下界 > 0）
    met_net_gain = bool(decided and wilson_low > 0.5)

    report = {
        "schema_version": "1.0",
        "pairs": n, "better": better, "worse": worse, "no_diff_or_uncertain": no_diff,
        "decided": decided,
        "net_rate": round(net_rate, 4),
        "better_rate": round(better_rate, 4) if better_rate is not None else None,
        "wilson_ci_95_better_rate": [wilson_low, wilson_high],
        "wilson_ci_low": wilson_low,
        "met_net_gain": met_net_gain,
        "injection_chars": len(injection),
        "provider_model": req_model,
        "pairs_detail": results,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n  合计: better={better} worse={worse} 弃权={no_diff} n={n} decided={decided}")
    print(f"  net_rate = {net_rate:+.3f}   better_rate = {better_rate if better_rate is not None else 0:.3f}")
    print(f"  Wilson 95% CI (better_rate) = [{wilson_low}, {wilson_high}]")
    print(f"  净收益判据（better_rate CI 下界 > 0.5）: {'PASS' if met_net_gain else 'FAIL'}")
    print(f"  报告: {args.out}")
    return 0 if met_net_gain else 1


if __name__ == "__main__":
    sys.exit(main())
