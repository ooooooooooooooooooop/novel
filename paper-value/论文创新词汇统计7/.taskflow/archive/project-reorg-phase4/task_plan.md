# 全项目整理 Phase 4（硬编码路径与历史配置表达清理）

## 目标
在保持主链路稳定可运行的前提下，清理硬编码路径，统一历史配置表达到 `project_config` 与 `configs/paths.default.json`，并以分批方式推进 legacy 改造。

## 批次策略
- 主链路优先，legacy 渐进。
- 每批可验证、可回退、独立提交。

## 变更列表
- [x] P4-0: 基线盘点（硬编码与历史配置表达）
  - 范围：`scripts/pipeline`、`scripts/query`、`scripts/analyze`、`scripts/train`、`scripts/legacy`、`docs/*`
  - 产出：分类清单（main/train/legacy）、迁移优先级、影响面标记（见 `p4-0-baseline.md`）
- [x] P4-1: 主链路硬编码清理
  - 范围：`scripts/pipeline`、`scripts/query`、`scripts/analyze` 与 6 个主入口
  - 动作：移除路径常量/拼接字面量，统一经 `project_config` 读取
  - 结果：`calculate_innovation` 默认输入路径、动词权重路径、日志路径完成配置化；`calculate_impact_v2` 日志路径完成配置化；`merge_signals` 文档注释同步
- [x] P4-2: 训练链路配置语义对齐
  - 范围：`scripts/train/*` 与 DeBERTa 相关脚本
  - 动作：统一模型目录、标签目录、输出目录键；收敛历史 fallback
  - 结果：`train_research_structure_extractor` 接入 `project_config` 并移除绝对路径；`train_deberta_multihead` 改为缺少路径键即显式报错
- [x] P4-3: legacy 脚本渐进改造
  - 范围：`scripts/legacy/*`（高频优先）
  - 动作：分批替换硬编码，保留必要兼容入口
  - 当前进展：首批已完成 `convert_rpu_to_spans.py`、`mine_phrases.py`、`apply_abstract_layer.py`；第二批已完成 `normalize_cores.py`、`calculate_impact_v2_lowmem.py`、`calculate_impact_v2_optimized.py`；第三批已完成 `supplement_paper_metadata.py`、`rpu_full_extraction.py`、`rpu_full_extraction_deberta.py`、`inspect_opinion_meta.py`
  - 结果：legacy 高频路径键统一到 `project_config` + `configs/paths.default.json`，并补齐 opinion meta LMDB 主备路径解析
- [x] P4-4: 治理收口与文档同步
  - 范围：`tools/health_check.ps1`、`docs/06_脚本指南.md`、`docs/11_迁移说明.md`
  - 动作：新增硬编码路径扫描并分级（scripts 失败、docs 告警）、同步迁移规范与示例
  - 结果：`health_check` 新增 Hardcoded Path Scan（scripts fail-fast + docs warn-only）；文档已同步 Phase 4 配置化增量与迁移约束，当前 scripts/docs 硬编码命中均为 0

## 每批门禁（执行后必做）
- `python -m py_compile` 覆盖本批改动脚本。
- `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1` 通过，且无 scripts 硬编码命中、无新增主链路告警。
- 主入口 smoke：`run_v2_full.py --help`、`calculate_impact_v2.py --help`、`merge_signals.py --help`、`query_paper.py --help`、`analyze_distributions.py --help`、`analyze_trends.py --help`。
- 最小链路实跑（按批次受影响入口执行 1 条最小命令）。

## 回退策略
- 批次独立提交（建议 `P4-1` ~ `P4-4` 分开提交）。
- 出现回归时仅回退当前批次提交，不跨批次回滚。
- legacy 兼容入口默认保留，待下线窗口确认后再移除。

## 风险
- 路径抽象不一致可能导致读写目录漂移。
- 扫描规则过严可能产生误报，需先告警后收紧。
- legacy 脚本调用面不完整会遗漏隐性依赖。

## 完成定义
- 主链路脚本无硬编码路径表达。
- 训练链路与 legacy 高频脚本完成配置化改造。
- health_check 与文档规则与实际实现一致。
