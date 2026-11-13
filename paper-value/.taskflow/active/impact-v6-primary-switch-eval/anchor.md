# Grounding Anchor

**Intent**: 在不改变当前默认主分（`diffusion_impact`）的前提下，落地一套可执行的 `V6 主分切换评估` 工具与报告。

**Constraints**:
- 不引入引用数据，仅使用现有标题/关键词/摘要派生字段与已有产物。
- 不直接切换线上主分语义，仅新增评估入口与诊断结论。

**Scope**:
- Include: 新增评估脚本；支持候选通道（`foundation_utility` / `method_transferability` / `blend_v1`）与门禁建议输出；补充文档入口。
- Exclude: 不修改 `calculate_impact_v6.py` 的默认主分输出；不改历史产物。

**Done-when**:
- 新脚本可运行并输出结构化 JSON 评估报告（含覆盖率、分布、零值堆积、样本对方向、建议结论）。
- 文档中有明确使用方式；任务记录写入 `.taskflow`。

**Resolved Ambiguities**:
- “开始下一轮任务” → 决议为“先做主分切换评估工具与门禁结论，不直接切主分”。
