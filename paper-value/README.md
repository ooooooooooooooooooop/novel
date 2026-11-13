# paper-value

在大规模论文语料上，为**每一篇论文**生成客观、可追溯的**价值信号**，支持好坏裁决。**不使用引用数据**，仅基于论文标题、关键词、摘要等内容；通过**可比较的维度**给出可解释的度量结果。

## 可比较的维度（双信号）

| 维度 | 含义 | 时间锚点 |
|------|------|----------|
| **创新度 (Innovation)** | 相对于历史语料的新颖距离——“你是不是第一个？” | 发表时 |
| **影响力 (Impact)** | 概念在后续学术系统中的采纳强度——“别人是否因你而改变？” | 发表后 |

两维度可合成为论文贡献类型（Pioneer、Ahead-of-time、Diffuser、Routine），便于在同一尺度下比较与裁决。详见 `论文创新词汇统计7/TODO_execution_plan.md` 与 `docs/paper_value_signal_system_v2.md`。

## V6.1 当前口径（语义纠偏）

- 当前影响力主分语义：`diffusion_impact`（概念在后续论文中的扩散采纳强度）。
- 兼容字段：`impact_score` 仍保留，并与 `diffusion_impact` 等值映射，避免下游 schema 断裂。
- 并行通道：已新增 `foundation_utility_raw/foundation_utility_norm`（V6.2）与 `method_transferability_raw/method_transferability_norm`（V6.3），与 `diffusion_impact` 并行输出，不切主分。
- 多通道发布策略：当前为三通道并行输出（`diffusion_impact + foundation_utility + method_transferability`），通过门禁后再评估是否切换主评分口径。
- 约束不变：全流程仅使用标题/关键词/摘要文本特征，不使用引用数据。

## 入口

- **主流程**：`论文创新词汇统计7/run_v2_full.py`（创新度 V2 全量运行，断点续传）
- **根目录**：`calculate_innovation.py`、`calculate_impact.py`（独立入口，需配置 DB 路径）
- **main.py**：占位入口

## 项目结构

| 目录 | 用途 |
|------|------|
| **config/** | 停用词等词表 |
| **data/raw/** | 输入 CSV；大体积数据不入库，见 `.gitignore` |
| **output/** | 流水线输出 |
| **resources/** | 二进制资源 |
| **docs/** | 文档与设计图 |
| **tools/** | 独立工具脚本（预处理、查看结果等） |
| **论文创新词汇统计7/** | 主实现：RPU 抽取、抽象层、创新度/影响力计算、anomaly_detection 等 |
| **历史版本/** | 历代脚本归档，不参与主流程 |

配置与数据路径以项目根或 `论文创新词汇统计7` 为基准。

## 环境

- Python ≥ 3.12，依赖见 `pyproject.toml`，建议使用 `uv` 管理。
