# P4-0 基线盘点（硬编码路径与历史配置表达）

## 盘点范围
- 主链路：`scripts/pipeline`、`scripts/query`、`scripts/analyze`、根目录 6 个入口脚本。
- 训练链路：`scripts/train`。
- legacy 链路：`scripts/legacy`（含 `validation`）。
- 文档：`docs/*`（含 `docs/reference/*`）。

## 盘点方法
- 使用 `rg` 按关键目录名、路径字面量、`FileHandler`、绝对路径模式（`D:\...`）扫描。
- 对命中项做人工复核，剔除注释噪声与非路径字符串。
- 输出按 `P4-1~P4-4` 可执行分批映射。

## 结论总览
- 主链路：2 个高优先级代码问题 + 2 个中优先级配置/文档问题。
- 训练链路：2 个高优先级硬编码问题 + 1 个中优先级配置一致性问题。
- legacy 链路：10 个高优先级硬编码/历史路径问题（集中在脚本内 `CONFIG` 常量）。
- 文档：4 个中低优先级历史描述残留点（与 P3 后现状不一致或属历史参考内容）。

## 分批清单

### P4-1（主链路优先）
- [HIGH] `scripts/pipeline/calculate_innovation.py:2375`
  - 问题：`--input_path` 默认值为绝对路径 `d:\...\test_rpus.csv`。
  - 影响：跨机器不可用，默认行为受本地目录耦合。
- [HIGH] `scripts/pipeline/calculate_innovation.py:1314`
  - 问题：`verb_innovation_weights.json` 从 `Path(__file__).parent` 读取。
  - 现状：实际文件位于根目录 `verb_innovation_weights.json`，脚本目录下不存在同名文件。
  - 影响：配置静默失效，回退为纯 IDF 权重。
- [MEDIUM] `scripts/pipeline/calculate_innovation.py:52`
  - 问题：日志文件名硬编码为 `innovation_calculation.log`（相对当前工作目录）。
- [MEDIUM] `scripts/pipeline/calculate_impact_v2.py:43`
  - 问题：日志文件名硬编码为 `impact_calculation.log`（相对当前工作目录）。
- [LOW] `scripts/pipeline/merge_signals.py:6`
- [LOW] `scripts/pipeline/merge_signals.py:7`
- [LOW] `scripts/pipeline/merge_signals.py:10`
  - 问题：模块注释仍使用旧目录表述（`impact_output/*`、`paper_signals_output/*`），与当前配置语义不完全一致。

### P4-2（训练链路对齐）
- [HIGH] `scripts/train/train_research_structure_extractor.py:386`
  - 问题：训练数据 Excel 使用绝对路径 `D:\...\research_structure_training_data.xlsx`。
- [HIGH] `scripts/train/train_research_structure_extractor.py:389`
  - 问题：输出目录硬编码为 `./models/cached_models/research_structure_extractor`。
- [MEDIUM] `scripts/train/train_deberta_multihead.py:52`
- [MEDIUM] `scripts/train/train_deberta_multihead.py:53`
  - 问题：使用 `_paths.get(..., fallback)` 历史 fallback 语义，缺少配置键时会静默退回根目录路径。
  - 建议：改为配置缺失即显式报错，保证训练路径确定性。

### P4-3（legacy 渐进改造）
- [HIGH] `scripts/legacy/convert_rpu_to_spans.py:28`
- [HIGH] `scripts/legacy/convert_rpu_to_spans.py:29`
- [HIGH] `scripts/legacy/convert_rpu_to_spans.py:30`
  - 问题：输入/输出路径全部为绝对路径。
- [HIGH] `scripts/legacy/mine_phrases.py:37`
- [HIGH] `scripts/legacy/mine_phrases.py:38`
- [HIGH] `scripts/legacy/mine_phrases.py:52`
  - 问题：`db_path`、`output_path`、`temp_dir` 全部为绝对路径。
- [HIGH] `scripts/legacy/apply_abstract_layer.py:32`
- [HIGH] `scripts/legacy/apply_abstract_layer.py:33`
- [HIGH] `scripts/legacy/apply_abstract_layer.py:35`
  - 问题：数据库/短语表/core 映射路径全部为绝对路径。
- [HIGH] `scripts/legacy/normalize_cores.py:27`
- [HIGH] `scripts/legacy/normalize_cores.py:28`
  - 问题：输入输出路径为绝对路径。
- [HIGH] `scripts/legacy/normalize_cores.py:41`
  - 问题：API Key 明文硬编码（额外安全风险，建议同步纳入治理）。
- [HIGH] `scripts/legacy/calculate_impact_v2_lowmem.py:36`
- [HIGH] `scripts/legacy/calculate_impact_v2_lowmem.py:37`
- [HIGH] `scripts/legacy/calculate_impact_v2_lowmem.py:38`
  - 问题：仍使用历史目录表达（`output_7_deberta_full/*`、`impact_output/*`）。
- [HIGH] `scripts/legacy/calculate_impact_v2_optimized.py:56`
- [HIGH] `scripts/legacy/calculate_impact_v2_optimized.py:57`
  - 问题：仍使用历史目录表达（`output_7_deberta_full/*`、`impact_output/*`）。
- [HIGH] `scripts/legacy/rpu_full_extraction.py:40`
  - 问题：输出目录硬编码为历史目录 `output_7_full`。
- [HIGH] `scripts/legacy/supplement_paper_metadata.py:25`
  - 问题：数据库路径固定到 `output_7_deberta_full/rpu_database.db`。
- [MEDIUM] `scripts/legacy/rpu_full_extraction_deberta.py:41`
  - 问题：输入 CSV 文件名固定为 `data/raw/2026外文论文.csv`。
- [MEDIUM] `scripts/legacy/rpu_full_extraction_deberta.py:49`
  - 问题：checkpoint 仍有 `_paths.get(..., fallback)` 历史 fallback。
- [MEDIUM] `scripts/legacy/inspect_opinion_meta.py:18`
- [MEDIUM] `scripts/legacy/inspect_opinion_meta.py:20`
  - 问题：内置历史目录回退（`output/v6_opinion` 与 `output_6_2_opinion_identification`）。

### P4-4（治理收口与文档同步）
- [MEDIUM] `docs/01_项目导读.md:35`
- [MEDIUM] `docs/01_项目导读.md:36`
- [MEDIUM] `docs/01_项目导读.md:38`
  - 问题：目录体量示例仍出现历史输出目录名（`impact_output/`、`innovation_v2_output/`、`paper_signals_output/`）。
- [MEDIUM] `docs/10_项目整理设计.md:41`
- [MEDIUM] `docs/10_项目整理设计.md:42`
- [MEDIUM] `docs/10_项目整理设计.md:46`
  - 问题：设计文档仍表述旧输出目录保持原位，需明确“历史方案”或补充现状注记。
- [MEDIUM] `docs/11_迁移说明.md:57`
  - 问题：仍写“`innovation_v2_output/`、`impact_output/` 保持原位”，与 P3 收口后现状不一致。
- [LOW] `docs/reference/TODO_execution_plan.md:304`
  - 问题：保留绝对路径 `cd D:\...`，建议改为相对路径示例并注明历史上下文。

## 建议新增配置键（用于下一批实施）
- `verb_innovation_weights_path`
- `innovation_log_path`
- `impact_log_path`
- `training_data_excel_path`
- `research_structure_model_dir`
- `phrase_table_path`
- `core_mapping_path`
- `legacy_temp_dir`
- `alignment_failed_samples_path`
- `legacy_temporal_db_path`

## 批次执行建议（按风险）
1. 先做 `P4-1`：修主链路高优先级路径与配置入口（不改算法逻辑）。
2. 再做 `P4-2`：统一训练链路配置语义，消除绝对路径与静默 fallback。
3. 然后做 `P4-3`：legacy 按“高频脚本优先”分两到三批迁移。
4. 最后做 `P4-4`：health_check 扫描规则与文档描述同步收口。
