"""ReaderResponse — 多读者/多评审原始响应逐份留存对象（design §10）.

`responses/<reader_id>.json` 逐份保存，禁止覆盖。每份记录 prompt hash、模型、版本、
采样、运行 ID 和正文包 hash，使原始评审响应可追溯（T7.3 / G7）。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class ReaderResponseRecord(BaseModel):
    """单份读者/评审原始响应（防覆盖、带元数据）."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(default="1.0")
    reader_id: str = Field(description="读者/评审标识（responses/<reader_id>.json）")
    prompt_hash: str = Field(description="问卷/评审 prompt SHA-256（追溯与去重）")
    model: str = Field(description="响应模型身份（请求模型）")
    model_version: str = Field(default="", description="模型版本（可空）")
    sampling: str = Field(default="", description="采样参数摘要（如 temperature=0.0）")
    run_id: str = Field(description="所属运行 id")
    prose_package_hash: str = Field(description="正文包 SHA-256（评审读到的正文指纹）")
    response: str = Field(description="原始响应（JSON 字符串或自由文本）")

    @field_validator("reader_id", "prompt_hash", "model", "run_id")
    @classmethod
    def _text_must_be_non_blank(
        cls, value: str, info: ValidationInfo
    ) -> str:
        return _require_non_blank(value, info.field_name)
