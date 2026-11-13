# progress

- 2026-02-10: 初始化 `project-reorg-phase5` active 目录并建立 `task_plan.md`。
- 2026-02-10: 完成 `P5-0/P5-1` 基线盘点：根目录仅剩 6 个主链路兼容入口，当前无低频根入口可直接下线。
- 2026-02-10: 执行 `P5-2`：为 6 个根目录兼容入口新增统一弃用告警与 canonical 路径提示，支持 `PROJECT_COMPAT_SILENCE_WARN=1` 静默。
- 2026-02-10: 同步文档兼容入口口径，补充弃用告警行为与迁移方式。
- 2026-02-10: 验证通过：`python -m py_compile`（6 个根目录兼容入口）通过。
- 2026-02-10: 验证通过：`tools/health_check.ps1`、6 个主入口 `--help` smoke 均通过。
- 2026-02-10: 执行 `P5-3`：抽取 `scripts/compat_launcher.py`，统一兼容入口告警与调用观测写入。
- 2026-02-10: 配套：`configs/paths.default.json` 新增 `compat_usage_log_path`，并支持 `PROJECT_COMPAT_USAGE_LOG_PATH` 覆盖。
- 2026-02-10: 文档同步：`README.md`、`docs/06_脚本指南.md`、`docs/11_迁移说明.md` 补充调用观测与环境变量说明。
- 2026-02-10: `P5-3` 验证通过：`python -m py_compile`（wrapper + `scripts/compat_launcher.py`）、`tools/health_check.ps1`、6 个主入口 `--help` smoke 全部通过。
- 2026-02-10: 观测写入验证：`compat_launcher_usage.jsonl` 行数从 0 增至 6，字段包含 `launcher/canonical/argv/timestamp_utc/cwd/python`。
- 2026-02-10: `P5-4` 准备：新增 `tools/compat_usage_report.py`，支持按窗口输出兼容入口调用聚合与低频候选建议（可选 JSON 导出）。
- 2026-02-10: 观测分析规则更新：`compat_usage_report.py` 默认排除 `--help/-h` 调用，避免 smoke 测试噪声干扰下线判断。
- 2026-02-10: `P5-4` 首批实施：下线根目录低频分析兼容入口 `analyze_distributions.py`、`analyze_trends.py`，统一迁移至 `scripts/analyze/*` canonical 路径。
- 2026-02-10: `P5-4` 配套：`tools/health_check.ps1` CLI smoke 与 root whitelist 调整为 4 个根目录兼容入口。
- 2026-02-10: `P5-4` 文档同步：`README.md`、`docs/01_项目导读.md`、`docs/02_脚本地图.md`、`docs/04_快速开始.md`、`docs/06_脚本指南.md`、`docs/11_迁移说明.md`、`docs/12_提交建议.md`、`docs/13_提交执行清单.md`。
- 2026-02-10: `P5-5` 收口：规则统一为“4 个根目录兼容入口 + 2 个 canonical 分析入口”，并完成 `task_plan/progress` 口径收敛。
