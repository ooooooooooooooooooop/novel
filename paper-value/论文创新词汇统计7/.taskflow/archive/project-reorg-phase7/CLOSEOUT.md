# CLOSEOUT - project-reorg-phase7

## 范围
- 阶段：Phase 7（compat 治理残留清理）
- 时间：2026-02-10
- 目标：移除已下线兼容入口的残留代码/配置表达，保持 canonical-only 主链路。

## 已完成
- 完成 `P7-1` ~ `P7-4` 全部任务。
- 删除 compat 残留代码：
  - `scripts/compat_launcher.py`
  - `tools/compat_usage_report.py`
  - `tools/compat_observation_snapshot.py`
- 清理配置残留：
  - `configs/paths.default.json` 移除 `compat_usage_log_path`
- 文档收口：
  - `scripts/train/README.md`
  - `scripts/legacy/README.md`
  - `docs/10_项目整理设计.md`
  - `docs/11_迁移说明.md`

## 关键提交
- `52c1b27` `chore: remove compat governance residuals and clean paths config`

## 验收结论
- `tools/health_check.ps1`：通过。
- canonical smoke 通过：
  - `python scripts/pipeline/run_v2_full.py --help`
  - `python scripts/pipeline/calculate_impact_v2.py --help`
  - `python scripts/pipeline/merge_signals.py --help`
  - `python scripts/query/query_paper.py --help`
  - `python scripts/analyze/analyze_distributions.py --help`
  - `python scripts/analyze/analyze_trends.py --help`

## 剩余风险
- `docs/11_迁移说明.md` 中保留了历史阶段记录（包含 compat 术语），属于历史追溯信息，不影响当前运行。

## 后续建议
- 当前主链路已完成 canonical-only 收口，后续可转入业务能力迭代。
