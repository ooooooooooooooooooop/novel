# 论文价值信号系统

> 面向 2010-2025 年论文的大规模价值信号计算系统（创新度 + 影响力）

## 项目目标

- 计算 `innovation_score`：论文在发表时点的创新性
- 计算 `impact_score`：论文发表后被后续研究采纳的影响力
- 基于年度阈值生成四类角色：`Pioneer` / `Ahead-of-time` / `Diffuser` / `Routine`

## 文档入口

- 项目导读：`docs/01_项目导读.md`
- 脚本地图：`docs/02_脚本地图.md`
- 重构前基线：`docs/03_重构前基线.md`
- 快速开始：`docs/04_快速开始.md`
- 数据与产物：`docs/05_数据与产物.md`
- 脚本指南：`docs/06_脚本指南.md`
- 创新度算法：`docs/07_创新度算法.md`
- 影响力算法：`docs/08_影响力算法.md`
- 开发进度：`docs/09_开发进度.md`
- 项目整理设计：`docs/10_项目整理设计.md`
- 迁移说明：`docs/11_迁移说明.md`

## 核心设计文档（原始）

- `docs/reference/INNOVATION_V2_DESIGN.md`
- `docs/reference/IMPACT_V2_DESIGN.md`
- `docs/reference/TODO_execution_plan.md`
- `docs/reference/CONFIG_SYSTEM_README.md`

## 当前策略

当前优先进行文档整理与项目理解；代码结构重构在文档共识后单独设计并执行。

## 入口约定（当前）

- `scripts/` 下脚本为 canonical 实现入口。
- 主链路入口统一为：
  - `scripts/pipeline/run_v2_full.py`
  - `scripts/pipeline/calculate_impact_v2.py`
  - `scripts/pipeline/merge_signals.py`
  - `scripts/query/query_paper.py`
  - `scripts/analyze/analyze_distributions.py`
  - `scripts/analyze/analyze_trends.py`
- 根目录已不再保留运行入口脚本（兼容启动器已下线）。
- 环境与入口检查：`tools/health_check.ps1`
