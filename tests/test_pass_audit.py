"""PASS Blind Audit tests — 测 Review 漏检率（False Negative Rate）.

覆盖：
- build_audit_prompt：不透露 PASS 样本身份、不给原 Review 结果、自由找缺陷。
- parse_audit 严格性（clean 必须 bool / issue_type 词表 / severity 枚举 / evidence 必填）。
- run_pass_audit：独立 Judge 写回 {chapter_label, clean, findings}。
- summarize_pass_audit：miss_rate 估算 + 按 issue_type 分层 + severity 分布。
"""

import json

import pytest

from src.boundary_control.chapter_commit import ChapterCommitBoundary
from src.experiment.pass_audit import (
    PassAuditUnit,
    summarize_pass_audit,
)
from src.pass_audit_short_form import _chapter_num, _load_provenance


def _chapter(text: str) -> tuple[str, str]:
    return ("chapter_1", text)


def test_audit_prompt_hides_pass_status():
    p = PassAuditUnit().build_audit_prompt("正文……", "chapter_1")
    assert "正文……" in p
    # 不透露这是 PASS 样本、不给原 Review 结果
    assert "pass" not in p.lower().replace("章节", "").replace("审查", "")
    assert "review" not in p.lower()
    assert "clean" in p  # 只给判定契约，不给结论


def test_audit_prompt_freely_searches_issues():
    p = PassAuditUnit().build_audit_prompt("他忽然明白了一切。", "chapter_1")
    # 自由审查维度在场（AI 味/解释过度/现场感等）
    assert "AI 味" in p or "解释过度" in p
    assert "不要假设它一定好或一定坏" in p


def test_parse_audit_clean():
    r = PassAuditUnit().parse_audit(json.dumps({"clean": True, "findings": []}))
    assert r["clean"] is True and r["findings"] == []


def test_parse_audit_with_finding():
    resp = json.dumps({
        "clean": False,
        "findings": [{
            "issue_type": "redundancy",
            "location": "『你说过，你三年前走进宪碑司』",
            "severity": "warning",
            "evidence": "同章对白逐字重复两次",
        }],
    })
    r = PassAuditUnit().parse_audit(resp)
    assert r["clean"] is False
    assert r["findings"][0]["issue_type"] == "redundancy"


def test_parse_audit_rejects_missing_clean():
    with pytest.raises(ValueError):
        PassAuditUnit().parse_audit(json.dumps({"findings": []}))


def test_parse_audit_rejects_unknown_issue_type():
    with pytest.raises(ValueError):
        PassAuditUnit().parse_audit(json.dumps({
            "clean": False, "findings": [{"issue_type": "spelling",
                                          "severity": "low", "evidence": "x"}],
        }))


def test_parse_audit_rejects_bad_severity():
    with pytest.raises(ValueError):
        PassAuditUnit().parse_audit(json.dumps({
            "clean": False, "findings": [{"issue_type": "redundancy",
                                          "severity": "fatal", "evidence": "x"}],
        }))


def test_run_pass_audit_records_findings():
    def fake_judge(prompt: str) -> str:
        return json.dumps({
            "clean": False,
            "findings": [{
                "issue_type": "generative_indicia", "location": "…",
                "severity": "warning", "evidence": "情绪靠声明",
            }],
        })

    results = PassAuditUnit().run_pass_audit([_chapter("正文……")], fake_judge)
    assert results[0]["original_review_route"] == "pass"
    assert results[0]["clean"] is False
    assert results[0]["findings"][0]["issue_type"] == "generative_indicia"


def test_summarize_miss_rate(tmp_path):
    def fake_judge(prompt: str) -> str:
        return json.dumps({
            "clean": False,
            "findings": [{
                "issue_type": "redundancy", "location": "…",
                "severity": "warning", "evidence": "重复",
            }],
        })

    clean_judge = lambda prompt: json.dumps({"clean": True, "findings": []})  # noqa: E731
    results = PassAuditUnit().run_pass_audit([_chapter("a……"), _chapter("b……"), _chapter("c……")], clean_judge)
    results += PassAuditUnit().run_pass_audit([_chapter("d……"), _chapter("e……")], fake_judge)
    s = summarize_pass_audit(results)
    o = s["overall"]
    assert o["n_chapters"] == 5
    assert o["clean"] == 3
    assert o["has_issues"] == 2
    assert o["audit_finding_rate"] == pytest.approx(0.4)
    assert o["true_miss_rate"] == pytest.approx(0.4)
    assert o["by_issue_type"]["redundancy"]["count"] == 2

    # staged --sample 必须跨重跑稳定，否则 response 会错配章节。
    import random

    chapters = []
    for number in range(1, 31):
        path = tmp_path / f"chapter_{number}.txt"
        path.write_text(str(number), encoding="utf-8")
        chapters.append(path)
    first = sorted(random.Random(0).sample(chapters, 10), key=_chapter_num)
    second = sorted(random.Random(0).sample(chapters, 10), key=_chapter_num)
    assert [path.name for path in first] == [path.name for path in second]

    # A1 每章独立 run：只有 recover 认可且 review_route=pass 的事务 sidecar 可作为 O。
    provenance_root = tmp_path / "novel" / "output"
    committed = provenance_root / "ch1-try2"
    chapters_dir = tmp_path / "novel" / "chapters"
    committed.mkdir(parents=True)
    chapters_dir.mkdir()
    state_path = committed / "state.json"
    state_path.write_text('{"state":"before"}', encoding="utf-8")
    review_issues = []
    review_hash = __import__("hashlib").sha256(
        json.dumps(review_issues, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    provenance_json = json.dumps(
        {
            "chapters": {
                "chapter_1": {
                    "review_version": "post-prose-v1",
                    "review_issues": review_issues,
                    "review_evidence_hash": review_hash,
                }
            }
        }
    )
    ChapterCommitBoundary(committed, chapters_dir).commit(
        run_id="compose-1",
        mode="compose",
        chapter_number=1,
        chapter_text="正文",
        state_path=state_path,
        state_json='{"state":"after"}',
        frames_path=committed / "frames.json",
        frames_json="[]",
        archive_text="正文",
        provenance_json=provenance_json,
        facts_package_hash="f" * 64,
        review_route="pass",
    )
    failed = provenance_root / "ch1-try3"
    failed.mkdir()
    (failed / "chapter_provenance.json").write_text(
        json.dumps({"chapters": {"chapter_1": {"review_version": "must-not-win"}}}),
        encoding="utf-8",
    )

    assert _load_provenance(provenance_root)["chapter_1"]["review_version"] == "post-prose-v1"


def test_summarize_empty():
    s = summarize_pass_audit([])
    assert s["overall"]["n_chapters"] == 0
    assert s["overall"]["audit_finding_rate"] == 0.0
    assert s["overall"]["true_miss_rate"] == 0.0


def test_match_issue_requires_same_type_and_text_overlap():
    """PASS ≠ Review 没发现 issue：audit 复现原 Review 已报的 issue 不算漏检."""
    from src.experiment.pass_audit import match_issue

    review = {"issue_type": "generative_indicia", "severity": "low",
              "location": "chapters/chapter_9.txt 中部",
              "description": "『他忽然』『忽然明白』『忽然想起』同章出现三次"}
    # 同 type + 共享 bigram（忽然）→ 复现，匹配
    audit_same = {"issue_type": "generative_indicia", "severity": "warning",
                  "location": "『他忽然明白』『他忽然想起』『他忽然知道』同章三次",
                  "evidence": "『忽然』转折标记三次"}
    assert match_issue(review, audit_same) is True
    # 同 type 但完全不同的缺陷 → 不匹配
    audit_diff = {"issue_type": "generative_indicia", "severity": "low",
                  "location": "『不是A而是B』壳句式偏多",
                  "evidence": "转折结构重复"}
    assert match_issue(review, audit_diff) is False
    # 不同 type → 不匹配
    audit_other_type = {"issue_type": "interpretive_space", "severity": "low",
                        "location": "『他忽然明白…』",
                        "evidence": "留白偏满"}
    assert match_issue(review, audit_other_type) is False


def test_true_miss_excludes_review_reported_issues():
    """audit 复现 Review 已报的 issue 不计入 miss；未报的才算 True Miss."""
    from src.experiment.pass_audit import PassAuditUnit, summarize_pass_audit

    u = PassAuditUnit()
    # 一章：Review 报了『忽然×3』，audit 复现它（共享『他忽然明白』连续片段）+ 新报一个 interpretive_space
    results = [{
        "chapter_label": "chapter_9", "prose_review_enabled": True,
        "review_version": "post-prose-v1",
        "review_issues": [{"issue_type": "generative_indicia", "severity": "low",
                           "location": "『他忽然明白』『他忽然想起』同章三次",
                           "description": "『忽然』转折标记重复"}],
        "clean": False,
        "findings": [
            {"issue_type": "generative_indicia", "severity": "warning",
             "location": "『他忽然明白』『他忽然想起』『他忽然知道』同章三次",
             "evidence": "『忽然』转折标记重复"},
            {"issue_type": "interpretive_space", "severity": "low",
             "location": "『他忽然知道』", "evidence": "留白偏满"},
        ],
    }]
    o = summarize_pass_audit(results)["overall"]
    assert o["audit_finding_rate"] == 1.0   # audit 发现了东西
    assert o["true_miss_rate"] == 1.0       # 1/1 章有 unmatched（interpretive_space）
    assert o["actionable_true_miss_rate"] == 0.0  # unmatched 都是 low
    assert o["severity_disagreement_rate"] == 1.0  # 复现的『忽然』：low vs warning


def test_match_issue_requires_continuous_fragment_not_common_bigram():
    """匹配要求连续较长公共片段（LCS≥4），公共 2-gram（人物/情绪/不是）不构成匹配."""
    from src.experiment.pass_audit import match_issue

    review = {"issue_type": "generative_indicia", "severity": "low",
              "location": "某段", "description": "『不是A而是B』壳句式偏多"}
    # 同类问题、都含『不是』，但位置/证据完全不同 → 不应匹配（避免 True Miss 被低估）
    audit_different_spot = {"issue_type": "generative_indicia", "severity": "low",
                            "location": "另一段", "evidence": "转折结构用了两次『而是』"}
    assert match_issue(review, audit_different_spot) is False
    # 连续较长公共片段（≥4 字符）→ 匹配
    audit_same_spot = {"issue_type": "generative_indicia", "severity": "warning",
                       "location": "『不是A而是B』壳句式", "evidence": "『不是』转折结构重复"}
    assert match_issue(review, audit_same_spot) is True


def test_summarize_tiered_miss_rates():
    """any / actionable / blocking 三档分开：漏整段重复 ≠ 『忽然』稍多."""
    from src.experiment.pass_audit import PassAuditUnit
    def j_blocking(prompt):
        return json.dumps({"clean": False, "findings": [{
            "issue_type": "redundancy", "location": "…", "severity": "blocking",
            "evidence": "整段重复"}]})
    def j_low(prompt):
        return json.dumps({"clean": False, "findings": [{
            "issue_type": "generative_indicia", "location": "…", "severity": "low",
            "evidence": "『忽然』稍多"}]})
    u = PassAuditUnit()
    results = u.run_pass_audit([("a", "t"), ("b", "t"), ("c", "t")], j_blocking)
    results += u.run_pass_audit([("d", "t"), ("e", "t")], j_low)
    o = summarize_pass_audit(results)["overall"]
    assert o["audit_finding_rate"] == pytest.approx(1.0)
    assert o["actionable_true_miss_rate"] == pytest.approx(0.6)
    assert o["blocking_true_miss_rate"] == pytest.approx(0.6)


def test_summarize_cohort_split():
    """不同审核世代分 cohort，不混算."""
    from src.experiment.pass_audit import PassAuditUnit
    u = PassAuditUnit()
    results = u.run_pass_audit([("legacy_ch", "t"), ("legacy_ch2", "t")], lambda p: json.dumps({"clean": True, "findings": []}))
    results += u.run_pass_audit([("cur_ch", "t")], lambda p: json.dumps({"clean": False, "findings": [{
        "issue_type": "redundancy", "location": "…", "severity": "blocking", "evidence": "x"}]}))
    for r in results:
        r["prose_review_enabled"] = r["chapter_label"].startswith("cur")
        r["review_version"] = "post-prose-v1" if r["prose_review_enabled"] else "pre-prose-v0"
    s = summarize_pass_audit(results)
    assert s["by_cohort"]["legacy"]["blocking_true_miss_rate"] == 0.0
    assert s["by_cohort"]["post-prose-v1"]["blocking_true_miss_rate"] == pytest.approx(1.0)
