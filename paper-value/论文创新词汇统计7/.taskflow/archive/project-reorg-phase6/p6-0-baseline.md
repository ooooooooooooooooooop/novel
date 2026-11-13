# P6-0 Baseline - Critical Compatibility Launcher Cutover

## 当前兼容入口范围

- `run_v2_full.py`
- `calculate_impact_v2.py`
- `merge_signals.py`
- `query_paper.py`

## 观测快照（2026-02-10）

- 命令：`python tools/compat_usage_report.py --days 30 --min-calls 3`
  - 结果：默认排除 `--help/-h` 后，当前窗口内无记录（暂无真实业务调用样本）。
- 命令：`python tools/compat_usage_report.py --days 30 --min-calls 3 --include-help`
  - 结果：当前样本主要来自 smoke/验证调用。
  - 计数（含 `--help`）：
    - `run_v2_full.py`: 5
    - `calculate_impact_v2.py`: 5
    - `merge_signals.py`: 5
    - `query_paper.py`: 5

## 结论

- 关键入口下线前仍需真实观察窗口（建议 14 天起）。
- P6 优先执行策略化切换能力（warn/error + blocklist），再按窗口数据落地最终删除。
