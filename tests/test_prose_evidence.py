"""ProseEvidence 提取器单元测试 — 代码级确定性提取（零 LLM）.

断言：每条断言带原文证据锚点；实体/道具核对依赖 entities 注册表（无则静默为空）；
8 类 Phase 0 夹具对应的失败信号都能被无歧义提取。
"""

import hashlib

from src.workflow_action.prose_evidence import (
    ambient_only,
    conclusion_sentences,
    extract_prose_evidence,
    opening_signature,
    split_sentences,
)

# 官方 8 类夹具（与 test_q1_phase0_baseline.py 的 FIXTURES 对齐，防止漂移）
F01 = "周末，方宇翻开那本诗集，拈出一片干花瓣，凑到灯下端详。花瓣已经脆了，边缘卷起。他把它夹回书里，合上。"
F02 = "第二天一早，陈叔去喊李文起床，被子叠得整整齐齐，人不见了。院里井盖的泥脚印是新的。陈叔放下碗，出门去找。"
F03 = "十二月又到了。寒风卷着枯叶扑在窗上，河面重新结了冰。屋里生起炉子，众人围着火说话。"
F04 = "十一年过去，铜牌上的字迹又淡了。长老们说，试炼之期临近届满，各峰弟子早早开始准备。"
F05 = "上一章末她还在码头。本章她回到家中，推开窗，让风吹进来。她倒了一杯水，在窗前坐了很久。"
F06 = "雨下了一夜。赵立在窗前抽烟，烟灰落在窗台上。他听见楼下有人喊他名字。"
F07 = "他终于明白，放下才是对父亲的告慰。下山时下起小雨，他没有打伞。"
F08 = "林生仍坐在江边，看着水面上自己的倒影。云过来又过去，他把船票换到左手，又换了回去。天渐渐暗了，他起身掸了掸裤腿，沿着来路走回屋里。这一晚他没有再出门。"

_REG = {
    "c001": ["方宇"],
    "c002": ["李文"],
    "c003": ["陈叔"],
    "c005": ["赵立"],
    "c006": ["林生"],
    "obj_ticket": ["票根"],
}


def test_extract_time_month():
    pkg = extract_prose_evidence(F03, entities=_REG)
    times = pkg.of_kind("time")
    months = [i for i in times if "月份" in i.claim or "月" in i.evidence]
    assert any("十二" in i.claim for i in months), times
    # 每条时间断言必须带原文证据
    for i in times:
        assert i.evidence in F03


def test_extract_time_relative_years():
    pkg = extract_prose_evidence(F04, entities=_REG)
    rel = [i for i in pkg.of_kind("time") if "相对时长" in i.claim]
    assert any("十一年" in i.evidence for i in rel), rel
    assert any("相对时长" in i.claim for i in rel)


def test_extract_entity_status_missing():
    pkg = extract_prose_evidence(F02, entities=_REG)
    statuses = pkg.of_kind("entity_status")
    assert any("missing" in i.claim for i in statuses), statuses
    for i in statuses:
        assert i.evidence and i.location in ("开头", "中段", "结尾")


def test_extract_entity_status_needs_registry():
    # 无注册表 -> 无法核对实体身份 -> 静默为空（诚实边界）
    pkg = extract_prose_evidence(F02)
    assert pkg.of_kind("entity_status") == []


def test_extract_prop_identity_pull():
    pkg = extract_prose_evidence(F01, entities=_REG)
    props = pkg.of_kind("prop_identity")
    assert any("花瓣" in i.claim or "拈出" in i.evidence for i in props), props


def test_extract_meta_text():
    pkg = extract_prose_evidence(F05, entities=_REG)
    metas = pkg.of_kind("meta_text")
    assert len(metas) >= 2, metas  # 上一章 + 本章
    assert any("上一章" in i.evidence for i in metas)
    assert any("本章" in i.evidence for i in metas)


def test_extract_choice():
    draft = "他下定决心要离开，结果船票已经没了。"
    pkg = extract_prose_evidence(draft)
    assert pkg.has_kind("choice")
    assert pkg.has_kind("consequence")


def test_extract_state_change_substantive():
    draft = "她终于开口，告诉他自己收到了那封信。"
    pkg = extract_prose_evidence(draft)
    assert pkg.has_kind("state_change")


def test_opening_signature():
    assert opening_signature(F06, 2) == opening_signature("雨下了一夜。赵立在窗前抽烟，烟灰落在窗台上。他改了后文。", 2)


def test_opening_signature_differs():
    assert opening_signature(F06, 2) != opening_signature(F05, 2)


def test_conclusion_sentences_f07():
    conc = conclusion_sentences(F07)
    assert any("放下才是对父亲的告慰" in c for c in conc), conc


def test_ambient_only_f08_true():
    assert ambient_only(F08) is True


def test_ambient_only_dialogue_false():
    assert ambient_only("林生把船票放进怀里，对老船工说：“明天我还是要走的。”") is False


def test_package_evidence_anchors_and_hash():
    pkg = extract_prose_evidence(F02, entities=_REG)
    assert pkg.source_text_hash == hashlib.sha256(F02.encode("utf-8")).hexdigest()
    assert pkg.chapter_ref == "" and pkg.package_id == "pe"
    for i in pkg.items:
        assert i.evidence in F02, f"证据锚点不在原文: {i.item_id}"
