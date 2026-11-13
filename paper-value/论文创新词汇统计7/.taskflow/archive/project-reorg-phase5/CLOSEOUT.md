# CLOSEOUT - project-reorg-phase5

## 范围
- 阶段：Phase 5（legacy 兼容入口下线策略）
- 时间：2026-02-10
- 目标：建立“先告警、后下线”的兼容入口治理链路，并完成首批低频入口下线。

## 已完成
- 完成 `P5-0` ~ `P5-5` 全部任务。
- 根目录兼容入口统一弃用告警，支持 `PROJECT_COMPAT_SILENCE_WARN=1` 静默。
- 兼容入口调用观测落地：
  - 统一入口：`scripts/compat_launcher.py`
  - 日志路径：`paths.compat_usage_log_path`
  - 覆盖变量：`PROJECT_COMPAT_USAGE_LOG_PATH`
- 观测分析工具落地：`tools/compat_usage_report.py`
  - 默认排除 `--help/-h` 噪声
  - 支持窗口统计、低频候选判断、JSON 导出
- 首批低频入口下线完成：
  - 删除根目录：`analyze_distributions.py`、`analyze_trends.py`
  - 分析入口统一到：`scripts/analyze/*`
- 规则收口完成：
  - 根目录兼容入口：4 个（`run_v2_full.py`、`calculate_impact_v2.py`、`merge_signals.py`、`query_paper.py`）
  - 分析入口：2 个 canonical（`scripts/analyze/analyze_distributions.py`、`scripts/analyze/analyze_trends.py`）

## 关键提交
- `674bb1a` `chore: start phase5 with compatibility deprecation warnings`
- `30a13ee` `chore: add compat launcher usage telemetry for phase5`
- `fae4c55` `chore: add compatibility usage reporting for phase5 deprecation`
- `12ca58e` `refactor: remove low-frequency root analyze compatibility launchers`

## 验收结论
- `tools/health_check.ps1`：通过（包含 root whitelist、canonical script、hardcoded path scan）。
- smoke 通过：
  - 根目录：`run_v2_full.py --help`、`calculate_impact_v2.py --help`、`merge_signals.py --help`、`query_paper.py --help`
  - canonical：`scripts/analyze/analyze_distributions.py --help`、`scripts/analyze/analyze_trends.py --help`
- 观测写入验证通过：`compat_launcher_usage.jsonl` 可持续记录 `launcher/canonical/argv/timestamp_utc/cwd/python`。

## 剩余风险
- 关键主链路 4 个兼容入口仍保留，后续下线需要更长观察窗口。
- 历史参考文档中仍可能保留旧入口示例（不影响运行，但需持续维护）。

## 下一阶段建议（P6）
- 主题：关键兼容入口最终下线窗口设计。
- 原则：数据驱动、分批下线、可回退。
- 建议动作：
  - 建立观测窗口阈值（例如 14/30 天）
  - 对 4 个关键兼容入口分批下线或改为“硬失败 + 明确迁移提示”
  - 收口文档中的 legacy/兼容表述并冻结治理规则
