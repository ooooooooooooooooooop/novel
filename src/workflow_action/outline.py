"""OutlineUnit — 结构概览工作流.

从全文章节采样中提取 L1 结构层（book → arc → chapter 映射）。
"""

import json
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_non_blank_items(values: list[str], field_name: str) -> list[str]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} entries must be non-empty")
    return values


class ArcOutline(BaseModel):
    """单个 Arc 的概览."""

    model_config = ConfigDict(extra="forbid")

    arc_id: str = Field(description="Arc 唯一标识，如 arc_001")
    name: str = Field(description="Arc 名称，如'重生觉醒'")
    chapter_range: str = Field(description="覆盖章节范围，如'1-15'")
    purpose: str = Field(description="Arc 在全书中的叙事功能")
    key_characters: list[str] = Field(
        default_factory=list, description="该 Arc 中的核心角色ID"
    )
    key_events: list[str] = Field(
        default_factory=list, description="该 Arc 中的关键事件摘要"
    )


    @field_validator("arc_id", "name", "chapter_range", "purpose")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("key_characters", "key_events")
    @classmethod
    def _list_items_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        return _require_non_blank_items(values, info.field_name)


class CharacterOutline(BaseModel):
    """角色概览（仅基础信息，不含心理深度）."""

    model_config = ConfigDict(extra="forbid")

    character_id: str = Field(description="角色ID")
    name: str = Field(description="角色名")
    identity: str = Field(description="身份定位，如'重生者/官员'")
    first_appearance: str = Field(description="首次出场章节，如'第1章'")


    @field_validator("character_id", "name", "identity", "first_appearance")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class WorldOutline(BaseModel):
    """世界观框架概览."""

    model_config = ConfigDict(extra="forbid")

    genre: str = Field(description="类型，如都市重生/仙侠")
    power_system: str = Field(description="力量/资源/核心能力体系")
    time_period: str = Field(description="时间跨度，如'1994-2008'")
    key_rules: list[str] = Field(
        default_factory=list, description="影响叙事的核心世界规则"
    )


    @field_validator("genre", "power_system", "time_period")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("key_rules")
    @classmethod
    def _key_rules_must_be_non_blank(
        cls, values: list[str], info: ValidationInfo
    ) -> list[str]:
        return _require_non_blank_items(values, info.field_name)


class TimelineEntry(BaseModel):
    """时间线节点."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(description="叙事时间点")
    event: str = Field(description="事件摘要")
    chapters: str = Field(description="覆盖章节，如'1-3'")


    @field_validator("timestamp", "event", "chapters")
    @classmethod
    def _required_text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)


class BookOutline(BaseModel):
    """全书结构概览."""

    model_config = ConfigDict(extra="forbid")

    arcs: list[ArcOutline] = Field(description="Arc 列表（建议 3-8 个）")
    characters: list[CharacterOutline] = Field(
        default_factory=list, description="主要角色概览（≥3 次出场的角色）"
    )
    world: WorldOutline = Field(description="世界观框架")
    timeline: list[TimelineEntry] = Field(
        default_factory=list, description="主线时间线"
    )


    @field_validator("arcs")
    @classmethod
    def _arcs_must_be_non_empty(
        cls, values: list[ArcOutline], info: ValidationInfo
    ) -> list[ArcOutline]:
        if not values:
            raise ValueError(f"{info.field_name} must contain at least one arc")
        return values


class ChapterSample(NamedTuple):
    """章节采样."""

    chapter_index: int
    chapter_title: str
    sample_text: str


class OutlineUnit:
    """结构概览工作流."""

    MAX_SAMPLE_CHAPTERS = 30
    SAMPLE_CHARS_PER_CHAPTER = 300

    def build_prompt(
        self,
        text: str,
        chapter_samples: list[ChapterSample],
        total_chapters: int,
        total_chars: int,
    ) -> str:
        """生成结构概览 prompt.

        Args:
            text: 全文（仅用于长度感知，不直接放入 prompt）
            chapter_samples: 章节采样列表
            total_chapters: 总章节数
            total_chars: 总字符数
        """
        sample_ctx = []
        for idx, title, sample in chapter_samples:
            sample_ctx.append(
                f"--- 第{idx}章: {title} ---\n"
                f"{sample[:self.SAMPLE_CHARS_PER_CHAPTER]}"
            )

        samples_text = "\n\n".join(sample_ctx)
        arc_hint = self._suggest_arc_count(total_chapters)

        return f"""你是一位叙事结构分析专家。请基于以下章节采样，分析全书的宏观结构。

【文本概况】
- 总章节数: {total_chapters}
- 总字符数: {total_chars}
- 采样章节数: {len(chapter_samples)}（均匀采样）

【章节采样】
{samples_text}

【分析要求】

1. Arc 划分（建议 {arc_hint} 个）
   - 每个 Arc 说明其叙事功能（setup / confrontation / resolution 等）
   - 给出覆盖章节范围
   - 列出该 Arc 的关键事件（2-4 个）

2. 主要角色（≥3 次出场）
   - 角色ID（建议 c001, c002... 格式）
   - 姓名
   - 身份定位
   - 首次出场章节

3. 世界观框架
   - 类型（genre）
   - 核心力量/资源体系
   - 时间跨度
   - 2-3 条核心规则（如"重生者保留前世记忆"）

4. 主线时间线
   - 关键时间点
   - 对应事件
   - 覆盖章节

【输出格式】
严格输出 JSON，不要任何额外解释：
{{
  "arcs": [
    {{
      "arc_id": "arc_001",
      "name": "Arc名称",
      "chapter_range": "1-15",
      "purpose": "叙事功能描述",
      "key_characters": ["c001"],
      "key_events": ["事件摘要"]
    }}
  ],
  "characters": [
    {{
      "character_id": "c001",
      "name": "主角",
      "identity": "身份",
      "first_appearance": "第1章"
    }}
  ],
  "world": {{
    "genre": "类型",
    "power_system": "力量体系",
    "time_period": "时间跨度",
    "key_rules": ["核心规则1"]
  }},
  "timeline": [
    {{
      "timestamp": "时间点",
      "event": "事件",
      "chapters": "1-3"
    }}
  ]
}}
"""

    def parse_response(self, response: str) -> BookOutline:
        """解析结构概览响应."""
        data = json.loads(response)
        return BookOutline(**data)

    def _suggest_arc_count(self, total_chapters: int) -> str:
        """根据总章节数建议 Arc 数量."""
        if total_chapters <= 30:
            return "3-4"
        if total_chapters <= 100:
            return "4-6"
        return "6-8"

    def sample_chapters(self, chunks: list) -> list[ChapterSample]:
        """从章节列表中均匀采样.

        Args:
            chunks: chunking 模块返回的章节对象列表
        """
        if len(chunks) <= self.MAX_SAMPLE_CHAPTERS:
            return [
                ChapterSample(
                    chapter_index=c.chapter_index,
                    chapter_title=getattr(c, "chapter_title", f"第{c.chapter_index}章"),
                    sample_text=getattr(c, "text", "")[
                        : self.SAMPLE_CHARS_PER_CHAPTER
                    ],
                )
                for c in chunks
            ]

        step = len(chunks) / self.MAX_SAMPLE_CHAPTERS
        sampled = []
        for i in range(self.MAX_SAMPLE_CHAPTERS):
            idx = int(i * step)
            c = chunks[idx]
            sampled.append(
                ChapterSample(
                    chapter_index=c.chapter_index,
                    chapter_title=getattr(c, "chapter_title", f"第{c.chapter_index}章"),
                    sample_text=getattr(c, "text", "")[
                        : self.SAMPLE_CHARS_PER_CHAPTER
                    ],
                )
            )
        return sampled
