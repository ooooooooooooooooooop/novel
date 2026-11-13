# CLOSEOUT - project-reorg-phase4

## 范围
- 阶段：Phase 4（硬编码路径与历史配置表达清理）
- 时间：2026-02-10
- 目标：主链路优先完成配置化，legacy 渐进改造，并建立可执行的硬编码治理门禁。

## 已完成
- 完成 `P4-0` ~ `P4-4` 全部任务。
- 主链路与训练链路路径统一经 `project_config` + `configs/paths.default.json` 读取。
- legacy 高频脚本完成三批配置化改造，移除高风险硬编码路径依赖。
- `tools/health_check.ps1` 新增 Hardcoded Path Scan：
  - `scripts/` 命中即失败（fail-fast）
  - `docs/` 命中告警（warn-only）
- 文档路径表达已收敛，当前 `scripts/docs` 扫描命中均为 0。

## 验收结论
- `python -m py_compile`：第三批 legacy 脚本通过。
- `tools/health_check.ps1`：通过（exit code `0`），并显示：
  - `scripts hardcoded-path scan clean`
  - `docs hardcoded-path scan clean`
- 主入口 smoke（`--help`）通过：
  - `run_v2_full.py`
  - `calculate_impact_v2.py`
  - `merge_signals.py`
  - `query_paper.py`
  - `analyze_distributions.py`
  - `analyze_trends.py`

## 关键产物
- 配置键增量：`configs/paths.default.json`
- 主链路改造：`scripts/pipeline/*`
- 训练链路改造：`scripts/train/*`
- legacy 三批改造：`scripts/legacy/*`
- 治理与文档收口：`tools/health_check.ps1`、`docs/*`
- 过程记录：`task_plan.md`、`progress.md`、`p4-0-baseline.md`

## 剩余风险
- 仍有低频 legacy 脚本可继续做一致性清理（非主链路，不阻断）。
- 后续若引入新脚本，需保持 `project_config` 路径语义一致，避免绕过门禁。

## 下一阶段建议（P5）
- 主题：legacy 兼容入口下线策略。
- 原则：先告警、后下线；先低频、后高频；每批可验证可回退。
- 建议分批：
  - `P5-1` 建立下线清单与调用观察点（脚本/文档/调用方）
  - `P5-2` 在兼容入口增加统一弃用告警文案与迁移指引
  - `P5-3` 移除低频兼容入口并补齐回归验证
  - `P5-4` 收口文档与健康检查规则