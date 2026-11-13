# 校验点记录

## Trace Stub

**目标**：新增 `V6 主分切换评估` 工具，给出候选通道切换是否就绪的可复现报告。

**当前假设**：基于现有 `impact_v6_final_*.jsonl` 即可完成切换评估，无需重跑上游计算。

**已排除**：
- “必须先改主流程主分再评估”这一假设（先评估再切换更可控）。

---

## 校验点日志

### [2026-02-25 任务启动] 新任务创建

**anchor 摘要**: 不改默认主分，先落地主分切换评估工具与门禁报告。

---

#### [执行中] 读取现状并确定改动点

已完成：
- 复核 `impact-v6-remediation` 任务闭环状态与门禁产物。
- 复核 `validate_impact_v6.py` 的 score-field 与 gate 机制，确定新增独立评估脚本最小侵入。

下一步：
- 新增 `evaluate_primary_channel_switch.py` 并完成最小样本冒烟。
- 同步文档入口与本 checkpoint。

---

#### [完成] 新增主分切换评估脚本与验证

已完成：
- 新增脚本：`论文创新词汇统计7/scripts/legacy/validation/evaluate_primary_channel_switch.py`
  - 候选策略：`foundation_utility` / `method_transferability` / `blend_v1`
  - 门禁输出：`coverage_ok`、`dispersion_ok`、`zero_pileup_ok`、`pairwise_ok`、`ready_to_switch`
  - 支持参数：`--blend-mode`、`--blend-weights`、`--pair*`、`--max-records-per-year`、`--progress`
- 验证：
  - `python -m py_compile .../evaluate_primary_channel_switch.py` ✅
  - `--help` ✅
  - 2020 截样冒烟（20k）：`ready_to_switch=False`（样本对未命中，`pairwise_ok=False`）✅
  - 2020 全量：`ready_to_switch=True`，`pairwise_ok=True (1/1)`，`pearson_corr_common=0.883232` ✅
- 产物：
  - `论文创新词汇统计7/artifacts/runtime/impact_output/impact_v6_primary_switch_eval_blend_v1_2020_smoke.json`
  - `论文创新词汇统计7/artifacts/runtime/impact_output/impact_v6_primary_switch_eval_blend_v1_2020_full.json`

---

#### [完成] 文档同步

已完成：
- `论文创新词汇统计7/docs/08_影响力算法.md`：新增主分切换评估工具入口与脚本清单。
- `论文创新词汇统计7/docs/reference/IMPACT_V6_DESIGN.md`：新增切换评估工具说明与门禁口径。

---

#### [完成] 进度显示与断点续传增强（2026-02-25）

已完成：
- `evaluate_primary_channel_switch.py` 增加可恢复执行能力：
  - `--resume/--no-resume`（默认开启）
  - `--resume-path`
  - `--resume-flush-seconds`（默认 20s）
  - 运行中保存扫描 offset、当前 year 已处理记录数与全局统计累积状态。
- 增强进度可见性：
  - 默认 `--progress` 开启，显示 year 级进度条。
  - 按 20s 输出 heartbeat（rows/valid/rate/elapsed）。
- 冒烟验证：
  - 首次运行创建 checkpoint：`[RESUME] Created checkpoint ...`
  - 第二次同参数运行：`[RESUME] Loaded checkpoint ...` + `[RESUME] Skip completed year: 2020`

---

## Re-grounding 记录

| 时间 | 对齐 | 说明 | 动作 |
|------|------|------|------|
| 任务启动 | ✅ | 用户目标是“继续下一轮”，已落地为“主分切换评估” | 继续 |
| 执行完成 | ✅ | 已完成“先评估再切换”的最小闭环，未触碰默认主分 | 继续推进全量评估 |

---

## Debug 记录

| 问题 | Strike | 尝试方案 | 结果 |
|------|--------|----------|------|
| 无 | 0 | 无 | ✅ |
