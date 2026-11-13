# progress

- 2026-02-09: 启动 unified-taskflow（Standard 模式）。
- 2026-02-09: 完成项目扫描与现状盘点（34 根脚本、输出目录体量、已有未提交改动）。
- 2026-02-09: 根据用户澄清，优先“文档整理”，暂不做代码结构迁移。
- 2026-02-09: 完成 D1 文档：`docs/01_项目导读.md`、`docs/02_脚本地图.md`、`docs/03_重构前基线.md`。
- 2026-02-09: 完成 D2 文档：`README.md`、`docs/04_快速开始.md`、`docs/05_数据与产物.md`、`docs/06_脚本指南.md`、`docs/07_创新度算法.md`、`docs/08_影响力算法.md`、`docs/09_开发进度.md`、`docs/README.md`。
- 2026-02-09: 完成 D3 设计：`docs/10_项目整理设计.md`（目标结构、配置统一、CLI兼容、分阶段迁移、回滚策略）。
- 2026-02-09: 完成 D4-S1：新增 `project_config.py`、`configs/paths.default.json`、`configs/runtime.default.json`。
- 2026-02-09: 主链路脚本接入配置统一与 `--config` 参数：`run_v2_full.py`、`calculate_impact_v2.py`、`merge_signals.py`、`query_paper.py`、`analyze_distributions.py`、`analyze_trends.py`。
- 2026-02-09: 新增 `tools/health_check.ps1` 并完成本机验证（通过）。
- 2026-02-09: 完成 D4-S2：主链路脚本迁移到 `scripts/pipeline|query|analyze`，根目录保留兼容启动器。
- 2026-02-09: 验证通过：旧入口/新入口 `--help` 与 `run_v2_full --dry-run` 均可运行，`tools/health_check.ps1` 通过。
- 2026-02-09: 完成 D4-S3：将 `calculate_impact_v2_lowmem.py`、`calculate_impact_v2_optimized.py` 收敛到 `scripts/legacy/`，根目录保留兼容启动器。
- 2026-02-09: 新增 `scripts/legacy/README.md`，明确默认实现与 legacy 边界。
- 2026-02-09: 更新 `tools/health_check.ps1` 覆盖 legacy 入口检查，验证通过。
- 2026-02-09: 完成收尾文档：`docs/11_迁移说明.md`、`docs/12_提交建议.md`，并将 D4 标记完成。
- 2026-02-09: 扩展非主链路配置统一：`check_emerging_topic_scores.py`、`check_landmark_paper_scores.py`、`validate_impact_v2.py` 接入 `project_config` 与 `--config`。
- 2026-02-09: 语法检查与 `--help` 验证通过；`validate_impact_v2.py --year 2025` 在当前数据规模下长时间运行（超时），需离线长跑验证。
