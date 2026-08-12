#!/usr/bin/env python3
"""a1_t8_canary_setup — T8 三类 30 章无人 Canary 引导脚本（确定性、自校验）.

为冻结 policy.canary.genres（contemporary_officialdom / mythic_fantasy /
historical_strategy）各构建一个**原创**（非任何真实作品）可运行 30 章的初始状态：

    WorkSpec + WorldModel + CharacterModel×3 + NarrativeState + FactLedger
    + ForeshadowGraph（2~3 条 active 承诺）+ 30-scene 开放 Frame

产物（runtime/refs/t8_canary/<genre>/）：
    base_state_package.json   SerializationPackage（serializer.build_package）
    base_frames.json          30 场景 Frame 状态（scene_001 active，余 planned）
    setup_manifest.json       各文件 SHA-256 + 对象摘要（不落正文）

隐私红线：全部内容为脚本内原创设定，不含任何真实作品名/正文/作者笔名。
"""

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.boundary_control.serialization import SerializationBoundaryUnit
from src.object_state.charactermodel import CharacterModel
from src.object_state.factledger import FactEntry, FactLedger
from src.object_state.foreshadowgraph import ForeshadowEntry, ForeshadowGraph
from src.object_state.narrativestate import NarrativeState
from src.object_state.workspec import WorkSpec
from src.object_state.worldmodel import WorldModel
from src.workflow_action.frame import NarrativeFrameUnit

OUT_DIR = PROJECT_ROOT / "runtime" / "refs" / "t8_canary"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(out_dir: Path, name: str, data) -> Path:
    path = out_dir / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 三类设定数据

# 每个 genre 的 scenes：30 个 (name, purpose)，name 用于 formula_node（不得是
# 终止型节点 resolution/payoff/catastrophe/return/exit/act3_resolution）。
CONTEMPORARY_OFFICIALDOM_SCENES = [
    ("cold_open", "沈砚收到匿名举报信，指向县里土地拍卖背后的利益输送；开章渲染反腐一线的压力"),
    ("inciting_incident", "举报信被安排进信访办积压件，沈砚发现有人要压案；他决定暗中核查"),
    ("first_plot_point", "档案室查证旧卷宗，发现一块关键地块的评估价异常偏低"),
    ("escalation", "副镇长暗示他『别碰不该碰的事』；同僚开始疏远他"),
    ("turning_point", "老友顾承风调任同县任职，两人重聚，却各怀立场"),
    ("rising_action", "沈砚找到最初那份测绘报告的异常处，证据链出现第一环"),
    ("complication", "当事人之一的账本突然失窃，有人抢先动手"),
    ("midpoint_twist", "匿名信的真实来源浮出水面——竟是旧案受害人家属，他曾在十年前被强行拆迁"),
    ("deepening", "沈砚介入拆迁旧案，发现自己的父亲当年参与过其中一桩补偿决定"),
    ("pressure_mounts", "上级打来『关怀』电话，暗示他该收敛；家中也因他的坚持生出矛盾"),
    ("alliance", "顾承风私下透露土地案牵涉市里某位领导，两人达成暗中合作的默契"),
    ("setback", "关键证人改口，证据效力被削弱；沈砚被调去处理无关的信访积案"),
    ("second_plot_point", "从积案中挖出与土地案同源的另一个案子，两条线索互相印证"),
    ("confrontation", "沈砚与牵涉其中的中间人正面交锋，对方亮出威胁"),
    ("revelation", "十年前拆迁案的补偿档案被人涂改，父亲的签名位置有蹊跷"),
    ("crisis", "顾承风被迫站到对立面，公开支持压案的一方；沈砚陷入孤立"),
    ("low_point", "举报信被定性为诬告，沈砚面临停职调查"),
    ("recovery", "旧案受害人家属拿出当年的原始单据，局势出现转机"),
    ("countermove", "沈砚把证据链整理成册，借信访积案的名义重新立案"),
    ("exposure", "土地评估的第三方机构承认数据被篡改，利益网裂开一道口子"),
    ("escalation_2", "市里调查组进驻，沈砚被约谈；他据实陈述全部发现"),
    ("betrayal", "身边亲信把内部消息泄露给被调查方，沈砚的行踪被监控"),
    ("showdown", "公开听证会上，沈砚当面出示测绘报告与账本的对账结果"),
    ("turning_point_2", "顾承风在最后一刻倒戈，交出了关键的一笔转账记录"),
    ("breakthrough", "利益输送的完整链条浮出：从开发商到评估机构再到审批环节"),
    ("settlement", "涉案官员相继被处理，沈砚洗清诬告，重新主持信访工作"),
    ("cost", "沈砚为守原则付出了与旧友反目、家庭裂痕的代价，他一一面对"),
    ("rebalance", "土地案善后开始：补发拆迁补偿、重审旧案，他推动制度化整改"),
    ("closing", "沈砚收到新的匿名信——这次指向更高处；他平静地收好，决定继续"),
    ("denouement", "冬去春来，县里信访秩序重建；沈砚回到最初那张办公桌前"),
]

MYTHIC_FANTASY_SCENES = [
    ("cold_open", "外门弟子陆离在山门枯泉边发现剑诀残页，剑意与师父旧剑相通；开章立仙门世情"),
    ("inciting_incident", "残页剑诀在体内引动一缕异样灵气，陆离修为松动，牵出师父失踪旧事"),
    ("first_plot_point", "同门师妹白芷被查出身中寒毒，解药指向封禁百年的禁地"),
    ("escalation", "掌门下令彻查残页来历；陆离被怀疑偷学禁术"),
    ("turning_point", "藏经阁旧档记载：师父当年正是进禁地后失踪，剑诀是其遗留"),
    ("rising_action", "陆离以采药名义接近禁地边缘，探得入口封印已松动"),
    ("complication", "寒毒扩散，白芷修为跌落；内门师兄苏衍主张以禁地宝物救人"),
    ("midpoint_twist", "禁地深处的剑冢，陆离的残页与之共鸣——那是一把等待主人的古剑"),
    ("deepening", "古剑剑灵传出零碎讯息：灵气衰落的源头在宗门外，而非禁地"),
    ("pressure_mounts", "掌门关闭禁地出口，陆离与白芷、苏衍被滞留在内"),
    ("alliance", "剑灵认主，陆离获知师父留下的完整剑诀与一句警告"),
    ("setback", "寒毒反扑，白芷昏迷；剑灵说解毒需斩断禁地中央的封脉石"),
    ("second_plot_point", "封脉石下压着的竟是一条通向山门的灵脉支线，斩断则宗门灵泉枯死"),
    ("confrontation", "苏衍主张斩石取宝，陆离主张另寻他法，两人在剑冢对峙"),
    ("revelation", "灵泉枯死的真正原因不是灵气衰落，而是有人在外界截流宗门灵脉"),
    ("crisis", "封印全面崩解，禁地凶兽苏醒，三人被迫联手御敌"),
    ("low_point", "陆离为护白芷重伤，剑诀剑意濒临溃散"),
    ("recovery", "白芷以寒毒本源反哺，暂时压制伤势；剑灵指认截流者气息"),
    ("countermove", "三人绕开凶兽，找到禁地与外界灵脉的交汇节点"),
    ("exposure", "截流者竟是宗门长老，他借灵脉滋养私炼法宝多年"),
    ("escalation_2", "长老察觉闯入，封锁消息并启动护山杀阵"),
    ("betrayal", "内门弟子中有人被长老收买，出卖了陆离等人的位置"),
    ("showdown", "陆离以完整剑诀驱动古剑，斩断截流术阵，灵脉重新贯通"),
    ("turning_point_2", "长老的真面目被揭穿，掌门带人赶到，禁地真相大白"),
    ("breakthrough", "灵泉复苏，白芷寒毒自解；师父失踪之谜揭开——他早知截流而以身封印"),
    ("settlement", "长老伏法，宗门整顿；陆离被正式收为真传弟子"),
    ("cost", "陆离为驾驭古剑付出了修为根基受损的代价，需重铸剑心"),
    ("rebalance", "宗门重建护山大阵，陆离承袭师父遗志，成为新的守脉之人"),
    ("closing", "剑冢重封，陆离立誓：不再让灵脉落入私欲之手"),
    ("denouement", "春回宗门，枯泉重涌；陆离在剑冢前开始修行新的剑意"),
]

HISTORICAL_STRATEGY_SCENES = [
    ("cold_open", "谢云峥于深夜拆阅边关密信，信中暗语指向有人私通外敌；开章立朝堂与边关双线"),
    ("inciting_incident", "送信的信使途中被杀，密信原件失踪，只剩谢云峥抄录的残本"),
    ("first_plot_point", "朝中主和派借边关生变弹劾主战将领，谢云峥察觉弹劾背后另有推手"),
    ("escalation", "兵部核销军粮账目，发现一批军粮去向不明"),
    ("turning_point", "太子的近臣私下接触谢云峥，暗示边关与储位之争有关"),
    ("rising_action", "谢云峥循军粮账目追查到漕运，发现一笔银子拐进某个皇商名下"),
    ("complication", "皇商突然暴毙，账本被焚；线索指向宫中"),
    ("midpoint_twist", "密信残本中的暗语破译——通敌的不是边将，而是朝中某位重臣"),
    ("deepening", "重臣正是当年拥立先帝的旧臣，与太子一脉牵连极深"),
    ("pressure_mounts", "主战将领被下狱，边关防线吃紧；谢云峥被调去协办军粮"),
    ("alliance", "谢云峥与冷宫废妃的旧人搭上线，得知宫闱旧事的另一面"),
    ("setback", "废妃旧人被杀灭口，谢云峥被指控私通废妃、图谋不轨"),
    ("second_plot_point", "军粮案与密信案实为同一局：以边关乱局掩盖朝中夺嫡"),
    ("confrontation", "谢云峥在朝堂上当面质询重臣，指出军粮缺口与通敌暗语同源"),
    ("revelation", "先帝驾崩时的一份密诏被找到——太子身世另有隐情"),
    ("crisis", "重臣发动宫变，封锁宫门，谢云峥与主战将领家眷被困"),
    ("low_point", "谢云峥被捕下狱，通敌罪名坐实，眼看要被处决"),
    ("recovery", "狱中旧友以一封错发的奏章传递消息，谢云峥找到翻盘之机"),
    ("countermove", "谢云峥借军中旧识策应，把密信残本与军粮对账的证据送出狱"),
    ("exposure", "证据落入主战将领旧部手中，边关守军按兵不动以待朝局"),
    ("escalation_2", "宫变扩大，太子被迫站队；谢云峥的证词成为关键筹码"),
    ("betrayal", "太子身边有人倒向重臣，把谢云峥的部署泄露出去"),
    ("showdown", "宫门前，谢云峥当众公布密诏与军粮账本，重臣的局被拆穿"),
    ("turning_point_2", "边关守军在最后关头勤王，宫变平定"),
    ("breakthrough", "重臣伏诛，密诏公之于众——太子身世澄清，正统得立"),
    ("settlement", "军粮案全面彻查，主战将领平反，边关防线重筑"),
    ("cost", "谢云峥为护大局牺牲了旧友性命，背负骂名，心结难解"),
    ("rebalance", "新朝整顿吏治，谢云峥受命主理军粮与边务"),
    ("closing", "谢云峥收到又一封边关密信，这一次他提笔亲批：阅后即焚"),
    ("denouement", "风雪边关，谢云峥巡营；他望着远方，心中已有新的棋局"),
]


# ---------------------------------------------------------------- 对象构建

def _workspec(genre_key: str, data: dict) -> WorkSpec:
    return WorkSpec(
        genre=data["genre"],
        subgenre=data["subgenre"],
        audience=data["audience"],
        theme=data["theme"],
        tone=data["tone"],
        pacing=data["pacing"],
        structure_template="eight_node",
        platform="web_novel_daily",
        temperament=data["temperament"],
        length_target=data["length_target"],
        constraints=data["constraints"],
    )


def _worldmodel(data: dict) -> WorldModel:
    return WorldModel(
        world_facts=data["world_facts"],
        social_structure=data.get("social_structure"),
        power_system=data.get("power_system"),
        resource_system=data.get("resource_system"),
        geography=data.get("geography"),
        factions=data["factions"],
        time_rules=data["time_rules"],
        prohibitions=data["prohibitions"],
        consequence_logic=data["consequence_logic"],
        hard_rules=data["hard_rules"],
        death_rule=data.get("death_rule"),
        forbidden_actions=data["forbidden_actions"],
        exception_rules=data["exception_rules"],
    )


def _characters(data: dict) -> list[CharacterModel]:
    out = []
    for spec in data["characters"]:
        out.append(
            CharacterModel(
                character_id=spec["character_id"],
                name=spec["name"],
                identity=spec["identity"],
                outer_goal=spec["outer_goal"],
                inner_need=spec["inner_need"],
                fear=spec["fear"],
                flaw=spec["flaw"],
                strength=spec["strength"],
                secret=spec.get("secret"),
                stance=spec["stance"],
                arc_stage=spec.get("arc_stage"),
                self_image=spec.get("self_image"),
                knowledge_state=spec.get("knowledge_state", []),
                misinformation=spec.get("misinformation", []),
                relations=spec.get("relations", {}),
                current_pressure=spec.get("current_pressure", []),
                change_trajectory=spec.get("change_trajectory", []),
                relation_behaviors=spec.get("relation_behaviors", {}),
            )
        )
    return out


def _narrative_state(data: dict, char_ids: list[str]) -> NarrativeState:
    return NarrativeState(
        state_id=data["state_id"],
        current_time=data["current_time"],
        current_location=data["current_location"],
        active_characters=char_ids,
        current_situation=data["current_situation"],
        primary_goal=data.get("primary_goal"),
        active_conflicts=data.get("active_conflicts", []),
        emotional_temperature=data.get("emotional_temperature"),
        public_information=data.get("public_information", []),
        hidden_information=data.get("hidden_information", []),
        private_information_map=data.get("private_information_map", {}),
        open_questions=data.get("open_questions", []),
        active_suspense_items=data.get("active_suspense_items", []),
        current_goals=data.get("current_goals", []),
        linked_open_threads=data.get("linked_open_threads", []),
        current_facts_in_scope=data.get("current_facts_in_scope", []),
    )


def _facts(data: dict) -> FactLedger:
    return FactLedger(
        entries=[
            FactEntry(
                fact_id=f["fact_id"],
                statement=f["statement"],
                fact_type=f["fact_type"],
                involved_entities=f.get("involved_entities", []),
                source_plotunit=f.get("source_plotunit"),
                confirmed=f.get("confirmed", True),
                timestamp=f.get("timestamp"),
                known_by=f.get("known_by", []),
                chronological_order=f.get("chronological_order"),
            )
            for f in data["facts"]
        ]
    )


def _foreshadows(data: dict) -> ForeshadowGraph:
    return ForeshadowGraph(
        entries=[
            ForeshadowEntry(
                thread_id=t["thread_id"],
                setup_point=t["setup_point"],
                content=t["content"],
                visibility_level=t["visibility_level"],
                expected_payoff=t["expected_payoff"],
                current_status="active",
                expiry_risk=t.get("expiry_risk"),
                advancement_nodes=t.get("advancement_nodes", []),
                narrowing_events=t.get("narrowing_events", []),
                payoff_nodes=t.get("payoff_nodes", []),
                urgency_to_payoff=t.get("urgency_to_payoff"),
                overdue_risk=t.get("overdue_risk"),
                scope_level=t.get("scope_level", "arc"),
                linked_characters=t.get("linked_characters", []),
                linked_facts=t.get("linked_facts", []),
                linked_plotunits=t.get("linked_plotunits", []),
            )
            for t in data["threads"]
        ]
    )


def _frames(scene_beats: list[tuple[str, str]]) -> list[dict]:
    """30-scene 开放 Frame：book/arc/chapter 各一 active + 30 个 scene（scene_001 active）."""
    frames = [
        {
            "frame_id": "book_001",
            "level": "book",
            "title": "Book 1",
            "purpose": "完整三十章故事主线：开篇→发展→转折→收束，含至少一条可信终局",
            "position": "full",
            "status": "active",
            "order_index": 0,
        },
        {
            "frame_id": "arc_001",
            "level": "arc",
            "title": "Arc 1",
            "purpose": "主线冲突的建立、升级与收束（三十个场景节拍）",
            "position": "full",
            "status": "active",
            "parent_id": "book_001",
            "order_index": 0,
        },
        {
            "frame_id": "chapter_001",
            "level": "chapter",
            "title": "Chapter 1-30",
            "purpose": "连续三十章逐场景推进",
            "position": "full",
            "status": "active",
            "parent_id": "arc_001",
            "order_index": 0,
        },
    ]
    for index, (name, purpose) in enumerate(scene_beats, start=1):
        frames.append(
            {
                "frame_id": f"scene_{index:03d}",
                "level": "scene",
                "title": f"Scene {index} — {name}",
                "purpose": purpose,
                "position": "flexible",
                "status": "active" if index == 1 else "planned",
                "parent_id": "chapter_001",
                "order_index": index - 1,
                "formula_node": name,
                "target_plotunit_ids": [],
                "active_thread_ids": [],
            }
        )
    return frames


# ---------------------------------------------------------------- 三类型数据

GENRES = {
    "contemporary_officialdom": {
        "genre": "当代官场",
        "subgenre": "现实官场",
        "audience": "成年读者",
        "theme": "权力与初心：在体制的缝隙里守住一条底线",
        "tone": "克制冷静，写实",
        "pacing": "中速，线索层层推进",
        "temperament": "审慎、多思、以证据服人",
        "length_target": 3500,
        "constraints": [
            "不出现真实机关单位与人物姓名",
            "尊重组织程序，不渲染极端黑幕",
            "主角以证据与程序行事，不诉诸暴力",
        ],
        "world_facts": [
            "清水县处于经济转型期，土地拍卖与旧城改造同步推进",
            "县信访办积压大量历史遗留上访件",
            "县里即将启动新一轮干部调整",
            "十年前清水镇曾有一次大规模拆迁，补偿存在争议",
        ],
        "social_structure": "县—镇两级行政体系，各部门业务交叉",
        "power_system": "党委领导下行政运行，主要领导对人事与项目有决定性话语权",
        "resource_system": "土地出让金是县财政的重要来源",
        "geography": "清水县位于省城周边，下辖清水镇等乡镇，有开发区",
        "factions": ["信访办", "国土局", "开发区管委会", "市纪委调查组"],
        "time_rules": ["对话、会议、信访受理均需符合日常工作节奏"],
        "prohibitions": ["不虚构现实人名地名", "不渲染暴恐或色情内容"],
        "consequence_logic": [
            "越级反映问题会带来纪律上的敏感性",
            "证据不足时上级倾向于维持原判",
        ],
        "hard_rules": ["主角的每一次突破都必须建立在可核验的证据上"],
        "death_rule": None,
        "forbidden_actions": ["主角不得以非法手段获取证据"],
        "exception_rules": [],
        "characters": [
            {
                "character_id": "shen_yan",
                "name": "沈砚",
                "identity": "清水县信访办副主任科员，三十岁出头",
                "outer_goal": "查清匿名举报信指向的土地拍卖利益输送",
                "inner_need": "证明自己依然能守住做人的底线",
                "fear": "重蹈父亲当年在原则问题上妥协的覆辙",
                "flaw": "固执，不擅经营关系，易把同僚推到对立面",
                "strength": "严谨、耐心，擅长从卷宗里找破绽",
                "secret": "十年前父亲参与过清水镇拆迁的补偿决定",
                "stance": "温和坚定，主张按程序办",
                "arc_stage": "setup",
                "self_image": "一个普通的、但守规矩的干部",
                "knowledge_state": ["信访积压件中有异常", "土地评估价有疑点"],
                "relations": {"gu_chengfeng": "大学同窗，旧友"},
            },
            {
                "character_id": "gu_chengfeng",
                "name": "顾承风",
                "identity": "清水县新到任的副镇长",
                "outer_goal": "在任上平稳落地，争取更进一步",
                "inner_need": "在旧情与仕途之间找到能自洽的位置",
                "fear": "被旧友拖入自己无法收场的局面",
                "flaw": "圆滑，习惯权衡，倾向明哲保身",
                "strength": "人脉广，消息灵，懂得怎样在体制内借力",
                "secret": "他受人之托，本要劝沈砚收手",
                "stance": "两面周旋，暗中合作",
                "arc_stage": "setup",
                "self_image": "一个能把握分寸的务实者",
                "knowledge_state": ["土地案牵涉市里某位领导"],
                "relations": {"shen_yan": "大学同窗，旧友"},
            },
            {
                "character_id": "tian_guifang",
                "name": "田桂芳",
                "identity": "清水镇十年前拆迁的受害人家属",
                "outer_goal": "为当年被压的补偿讨回公道",
                "inner_need": "确认当年的真相，让家人解脱",
                "fear": "再次被有权势的人消音",
                "flaw": "多疑，试探性强",
                "strength": "执着，保留了当年的原始单据",
                "secret": "匿名举报信出自她手",
                "stance": "警惕而决绝",
                "arc_stage": "setup",
                "self_image": "一个必须讨说法的人",
                "knowledge_state": ["当年补偿被压低", "原始单据尚在"],
                "relations": {"shen_yan": "举报对象，存疑"},
            },
        ],
        "state_id": "ns_cod_000",
        "current_time": "四月上旬，工作日早晨",
        "current_location": "清水县人民政府信访接待室",
        "current_situation": "沈砚刚上班，信访接待桌上多出一封没有落款的匿名举报信，举报县开发区地块拍卖存在利益输送，怀疑是有人有意压案",
        "primary_goal": "确认举报信内容是否属实，决定是否跟进",
        "active_conflicts": ["举报信被安排进积压件", "同僚暗示不要多事"],
        "emotional_temperature": "克制、警觉",
        "public_information": ["县里正推进土地拍卖", "信访办积压件多"],
        "hidden_information": ["举报信内容", "十年前拆迁补偿存在争议"],
        "private_information_map": {
            "shen_yan": ["举报信内容", "父亲曾参与拆迁补偿决定"],
            "tian_guifang": ["匿名信是自己写的", "保留原始单据"],
        },
        "open_questions": ["举报信指向谁", "是谁把信放进接待桌"],
        "active_suspense_items": ["匿名举报信的后续发展"],
        "current_goals": ["核实举报信中的地块与评估数据"],
        "linked_open_threads": ["rem_cod_001", "rem_cod_002", "rem_cod_003"],
        "current_facts_in_scope": ["fact_cod_001", "fact_cod_002"],
        "facts": [
            {
                "fact_id": "fact_cod_001",
                "statement": "县开发区准备拍卖一块约三十亩的商住地块",
                "fact_type": "event",
                "involved_entities": ["shen_yan"],
                "known_by": ["shen_yan"],
            },
            {
                "fact_id": "fact_cod_002",
                "statement": "信访办收到一封未署名的匿名举报信",
                "fact_type": "event",
                "involved_entities": ["shen_yan"],
                "known_by": ["shen_yan"],
            },
            {
                "fact_id": "fact_cod_003",
                "statement": "清水镇十年前拆迁时部分补偿低于标准",
                "fact_type": "event",
                "involved_entities": ["tian_guifang"],
                "known_by": ["tian_guifang"],
            },
        ],
        "threads": [
            {
                "thread_id": "rem_cod_001",
                "setup_point": "匿名举报信出现",
                "content": "举报信指向开发区地块拍卖的利益输送，真相与背后的利益网有待查清",
                "visibility_level": "explicit",
                "expected_payoff": "查清利益输送链条，涉案者被处理",
                "linked_characters": ["shen_yan"],
                "linked_facts": ["fact_cod_001", "fact_cod_002"],
            },
            {
                "thread_id": "rem_cod_002",
                "setup_point": "顾承风调任同县",
                "content": "旧友重逢却各怀立场，友情与原则的考验将贯穿主线",
                "visibility_level": "implicit",
                "expected_payoff": "顾承风在原则与立场之间做出选择",
                "linked_characters": ["shen_yan", "gu_chengfeng"],
            },
            {
                "thread_id": "rem_cod_003",
                "setup_point": "十年前拆迁旧案被提及",
                "content": "旧案补偿争议与土地案同源，且牵出沈砚父亲当年的决定",
                "visibility_level": "implicit",
                "expected_payoff": "旧案真相大白，补偿得到善后",
                "linked_characters": ["shen_yan", "tian_guifang"],
                "linked_facts": ["fact_cod_003"],
            },
        ],
        "scenes": CONTEMPORARY_OFFICIALDOM_SCENES,
    },
    "mythic_fantasy": {
        "genre": "仙侠",
        "subgenre": "宗门修真",
        "audience": "年轻读者",
        "theme": "求道与执念：在灵气衰落的时代守住本心",
        "tone": "清冽、意境化",
        "pacing": "中快，秘境冒险与内心修行交织",
        "temperament": "坚韧、重情、于危局中见真章",
        "length_target": 3500,
        "constraints": [
            "不出现真实宗教教义",
            "力量体系以灵气/剑意为根，不做无来由的升级",
            "禁地凶险须付出代价，不无脑开挂",
        ],
        "world_facts": [
            "宗门灵泉近三百年持续枯竭，灵气稀薄",
            "封禁百年的禁地封印在松动",
            "师父三年前进禁地后失踪，留下一把旧剑与残缺剑诀",
            "宗门内灵脉支线经禁地脚下穿过",
        ],
        "social_structure": "外门—内门—真传—长老—掌门五级",
        "power_system": "修为境界 + 宗门功勋，剑意为镇宗之本",
        "resource_system": "灵泉与灵脉是修炼根基，灵石为流通货币",
        "geography": "青山环绕，山门居中，禁地在后山深谷，灵脉横贯山体",
        "factions": ["外门弟子", "内门一系", "长老会", "藏经阁"],
        "time_rules": ["四季更替影响灵气浓度", "禁地开启有周期性窗口"],
        "prohibitions": ["禁地非受命不得擅入"],
        "consequence_logic": [
            "动用禁术或窃取灵脉会折损根基",
            "强行斩断封脉石会断送宗门灵泉",
        ],
        "hard_rules": ["每一次破境都必须付出对应代价"],
        "death_rule": "重伤濒死可救，但修为根基会受损",
        "forbidden_actions": ["不得轻易以性命为代价强行破禁"],
        "exception_rules": ["掌门特许的试炼可豁免部分禁令"],
        "characters": [
            {
                "character_id": "lu_li",
                "name": "陆离",
                "identity": "青山宗外门弟子，十九岁",
                "outer_goal": "查明师父失踪的真相，救回寒毒缠身的白芷",
                "inner_need": "证明自己能继承师父的剑道而不迷失",
                "fear": "重蹈师父以身封印、身死道消的覆辙",
                "flaw": "重情，遇事易把责任全揽在自己肩上",
                "strength": "剑意澄澈，能与旧剑共鸣",
                "secret": "已与剑灵立下认主之契",
                "stance": "坚定但不冒进",
                "arc_stage": "setup",
                "self_image": "一个资质平平却想守住宗门的外门弟子",
                "knowledge_state": ["剑诀残页与自己相通", "师父进过禁地"],
                "relations": {"bai_zhi": "同门，心中在意", "su_yan": "内门师兄，敬而远之"},
            },
            {
                "character_id": "bai_zhi",
                "name": "白芷",
                "identity": "青山宗外门弟子，与陆离同期入门",
                "outer_goal": "撑过寒毒，不让身边人替自己冒险",
                "inner_need": "确认自己值得被这样拼命相护",
                "fear": "成为拖累，连累同门",
                "flaw": "隐忍，总把痛楚咽下去",
                "strength": "感知敏锐，能察觉灵脉异常",
                "secret": "寒毒源头是她在禁地边缘误吸的一缕异气",
                "stance": "温柔而倔强",
                "arc_stage": "setup",
                "self_image": "不想给别人添麻烦的人",
                "knowledge_state": ["寒毒来自禁地边缘的异气"],
                "relations": {"lu_li": "同门，最信任的人"},
            },
            {
                "character_id": "su_yan",
                "name": "苏衍",
                "identity": "青山宗内门弟子，筑基中阶",
                "outer_goal": "借禁地之行立下功勋，向真传之位更进一步",
                "inner_need": "证明自己不是靠出身而是靠实力",
                "fear": "被人看轻为『长老子弟』",
                "flaw": "好胜，手段里带着功利",
                "strength": "修为扎实，剑法凌厉",
                "secret": "暗中受长老之托留意禁地灵脉",
                "stance": "倨傲，但对同门尚有底线",
                "arc_stage": "setup",
                "self_image": "一个靠实力说话的内门精英",
                "knowledge_state": ["灵脉支线经禁地脚下"],
                "relations": {"lu_li": "内门看外门，存轻视"},
            },
        ],
        "state_id": "ns_mf_000",
        "current_time": "初秋，晨雾未散",
        "current_location": "青山宗外门演武场边的枯泉旁",
        "current_situation": "陆离晨练后在枯泉边拾到一枚残页剑诀，剑意竟与师父旧剑相通；同时得知白芷被查出身中寒毒，解药指向禁地",
        "primary_goal": "查清残页来历，设法为白芷解毒",
        "active_conflicts": ["剑诀来历存疑，可能牵连禁术", "白芷寒毒扩散"],
        "emotional_temperature": "焦灼、克制",
        "public_information": ["宗门灵泉枯竭", "师父三年前进禁地失踪"],
        "hidden_information": ["残页剑诀与师父的关系", "寒毒源头", "灵脉被截流的真相"],
        "private_information_map": {
            "lu_li": ["残页剑诀与自己相通", "已与剑灵立契"],
            "bai_zhi": ["寒毒来自禁地边缘异气"],
            "su_yan": ["受托留意禁地灵脉"],
        },
        "open_questions": ["残页剑诀从何而来", "师父为何进禁地"],
        "active_suspense_items": ["残页剑诀的来历", "白芷寒毒的解药"],
        "current_goals": ["求证剑诀来历", "探明禁地入口"],
        "linked_open_threads": ["rem_mf_001", "rem_mf_002", "rem_mf_003"],
        "current_facts_in_scope": ["fact_mf_001", "fact_mf_002"],
        "facts": [
            {
                "fact_id": "fact_mf_001",
                "statement": "陆离在枯泉边拾到一枚残页剑诀",
                "fact_type": "event",
                "involved_entities": ["lu_li"],
                "known_by": ["lu_li"],
            },
            {
                "fact_id": "fact_mf_002",
                "statement": "白芷被查出身中寒毒",
                "fact_type": "event",
                "involved_entities": ["bai_zhi"],
                "known_by": ["lu_li", "bai_zhi"],
            },
            {
                "fact_id": "fact_mf_003",
                "statement": "宗门灵泉近三百年持续枯竭",
                "fact_type": "rule",
                "involved_entities": [],
                "known_by": ["lu_li"],
            },
        ],
        "threads": [
            {
                "thread_id": "rem_mf_001",
                "setup_point": "残页剑诀出现",
                "content": "剑诀残页与师父旧剑相通，其完整来历与师父失踪之谜相关",
                "visibility_level": "explicit",
                "expected_payoff": "剑诀来历揭晓，师父失踪之谜解开",
                "linked_characters": ["lu_li"],
                "linked_facts": ["fact_mf_001"],
            },
            {
                "thread_id": "rem_mf_002",
                "setup_point": "白芷身中寒毒",
                "content": "寒毒解药指向禁地，救人之路凶险",
                "visibility_level": "explicit",
                "expected_payoff": "寒毒解除，白芷脱险",
                "linked_characters": ["lu_li", "bai_zhi"],
                "linked_facts": ["fact_mf_002"],
            },
            {
                "thread_id": "rem_mf_003",
                "setup_point": "灵泉枯竭的异样",
                "content": "灵泉枯竭的真正原因不明，疑与灵脉被截流有关",
                "visibility_level": "implicit",
                "expected_payoff": "灵泉复苏，宗门根基重立",
                "linked_characters": ["lu_li"],
                "linked_facts": ["fact_mf_003"],
            },
        ],
        "scenes": MYTHIC_FANTASY_SCENES,
    },
    "historical_strategy": {
        "genre": "历史",
        "subgenre": "架空历史权谋",
        "audience": "成年读者",
        "theme": "家国与权谋：在朝堂倾轧中守护江山社稷",
        "tone": "沉郁、机锋",
        "pacing": "中快，密信、朝堂、边关三线交织",
        "temperament": "深谋、隐忍、以大局为重",
        "length_target": 3500,
        "constraints": [
            "全部朝臣/官职为架空虚构",
            "权谋要有代价，不降智",
            "边关与朝堂双线需互相呼应",
        ],
        "world_facts": [
            "王朝边关正与邻国对峙，粮草吃紧",
            "兵部军粮账目出现去向不明的缺口",
            "先帝驾崩不过三年，今上年少，储位未稳",
            "主战派与主和派在朝堂角力",
        ],
        "social_structure": "皇权—内阁—六部—地方，边军自成体系",
        "power_system": "君权 + 旧臣元老集团 + 储位之争三方制衡",
        "resource_system": "漕运与军粮是国家命脉，皇商领盐引",
        "geography": "都城在腹地，边关在西北，漕运经东线北上",
        "factions": ["主战派将领", "主和重臣一系", "太子近臣", "边军旧部"],
        "time_rules": ["朝会议程严格", "军情传递有加急时限"],
        "prohibitions": ["不得私通外敌", "不得私议储位"],
        "consequence_logic": [
            "通敌、谋逆为株连大罪",
            "军情延误可能贻误战机",
        ],
        "hard_rules": ["每一次翻盘都必须建立在证据链上"],
        "death_rule": "主角不轻易死；关键配角可牺牲",
        "forbidden_actions": ["主角不得亲自操刀谋逆"],
        "exception_rules": ["边将奉密旨可便宜行事"],
        "characters": [
            {
                "character_id": "xie_yunzheng",
                "name": "谢云峥",
                "identity": "中书舍人，掌机要文书，三十岁",
                "outer_goal": "查清边关密信与军粮案背后的通敌网",
                "inner_need": "在权谋中守住自己做人的底线",
                "fear": "自己的一步棋把无辜者推向死地",
                "flaw": "算无遗策却心软，易被情感牵动",
                "strength": "洞察文书细节，能破译暗语",
                "secret": "密信残本是他抄录的副本",
                "stance": "隐忍，谋定后动",
                "arc_stage": "setup",
                "self_image": "一个只忠于社稷的中枢幕僚",
                "knowledge_state": ["密信暗语指向朝中重臣", "军粮账目有缺口"],
                "relations": {"shen_mo": "故交，边军参将"},
            },
            {
                "character_id": "shen_mo",
                "name": "沈墨",
                "identity": "西北边军参将，主战派旧部",
                "outer_goal": "守住边关防线，为被下狱的主帅洗冤",
                "inner_need": "在军令与道义之间不迷失",
                "fear": "被当作弃子，让边防崩坏",
                "flaw": "刚直，不擅朝堂博弈",
                "strength": "治军严整，边关将士信服",
                "secret": "暗中保存了主帅被构陷的证据",
                "stance": "刚烈，忠于旧主",
                "arc_stage": "setup",
                "self_image": "一个以命守边的军人",
                "knowledge_state": ["军粮缺口在边关造成实害"],
                "relations": {"xie_yunzheng": "故交，可托付密信"},
            },
            {
                "character_id": "jing_huai",
                "name": "敬怀",
                "identity": "太子东宫属官，少詹事",
                "outer_goal": "稳固太子的储位，清除逼宫隐患",
                "inner_need": "在忠诚与良知之间找到平衡",
                "fear": "太子的位子因自己的失误而动摇",
                "flaw": "多疑，情报压倒道义",
                "strength": "深谙宫闱旧事，门路通达",
                "secret": "知道先帝密诏的存在",
                "stance": "审慎，必要时决绝",
                "arc_stage": "setup",
                "self_image": "一个为储君分忧的孤臣",
                "knowledge_state": ["密诏牵动太子身世"],
                "relations": {"xie_yunzheng": "可合作的朝中同僚"},
            },
        ],
        "state_id": "ns_hs_000",
        "current_time": "深秋，深夜",
        "current_location": "中书省值房",
        "current_situation": "谢云峥于值房拆阅一封加急边关密信，暗语指向朝中有人私通外敌；同时兵部军粮账目出现缺口，他察觉两案或有关联",
        "primary_goal": "核实密信暗语所指，追查军粮缺口",
        "active_conflicts": ["主战派被弹劾下狱", "军粮缺口去向不明"],
        "emotional_temperature": "凝重、警觉",
        "public_information": ["边关对峙吃紧", "兵部核销军粮"],
        "hidden_information": ["密信暗语所指之人", "军粮缺口去向", "先帝密诏"],
        "private_information_map": {
            "xie_yunzheng": ["密信残本为副本", "暗语部分破译"],
            "shen_mo": ["暗中保存主帅受构陷的证据"],
            "jing_huai": ["知晓先帝密诏存在"],
        },
        "open_questions": ["密信暗语指向谁", "军粮缺口去了哪里"],
        "active_suspense_items": ["边关密信暗语", "军粮缺口"],
        "current_goals": ["破译密信暗语", "追查军粮账目"],
        "linked_open_threads": ["rem_hs_001", "rem_hs_002", "rem_hs_003"],
        "current_facts_in_scope": ["fact_hs_001", "fact_hs_002"],
        "facts": [
            {
                "fact_id": "fact_hs_001",
                "statement": "边关送来一封加急密信，内有暗语",
                "fact_type": "event",
                "involved_entities": ["xie_yunzheng"],
                "known_by": ["xie_yunzheng"],
            },
            {
                "fact_id": "fact_hs_002",
                "statement": "兵部军粮账目出现去向不明的缺口",
                "fact_type": "event",
                "involved_entities": ["xie_yunzheng"],
                "known_by": ["xie_yunzheng"],
            },
            {
                "fact_id": "fact_hs_003",
                "statement": "主战派主帅被弹劾下狱",
                "fact_type": "event",
                "involved_entities": ["shen_mo"],
                "known_by": ["shen_mo"],
            },
        ],
        "threads": [
            {
                "thread_id": "rem_hs_001",
                "setup_point": "边关密信出现",
                "content": "密信暗语指向朝中有人私通外敌，真凶与通敌网待查",
                "visibility_level": "explicit",
                "expected_payoff": "通敌网被揭穿，真凶伏法",
                "linked_characters": ["xie_yunzheng"],
                "linked_facts": ["fact_hs_001"],
            },
            {
                "thread_id": "rem_hs_002",
                "setup_point": "军粮账目出现缺口",
                "content": "军粮缺口与密信案疑同源，指向朝中夺嫡之争",
                "visibility_level": "implicit",
                "expected_payoff": "军粮案彻查，边关粮草补齐",
                "linked_characters": ["xie_yunzheng", "shen_mo"],
                "linked_facts": ["fact_hs_002"],
            },
            {
                "thread_id": "rem_hs_003",
                "setup_point": "先帝密诏的传闻",
                "content": "先帝密诏牵动太子身世与正统，被各方觊觎",
                "visibility_level": "implicit",
                "expected_payoff": "密诏公之于众，储位争端化解",
                "linked_characters": ["xie_yunzheng", "jing_huai"],
            },
        ],
        "scenes": HISTORICAL_STRATEGY_SCENES,
    },
}


def main() -> int:
    serializer = SerializationBoundaryUnit()
    frame_unit = NarrativeFrameUnit()
    manifest = {"schema_version": 1, "genres": {}}
    for genre_key, data in GENRES.items():
        out_dir = OUT_DIR / genre_key
        out_dir.mkdir(parents=True, exist_ok=True)
        workspec = _workspec(genre_key, data)
        worldmodel = _worldmodel(data)
        characters = _characters(data)
        char_ids = [c.character_id for c in characters]
        narrative = _narrative_state(data, char_ids)
        facts = _facts(data)
        foreshadows = _foreshadows(data)
        frames = _frames(data["scenes"])

        # 自校验：frame 状态必须通过确定性验证。
        blocking = [i for i in frame_unit.validate_frame_state(frames) if i["severity"] == "blocking"]
        if blocking:
            raise SystemExit(f"{genre_key}: frame blocking issues: {blocking}")
        cursor = frame_unit.get_cursor(frames)
        if cursor is None or cursor["current_frame_id"] != "scene_001":
            raise SystemExit(f"{genre_key}: cursor not at scene_001: {cursor}")

        objects = [workspec, worldmodel, *characters, narrative, facts, foreshadows]
        package = serializer.build_package(*objects)
        # 自校验：往返序列化必须还原全部对象。
        reloaded = serializer.deserialize_package(package)
        type_counts = {}
        for obj in reloaded:
            type_counts[type(obj).__name__] = type_counts.get(type(obj).__name__, 0) + 1
        expect = {
            "WorkSpec": 1, "WorldModel": 1, "CharacterModel": len(characters),
            "NarrativeState": 1, "FactLedger": 1, "ForeshadowGraph": 1,
        }
        if type_counts != expect:
            raise SystemExit(f"{genre_key}: round-trip mismatch: {type_counts} != {expect}")

        state_pkg_path = _write(out_dir, "base_state_package.json", package.model_dump())
        frames_path = _write(out_dir, "base_frames.json", frames)
        manifest["genres"][genre_key] = {
            "state_package": {
                "file": str(state_pkg_path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256_file(state_pkg_path),
            },
            "frames": {
                "file": str(frames_path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256_file(frames_path),
            },
            "scenes": len(frames) - 3,
            "characters": [c.character_id for c in characters],
            "threads": [t.thread_id for t in foreshadows.entries],
            "open_promises": len(foreshadows.get_active()),
        }
        print(f"{genre_key}: OK — scenes={len(frames)-3}, "
              f"characters={char_ids}, open_promises={len(foreshadows.get_active())}")

    manifest_path = _write(OUT_DIR, "setup_manifest.json", manifest)
    print("manifest:", manifest_path.relative_to(PROJECT_ROOT),
          _sha256_file(manifest_path)[:16], "…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
