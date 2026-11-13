# Closeout Checklist (project-reorg-phase2)

## 1. 阶段结论
- [x] P2-1: legacy validation 脚本接入 `project_config` 与 `--config`
- [x] P2-2: validation 根目录兼容启动器补齐
- [x] P2-3: `tools/health_check.ps1` 增加 validation 入口检查
- [x] P2-4: 根目录脚本继续分层收口（legacy/query/train）
- [x] P2-5: 文档增量更新（`README.md`、`docs/06_脚本指南.md`、`docs/11_迁移说明.md`）

## 2. 回归检查
- [x] `python -m py_compile`（本阶段迁移/启动器相关脚本）
- [x] `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1`

## 3. 结果确认
- [x] 根目录 legacy/query/train/validation 相关脚本均保留兼容启动器
- [x] canonical 实现已分层到 `scripts/pipeline|query|analyze|legacy|train`
- [x] `docs/11_迁移说明.md` 已补齐 Phase 2 增量说明

## 4. 待提交动作（手工）
- [ ] 按主题分批提交（建议：P2-1~P2-3，P2-4，P2-5）
- [ ] `git status --short` 确认工作区符合预期
- [ ] 可选：完成后归档到 `.taskflow/archive/project-reorg-phase2-2026-02-09/`

备注：
- 当前工作区包含 Phase 2 全量改动，尚未提交。
