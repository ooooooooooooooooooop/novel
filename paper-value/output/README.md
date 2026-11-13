# 输出目录

流水线输出统一放于此目录；脚本已改为优先使用本目录下子路径。

| 子目录 | 说明 | 来源 |
|--------|------|------|
| `checkpoints/` | 创新计算状态快照（state_20xx.pkl） | 原根目录 `innovation_checkpoints/` |
| `v6_opinion/` | 阶段6 观点识别输出（DB、缓存等） | 原根目录 `output_6_2_opinion_identification/` |
| `v7_impact/` | 可选：论文创新词汇统计7 的 impact 输出可迁入此处 | 7 下 `impact_output/` |

**迁移**：若根目录仍存在 `innovation_checkpoints/` 或 `output_6_2_opinion_identification/`，请在项目根执行一次：  
`python migrate_outputs.py`  
确认无误后可删除原目录。

其他结果文件（如 `evaluation_results.xlsx`、`*_results*.csv`）可继续放根目录或移入本目录并更新对应脚本路径。
