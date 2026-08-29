"""PASS Blind Audit — 测 Post-Prose Review 的漏检率（False Negative Rate）.

当前 A/B 台账只覆盖『Review 决定动刀』的案例（Original / Revision），只能测
Revision Gain（刀法），测不到：
- Review 决定 PASS 的章节，是真的 clean，还是漏掉了问题？

方法（measurement-only，不改生产 Review）：
- 抽样 route=pass 的 committed chapter（Draft/Commit 保证只有 PASS 才提交）。
- 交给独立 Blind Audit：不告诉它这是 PASS 样本、不给原 Review 结果，
  自由寻找正文缺陷并附 evidence。
- 产出 clean / issue 判定，按 issue_type 统计——估算 Review 的漏检率。

与 Detection Precision / Revision Gain 并列，构成完整三层：
    Detection Precision    Review 报的问题，是真的吗？
    Detection Miss Rate    Review 没报的问题，有多少其实存在？
    Revision Gain          按 Review 改，文本真的更好吗？
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from src.workflow_action.json_repair import parse_json

JudgeFn = Callable[[str], str]

# 与 Review 失败类型字典对齐的自由 issue_type 词汇（judge 可自由使用）
VALID_ISSUE_TYPES = (
    "redundancy", "dialogue_flat", "emotion_landing", "interpretive_space",
    "scene_presence", "generative_indicia", "character_distortion",
    "exposition_heavy", "style_drift", "other",
)


class PassAuditUnit:
    """PASS 样本盲审：自由找缺陷，不透露原 Review 结果."""

    def build_audit_prompt(self, chapter_text: str, chapter_label: str = "") -> str:
        """Judge 自由审查一章正文。刻意不告诉它：
        - 这是 Review=PASS 的章节；
        - 原 Review 报了什么 / 没报什么。
        """
        head = f"【章节：{chapter_label}】\n" if chapter_label else ""
        return (
            "你是一位小说质量评审。下面是一章小说正文。"
            "请**自由**审查它是否存在影响阅读质量的缺陷，"
            "不要假设它一定好或一定坏。\n\n"
            + head
            + chapter_text
            + "\n\n【审查维度参考】对白自然度/重复/情绪是否靠声明/解释过度/"
            "现场感/人物一致性/AI 味（句式整齐、情感总被总结、同质化）等。\n"
            "【输出格式】严格 JSON：\n"
            '{"clean": true|false, "findings": ['
            '{"issue_type": "...", "location": "引用原文片段", "severity": '
            '"critical"|"blocking"|"warning"|"low", "evidence": "为什么这是问题"}]}\n'
            "- clean: 该章整体上没有需要修的问题则为 true\n"
            "- findings: 非空时列出每条缺陷；无则 []\n"
            "issue_type 可取值：redundancy / dialogue_flat / emotion_landing / "
            "interpretive_space / scene_presence / generative_indicia / "
            "character_distortion / exposition_heavy / style_drift / other\n"
            "只输出 JSON。"
        )

    def parse_audit(self, response: str) -> dict:
        # 与 judge/plan 解析同一容错层（围栏/前导散文/裸引号——见 json_repair 模块
        # 文档的实测缺陷记录）；干净 JSON 在 parse_json 首选路径下逐字节等价。
        data = parse_json(response)
        if not isinstance(data, dict):
            raise ValueError("audit response must be a JSON object")
        clean = data.get("clean")
        if not isinstance(clean, bool):
            raise ValueError("audit response must declare clean: true|false")
        findings = data.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("audit response field findings must be a list")
        for f in findings:
            if not isinstance(f, dict):
                raise ValueError("findings entries must be JSON objects")
            ft = f.get("issue_type")
            if not isinstance(ft, str) or not ft.strip():
                raise ValueError("finding must have issue_type")
            if ft not in VALID_ISSUE_TYPES:
                raise ValueError(f"unknown issue_type: {ft}")
            sev = f.get("severity")
            if sev not in ("critical", "blocking", "warning", "low"):
                raise ValueError(f"invalid severity: {sev}")
            if not f.get("evidence"):
                raise ValueError("finding must have evidence")
        return {"clean": clean, "findings": findings}

    def run_pass_audit(
        self,
        chapters: list[tuple[str, str]],
        judge: JudgeFn,
    ) -> list[dict]:
        """对每章跑 PASS 盲审，返回 [{chapter_label, clean, findings}]."""
        results = []
        for label, text in chapters:
            prompt = self.build_audit_prompt(text, label)
            parsed = self.parse_audit(judge(prompt))
            results.append({
                "chapter_label": label,
                "original_review_route": "pass",  # committed ⇒ PASS（Draft/Commit）
                "clean": parsed["clean"],
                "findings": parsed["findings"],
            })
        return results


def _longest_common_substring(a: str, b: str) -> int:
    """最长公共子串长度（连续），用于 issue 匹配的『连续较长公共片段』判定."""
    if not a or not b:
        return 0
    n, m = len(a), len(b)
    dp = [0] * (m + 1)
    best = 0
    for i in range(1, n + 1):
        prev = 0
        for j in range(1, m + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > best:
                    best = dp[j]
            else:
                dp[j] = 0
            prev = cur
    return best


# 匹配要求：同 issue_type + 连续公共片段长度 ≥ 此阈值。
# 阈值 4（= 2 个连续 bigram）能抓到『他忽然明白』这类真实复现，但排除
# 『人物/情绪/不是』等公共 2-gram 造成的错配（不同位置同类问题被误判为同一 issue）。
MATCH_LCS_MIN = 4


def match_issue(review_issue: dict, audit_finding: dict) -> bool:
    """判断 Audit finding 是否就是 Review 已报过的同一 issue.

    PASS ≠ Review 没发现 issue——Blind Audit 再次发现原 Review 已报过的 issue
    是『复现/一致判断』，不是漏检。匹配不要求文字完全一样，按：
        issue_type 相同
        AND 位置/描述 与 位置/evidence 之间有**连续较长**公共片段（LCS ≥ 4）

    注意不能用『任意一个 bigram』（中文公共 2-gram 如 人物/情绪/不是 会让不同
    位置的同类问题被误判为同一 issue，导致 True Miss 被低估）。
    只有 unmatched 的 audit finding 才计入 True Miss。
    """
    if review_issue.get("issue_type") != audit_finding.get("issue_type"):
        return False
    r_text = (
        (review_issue.get("location") or "") + " " + (review_issue.get("description") or "")
    )
    a_text = (
        (audit_finding.get("location") or "") + " " + (audit_finding.get("evidence") or "")
    )
    return _longest_common_substring(r_text, a_text) >= MATCH_LCS_MIN


def classify_chapter(
    review_issues: list[dict],
    audit_findings: list[dict],
) -> dict:
    """对一章做 O∩A 匹配，返回 matched / missed / original_only + severity 分歧.

    Returns:
        matched:      audit findings 与原 Review 指向同一缺陷（复现，非漏检）
        missed:       audit findings 原 Review 完全没报（True Miss 候选）
        original_only:原 Review 报了但 audit 没复现（不构成漏检，也不加分）
        severity_disagreements: matched 对中两边严重度判断不同
    """
    matched: list[dict] = []
    missed: list[dict] = []
    used: list[dict] = []
    for f in audit_findings:
        hit = next(
            (r for r in review_issues if match_issue(r, f)),
            None,
        )
        if hit is not None:
            matched.append({"audit": f, "review": hit})
            used.append(hit)
        else:
            missed.append(f)
    original_only = [r for r in review_issues if r not in used]
    severity_disagreements = [
        m for m in matched
        if m["audit"].get("severity") != m["review"].get("severity")
    ]
    return {
        "matched": matched,
        "missed": missed,
        "original_only": original_only,
        "severity_disagreements": severity_disagreements,
    }


def _is_actionable(severity: str) -> bool:
    return severity in ("warning", "blocking", "critical")


def _is_blocking(severity: str) -> bool:
    return severity in ("blocking", "critical")


def summarize_pass_audit(results: list[dict]) -> dict:
    """估算 Review 漏检率（分 cohort + 三档 + True Miss 口径）。

    **口径（验收修正）**：PASS ≠ Review 没发现 issue。Blind Audit 再次发现原
    Review 已报过的 issue 是复现，不算 miss。只有 unmatched 才算 True Miss。

    每章对比 O（原 Review issues，来自 chapter_provenance）与 A（独立 Blind Audit
    findings），输出：
        audit_finding_rate          独立审查又发现问题的章节比例
        true_miss_rate              独立审查发现、原 Review 完全没报的比例
        actionable_true_miss_rate   unmatched 中 severity ∈ {warning,blocking,critical}
        blocking_true_miss_rate     unmatched 中 severity ∈ {blocking,critical}
        severity_disagreement_rate  两边都发现同一问题、但严重度判断不同的匹配对
        original_only_rate          Review 报了、audit 没复现的比例（不计漏检）
    """
    from collections import Counter, defaultdict

    def _tiers(rows: list[dict]) -> dict:
        n = len(rows)
        audited_find = sum(1 for r in rows if r.get("findings"))
        true_missed = sum(1 for r in rows if r.get("_missed"))
        actionable_missed = sum(
            1 for r in rows
            if any(_is_actionable(f.get("severity")) for f in r.get("_missed", []))
        )
        blocking_missed = sum(
            1 for r in rows
            if any(_is_blocking(f.get("severity")) for f in r.get("_missed", []))
        )
        sev_dis = sum(len(r.get("_sev_dis", [])) for r in rows)
        orig_only = sum(len(r.get("_original_only", [])) for r in rows)
        type_counter: Counter = Counter()
        severity_counter: Counter = Counter()
        for r in rows:
            for f in r.get("findings", []):
                type_counter[f["issue_type"]] += 1
                severity_counter[(f["issue_type"], f["severity"])] += 1
        return {
            "n_chapters": n,
            "clean": sum(1 for r in rows if r.get("clean")),
            "has_issues": audited_find,
            "audit_finding_rate": round(audited_find / n, 4) if n else 0.0,
            "true_miss_rate": round(true_missed / n, 4) if n else 0.0,
            "actionable_true_miss_rate": round(actionable_missed / n, 4) if n else 0.0,
            "blocking_true_miss_rate": round(blocking_missed / n, 4) if n else 0.0,
            "severity_disagreement_rate": round(sev_dis / n, 4) if n else 0.0,
            "original_only_total": orig_only,
            "by_issue_type": {
                t: {
                    "count": type_counter[t],
                    "severity_counts": {
                        s: severity_counter[(t, s)] for s in ("critical", "blocking", "warning", "low")
                    },
                }
                for t in sorted(type_counter)
            },
        }

    classified = []
    for r in results:
        c = classify_chapter(r.get("review_issues", []), r.get("findings", []))
        classified.append({
            **r,
            "_matched": c["matched"],
            "_missed": c["missed"],
            "_sev_dis": c["severity_disagreements"],
            "_original_only": c["original_only"],
        })

    by_cohort: dict[str, list[dict]] = defaultdict(list)
    for r in classified:
        cohort = "legacy" if not r.get("prose_review_enabled") else (
            r.get("review_version") or "current"
        )
        by_cohort[cohort].append(r)

    return {
        "overall": _tiers(classified),
        "by_cohort": {c: _tiers(rows) for c, rows in sorted(by_cohort.items())},
        "findings_by_chapter": [
            {
                "chapter": r["chapter_label"],
                "cohort": "legacy" if not r.get("prose_review_enabled") else (
                    r.get("review_version") or "current"
                ),
                "clean": r["clean"],
                "n_findings": len(r.get("findings", [])),
                "matched": [m["audit"] for m in r["_matched"]],
                "missed": r["_missed"],
                "severity_disagreements": r["_sev_dis"],
                "original_only": r["_original_only"],
            }
            for r in classified
        ],
    }


def load_pass_audit_results(output_dir: Path) -> list[dict]:
    """读 PASS 盲审结果（output/pass_audit/pass_audit_results.json，无则空列表）."""
    path = Path(output_dir) / "pass_audit" / "pass_audit_results.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
