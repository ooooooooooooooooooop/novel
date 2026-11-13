# CLOSEOUT - project-reorg-phase3

## 范围
- 阶段：Phase 3（根目录硬收口）
- 时间：2026-02-09 ~ 2026-02-10
- 目标：在保持主链路可运行的前提下，显著降低根目录混杂度，建立白名单治理。

## 已完成
- 完成 P3-1 ~ P3-14 全部任务。
- 根目录脚本收口为 6 个主链路入口 + `project_config.py`。
- 运行产物统一到 `artifacts/runtime/*`。
- 重复/历史目录下沉到 `artifacts/legacy_outputs/*` 与 `artifacts/archives/*`。
- `src/innovation_core` 抽离完成并接入主链路。
- `tools/health_check.ps1` 增强为：
  - CLI/canonical 映射检查
  - Root File Whitelist 检查
  - Root Directory Whitelist 检查

## 关键提交
- `6a9d09d` `chore(reorg-phase3): enforce root whitelist and sink reference artifacts`
- `1421677` `refactor(reorg-phase3): move innovation core modules to src and finalize root cleanup`
- `e139276` `refactor(reorg-phase3): sink legacy extraction utilities and preserve root compatibility`
- `2a4e960` `refactor(reorg-phase3): sink innovation/query core scripts and keep import-compatible wrappers`
- `a400a62` `refactor(reorg-phase3): hard-prune root and sink duplicate output dirs`
- `7ef586c` `refactor(reorg-phase3): consolidate runtime outputs under artifacts/runtime`
- `26aff8c` `refactor(reorg-phase3): finalize root cleanup and archive legacy pipeline`

## 验收结论
- `tools/health_check.ps1`：通过。
- 主入口 smoke（`--help`）：
  - `run_v2_full.py`
  - `calculate_impact_v2.py`
  - `merge_signals.py`
  - `query_paper.py`
  - `analyze_distributions.py`
  - `analyze_trends.py`

## 当前结构状态
- 根目录保留核心代码/配置/数据入口目录，历史与运行产物已分层。
- 大体量核心数据库仍保留原位：`output_7_deberta_full/`。
- DeBERTa 训练产物路径已统一为 `models/deberta/`（并在 `.gitignore` 忽略）。

## 剩余风险
- legacy/anomaly 文档中仍有少量历史路径示例（不影响主链路运行）。
- 部分 legacy 脚本仍存在硬编码风格，建议在下一阶段逐步配置化。

## 下一阶段建议（P4）
- 主题：硬编码路径与历史配置表达清理。
- 原则：主链路优先、legacy 渐进、每批可验证可回退。
- 目标：主链路硬编码路径清零，历史配置表达统一到 `project_config` 与 `configs/paths.default.json`。
- 建议分批：
  - `P4-1` 主链路脚本清理：覆盖 `scripts/pipeline`、`scripts/query`、`scripts/analyze` 与 6 个主入口，移除硬编码路径，统一走配置读取。
  - `P4-2` 训练链路对齐：覆盖 `scripts/train` 与 DeBERTa 相关脚本，统一模型/标签/输出路径语义，收敛历史 fallback。
  - `P4-3` legacy 渐进改造：覆盖 `scripts/legacy` 高频脚本，按“高频优先、低频后置”迁移，保留必要兼容层。
  - `P4-4` 治理收口：补齐 `docs/06_脚本指南.md`、`docs/11_迁移说明.md`，并在 `tools/health_check.ps1` 增加硬编码路径扫描（告警级）。
- 每批验收：`python -m py_compile` 覆盖变更脚本；`tools/health_check.ps1` 通过且无新增主链路告警；主入口 smoke（`--help`）与最小链路实跑通过。
- 回退策略：按批次独立提交（`P4-1`~`P4-4`）；回归时仅回退当前批次；legacy 默认保留兼容入口直至明确下线窗口。
