# progress

- 2026-02-10: 初始化 `project-reorg-phase7`，目标为 compat 治理残留清理并收敛到 canonical-only。
- 2026-02-10: 完成影响面盘点：compat 代码残留位于 `scripts/compat_launcher.py` 与 `tools/compat_*`，配置残留位于 `configs/paths.default.json` 的 `compat_usage_log_path`。
- 2026-02-10: 删除 compat 残留代码：`scripts/compat_launcher.py`、`tools/compat_usage_report.py`、`tools/compat_observation_snapshot.py`。
- 2026-02-10: 清理配置残留：`configs/paths.default.json` 移除 `compat_usage_log_path`。
- 2026-02-10: 文档同步：`scripts/train/README.md`、`scripts/legacy/README.md`、`docs/10_项目整理设计.md`、`docs/11_迁移说明.md` 更新为 canonical-only 现状表达。
- 2026-02-10: 验证通过：`tools/health_check.ps1` 与 6 个 canonical 入口 `--help` smoke 全部通过。
