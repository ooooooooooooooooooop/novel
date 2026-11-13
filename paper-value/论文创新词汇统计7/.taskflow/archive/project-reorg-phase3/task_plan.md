# 全项目整理 Phase 3（根目录硬收口）

## 目标
在保持兼容命令可用的前提下，进一步降低根目录混杂度，建立可执行的根目录白名单治理。

## 变更列表
- [x] P3-1: 建立 Phase3 任务与白名单规则
- [x] P3-2: 低风险根目录去杂乱（非运行时文档下沉）
- [x] P3-3: `tools/health_check.ps1` 增加 Root Whitelist 检查
- [x] P3-4: 文档同步（README + docs 索引）
- [x] P3-5: 清理 Root Whitelist 告警文件（log/jsonl/nul）
- [x] P3-6: 非入口公共模块迁入 `src/innovation_core`（并修正导入）
- [x] P3-7: legacy 数据处理脚本下沉到 `scripts/legacy`（保留根目录兼容入口）
- [x] P3-8: health_check 同步新增脚本映射检查（CLI + canonical）
- [x] P3-9: `calculate_innovation.py` 下沉到 `scripts/pipeline`（保留兼容入口）
- [x] P3-10: `infer_single_paper_deberta.py` 下沉到 `scripts/query`（保留兼容入口）
- [x] P3-11: 根目录兼容入口硬收口（仅保留主链路 6 个入口 + project_config）
- [x] P3-12: 重复/历史目录下沉到 `artifacts/`（并新增根目录目录白名单检查）
- [x] P3-13: 运行产物目录统一迁移到 `artifacts/runtime/*`（配置/脚本/文档同步）
- [x] P3-14: 根目录最终收口（移除 `reports/`、迁移 `output_7_deberta`、归档 `_archived_srl_ner_pipeline`）

## 风险
- 误迁移运行时依赖文件可能导致脚本失败。
- 白名单过严会误报，需先以可视化检查为主。

## 验收
- 根目录非入口文档明显减少。
- health_check 能输出根目录白名单检查结果。
- README 与实际文件位置一致。
