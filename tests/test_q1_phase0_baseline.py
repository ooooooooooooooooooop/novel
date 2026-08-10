"""Q1 Phase 0 基线探针：证明现有流程会错误放行 8 类合成夹具.

背景：docs/00_project/45_reader_credible_serial_generation.md —— Q1 要求
「连续事实可信、人物不变形、每章有新进展」。当前系统缺少正文事实提取、相邻章差分、
滑动窗口审查与续写可行性判断，下列夹具所代表的失败模式应被未来门禁阻断。

**翻转约定（重要）**
- 本文件断言「现有门禁不阻断夹具」== 当前真实行为，作为失败基线（Phase 0 门禁：
  *先证明现有流程会错误放行这些夹具*）。
- Phase 1/4 实现 ProseEvidence / SerialReaderUnit / ReaderQualityGate 后，
  逐条把断言翻转为「必须阻断」，本文件即成为回归基线。
- **Phase 1 已落地**：翻转后的「必须阻断」断言在
  `tests/test_prose_reconcile.py`（test_phase1_prose_reconcile_must_block，
  8 类夹具全部被新门禁拦截，且命中正确的 issue_type）。本文件保持旧门禁
  「仍不阻断」的基线证据，两套断言并存、互不矛盾。
- 夹具全部为合成文本，不含任何真实作品内容。

每个夹具探测的现有真实门禁：
1. `is_duplicate_of_last`（prose.py:69，落盘点兜底）——整章逐句重叠 ≥70% 判重复。
2. Pre-Review 代码闸 `_hard_rules` + `_domain_rules`（review.py:370/602）——对象层结构规则，不读正文。
3. `check_temporal_contradictions`（reconcile.py:411）——死亡后活跃/过期事实仍持有/时间感知否定。
4. `run_time_audit`（time_audit.py:197，FACTTRACK v2）——anchor 回退/伏笔逾期/季节违反，全 warning 非阻断。
"""

import importlib

import pytest

from src.object_state import (
    FactEntry,
    FactLedger,
    ForeshadowEntry,
    ForeshadowGraph,
    NarrativeState,
)
from src.workflow_action.prose import is_duplicate_of_last
from src.workflow_action.reconcile import ReconcileUnit
from src.workflow_action.review import ReviewUnit
from src.workflow_action.time_audit import run_time_audit

# TimeBook 延迟导入（避免 src 顶部循环依赖，与生产 import 路径一致）
TimeBook = importlib.import_module("src.object_state.timebook").TimeBook
TimeAnchor = importlib.import_module("src.object_state.timebook").TimeAnchor


def _ledger(*entries: FactEntry) -> FactLedger:
    return FactLedger(entries=list(entries))


# --------------------------------------------------------------------------
# 夹具：每项 = 上一可信章正文 + 本章草稿 + 可信状态对象 + 可选 TimeBook
# --------------------------------------------------------------------------

FIXTURES = [
    {
        "fixture_id": "f01_ticket_to_petal",
        "desc": "票根在下一章变成花瓣（道具身份变化，无事件支撑）",
        "q1_gate": "ProseEvidence 道具身份核对",
        "prev_text": "晚饭后，方宇把那张电影票根小心夹进诗集里，想着留到十年后再看。",
        "draft_text": "周末，方宇翻开那本诗集，拈出一片干花瓣，凑到灯下端详。花瓣已经脆了，边缘卷起。他把它夹回书里，合上。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_ticket",
                    statement="票根 夹在 诗集里",
                    fact_type="relation",
                    involved_entities=["obj_ticket", "obj_book", "c001"],
                    confirmed=True,
                    timestamp="第一章",
                )
            ),
            NarrativeState(
                state_id="ns_f01",
                current_time="次日",
                current_location="家中",
                current_situation="方宇翻看诗集",
            ),
        ],
        "time_book": None,
    },
    {
        "fixture_id": "f02_found_to_missing",
        "desc": "已找到的人重新变成失踪（状态回退，无新事件支撑）",
        "q1_gate": "ProseEvidence 状态差分 vs 上一可信状态",
        "prev_text": "李文在码头被找到时，身上裹着件旧棉袄。陈叔把他带回家，招呼他先吃饭。",
        "draft_text": "第二天一早，陈叔去喊李文起床，被子叠得整整齐齐，人不见了。院里井盖的泥脚印是新的。陈叔放下碗，出门去找。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_found",
                    statement="李文 已找到 在码头",
                    fact_type="relation",
                    involved_entities=["c002", "loc_dock"],
                    confirmed=True,
                    timestamp="第一章",
                )
            ),
            NarrativeState(
                state_id="ns_f02",
                current_time="次日清晨",
                current_location="陈叔家",
                current_situation="李文在陈叔家暂住",
                active_characters=["c002", "c003"],
            ),
        ],
        "time_book": None,
    },
    {
        "fixture_id": "f03_january_to_december",
        "desc": "一月之后又回到十二月（时间回退，无闪回标记）",
        "q1_gate": "时间单位 + 显式算术检查（需显式 flashback 标记才放行）",
        "prev_text": "次年一月，河面刚开冻，柳条抽了新芽。雪水顺着屋檐滴答了一整天。",
        "draft_text": "十二月又到了。寒风卷着枯叶扑在窗上，河面重新结了冰。屋里生起炉子，众人围着火说话。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_time_now",
                    statement="现在是次年一月",
                    fact_type="time_order",
                    involved_entities=[],
                    confirmed=True,
                    timestamp="第一章",
                )
            ),
            NarrativeState(
                state_id="ns_f03",
                current_time="次年一月",
                current_location="江边小镇",
                current_situation="开冻回暖",
            ),
        ],
        # TimeBook 只含可信边界锚点（2026-01-15）；草稿的「十二月」尚未入锚表
        "time_book": lambda: TimeBook(
            schema_version=1,
            anchors=[TimeAnchor(chapter="第1章", date="2026-01-15")],
        ),
    },
    {
        "fixture_id": "f04_cycle_60yr_expires_11yr",
        "desc": "六十年周期却隔十一年再次到期（时间算术错误）",
        "q1_gate": "时间单位 + 显式算术检查（60 年周期不得 11 年再开）",
        "prev_text": "一甲子一期的试炼，这一世又开始倒计时。长老们把日子刻在铜牌上，挂在祠堂门口。",
        "draft_text": "十一年过去，铜牌上的字迹又淡了。长老们说，试炼之期临近届满，各峰弟子早早开始准备。",
        "objects": lambda: [
            ForeshadowGraph(
                entries=[
                    ForeshadowEntry(
                        thread_id="fs_cycle",
                        setup_point="第一章",
                        content="试炼一甲子一期",
                        visibility_level="explicit",
                        expected_payoff="六十年后开启",
                        current_status="active",
                        expires_at="2086-01-01",
                    )
                ]
            ),
            _ledger(
                FactEntry(
                    fact_id="f_cycle",
                    statement="试炼 一甲子一期 每六十年开启",
                    fact_type="rule",
                    involved_entities=["org_sect"],
                    confirmed=True,
                    timestamp="第一章",
                )
            ),
        ],
        # 2026-01-15 << 2086-01-01，伏笔未过期 → 现有逾期检测不触发
        "time_book": lambda: TimeBook(
            schema_version=1,
            anchors=[TimeAnchor(chapter="第1章", date="2026-01-15")],
        ),
    },
    {
        "fixture_id": "f05_metatext_leak",
        "desc": "第 N 章末等元文本泄漏（生成过程文字进入正文）",
        "q1_gate": "SerialReaderUnit 元文本泄漏检查",
        "prev_text": "她收拾好行装，把门钥匙挂在门后挂钩上，回头看了空屋子最后一眼。",
        "draft_text": "上一章末她还在码头。本章她回到家中，推开窗，让风吹进来。她倒了一杯水，在窗前坐了很久。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_pack",
                    statement="她 收拾好行装 离开旧居",
                    fact_type="event",
                    involved_entities=["c004"],
                    confirmed=True,
                    timestamp="第一章",
                )
            )
        ],
        "time_book": None,
    },
    {
        "fixture_id": "f06_same_opening",
        "desc": "两章以相同句子和相同场景开始（机械复述上章开头）",
        "q1_gate": "SerialReaderUnit 相邻章开头复述检查（is_duplicate_of_last 抓不到 <70% 重叠）",
        "prev_text": "雨下了一夜。赵立在窗前抽烟，烟灰落在窗台上。他一动不动，像是等什么人。楼上传来孩子的哭声，又很快安静下去。他把烟按灭，没有开灯。门外有人轻轻走过，脚步声在雨里湿软地远了。",
        "draft_text": "雨下了一夜。赵立在窗前抽烟，烟灰落在窗台上。他听见楼下有人喊他名字，是那个消失三天的老邻居。他掐灭烟，披上外衣下楼。楼道里的灯坏了一盏，一闪一闪。他推开门，雨里站着的人浑身湿透，手里捏着一张纸。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_rain",
                    statement="雨下了一夜 赵立 在家",
                    fact_type="event",
                    involved_entities=["c005", "loc_home"],
                    confirmed=True,
                    timestamp="第一章",
                )
            )
        ],
        "time_book": None,
    },
    {
        "fixture_id": "f07_epiphany_repeated_3ch",
        "desc": "已完成顿悟连续三章重新完成（三章窗口重复同一心理结论）",
        "q1_gate": "三至五章窗口「重复顿悟」检查",
        # 前两章正文由夹具提供（写入 chapters 目录），draft_text 是第三节草稿
        "prev_text": "赵立在医院走廊坐到天亮。母亲握着父亲留下的手帕。他想到这些年没能说出口的话，忽然明白，放下才是对父亲的告慰。护士过来换了吊瓶，他起身离开。",
        "prev_prev_text": "父亲走后，赵立整理旧物。他翻出一本泛黄的账本，里面夹着父亲的批注。他忽然明白，放下才是对父亲的告慰。窗外起了风，他把账本放回抽屉。",
        "draft_text": "清明那天，赵立去扫墓。他在碑前站了很久，想起父亲最后一次送他的样子。他终于明白，放下才是对父亲的告慰。下山时下起小雨，他没有打伞。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_epiphany",
                    statement="赵立 已明白 放下才是告慰",
                    fact_type="reveal_status",
                    involved_entities=["c005"],
                    confirmed=True,
                    timestamp="第二章",
                )
            )
        ],
        "time_book": None,
    },
    {
        "fixture_id": "f08_no_state_change",
        "desc": "当前章没有有效状态变化（纯氛围，无事件/无选择/无后果）",
        "q1_gate": "ContinuationViability + 状态差分「每章必须有可描述新变化」",
        "prev_text": "午后，林生在江边坐着，手里捏着一张船票。远处有船鸣笛，他没有抬头。",
        "draft_text": "林生仍坐在江边，看着水面上自己的倒影。云过来又过去，他把船票换到左手，又换了回去。天渐渐暗了，他起身掸了掸裤腿，沿着来路走回屋里。这一晚他没有再出门。",
        "objects": lambda: [
            _ledger(
                FactEntry(
                    fact_id="f_ticket",
                    statement="林生 持有一张船票",
                    fact_type="object",
                    involved_entities=["c006", "obj_ticket"],
                    confirmed=True,
                    timestamp="第一章",
                )
            ),
            NarrativeState(
                state_id="ns_f08",
                current_time="午后",
                current_location="江边",
                current_situation="林生在江边坐着",
                active_characters=["c006"],
            ),
        ],
        "time_book": None,
    },
]


def _probe_blocks(draft_text, chapters_dir, objects, time_book):
    """驱动现有真实门禁，返回其产生的 blocking issue 列表（空 = 未阻断）. """
    blocking = []
    # 1. 落盘点防重闸（仅整章逐句重叠 ≥70% 判重复）
    if is_duplicate_of_last(draft_text, chapters_dir):
        blocking.append("is_duplicate_of_last")
    # 2. Pre-Review 代码闸（对象层硬规则 + 弱信号）
    unit = ReviewUnit()
    code_issues = unit._hard_rules(objects) + unit._domain_rules(objects)
    blocking.extend(i.issue_type for i in code_issues if i.is_blocking())
    # 3. FACTTRACK 时间矛盾（现有 3 项 + TimeBook 增量，全 warning 非阻断）
    blocking.extend(
        i.issue_type for i in run_time_audit(objects, time_book) if i.is_blocking()
    )
    return blocking


@pytest.fixture()
def chapters_dir(tmp_path):
    return tmp_path


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f["fixture_id"])
def test_phase0_baseline_current_pipeline_wrongly_passes(fixture, chapters_dir):
    """Phase 0 门禁：证明现有流程错误放行每类夹具.

    当前断言 == []（现有门禁不阻断）即为通过——失败基线。
    Phase 1/4 实现新门禁后，翻转为 assert probe_blocks 非空。
    """
    objects = fixture["objects"]()
    time_book = fixture["time_book"]() if fixture["time_book"] else None

    # 建立 chapters 目录：写入上一章（f07 额外写入前两章）
    prev_files = [(1, fixture["prev_text"])]
    if "prev_prev_text" in fixture:
        prev_files = [(1, fixture["prev_prev_text"]), (2, fixture["prev_text"])]
    for n, text in prev_files:
        (chapters_dir / f"chapter_{n}.txt").write_text(text, encoding="utf-8")

    blocking = _probe_blocks(fixture["draft_text"], chapters_dir, objects, time_book)

    assert blocking == [], (
        f"[Phase 0 基线被破坏] 夹具 {fixture['fixture_id']} 已被现有门禁阻断: {blocking}\n"
        f"夹具意图: {fixture['desc']}（应被 {fixture['q1_gate']} 拦截）\n"
        f"若这是新门禁生效所致，请按翻转约定把断言改为必须阻断。"
    )


def test_f06_same_opening_not_caught_by_duplicate_gate(chapters_dir):
    """证明 f06 漏检根因：整章重叠仅约 20%，is_duplicate_of_last 阈值 70% 抓不到."""
    f = next(x for x in FIXTURES if x["fixture_id"] == "f06_same_opening")
    (chapters_dir / "chapter_1.txt").write_text(f["prev_text"], encoding="utf-8")
    assert is_duplicate_of_last(f["draft_text"], chapters_dir) is False


def test_f07_epiphany_repeated_not_caught_by_duplicate_gate(chapters_dir):
    """证明 f07 漏检根因：三章正文不同、仅结尾同句，重叠 <70% 抓不到."""
    f = next(x for x in FIXTURES if x["fixture_id"] == "f07_epiphany_repeated_3ch")
    (chapters_dir / "chapter_1.txt").write_text(f["prev_prev_text"], encoding="utf-8")
    (chapters_dir / "chapter_2.txt").write_text(f["prev_text"], encoding="utf-8")
    assert is_duplicate_of_last(f["draft_text"], chapters_dir) is False
