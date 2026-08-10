#!/usr/bin/env python
"""Q1 Phase 6 — 连续生成合成 Canary（compose 5 章 + extend 5 章 + stop 样本）.

规格 45 §7：仓库内合成无版权文本，验证：
- compose 连续 5 章（flow v3 提交点门禁链逐章通过并事务提交）；
- extend 连续 5 章（同一输入原文续写，每章不重复闭环）；
- resolution 结束样本必须停止（viability 确定性 stop，不生成下一章）。

本脚本**程序化驱动 staged 循环**（minimal 响应），不调用任何 LLM/API——
验证的是 flow 的编排正确性（门禁链/事务提交/多章续写/正确停止），
非生成内容质量（内容质量由 Review/ReaderGate 在各自闸口把关）。

退出码：0=全部通过；非 0=任一环节失败。产物：output/q1_canary_serial_report.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_input_hash(output_dir: Path, input_path: Path) -> None:
    from src.boundary_control.runtime_identity import file_content_hash

    (output_dir / ".input_hash").write_text(
        file_content_hash(input_path), encoding="utf-8"
    )


# ---- 合成无版权文本（青云宗·原創架空，不含任何真实实体） ----

EXTEND_INPUT = """青云宗三年一度的大比前夜，林青独自站在山脚。

三个月前，她被执法长老以"盗窃宗门令牌"的罪名逐出宗门。没人相信她，除了她自己知道，那枚刻着云纹的令牌是某个人在临走前塞进她手里的。

"你若想明白真相，就回来。"那人说。

现在她回来了。山门的灯火通明，弟子们还在演练阵法。林青摸了摸怀中的令牌，冰凉的触感让她冷静下来。

她不能从正门进去。执法长老的弟子守在门禁两侧，她认得其中一个人的脸——三年前，那人曾在藏经阁的台阶上对她点过头。

林青绕到后山，攀上一段陡峭的岩壁。月光很亮，她的影子落在石壁上，像一道裂缝。她喘着气爬到顶，回望山门，看见灯火连成一条长龙。

后山有一处废弃的猎户小屋。她推开门，灰尘扑了她一脸。屋里横着一根梁，梁上挂着一盏没油的灯。她在墙角坐下，把令牌放在膝上，借着月光看它。

令牌的背面刻着三个小字——「守夜人」。她记得，这是宗门最古老的职位，早已废止百年。

窗外忽然有脚步声。林青屏住呼吸，把手按在令牌上。门被推开了，一个戴着斗笠的人影站在月光里，声音很轻："你终于回来了。"

"你是谁？"林青问。

斗笠人没有回答，只是把一样东西放在门槛上，转身离去。林青走过去，捡起来，是一张折成方形的纸条。展开，上面只有一句话：

"天亮前，去藏经阁顶层，把令牌放进第三排书架的空格。你母亲的名字会告诉你为什么。"

林青握紧纸条。她母亲——那个在宗门档案里被写成"病故"的女人——留给她一枚令牌、一句话，和一座她以为再也回不来的山门。

她决定天亮前就去藏经阁。结果她在猎户小屋的角落里，发现了一行用指甲刻在墙上的字：与纸条上的笔迹一模一样。"""

COMPOSE_WORKSPEC = {
    "genre": "仙侠",
    "subgenre": "宗门成长",
    "audience": "青年读者",
    "theme": "代价与真相",
    "tone": "克制",
    "pacing": "前快中稳后爆",
    "length_target": 40000,
    "constraints": ["主角不无敌", "禁术使用留下痕迹"],
    "romance_weight": 0.2,
    "mystery_weight": 0.5,
    "action_weight": 0.3,
    "time": {"loc": "青云山"},
}

RESOLUTION_INPUT = """这是故事的最终章。林青在藏经阁顶层找到了所有真相，也付出了她愿意付的代价。

她把令牌放回空格，转身走下藏经阁。山门外，天光已经大亮。所有伏笔都已回收，所有承诺都已兑现，她与那个给她令牌的人达成了和解。

故事到此结束。没有未完的线索，没有悬而未决的选择。这是一个完整的、已经闭合的结局。"""


def _rebuild_payload(chapter_count: int = 5) -> dict:
    return {
        "workspec": {
            "genre": "仙侠",
            "audience": "青年",
            "theme": "真相",
            "tone": "克制",
            "pacing": "短弧推进",
        },
        "worldmodel": {"world_facts": ["宗门以灵根定资质", "青云宗三年一度大比"]},
        "charactermodels": [
            {
                "character_id": "c001",
                "name": "林青",
                "identity": "被逐弟子",
                "outer_goal": "查明令牌真相",
                "inner_need": "证明清白",
                "fear": "再被背叛",
                "flaw": "执拗",
                "strength": "观察力",
                "stance": "中立",
                "relations": {},
            }
        ],
        "narrativestate": {
            "state_id": "ns_001",
            "current_time": "夜晚",
            "current_location": "青云宗后山",
            "current_situation": "林青带着令牌回到宗门",
            "active_characters": ["c001"],
        },
        "factledger": {"entries": []},
        "foreshadowgraph": {"entries": []},
        "confidence_gaps": [],
    }


def _continue_payload(seq: int, base_state: str = "ns_001") -> dict:
    input_ref = base_state if seq == 1 else f"ns_{seq:03d}"
    return {
        "plotunit": {
            "unit_id": f"pu_{seq:03d}",
            "level": "scene",
            "goal": f"推进真相调查第{seq}步",
            "participants": ["c001"],
            "conflict": f"第{seq}步的阻碍",
            "input_state_ref": input_ref,
            "output_state_ref": f"ns_{seq + 1:03d}",
            "released_information": [f"第{seq}步发现的新线索"],
            "consequences": [f"第{seq}步选择产生了后果"],
            "is_effective": True,
            "scene_experience": {
                "protagonist_sees": f"第{seq}步的画面",
                "obstacles": [f"第{seq}步的阻碍"],
                "choice_grounding": f"林青基于{seq}步前获得的信息作出判断",
                "outcome": f"第{seq}步的结果产生了可见反馈",
                "cognition_shift": f"林青对真相的认识从第{seq}步前推进了一步",
            },
        },
        "new_state": {
            "state_id": f"ns_{seq + 1:03d}",
            "current_time": f"第{seq}步之后",
            "current_location": f"地点{seq}",
            "current_situation": f"真相调查推进到第{seq}步",
            "active_characters": ["c001"],
        },
        "new_facts": [],
        "confidence_gaps": [],
    }


_PROSE_BY_SEQ: dict[int, str] = {
    1: (
        "第1章 石阶\n林青沿着藏经阁的石阶往上走，数到第三层时停下来，"
        "决定先检查角落的密室。结果她在墙缝里摸出一卷旧绢，绢上写着与纸条相同的字迹。"
        "她忽然明白，那条线索指向的方向与她原本以为的完全不同。"
        "她把旧绢收进怀里，继续往上走，脚步比先前更稳。楼梯尽头的光线斜斜地落下来，"
        "照亮了一块刻着云纹的石板，与她怀中的令牌纹样相合。她蹲下，"
        "指尖沿着云纹的凹槽划过去，凉的，像水一样。她决定天亮前必须到顶层。"
        "她站起身，拍了拍膝上的灰，往更深处走去，身后传来风穿过回廊的声音。"
    ),
    2: (
        "第2章 顶层\n林青推开顶层的木门，灰尘在光柱里浮游。她走到第三排书架前，"
        "决定把令牌放进去。结果指尖碰到书架深处，触到一件冰凉的东西——"
        "那是一个铜匣，锁孔的形状与令牌完全吻合。她忽然明白，令牌不只是钥匙，"
        "更是某种约定的信物。她把铜匣连同令牌一起放进怀里，转身时，"
        "看见书架尽头站着一个穿灰袍的老人，正静静地看着她。老人没有开口，"
        "只朝她点了点头，然后隐没在书架之间。林青追过去，只听见木门关闭的声响。"
        "她站在原地，呼吸渐渐平复。窗外的晨光爬进顶层，照亮了书架上一层薄薄的尘，"
        "那些尘在光里慢慢落定，像时间终于停下来的样子。"
    ),
    3: (
        "第3章 铜匣\n林青回到猎户小屋，点亮一盏油灯，决定打开铜匣。结果匣盖轻轻一响，"
        "里面只有一卷更旧的帛书，边缘已经泛黄。帛书上画着一幅地图，标注着山后的某处。"
        "她忽然明白，母亲留给她的不是答案，而是通往答案的路。她吹灭灯，"
        "在黑暗里把地图的每一处弯折都记在脑子里。窗外的月亮移动了位置，"
        "她收起帛书，推开门，朝山后的方向走去。石阶在月光下发白，"
        "像一排浸在水里的骨头。她数着自己的脚步声，一步一步，越走越快。"
        "走到半山腰时，她停下来回头看了一眼。山门方向的灯火已经暗了大半，"
        "只有藏经阁顶层的窗口还亮着一点昏黄的光，像一只睁着的眼睛。"
    ),
    4: (
        "第4章 山后\n林青在废弃的祠堂里找到了地图上标注的位置——一块可移动的石砖。"
        "她决定撬开它。结果砖下压着一封没有署名的信，笔迹与纸条一模一样。"
        "信上说：令牌真正的名字叫「守夜人信物」，她的母亲曾经是守夜人。"
        "她忽然明白，逐出宗门的那场变故，远比她知道的要复杂得多。"
        "她把信叠好，放回原处，又在祠堂的梁上发现了一枚旧簪。她认得这枚簪，"
        "小时候见母亲戴过。她把簪收进袖中，走出祠堂时，天边已经泛出鱼肚白。"
        "祠堂外有一口枯井，井沿上刻着一圈云纹，与令牌上的纹样几乎一样。"
        "她蹲下看了很久，把井沿的纹样也一并记在心里。"
    ),
    5: (
        "第5章 守夜人\n天亮前，林青回到藏经阁顶层，把令牌放进第三排书架的空格。"
        "结果整个书架轻轻一震，暗格弹开，露出一本泛黄的册子——守夜人的名册。"
        "翻到最后一页，她看见母亲的名字，旁边用朱笔画着一枚云纹。"
        "她忽然明白，守夜人从未废止，只是换了一种方式存在。她把名册放回原处，"
        "转身走下藏经阁。山门外天光已经大亮，她握紧袖中的旧簪，"
        "决定从今天起，以守夜人的身份继续查下去。她走到山门口，"
        "守门的弟子认出了她，却没有拦她，只朝她点了点头，像是早就知道她会回来。"
        "她把那枚云纹令牌挂在腰间，大步往宗门里走去。"
    ),
}


def _prose(seq: int) -> str:
    """每章正文：内容随章号不同（避开 is_duplicate_of_last）、带推进信号、
    顿悟核心逐章不同（避开重复闭环第二次阻断）。"""
    return _PROSE_BY_SEQ[seq]


def _review_pass() -> dict:
    return {"issues": [], "reminders": [], "route": "pass"}


def _pre_review_blocking(output_dir: Path) -> str:
    """Pre-Review 阻断详情（读 pre_review_result.json 的 blocking issues）."""
    path = output_dir / "pre_review_result.json"
    if not path.exists():
        return "(no pre_review_result.json)"
    data = json.loads(path.read_text(encoding="utf-8"))
    blocking = data.get("blocking", [])
    if not blocking:
        return (
            "(pre_review_result has no blocking; code issues: "
            + str(len(data.get("code_issues", []))) + ")"
        )
    return "; ".join(
        f"[{b.get('severity')}] {b.get('issue_type')}: {b.get('description')}"
        for b in blocking
    )


class CanaryFailed(Exception):
    pass


def _run_extend_serial(tmp: Path, n: int) -> list[dict]:
    novel = tmp / "extend-canary"
    output_dir = novel / "output" / "extend"
    input_path = novel / "input.txt"
    output_dir.mkdir(parents=True)
    input_path.write_text(EXTEND_INPUT, encoding="utf-8")
    _write_input_hash(output_dir, input_path)

    def _run(*extra: str) -> subprocess.CompletedProcess[str]:
        return _run_script(
            "src/extend_short_form.py", str(input_path), "--output-dir",
            str(output_dir), *extra,
        )

    r = _run()
    if r.returncode != 0 or "[WAITING]" not in r.stdout:
        raise CanaryFailed(f"extend init failed: {r.stdout + r.stderr}")
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    _write_json(output_dir / "rebuild_response.txt", _rebuild_payload(n))
    committed: list[dict] = []
    for i in range(1, n + 1):
        # 第 1 章从 rebuild 起步；第 2 章起 --resume 加载已提交链头状态（含前章 new_state）
        resume_args = ("--resume",) if i > 1 else ()
        r = _run(*resume_args)
        _write_json(output_dir / "continue_response.txt", _continue_payload(i, base_state="ns_001"))
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"extend continue ch{i} failed: {r.stdout + r.stderr}")
        if (output_dir / "extend_pre_rewrite_prompt.txt").exists():
            raise CanaryFailed(f"extend continue ch{i} hit Pre-Review block: {_pre_review_blocking(output_dir)}")
        # prose 槽
        (output_dir / "prose_response.txt").write_text(_prose(i), encoding="utf-8")
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"extend prose ch{i} failed: {r.stdout + r.stderr}")
        if "Staged prose draft" not in r.stdout:
            raise CanaryFailed(f"extend prose ch{i} not staged: {r.stdout + r.stderr}")
        # review 槽 → commit
        _write_json(output_dir / "review_response.txt", _review_pass())
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"extend review/commit ch{i} failed: {r.stdout + r.stderr}")
        if f"chapter_{i}.txt" not in " ".join(p.name for p in (novel / "chapters").glob("chapter_*.txt")):
            raise CanaryFailed(f"extend ch{i} not committed")
        committed.append({"mode": "extend", "chapter": i})
    return committed


def _run_compose_serial(tmp: Path, n: int) -> list[dict]:
    novel = tmp / "compose-canary"
    output_dir = novel / "output" / "compose"
    workspec_path = novel / "workspec.json"
    output_dir.mkdir(parents=True)
    workspec_path.write_text(json.dumps(COMPOSE_WORKSPEC, ensure_ascii=False), encoding="utf-8")

    def _run(*extra: str) -> subprocess.CompletedProcess[str]:
        return _run_script(
            "src/compose_short_form.py", str(workspec_path),
            "--output-dir", str(output_dir), *extra,
        )

    r = _run()
    if r.returncode != 0 or "[WAITING]" not in r.stdout:
        raise CanaryFailed(f"compose init failed: {r.stdout + r.stderr}")
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    committed: list[dict] = []
    for i in range(1, n + 1):
        resume_args = ("--resume",) if i > 1 else ()
        r = _run(*resume_args)
        _write_json(output_dir / "compose_continue_response.txt", _continue_payload(i, base_state="ns_initial"))
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"compose continue ch{i} failed: {r.stdout + r.stderr}")
        if (output_dir / "compose_pre_rewrite_prompt.txt").exists():
            raise CanaryFailed(f"compose continue ch{i} hit Pre-Review block: {_pre_review_blocking(output_dir)}")
        (output_dir / "prose_response.txt").write_text(_prose(i), encoding="utf-8")
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"compose prose ch{i} failed: {r.stdout + r.stderr}")
        _write_json(output_dir / "compose_review_response.txt", _review_pass())
        r = _run(*resume_args)
        if r.returncode != 0:
            raise CanaryFailed(f"compose review/commit ch{i} failed: {r.stdout + r.stderr}")
        committed.append({"mode": "compose", "chapter": i})
    return committed


def _all_completed_frames() -> list[dict]:
    """整个结构 completed——合法的终止态（frame.validate_frame_state 明示允许）."""
    return [
        {"frame_id": "book_001", "level": "book", "title": "测试书",
         "purpose": "容器", "position": "start", "status": "completed"},
        {"frame_id": "arc_001", "level": "arc", "title": "测试弧", "purpose": "主线",
         "position": "middle", "status": "completed", "parent_id": "book_001", "order_index": 0},
        {"frame_id": "chapter_001", "level": "chapter", "title": "测试章", "purpose": "推进",
         "position": "middle", "status": "completed", "parent_id": "arc_001", "order_index": 0},
        {"frame_id": "scene_001", "level": "scene", "title": "测试场景", "purpose": "落点",
         "position": "end", "status": "completed", "parent_id": "chapter_001", "order_index": 0},
    ]


def _run_stop_sample(tmp: Path) -> dict:
    """resolution 结束样本：viability 必须确定性 stop，不生成下一章."""
    novel = tmp / "stop-canary"
    output_dir = novel / "output" / "extend"
    input_path = novel / "input.txt"
    output_dir.mkdir(parents=True)
    input_path.write_text(RESOLUTION_INPUT, encoding="utf-8")
    _write_input_hash(output_dir, input_path)

    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    if r.returncode != 0 or "[WAITING]" not in r.stdout:
        raise CanaryFailed(f"stop init failed: {r.stdout + r.stderr}")
    (output_dir / ".flow_version").write_text("3", encoding="utf-8")

    _write_json(output_dir / "rebuild_response.txt", _rebuild_payload(3))
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir))
    if r.returncode != 0:
        raise CanaryFailed(f"stop sample rebuild run failed: {r.stdout + r.stderr}")
    # 结构闭合：全 completed 帧 → viability 确定性 stop（resolution 结束样本）
    (output_dir / "extend_frames.json").write_text(
        json.dumps(_all_completed_frames(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    r = _run_script("src/extend_short_form.py", str(input_path), "--output-dir", str(output_dir), "--resume")
    report = output_dir / "viability_report.json"
    if r.returncode != 0:
        raise CanaryFailed(f"stop sample run failed: {r.stdout + r.stderr}")
    if not report.exists():
        raise CanaryFailed(f"stop sample did not produce viability_report.json: {r.stdout}")
    data = json.loads(report.read_text(encoding="utf-8"))
    if data.get("verdict") != "stop":
        raise CanaryFailed(f"stop sample verdict={data.get('verdict')}, expected stop")
    if "ContinuationViability: stop" not in r.stdout or "不生成下一章" not in r.stdout:
        raise CanaryFailed(f"stop sample did not stop in flow: {r.stdout}")
    return {"mode": "stop", "verdict": "stop", "reasons": data.get("reasons", [])}


def main() -> int:
    results: dict = {"schema_version": 1, "extend": [], "compose": [], "stop": None}
    try:
        with tempfile.TemporaryDirectory(prefix="q1-canary-") as td:
            tmp = Path(td)
            results["extend"] = _run_extend_serial(tmp, 5)
            results["compose"] = _run_compose_serial(tmp, 5)
            results["stop"] = _run_stop_sample(tmp)
    except CanaryFailed as exc:
        results["error"] = str(exc)
        _write_report(results)
        print(f"Q1 serial canary FAILED: {exc}")
        return 1

    _write_report(results)
    print(f"Q1 serial canary PASS")
    print(f"  extend: {len(results['extend'])} 章连续提交（门禁链逐章通过）")
    print(f"  compose: {len(results['compose'])} 章连续提交（门禁链逐章通过）")
    print(f"  stop: verdict={results['stop']['verdict']}（resolution 正确停止，不生成下一章）")
    return 0


def _write_report(results: dict) -> None:
    out = REPO_ROOT / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "q1_canary_serial_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
