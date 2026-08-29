"""Review-after-Prose（42 设计 F3b 落地）测试.

覆盖：
- review.build_prompt 的 prose_text 注入：None/空串字节不变（零成本契约），
  非空注入【本章正文】+ 正文层 7 维审查
- prose.build_revision_prompt：正文层修订 prompt（post-prose Review 的 rewrite 路径）
- extend 集成：Continue → Pre-Review(代码闸) → Prose → Review(读正文) 的
  新时序；review_prompt 含【本章正文】；extend_result 记 prose_context
- Pre-Review 代码闸：结构阻断 → 对象层重写 → 不生成 prose
- 迁移检测：旧流程残留 review_response（缺 prose_response）→ fail-fast
"""

import json
import subprocess
import sys
from pathlib import Path

from src.workflow_action.review import ReviewUnit
from src.workflow_action.prose import build_revision_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _minimal_rebuild_payload(*, bad_relation: bool = False) -> dict:
    relations = {"c999": "不存在的关系"} if bad_relation else {}
    return {
        "workspec": {
            "genre": "悬疑",
            "audience": "青年",
            "theme": "真相",
            "tone": "克制",
            "pacing": "短弧推进",
        },
        "worldmodel": {"world_facts": ["世界事实"]},
        "charactermodels": [
            {
                "character_id": "c001",
                "name": "主角",
                "identity": "侦探",
                "outer_goal": "破案",
                "inner_need": "正义",
                "fear": "失败",
                "flaw": "固执",
                "strength": "观察力",
                "stance": "中立",
                "relations": relations,
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "夜晚",
            "current_location": "案发现场",
            "current_situation": "调查开始",
            "active_characters": ["c001"],
        },
        "factledger": {
            "entries": [
                {
                    "fact_id": "f1",
                    "statement": "确认事实",
                    "fact_type": "event",
                    "confirmed": True,
                }
            ]
        },
        "foreshadowgraph": {"entries": []},
        "confidence_gaps": [],
    }


def _minimal_continue_payload(*, input_state_ref: str = "ns_001") -> dict:
    return {
        "plotunit": {
            "unit_id": "pu_candidate",
            "level": "scene",
            "goal": "推进候选场景",
            "participants": ["c001"],
            "conflict": "候选冲突",
            "input_state_ref": input_state_ref,
            "output_state_ref": "ns_002",
            "released_information": ["候选信息"],
            "consequences": ["候选后果"],
            "is_effective": True,
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


def _long_prose() -> str:
    """超过 MIN_PROSE_CHARS(200) 的正文."""
    return (
        "第一章 开端\n他推开门，屋里的光线斜斜地落在桌上。杯子里剩下半口冷水，"
        "窗缝里有风，把桌角的一张纸吹起又落下。他站在那里，没有动，手停在门框上，"
        "听走廊尽头传来脚步声，越来越近。他想起三天前的事，想起那人临走时说的话。"
        "他原以为不会再回来，此刻却一步也迈不动。他低头，看见自己鞋底沾着刚干的泥，"
        "那是昨天夜里走夜路踩上的。桌上的纸又翻了个面，露出背面的字迹——是那个人的手笔。"
        "他认得那个勾法，认得那个收笔的位置。窗外有鸟叫，他忽然觉得这间屋子空得过分，"
        "连呼吸都有回声。他伸出手，指尖碰到纸边，又缩回来。他不知道自己在怕什么，"
        "只知道这一刻，他不该继续站在这里。脚步声停在了门口。"
    )


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_input_hash(output_dir: Path, input_path: Path) -> None:
    from src.boundary_control.runtime_identity import file_content_hash

    (output_dir / ".input_hash").write_text(
        file_content_hash(input_path), encoding="utf-8"
    )


def _setup_extend(tmp_path: Path) -> tuple[Path, Path, Path]:
    """建一个已过 Rebuild 的 extend 工作区（rebuild_package + .input_hash + frames）.

    output_dir 用三层（novel/output/extend）——extend 计算
    chapters_dir = output_dir.parent.parent/chapters，三层使 chapters 落在
    本测试独占的 tmp_path 下，避免各测试共享 pytest 临时根目录的 chapters/。
    """
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本，用于驱动 staged 流程。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)

    # 第一次运行：生成 rebuild_prompt 并 WAITING
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout, r.stdout + r.stderr
    # 落地 rebuild response，重跑 → continue_prompt
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    return input_path, output_dir, r


# ---- review.build_prompt prose_text 注入 ----


def test_review_prompt_zero_cost_without_prose():
    """prose_text=None/空串 时 prompt 与无参数逐字节相同（零成本契约）."""
    from src.object_state import NarrativeState

    objects = [
        NarrativeState(
            state_id="ns_1",
            current_time="夜",
            current_location="室",
            current_situation="调查",
        )
    ]
    review = ReviewUnit()
    base = review.build_prompt(objects, context="extend")
    assert review.build_prompt(objects, context="extend", prose_text=None) == base
    assert review.build_prompt(objects, context="extend", prose_text="") == base
    assert "【本章正文】" not in base


def test_review_prompt_injects_prose_section():
    objects = []
    prompt = ReviewUnit().build_prompt(
        objects, context="extend", prose_text="他推开门，杯子里剩下半口冷水。"
    )
    assert "【本章正文】" in prompt
    assert "他推开门，杯子里剩下半口冷水。" in prompt
    # 正文层审查维度在场
    for dim in ("兑现", "人物忠实", "情绪落地", "解读空间", "场景在场", "对白", "AI 味"):
        assert dim in prompt


def test_review_prompt_injects_only_when_prose_non_empty():
    review = ReviewUnit()
    with_prose = review.build_prompt([], context="extend", prose_text="正文。")
    without = review.build_prompt([], context="extend", prose_text=None)
    assert with_prose != without
    assert "【本章正文】" in with_prose
    assert "【本章正文】" not in without


# ---- prose.build_revision_prompt ----


def test_build_revision_prompt_contains_issues_and_chapter():
    from src.object_state import PlotUnit, ReviewIssue

    issue = ReviewIssue(
        issue_id="iss_1",
        issue_type="redundancy",
        severity="blocking",
        location="chapter",
        scope_of_impact="正文",
        violated_rule="同章对白不应逐字重复",
        description="『你说过，你三年前走进宪碑司』在同章出现两次",
        suggested_fix="删除重复段落，保留一次",
    )
    pu = PlotUnit(
        unit_id="pu_1",
        level="scene",
        goal="目标",
        conflict="冲突",
        input_state_ref="ns_1",
        output_state_ref="ns_2",
        is_effective=True,
    )
    prompt = build_revision_prompt(
        [issue], "第一章正文……", plotunit=pu, target_chapter_chars=1000
    )
    assert "redundancy" in prompt
    assert "『你说过，你三年前走进宪碑司』在同章出现两次" in prompt
    assert "第一章正文……" in prompt
    assert "【PlotUnit（结构依据）】" in prompt
    assert "输出修订后的完整章节正文" in prompt


# ---- extend 集成：先成文、后审查 ----


def test_extend_prose_before_review_prompt_contains_prose(tmp_path):
    """新时序：Continue → Pre-Review → Prose → Review（review_prompt 注入正文）."""
    input_path, output_dir, _ = _setup_extend(tmp_path)

    # 落地 continue response → 重跑 → Prose prompt（pre-review 通过，不阻断）
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pre-Review clear" in r.stdout
    assert "STEP: PROSE" in r.stdout
    assert (output_dir / "prose_prompt.txt").exists()
    # 结构通过 → 不进入对象层 pre-rewrite
    assert not (output_dir / "extend_pre_rewrite_prompt.txt").exists()

    # 落地 prose response → 重跑 → 正文 stage 为 draft + Review prompt（含【本章正文】）
    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout
    assert "STEP: REVIEW" in r.stdout
    review_prompt = (output_dir / "review_prompt.txt").read_text(encoding="utf-8")
    assert "【本章正文】" in review_prompt
    assert "他推开门" in review_prompt
    assert "正文层审查维度" in review_prompt
    assert (output_dir / "pre_review_result.json").exists()
    # Draft/Commit 边界：审查通过前正文只是 draft，尚未进入 chapters/
    assert (output_dir / "prose_draft.txt").exists()
    assert not list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))

    # 落地 review response（pass）→ 重跑 → draft 提交为正式章节
    _write_json(
        output_dir / "review_response.txt",
        {"issues": [], "reminders": [], "route": "pass"},
    )
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout
    assert "Extend complete: PASS" in r.stdout
    result = json.loads((output_dir / "extend_result.json").read_text(encoding="utf-8"))
    assert result["prose_context"] == "draft"
    assert result["route"] == "pass"
    committed = list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))
    assert len(committed) == 1


def test_extend_pre_review_blocks_prose_on_structural_issue(tmp_path):
    """Pre-Review 代码闸：结构阻断 → 对象层重写，不生成 prose."""
    input_path = tmp_path / "input.txt"
    output_dir = tmp_path / "novel" / "output" / "extend"
    output_dir.mkdir(parents=True)
    input_path.write_text("短篇续写输入文本，用于驱动 staged 流程。", encoding="utf-8")
    _write_input_hash(output_dir, input_path)

    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "[WAITING]" in r.stdout
    _write_json(output_dir / "rebuild_response.txt", _minimal_rebuild_payload(bad_relation=True))
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout

    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pre-Review blocked" in r.stdout
    assert "STEP: PRE-REWRITE" in r.stdout
    assert (output_dir / "extend_pre_rewrite_prompt.txt").exists()
    # 结构阻断 → 尚未生成 prose
    assert not (output_dir / "prose_prompt.txt").exists()


def test_extend_migration_fail_fast_on_old_flow_leftover(tmp_path):
    """旧流程残留 review_response（缺 prose_response）→ fail-fast 提示迁移."""
    input_path, output_dir, _ = _setup_extend(tmp_path)
    # 模拟旧版 mid-flow：Review 已完成（对象层）、尚未 Prose
    _write_json(output_dir / "review_response.txt", {"issues": [], "reminders": [], "route": "pass"})
    assert not (output_dir / "prose_response.txt").exists()

    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 1
    assert "迁移" in r.stdout or "旧版流程" in r.stdout


# ---- compose 集成：先成文、后审查 ----


def test_compose_prose_before_review_prompt_contains_prose(tmp_path):
    output_dir = tmp_path / "novel" / "output" / "compose"
    output_dir.mkdir(parents=True)

    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0 and "STEP: CONTINUE" in r.stdout, r.stdout + r.stderr
    _write_json(
        output_dir / "compose_continue_response.txt",
        _minimal_continue_payload(input_state_ref="ns_initial"),
    )
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STEP: PROSE" in r.stdout
    assert not (output_dir / "compose_pre_rewrite_prompt.txt").exists()

    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Staged prose draft" in r.stdout
    review_prompt = (output_dir / "compose_review_prompt.txt").read_text(encoding="utf-8")
    assert "【本章正文】" in review_prompt
    assert "他推开门" in review_prompt
    # Draft/Commit 边界：审查通过前不进入 chapters/
    assert (output_dir / "prose_draft.txt").exists()
    assert not list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))

    _write_json(
        output_dir / "compose_review_response.txt",
        {"issues": [], "reminders": [], "route": "pass"},
    )
    r = _run_script("src/compose_short_form.py", "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout
    assert "Compose complete: PASS" in r.stdout
    result = json.loads((output_dir / "compose_result.json").read_text(encoding="utf-8"))
    assert result["prose_context"] == "draft"
    assert len(list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))) == 1


# ---- misinformation 生命周期（belief state 与 knowledge truth 分离） ----


def test_reconcile_misinformation_disproven_and_corrected():
    from src.object_state import CharacterModel

    c = CharacterModel(
        character_id="c1", name="角色", identity="身份",
        outer_goal="目标", inner_need="需求", fear="恐惧",
        flaw="缺陷", strength="优势", stance="中立",
        misinformation=["一度怀疑自己看见旧字只是眼花（后自我纠正）", "以为父亲抛弃了自己"],
        knowledge_state=["看见旧字是真的"],
    )
    changed = c.reconcile_misinformation(
        disproven=["一度怀疑自己看见旧字只是眼花（后自我纠正）"],
        corrected=[{"from": "以为父亲抛弃了自己", "to": "明白父亲是被迫离开，仍有怨"}],
    )
    assert "一度怀疑自己看见旧字只是眼花（后自我纠正）" not in c.misinformation
    assert "明白父亲是被迫离开，仍有怨" in c.misinformation
    # 知识真值 ≠ 信念接受：disproven 不把信念追加到 knowledge_state
    assert "一度怀疑自己看见旧字只是眼花（后自我纠正）" not in c.knowledge_state
    assert len(changed) == 2


def test_review_parse_response_applies_misinformation_updates():
    from src.object_state import CharacterModel
    from src.workflow_action.review import ReviewUnit

    c = CharacterModel(
        character_id="c001", name="主角", identity="抄碑人",
        outer_goal="破案", inner_need="正义", fear="失败",
        flaw="固执", strength="观察力", stance="中立",
        misinformation=["以为墨痕只是砚台沾的灰", "怀疑自己看错了"],
    )
    response = json.dumps({
        "issues": [], "reminders": [], "route": "pass",
        "misinformation_updates": [
            {"character_id": "c001", "disproven": ["以为墨痕只是砚台沾的灰"],
             "corrected": [{"from": "怀疑自己看错了", "to": "确认自己看见的是旧字"}]}
        ],
    })
    ReviewUnit().parse_response(response, character_models=[c])
    fenced = "先核对正文后给出严格结果。\n```json\n" + response + "\n```"
    issues, reminders, route = ReviewUnit().parse_response(fenced)
    assert issues == [] and reminders == [] and route == "pass"
    assert "以为墨痕只是砚台沾的灰" not in c.misinformation
    assert "确认自己看见的是旧字" in c.misinformation
    assert "怀疑自己看错了" not in c.misinformation


def test_review_misinformation_does_not_merge_into_knowledge():
    """belief state 被击穿 ≠ 变成 knowledge truth——不自动合并."""
    from src.object_state import CharacterModel
    from src.workflow_action.review import ReviewUnit

    c = CharacterModel(
        character_id="c001", name="主角", identity="身份",
        outer_goal="目标", inner_need="需求", fear="恐惧",
        flaw="缺陷", strength="优势", stance="中立",
        misinformation=["以为父亲抛弃了自己"],
        knowledge_state=[],
    )
    response = json.dumps({
        "issues": [], "reminders": [], "route": "pass",
        "misinformation_updates": [
            {"character_id": "c001", "disproven": ["以为父亲抛弃了自己"]}
        ],
    })
    ReviewUnit().parse_response(response, character_models=[c])
    assert c.misinformation == []
    # 事实被证伪 ≠ 人物心理接受：不自动写入 knowledge_state
    assert c.knowledge_state == []


# ---- A/B 台账：Post-Prose Review 的 Revision 记录（Precision / Revision Gain 测量） ----


def test_record_prose_revision_ledger_unit(tmp_path):
    from src.workflow_action.prose import record_prose_revision
    from src.object_state import ReviewIssue

    issue = ReviewIssue(
        issue_id="iss_1", issue_type="redundancy", severity="blocking",
        location="chapter", scope_of_impact="正文", violated_rule="x",
        description="同章对白重复",
    )
    path = record_prose_revision(
        tmp_path,
        cycle_id="pu_009",
        issues=[issue],
        original="原稿……",
        revision="修订稿……",
    )
    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == 2
    assert len(ledger["revisions"]) == 1
    entry = ledger["revisions"][0]
    assert entry["cycle_id"] == "pu_009"
    assert entry["issue_types"] == ["redundancy"]
    assert entry["issue_severity"] == "blocking"
    # A/B 随机化：哪个是原文隐藏在 which_is_original，统计时可还原
    assert entry["which_is_original"] in ("a", "b")
    assert {entry["version_a"], entry["version_b"]} == {"原稿……", "修订稿……"}
    assert entry["revision_gain"]["preference"] is None  # 留待独立 Judge
    assert entry["detection"]["original_has_flaw"] is None

    # 追加而非覆盖
    record_prose_revision(tmp_path, cycle_id="pu_010", issues=[], original="a", revision="b")
    ledger2 = json.loads(path.read_text(encoding="utf-8"))
    assert len(ledger2["revisions"]) == 2


def test_extend_prose_revision_flows_draft_to_commit(tmp_path):
    """route=rewrite（正文层）→ prose_revise 修订 draft → re-review pass → 提交正式章."""
    input_path, output_dir, _ = _setup_extend(tmp_path)
    _write_json(output_dir / "continue_response.txt", _minimal_continue_payload())
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr

    (output_dir / "prose_response.txt").write_text(_long_prose(), encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STEP: REVIEW" in r.stdout

    # Review 报一个阻断性正文问题 → route=rewrite
    _write_json(
        output_dir / "review_response.txt",
        {
            "issues": [{
                "issue_id": "iss_block_dup", "issue_type": "redundancy",
                "severity": "blocking", "location": "chapter",
                "scope_of_impact": "正文", "violated_rule": "x",
                "description": "同章对白逐字重复",
            }],
            "reminders": [], "route": "rewrite",
        },
    )
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STEP: PROSE REVISE" in r.stdout
    assert (output_dir / "prose_revise_prompt.txt").exists()

    # 提供修订稿 → draft 更新
    revised = _long_prose().replace("他推开门，屋里的光线斜斜地落在桌上", "他伸手，先按了按门板")
    (output_dir / "prose_revise_response.txt").write_text(revised, encoding="utf-8")
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Revised prose draft" in r.stdout
    assert (output_dir / "prose_draft.txt").read_text(encoding="utf-8") == revised
    # A/B 台账记录了 original vs revision（v2：随机化 + which_is_original 隐藏）
    ledger = json.loads(
        (output_dir / "prose_revision_ledger.json").read_text(encoding="utf-8")
    )
    assert len(ledger["revisions"]) == 1
    e0 = ledger["revisions"][0]
    assert e0["issue_types"] == ["redundancy"]
    assert e0["which_is_original"] in ("a", "b")
    orig_va = e0["version_a"] if e0["which_is_original"] == "a" else e0["version_b"]
    rev_va = e0["version_b"] if e0["which_is_original"] == "a" else e0["version_a"]
    assert "他推开门" in orig_va
    assert "他伸手，先按了按门板" in rev_va
    # 修订后仍是 draft，未进入 chapters/
    assert not list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))

    # Re-Review pass → 提交
    _write_json(
        output_dir / "extend_rereview_response.txt",
        {"issues": [], "reminders": [], "route": "pass"},
    )
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Committed chapter" in r.stdout
    committed = list((output_dir.parent.parent / "chapters").glob("chapter_*.txt"))
    assert len(committed) == 1
    assert "他伸手，先按了按门板" in committed[0].read_text(encoding="utf-8")
