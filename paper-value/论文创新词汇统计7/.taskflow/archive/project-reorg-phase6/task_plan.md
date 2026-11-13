# 全项目整理 Phase 6（关键兼容入口最终下线窗口设计）

## 目标
对剩余 4 个根目录兼容入口完成最终下线，统一主链路到 `scripts/` canonical 路径。

## 批次策略
- 数据驱动：以 `compat_launcher_usage.jsonl` 为准。
- 先可控切换：支持全局与定向阻断，再决定删除。
- 每批可验证、可回退、独立提交。

## 变更列表
- [x] P6-0: 基线快照
  - 范围：兼容入口观测日志与报表
  - 结果：真实业务调用样本暂缺（默认排除 `--help` 后无记录），当前以观察窗口继续采样
- [x] P6-1: 策略化下线开关
  - 范围：`scripts/compat_launcher.py`、`tools/compat_usage_report.py`
  - 结果：支持 `PROJECT_COMPAT_MODE=error`（全量阻断）与 `PROJECT_COMPAT_BLOCKLIST`（定向阻断），日志新增 `mode/blocked/block_reason`
- [x] P6-2: 运行手册与切换流程
  - 范围：`README.md`、`docs/06_脚本指南.md`、`docs/11_迁移说明.md`
  - 结果：已补充灰度顺序（单入口 -> 全量）与回退方式
- [x] P6-3: 观察窗口执行（快速决策结束）
  - 结果：项目 owner 决策不采用 14/30 天观察窗口，改为当天快切。
- [x] P6-4: 关键兼容入口最终下线
  - 范围：`run_v2_full.py`、`calculate_impact_v2.py`、`merge_signals.py`、`query_paper.py`
  - 结果：4 个 root 兼容入口已删除，文档与 `health_check` 已同步到 canonical-only。
- [x] P6-5: 治理收口与归档
  - 目标：冻结规则并归档 phase6
  - 结果：Phase6 active 文档完成收口，后续可直接归档。

## 每批门禁（执行后必做）
- `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1` 通过。
- smoke：
  - `python scripts/pipeline/run_v2_full.py --help`
  - `python scripts/pipeline/calculate_impact_v2.py --help`
  - `python scripts/pipeline/merge_signals.py --help`
  - `python scripts/query/query_paper.py --help`
  - `scripts/analyze/analyze_distributions.py --help`
  - `scripts/analyze/analyze_trends.py --help`

## 回退策略
- 代码回退：恢复 4 个 root 入口文件并回退本批文档改动。
