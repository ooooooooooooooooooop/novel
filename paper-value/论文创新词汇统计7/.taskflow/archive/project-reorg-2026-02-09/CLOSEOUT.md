# Closeout Checklist (project-reorg)

## 1. 提交与标签
- [ ] 按 `docs/12_提交建议.md` 完成分批提交
- [ ] 执行 `git status --short` 确认工作区干净
- [ ] 可选：打标签 `reorg-d4-complete`

## 2. 回归检查
- [x] `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1`
- [x] `python run_v2_full.py --dry-run --years 2010-2010`
- [x] `python scripts/pipeline/run_v2_full.py --dry-run --years 2010-2010`

## 3. 迁移结果确认
- [x] 主入口已在 `scripts/pipeline|query|analyze`
- [x] legacy 脚本已在 `scripts/legacy/`
- [x] 根目录脚本仅保留兼容启动器

## 4. 归档建议
- [x] 完成后将 `project-reorg` 移动到 `.taskflow/archive/`

备注：
- 当前 `git status --short` 仍有未提交变更（taskflow/phase2 与 closeout 文档），待你提交后可打标签。
