"""Blind A/B 评审工具 — 测量 Post-Prose Review 的净效果（measurement-only）.

核心问题：Post-Prose Review 每次提出正文修改（prose_revise → A/B 台账），
到底让小说净变好多少？**不**默认「Review 成功」。

两个独立指标（正式固定，验收定义）：
- **Detection Precision**：Review 说『这里有缺陷』，盲评者是否也认为原文确实存在该缺陷？
- **Revision Gain**：在缺陷确实存在的前提下，修改版是否优于原版？

防评审自证的关键约束：
1. Judge ≠ Revision Agent：盲评 prompt 不展示 Review issue、不展示修改建议。
2. 隐藏 `which_is_original`：A/B 顺序在记录时已随机化，Judge 不知道哪个是原文。
3. 保留 Abstain：`no_difference` / `uncertain`，不允许强迫二选一——如果修改只是
   no difference，本身就不算高价值。
4. 按 issue_type 分层统计，不混成单一胜率；给出 95% Wilson CI 区分
   『稳定改善』vs『十几样本碰巧不错』。

输出示例（分层）：
    issue_type            better  worse  no_diff  uncertain  net   better_rate   95% CI
    redundancy            38      4      6        2          +34   0.90          (0.77, 0.96)
    generative_indicia    12      3      5        1          +9    0.80          (0.55, 0.93)
    interpretive_space    2       6      3        0          -4    0.25          (0.07, 0.59)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

PREFERENCE_OPTIONS = ("version_a", "version_b", "no_difference", "uncertain")

# Judge 协议：judge(prompt_text) -> str（返回 JSON 判断文本）
JudgeFn = Callable[[str], str]


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval（比例的小样本区间，避免正态近似在小 n 失效）."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _original_text(entry: dict) -> str:
    """取台账条目的原文（哪个是原文由记录时随机化，评审时隐藏，统计时揭晓）."""
    if entry.get("which_is_original") == "a":
        return entry.get("version_a", "")
    return entry.get("version_b", "")


def _revision_text(entry: dict) -> str:
    if entry.get("which_is_original") == "a":
        return entry.get("version_b", "")
    return entry.get("version_a", "")


class BlindEvalUnit:
    """生成盲评 prompt / 解析盲评响应（纯函数，可测）."""

    def build_revision_gain_prompt(self, entry: dict) -> str:
        """Revision Gain pass：呈现 A/B 两版，无任何标注——不透露哪个是原文、
        不展示 Review issue/建议。Judge 只读文本。
        """
        return (
            "你是一位小说质量评审。下面是对同一段小说正文的两个版本（A 和 B），"
            "它们来自同一次修改前后。请只凭文本质量判断，不要猜测哪个是『原文』：\n\n"
            "【版本 A】\n" + entry.get("version_a", "") + "\n\n"
            "【版本 B】\n" + entry.get("version_b", "") + "\n\n"
            "【输出格式】严格 JSON：\n"
            '{"preference": "version_a"|"version_b"|"no_difference"|"uncertain",'
            ' "confidence": 0-1}\n'
            "- preference: 哪个版本读起来更好；两者差不多用 no_difference（不是硬选）；"
            "拿不准/差异太小用 uncertain\n"
            "- confidence: 你对这个判断的把握（0-1）\n"
            "只输出 JSON。"
        )

    def parse_revision_gain(self, response: str) -> dict:
        """解析 Revision Gain 响应。返回 {preference, confidence}."""
        data = json.loads(response)
        pref = data.get("preference")
        if pref not in PREFERENCE_OPTIONS:
            raise ValueError(f"invalid preference: {pref}")
        conf = data.get("confidence")
        if conf is None:
            conf = 0.5
        return {"preference": pref, "confidence": float(conf)}

    def build_detection_prompt(self, entry: dict) -> str:
        """Detection Precision pass：只呈现原文 + 被标记的 issue_type，
        问『原文是否确实存在该缺陷』。注意：不展示 revision、不展示 issue 描述。
        """
        issue_types = entry.get("issue_types") or ["unknown"]
        return (
            "你是一位小说质量评审。下面是一段小说正文，以及审查者给它标记的问题类型。"
            "请判断该正文是否**确实**存在此类问题（不是审查者说有问题就一定有问题）。\n\n"
            "【被标记的问题类型】" + ", ".join(issue_types) + "\n\n"
            "【正文】\n" + _original_text(entry) + "\n\n"
            "【输出格式】严格 JSON：\n"
            '{"flaw_present": true|false|"uncertain", "confidence": 0-1}\n'
            "- flaw_present: 原文是否确实存在被标记的缺陷；拿不准用 \"uncertain\"\n"
            "只输出 JSON。"
        )

    def parse_detection(self, response: str) -> dict:
        data = json.loads(response)
        fp = data.get("flaw_present")
        if fp not in (True, False, "uncertain"):
            raise ValueError(f"invalid flaw_present: {fp}")
        conf = data.get("confidence")
        if conf is None:
            conf = 0.5
        return {"flaw_present": fp, "confidence": float(conf)}


def run_revision_gain(entries: list[dict], judge: JudgeFn, judge_id: str = "judge_1") -> list[dict]:
    """对每条目跑 Revision Gain 盲评，把 judge 结果追加到 entry["revision_gain"]["judgments"].

    schema 从一开始支持多 Judge（judgments: [{judge_id, preference, confidence}]），
    避免『同一模型家族 + 相似审美先验 互相认同』的自证；最终可区分 3/3、2/3、split。
    """
    unit = BlindEvalUnit()
    for entry in entries:
        prompt = unit.build_revision_gain_prompt(entry)
        result = unit.parse_revision_gain(judge(prompt))
        rg = entry.setdefault("revision_gain", {})
        rg.setdefault("judgments", []).append({
            "judge_id": judge_id,
            "preference": result["preference"],
            "confidence": result["confidence"],
        })
        # 聚合字段 = 多数意见（单一 Judge 时即该 Judge）
        rg["preference"] = _majority_preference(rg["judgments"])
    return entries


def run_detection(entries: list[dict], judge: JudgeFn, judge_id: str = "judge_1") -> list[dict]:
    """对每条目跑 Detection Precision 盲评，追加到 entry["detection"]["judgments"]."""
    unit = BlindEvalUnit()
    for entry in entries:
        prompt = unit.build_detection_prompt(entry)
        result = unit.parse_detection(judge(prompt))
        det = entry.setdefault("detection", {})
        det.setdefault("judgments", []).append({
            "judge_id": judge_id,
            "flaw_present": result["flaw_present"],
            "confidence": result["confidence"],
        })
        det["original_has_flaw"] = _majority_flaw(det["judgments"])
    return entries


def _majority_preference(judgments: list[dict]) -> str:
    """多数偏好；平票 → 'uncertain'（split，不硬选）。"""
    if not judgments:
        return None
    from collections import Counter
    counts = Counter(j["preference"] for j in judgments)
    top = counts.most_common()
    if len(top) >= 2 and top[0][1] == top[1][1]:
        return "uncertain"
    return top[0][0]


def _majority_flaw(judgments: list[dict]) -> object:
    if not judgments:
        return None
    from collections import Counter
    counts = Counter(
        j["flaw_present"] for j in judgments
        if j["flaw_present"] in (True, False)
    )
    if not counts:
        return "uncertain"
    top = counts.most_common()
    if len(top) >= 2 and top[0][1] == top[1][1]:
        return "uncertain"
    return top[0][0]


def summarize(entries: list[dict]) -> dict:
    """分层统计 Revision Gain + Detection Precision。

    返回按 issue_type 分组的：
        better / worse / no_diff / uncertain / n
        net_rate = (better - worse) / n
        better_rate = better / (better + worse)（只在有判断的样本上）
        better_rate_ci = Wilson 95% CI
        detection_precision = 原文确实有缺陷 的占比（在有判定样本上）
    以及 overall 汇总。
    """
    from collections import defaultdict

    def _stats(rows: list[dict]) -> dict:
        better = worse = no_diff = uncertain = 0
        detected = confirmed = 0
        consensus_all = consensus_majority = consensus_split = 0
        for r in rows:
            rg = r.get("revision_gain") or {}
            pref = rg.get("preference")
            judgments = rg.get("judgments") or []
            if len(judgments) >= 2:
                prefs = [j["preference"] for j in judgments]
                uniq = set(prefs)
                if len(uniq) == 1:
                    consensus_all += 1
                elif len(prefs) == 2 and len(uniq) == 2:
                    consensus_split += 1
                else:
                    # 多 Judge 平票 → split；多数一致 → majority
                    from collections import Counter
                    top = Counter(prefs).most_common(2)
                    if top[0][1] == top[1][1]:
                        consensus_split += 1
                    else:
                        consensus_majority += 1
            if pref == "version_b":
                # which_is_original=a 时 version_b=revision；否则反之
                if r.get("which_is_original") == "a":
                    better += 1
                else:
                    worse += 1
            elif pref == "version_a":
                if r.get("which_is_original") == "a":
                    worse += 1
                else:
                    better += 1
            elif pref == "no_difference":
                no_diff += 1
            elif pref == "uncertain":
                uncertain += 1
            fp = (r.get("detection") or {}).get("original_has_flaw")
            if fp in (True, False):
                detected += 1
                if fp is True:
                    confirmed += 1
        n = len(rows)
        decided = better + worse
        better_rate = better / decided if decided else None
        ci = _wilson_ci(better, decided) if decided else None
        return {
            "better": better, "worse": worse, "no_diff": no_diff,
            "uncertain": uncertain, "n": n,
            "net_rate": (better - worse) / n if n else 0.0,
            "better_rate": round(better_rate, 4) if better_rate is not None else None,
            "better_rate_ci": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "detection_precision": round(confirmed / detected, 4) if detected else None,
            "detection_n": detected,
            "consensus": {
                "all_agree": consensus_all,
                "majority": consensus_majority,
                "split": consensus_split,
            },
        }

    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        types = e.get("issue_types") or ["unknown"]
        for t in types:
            by_type[t].append(e)

    result: dict = {"overall": _stats(entries), "by_issue_type": {}}
    for t in sorted(by_type):
        result["by_issue_type"][t] = _stats(by_type[t])
    return result


def load_ledger(output_dir: Path) -> list[dict]:
    """读 A/B 台账（无则空列表）。"""
    path = Path(output_dir) / "prose_revision_ledger.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("revisions", [])
