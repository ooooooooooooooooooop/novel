# CLOSEOUT - project-reorg-phase6

## 范围
- 阶段：Phase 6（关键兼容入口最终下线）
- 时间：2026-02-10
- 目标：完成 root 兼容入口下线，统一主链路到 canonical 路径。

## 已完成
- 完成 `P6-0` ~ `P6-5` 全部任务。
- 原计划 14/30 天观察窗口在执行初期由 owner 决策改为当天快切。
- 删除 4 个 root 兼容入口：
  - `run_v2_full.py`
  - `calculate_impact_v2.py`
  - `merge_signals.py`
  - `query_paper.py`
- 入口统一到 canonical：
  - `scripts/pipeline/run_v2_full.py`
  - `scripts/pipeline/calculate_impact_v2.py`
  - `scripts/pipeline/merge_signals.py`
  - `scripts/query/query_paper.py`
- `tools/health_check.ps1` 已切换为 canonical-only 门禁：
  - root 4 个入口必须不存在
  - root whitelist 同步移除 4 个入口文件
- 文档同步完成：
  - `README.md`
  - `docs/01_项目导读.md`
  - `docs/02_脚本地图.md`
  - `docs/04_快速开始.md`
  - `docs/06_脚本指南.md`
  - `docs/07_创新度算法.md`
  - `docs/08_影响力算法.md`
  - `docs/11_迁移说明.md`
  - `docs/12_提交建议.md`
  - `docs/13_提交执行清单.md`

## 关键提交
- `cea9b41` `chore: start phase6 with strict compatibility cutover controls`
- `ce91ff6` `chore: start phase6 observation window protocol`
- `dadf086` `chore: automate phase6 observation snapshots`
- `a35621b` `docs: add gate-a execution checklist for 2026-02-24`
- `ab8a083` `refactor: remove root launchers and enforce canonical-only entrypoints`

## 验收结论
- `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1`：通过。
- canonical smoke 通过：
  - `python scripts/pipeline/run_v2_full.py --help`
  - `python scripts/pipeline/calculate_impact_v2.py --help`
  - `python scripts/pipeline/merge_signals.py --help`
  - `python scripts/query/query_paper.py --help`
  - `python scripts/analyze/analyze_distributions.py --help`
  - `python scripts/analyze/analyze_trends.py --help`
- root 入口删除验证通过：
  - `python run_v2_full.py --help` 预期失败（文件不存在）

## 剩余风险
- `scripts/compat_launcher.py` 与观测工具仍保留但已不在主链路运行路径；后续可按需清理。
- 历史参考文档（`docs/reference/*`）保留旧命令痕迹，不影响当前运行。

## 后续建议
- 归档 `.taskflow/active/project-reorg-phase6` 到 `.taskflow/archive/project-reorg-phase6`。
- 如无兼容策略复用需求，下一阶段评估下线：
  - `scripts/compat_launcher.py`
  - `tools/compat_usage_report.py`
  - `tools/compat_observation_snapshot.py`
