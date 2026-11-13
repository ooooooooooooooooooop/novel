# 全项目整理 Phase 5（legacy 兼容入口下线策略）

## 目标
在不破坏主链路使用习惯的前提下，建立兼容入口下线路径：先统一弃用告警与迁移指引，再按调用频次分批下线低频入口。

## 批次策略
- 先告警、后下线。
- 先低频、后高频。
- 每批可验证、可回退、独立提交。

## 变更列表
- [x] P5-0: 兼容入口基线盘点
  - 范围：根目录主入口、`scripts/*` canonical 入口、文档迁移口径
  - 产出：`p5-0-baseline.md`
- [x] P5-1: 下线清单与观察点建立
  - 结果：确认根目录仅剩 6 个主链路兼容入口，当前无“可直接下线”的低频根入口
- [x] P5-2: 兼容入口统一弃用告警
  - 范围：`run_v2_full.py`、`calculate_impact_v2.py`、`merge_signals.py`、`query_paper.py`、`analyze_distributions.py`、`analyze_trends.py`
  - 结果：新增统一弃用告警，提示 canonical 路径；支持 `PROJECT_COMPAT_SILENCE_WARN=1` 静默
- [x] P5-3: 调用观测机制落地
  - 范围：根目录 6 个兼容入口 + `scripts/compat_launcher.py`
  - 结果：兼容入口调用写入 `paths.compat_usage_log_path`；支持 `PROJECT_COMPAT_USAGE_LOG_PATH` 覆盖
- [x] P5-4: 基于观测的低频兼容入口下线（首批）
  - 范围：根目录分析兼容入口（`analyze_distributions.py`、`analyze_trends.py`）
  - 结果：已删除 2 个低风险根入口，分析命令统一到 `scripts/analyze/*` canonical 路径
- [x] P5-5: 治理收口与规则收紧
  - 结果：`health_check`、主入口 smoke 与文档入口口径已收敛到“4 个根目录兼容入口 + 2 个 canonical 分析入口”

## 每批门禁（执行后必做）
- `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1` 通过。
- 主入口 smoke：`run_v2_full.py --help`、`calculate_impact_v2.py --help`、`merge_signals.py --help`、`query_paper.py --help`、`scripts/analyze/analyze_distributions.py --help`、`scripts/analyze/analyze_trends.py --help`。

## 回退策略
- 告警仅提示不改变业务逻辑；回归时可单批回退 wrapper 告警改动。
- 入口下线前必须先完成至少一个周期的告警观察。
