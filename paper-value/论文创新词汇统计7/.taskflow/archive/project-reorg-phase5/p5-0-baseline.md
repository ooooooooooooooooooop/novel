# P5-0 Baseline - Compatibility Entry Inventory

## 根目录兼容入口（当前）

| Root launcher | Canonical target | 频次判断 | P5 处理 |
|---|---|---|---|
| `run_v2_full.py` | `scripts/pipeline/run_v2_full.py` | 高频（主链路） | 保留，先加弃用告警 |
| `calculate_impact_v2.py` | `scripts/pipeline/calculate_impact_v2.py` | 高频（主链路） | 保留，先加弃用告警 |
| `merge_signals.py` | `scripts/pipeline/merge_signals.py` | 高频（主链路） | 保留，先加弃用告警 |
| `query_paper.py` | `scripts/query/query_paper.py` | 高频（主链路） | 保留，先加弃用告警 |
| `analyze_distributions.py` | `scripts/analyze/analyze_distributions.py` | 高频（主链路） | 保留，先加弃用告警 |
| `analyze_trends.py` | `scripts/analyze/analyze_trends.py` | 高频（主链路） | 保留，先加弃用告警 |

## 结论

- 当前根目录不存在低频兼容入口，`P5-3` 暂不执行实删。
- 本轮先完成 `P5-2`，统一迁移提示与静默开关，降低未来下线成本。

## P5-4 更新（2026-02-10）

- 根目录低频分析兼容入口 `analyze_distributions.py`、`analyze_trends.py` 已完成首批下线。
- 当前根目录兼容入口保留 4 个：`run_v2_full.py`、`calculate_impact_v2.py`、`merge_signals.py`、`query_paper.py`。
