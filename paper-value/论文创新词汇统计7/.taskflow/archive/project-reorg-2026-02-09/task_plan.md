# 全项目整理（先文档整理，再项目整理设计）

## 目标
先完成文档体系整理并形成统一项目认知，再基于文档共识设计代码与目录整理方案。

## 执行策略
- [x] D1 文档化理解：提炼项目导读、脚本地图、重构前基线
- [x] D2 文档体系补齐：快速开始、数据与产物、脚本指南、算法摘要、开发进度
- [x] D3 项目整理设计：基于文档输出结构改造方案（不立即迁移代码）
- [x] D4 结构整理实施：按确认方案分阶段执行

## 当前阶段（D4-S1：配置统一）
- [x] `README.md`（项目文档入口）
- [x] `docs/01_项目导读.md`
- [x] `docs/02_脚本地图.md`
- [x] `docs/03_重构前基线.md`
- [x] `docs/04_快速开始.md`
- [x] `docs/05_数据与产物.md`
- [x] `docs/06_脚本指南.md`
- [x] `docs/07_创新度算法.md`
- [x] `docs/08_影响力算法.md`
- [x] `docs/09_开发进度.md`
- [x] `docs/README.md`
- [x] `configs/paths.default.json`
- [x] `configs/runtime.default.json`
- [x] `project_config.py`（统一配置加载）
- [x] `tools/health_check.ps1`（环境与路径自检）
- [x] 主链路脚本接入 `--config`（run/impact/merge/query/analyze）

## D4 分阶段状态
- [x] S1 入口与配置统一（低风险）
- [x] S2 脚本分层迁移（中风险）
- [x] S3 收敛清理与兼容收尾（中风险）

## D3 设计输出（下一步）
- [x] 目标目录结构（代码/脚本/数据/文档分层）
- [x] 配置统一方案（路径、日志、年份、输出）
- [x] CLI 兼容策略（旧命令别名与迁移提示）
- [x] 分阶段迁移清单与回滚策略

## 风险
- 在未统一配置前直接迁移脚本，容易导致运行回归。
- 大体量数据目录不应参与首轮结构迁移。

## 验收
- 新接手者可通过文档在短时间内理解项目全貌。
- 重构设计基于文档事实，而非脚本猜测。

## 收口
- 收口清单：`.taskflow/active/project-reorg/CLOSEOUT.md`
- 后续任务：`.taskflow/active/project-reorg-phase2/task_plan.md`
