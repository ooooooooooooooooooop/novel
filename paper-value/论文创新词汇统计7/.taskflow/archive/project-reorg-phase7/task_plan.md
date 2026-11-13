# 全项目整理 Phase 7（兼容治理残留清理）

## 目标
移除已下线 root 兼容入口的遗留治理代码与配置表达，收敛为 canonical-only 主链路。

## 变更列表
- [x] P7-1: 删除兼容治理代码
  - 范围：`scripts/compat_launcher.py`、`tools/compat_usage_report.py`、`tools/compat_observation_snapshot.py`
- [x] P7-2: 清理配置残留
  - 范围：`configs/paths.default.json` 中 `compat_usage_log_path`
- [x] P7-3: 同步文档表达
  - 范围：`scripts/*/README.md` 与核心文档中兼容入口现状描述
- [x] P7-4: 验证与收口
  - 门禁：`tools/health_check.ps1` + canonical smoke

## 验证清单
- `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1`
- `python scripts/pipeline/run_v2_full.py --help`
- `python scripts/pipeline/calculate_impact_v2.py --help`
- `python scripts/pipeline/merge_signals.py --help`
- `python scripts/query/query_paper.py --help`
- `python scripts/analyze/analyze_distributions.py --help`
- `python scripts/analyze/analyze_trends.py --help`

## 回退策略
- 若发现误删依赖：按提交粒度恢复 compat 文件与配置键。
