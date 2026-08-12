"""A1 T5 — EvaluatorPrecommit（design §8 评审预承诺）.

评审看正文前只读取可信状态、ReaderContract、PlotUnit 和承诺图，生成不可修改的
``EvaluatorPrecommit``；正文完成后用同一份预承诺执行证伪检查，候选不能改变
评审标准。

不可变性（G5：「评审预承诺在读取正文后不可变」）通过两条保证：
1. 结构上——模型字段全部来自正文前的输入（PlotUnit / new_state / 可信状态哈希 /
   ReaderContract 是否在场的标记），**没有正文字段**；``extra="forbid"`` 使任何
   试图把正文衍生信息塞进预承诺的构造直接失败。
2. 运行层——``build_evaluator_precommit`` 只接受正文前输入；同一份预承诺对两份
   不同正文产生完全相同的对象（有测试锁死），证伪结果写在新的 JudgeClaim 上，
   绝不回写预承诺。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluatorPrecommit(BaseModel):
    """评审看正文前冻结的预期事实与检查项."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    precommit_id: str = Field(min_length=1, description="如 precommit_plan_0001")
    plotunit_id: str = Field(min_length=1)
    input_state_id: str = Field(min_length=1)
    output_state_id: str = Field(min_length=1)
    # PlotUnit 预期输出状态变化（正文证据的对照基线，全部来自正文前输入）。
    expected_output_location: str = Field(min_length=1)
    expected_output_situation: str = Field(min_length=1)
    expected_released_information: tuple[str, ...]
    expected_consequences: tuple[str, ...]
    effective: bool = Field(description="PlotUnit.is_effective——关键单元强制正文证据")
    # 可信状态（facts ledger + 上一 NarrativeState）的哈希：锁定评审基线，
    # 证明预承诺冻结于「正文前的可信状态」而非正文。
    trusted_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    # 本预承诺将执行的证伪检查清单（design §8 子集）。
    check_list: tuple[str, ...] = (
        "plotunit_expected_change",
        "prose_actual_change",
        "semantic_seam",
        "reader_experience",
        "fact_certainty",
    )

    @model_validator(mode="after")
    def _expected_information_is_non_empty(self) -> "EvaluatorPrecommit":
        for field_name in ("expected_released_information", "expected_consequences"):
            values = getattr(self, field_name)
            if any(not item.strip() for item in values):
                raise ValueError(f"{field_name} entries must be non-empty")
        return self
