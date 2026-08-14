"""T4/T5 — 语义接缝重演阻断单元测试：事件指纹模型契约 + 提取 + 重演判断.

与 test_autonomous_runner.py 的集成测试互补：此处直接构造指纹/文本，断言判断逻辑：
- 手机电话重演（阳性阻断）；
- 回忆产生新状态（阴性不误杀）；
- 真幻不明（阴性不当作事实/重演证据）；
- 跨角色同行为（阴性不误杀）；
- 章距 window、行为者判别、participants 交集规则。
"""

import pytest
from pydantic import ValidationError

from src.object_state.event_fingerprint import (
    EventFingerprint,
    EventFingerprintSet,
    SeamReplayFinding,
)
from src.workflow_action.semantic_seam import (
    character_names,
    detect_event_replay,
    extract_event_fingerprints,
)


def _fingerprint(**overrides) -> EventFingerprint:
    payload = {
        "event_id": "ev_0001_end_001",
        "chapter_number": 1,
        "position": "end",
        "participants": ("林越", "乔晚"),
        "subject": "林越",
        "behavior": "接到电话得知乔晚去了远方",
        "object": "乔晚",
        "result": "",
        "state_change": "",
        "certainty": "certain",
    }
    payload.update(overrides)
    return EventFingerprint(**payload)


# ---------------------------------------------------------------- 模型契约


class TestEventFingerprintModel:
    def test_valid(self):
        fp = _fingerprint()
        assert fp.participants == ("林越", "乔晚")
        assert fp.certainty == "certain"

    def test_duplicate_participants_rejected(self):
        with pytest.raises(ValidationError):
            _fingerprint(participants=("林越", "林越"))

    def test_subject_must_be_participant(self):
        with pytest.raises(ValidationError):
            _fingerprint(subject="周生")

    def test_blank_behavior_rejected(self):
        # min_length=1：空串被拒；空白串通过 min_length（模型不承担规范化职责，
        # 提取层 _normalize 保证行为核心非空白）
        with pytest.raises(ValidationError):
            _fingerprint(behavior="")

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            _fingerprint(extra="x")

    def test_ambiguous_certainty(self):
        fp = _fingerprint(certainty="ambiguous")
        assert fp.certainty == "ambiguous"


class TestSeamReplayFindingModel:
    def test_defaults(self):
        finding = SeamReplayFinding(
            finding_id="seam_replay_ev_new_vs_ev_old",
            issue_type="seam_event_replay",
            previous_event_id="ev_0001_end_001",
            new_event_id="ev_0002_start_001",
            chapter_gap=1,
            description="重演",
        )
        assert finding.blocking is True
        assert finding.issue_type == "seam_event_replay"


class TestEventFingerprintSetModel:
    def test_members_share_chapter_and_position(self):
        fps = (
            _fingerprint(event_id="ev_0001_end_001", chapter_number=1, position="end"),
            _fingerprint(event_id="ev_0001_end_002", chapter_number=1, position="end"),
        )
        assert EventFingerprintSet(chapter_number=1, position="end", fingerprints=fps)

    def test_mismatched_chapter_rejected(self):
        with pytest.raises(ValidationError):
            EventFingerprintSet(
                chapter_number=1,
                position="end",
                fingerprints=(_fingerprint(chapter_number=2),),
            )


# ---------------------------------------------------------------- 提取


class TestExtractEventFingerprints:
    def test_extracts_participants_subject_behavior(self):
        fps = extract_event_fingerprints(
            "林越接到电话，得知乔晚去了远方。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert len(fps) == 1
        fp = fps[0]
        assert fp.chapter_number == 2
        assert fp.position == "start"
        assert set(fp.participants) == {"林越", "乔晚"}
        assert fp.subject == "林越"
        assert "接到电话" in fp.behavior

    def test_pronoun_subject_unresolvable(self):
        # 句首主事代词 → subject 空（重演判断按「假定同一行为者」处理，不跨实体误杀）
        fps = extract_event_fingerprints(
            "他接到电话，得知乔晚去了远方。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert fps
        assert fps[0].subject == ""

    def test_sentence_without_entity_skipped(self):
        fps = extract_event_fingerprints(
            "路灯在雨里发着昏黄的光。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert fps == []

    def test_ambiguous_sentence_marked_ambiguous(self):
        fps = extract_event_fingerprints(
            "林越接到电话，分不清那是真实还是梦。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert fps
        assert fps[0].certainty == "ambiguous"

    def test_connective_splits_result(self):
        fps = extract_event_fingerprints(
            "林越接到电话，于是决定去找乔晚。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert fps
        assert fps[0].result != ""

    def test_leading_connective_not_empty_behavior(self):
        # 句子以连接词开头（如「便向码头走去」）时，连接词是过渡标记而非结果
        # 引入词；behavior 不得为空串（回归：曾经触发 EventFingerprint 契约违例）。
        fps = extract_event_fingerprints(
            "便向码头走去。",
            chapter_number=2,
            entities=["码头"],
            position="start",
        )
        assert fps
        assert fps[0].behavior != ""
        assert fps[0].result == ""

    def test_leading_connective_then_real_connective(self):
        # 先导连接词跳过，后续真正连接词仍切出 result。
        fps = extract_event_fingerprints(
            "便决定答应林越，于是去了码头。",
            chapter_number=2,
            entities=["林越", "码头"],
            position="start",
        )
        assert fps
        assert fps[0].behavior != ""
        assert fps[0].result != ""


class TestCharacterNames:
    def test_collects_names(self):
        class _C:
            def __init__(self, name):
                self.name = name

        assert character_names([_C("林越"), _C("乔晚"), _C("  ")]) == ["林越", "乔晚"]

    def test_empty(self):
        assert character_names([]) == []


# ---------------------------------------------------------------- 重演判断


def _end_events():
    return extract_event_fingerprints(
        "林越接到电话，得知乔晚去了远方。",
        chapter_number=1,
        entities=["林越", "乔晚"],
        position="end",
    )


class TestDetectEventReplay:
    def test_phone_replay_blocked(self):
        # 上章末与本章首原样重演 → 1 finding（S 反例：电话重演阳性阻断）
        previous = _end_events()
        new = extract_event_fingerprints(
            "他又接到电话，得知乔晚去了远方。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        findings = detect_event_replay(previous, new)
        assert len(findings) == 1
        assert findings[0].issue_type == "seam_event_replay"
        assert findings[0].chapter_gap == 1

    def test_memory_new_state_not_replay(self):
        # 回忆同一事件但产生新状态 → 不阻断（状态变化不同，指纹不全等）
        previous = _end_events()
        new = extract_event_fingerprints(
            "林越想起那通电话，决定现在就去找乔晚。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert detect_event_replay(previous, new) == []

    def test_truth_fiction_ambiguity_not_replay(self):
        # 真幻不明（certainty=ambiguous）→ 不当作重演证据（S3 反例）
        previous = _end_events()
        new = extract_event_fingerprints(
            "林越接到电话，分不清那是真实还是梦。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert detect_event_replay(previous, new) == []

    def test_cross_actor_same_action_not_replay(self):
        # 周生做相同动作 → 行为者不同，不误杀（防跨角色同行为误判）
        previous = _end_events()
        new = extract_event_fingerprints(
            "周生接到电话，得知乔晚去了远方。",
            chapter_number=2,
            entities=["林越", "乔晚", "周生"],
            position="start",
        )
        assert detect_event_replay(previous, new) == []

    def test_different_behavior_not_replay(self):
        previous = _end_events()
        new = extract_event_fingerprints(
            "林越走到窗前，看见乔晚的车停在楼下。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert detect_event_replay(previous, new) == []

    def test_window_respected(self):
        # 章距超过 window → 不阻断
        previous = _end_events()
        new = extract_event_fingerprints(
            "他又接到电话，得知乔晚去了远方。",
            chapter_number=3,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert detect_event_replay(previous, new, window=1) == []

    def test_window_zero_same_chapter(self):
        previous = _end_events()
        new = extract_event_fingerprints(
            "他又接到电话，得知乔晚去了远方。",
            chapter_number=1,
            entities=["林越", "乔晚"],
            position="end",
        )
        findings = detect_event_replay(previous, new, window=0)
        assert len(findings) == 1

    def test_ambiguous_previous_not_used_as_evidence(self):
        # 歧义事件不能作为重演/事实证据（哪怕新事件是确证）
        previous = extract_event_fingerprints(
            "林越接到电话，分不清那是真实还是梦。",
            chapter_number=1,
            entities=["林越", "乔晚"],
            position="end",
        )
        new = extract_event_fingerprints(
            "他又接到电话，得知乔晚去了远方。",
            chapter_number=2,
            entities=["林越", "乔晚"],
            position="start",
        )
        assert detect_event_replay(previous, new) == []

    def test_empty_pools(self):
        assert detect_event_replay([], _end_events()) == []
        assert detect_event_replay(_end_events(), []) == []

    def test_replay_with_fingerprints_directly(self):
        # 直接构造指纹断言判断逻辑（不经提取启发式）
        previous = [_fingerprint(
            event_id="ev_0001_end_001",
            chapter_number=1,
            position="end",
            behavior="接到电话",
            result="得知乔晚去了远方",
            state_change="得知乔晚去了远方",
        )]
        new = [_fingerprint(
            event_id="ev_0002_start_001",
            chapter_number=2,
            position="start",
            behavior="接到电话",
            result="得知乔晚去了远方",
            state_change="得知乔晚去了远方",
        )]
        assert len(detect_event_replay(previous, new)) == 1

    def test_state_change_difference_not_replay(self):
        # 回忆产生新状态（state_change 不同）→ 不阻断
        previous = [_fingerprint(
            event_id="ev_0001_end_001",
            chapter_number=1,
            position="end",
            behavior="接到电话",
            result="得知乔晚去了远方",
            state_change="得知乔晚去了远方",
        )]
        new = [_fingerprint(
            event_id="ev_0002_start_001",
            chapter_number=2,
            position="start",
            behavior="想起电话",
            result="决定去找乔晚",
            state_change="决定去找乔晚",
        )]
        assert detect_event_replay(previous, new) == []
