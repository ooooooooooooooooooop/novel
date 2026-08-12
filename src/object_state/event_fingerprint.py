"""A1 T4 — 事件指纹（语义接缝重演阻断的事实基础）.

事件指纹把一个叙事事件结构化为 (参与者, 行为, 对象, 结果, 状态变化, 确定性)。

``certainty`` 区分「确证的事实」与「真幻不明的文学歧义」：歧义事件不得被当作
事实冲突或重演的证据（doc 48 §6 step 4/5，S3 反例：ch22 真幻不明不得误杀）。

本模型是纯结构契约；指纹的提取（heuristic）与重演判断在
``src/workflow_action/semantic_seam.py``，两者分离以便测试直接构造指纹断言判断逻辑。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventFingerprint(BaseModel):
    """单个叙事事件的结构化指纹。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1)
    chapter_number: int = Field(gt=0)
    position: Literal["start", "end", "middle"]
    participants: tuple[str, ...] = Field(min_length=1)
    subject: str = ""  # 行为者（主语位实体；句首为主语代词时为 ""，不可解析）
    behavior: str = Field(min_length=1)  # 行为核心（规范化后），如「接到电话得知乔晚去了远方」
    object: str = ""  # 行为作用对象（可空）
    result: str = ""  # 结果（连接词后落点；无则空）
    state_change: str = ""  # 产生的状态变化（与 result 同源；新状态反例的判别位）
    certainty: Literal["certain", "ambiguous"] = "certain"

    @model_validator(mode="after")
    def _participants_are_unique(self) -> "EventFingerprint":
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("participants must be unique")
        if self.subject and self.subject not in self.participants:
            raise ValueError("subject must be one of participants")
        return self


class SeamReplayFinding(BaseModel):
    """语义接缝重演阻断发现（确定性，blocking）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    finding_id: str = Field(min_length=1)
    issue_type: Literal["seam_event_replay"]
    blocking: Literal[True] = True
    previous_event_id: str = Field(min_length=1)
    new_event_id: str = Field(min_length=1)
    chapter_gap: int = Field(ge=0)
    description: str = Field(min_length=1)


class EventFingerprintSet(BaseModel):
    """一章（或一段）文本的事件指纹集合（可持久化到运行目录）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    chapter_number: int = Field(gt=0)
    position: Literal["start", "end", "middle"]
    fingerprints: tuple[EventFingerprint, ...]

    @model_validator(mode="after")
    def _fingerprints_share_chapter_and_position(self) -> "EventFingerprintSet":
        for fingerprint in self.fingerprints:
            if fingerprint.chapter_number != self.chapter_number:
                raise ValueError("fingerprint chapter differs from set chapter")
            if fingerprint.position != self.position:
                raise ValueError("fingerprint position differs from set position")
        return self
