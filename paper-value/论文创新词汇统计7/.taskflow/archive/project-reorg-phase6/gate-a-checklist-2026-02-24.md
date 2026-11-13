# Gate A Checklist - 2026-02-24 (14d)

## 执行日期

- 计划执行日：2026-02-24（UTC）
- 观察窗口起点：2026-02-10（UTC）
- 目标：对 4 个关键 root 兼容入口执行首轮 14 天门槛判定与定向阻断灰度。

## 预检

1. 确认工作区干净：
   - `git status --short`
2. 生成最新观察快照：
   - `python tools/compat_observation_snapshot.py --days 14,30 --min-calls 1`
3. 生成 14 天机读报告（可复核）：
   - `python tools/compat_usage_report.py --days 14 --min-calls 1 --json-output artifacts/runtime/logs/observation/gate_a_14d_20260224.json`

## 14 天门槛判定（不含 --help）

待判定入口：
- `run_v2_full.py`
- `calculate_impact_v2.py`
- `merge_signals.py`
- `query_paper.py`

判定规则：
- `count == 0`：进入 Gate A 候选（可执行定向阻断灰度）
- `count > 0`：继续观察，不做阻断

执行记录（人工填写）：

| Launcher | 14d count | Gate A Candidate | Blocklist Trial Done | Trial Result |
|---|---:|---|---|---|
| `run_v2_full.py` |  |  |  |  |
| `calculate_impact_v2.py` |  |  |  |  |
| `merge_signals.py` |  |  |  |  |
| `query_paper.py` |  |  |  |  |

## 定向阻断灰度（仅对候选入口）

以 `query_paper.py` 为例（其余入口同理）：

```powershell
$env:PROJECT_COMPAT_BLOCKLIST='query_paper.py'
python query_paper.py --help
# 预期退出码：2

python scripts/query/query_paper.py --help
# 预期退出码：0（canonical 不受影响）
```

灰度结束后回退：

```powershell
Remove-Item Env:PROJECT_COMPAT_BLOCKLIST -ErrorAction SilentlyContinue
```

## 验证门禁

1. `powershell -ExecutionPolicy Bypass -File tools/health_check.ps1`
2. smoke：
   - `python run_v2_full.py --help`
   - `python calculate_impact_v2.py --help`
   - `python merge_signals.py --help`
   - `python query_paper.py --help`
   - `python scripts/analyze/analyze_distributions.py --help`
   - `python scripts/analyze/analyze_trends.py --help`

## 结论输出

1. 产出 Gate A 结果摘要（建议写入 `progress.md`）。
2. 若存在候选入口且灰度成功：
   - 进入 `P6-4` 准备批次（30 天窗口前仅保留策略阻断，不做物理删除）。
3. 若无候选入口：
   - 保持 `warn` 模式，继续观察到 30 天窗口（2026-03-12）。
