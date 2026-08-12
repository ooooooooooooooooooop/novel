"""A1 T4 — PremiseCandidate（needs_premise 自动搜索的前提候选契约）.

当结构已完成但仍有未兑现承诺（viability=needs_premise）时，A1 不得 [WAITING]，
而是自动搜索新前提：新外部冲突 / 新阶段目标 / 与已闭合情感弧的边界 / 必须兑现的
旧承诺 / 可产生的新状态变化 / 读者契约合法性。

候选由 provider 生成、由 ``validate_premise_candidate`` 确定性验证（重新进入
viability 必须回到 continue）；全部失败 → ``premise_exhausted`` 终态。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PremiseCandidate(BaseModel):
    """一个可继续推进故事的新前提候选。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    candidate_id: str = Field(min_length=1)
    new_external_conflict: str = Field(min_length=1)  # 新的外部冲突
    new_phase_goal: str = Field(min_length=1)  # 新的阶段目标
    boundary_to_closed_arc: str = Field(min_length=1)  # 与已闭合情感弧的边界（不重开）
    obligations_to_old_promises: tuple[str, ...] = Field(min_length=1)  # 必须兑现的旧承诺
    new_state_change: str = Field(min_length=1)  # 可产生的新状态变化
    reader_contract_legal: bool  # 是否满足读者契约
    reader_contract_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _obligations_are_non_empty(self) -> "PremiseCandidate":
        if not self.obligations_to_old_promises:
            raise ValueError("obligations_to_old_promises must be non-empty")
        if any(not obligation.strip() for obligation in self.obligations_to_old_promises):
            raise ValueError("obligations_to_old_promises entries must be non-empty")
        return self
