# Tier 0 三流日常投产加固规划

**文档编号**：`docs/00_project/34_tier0_daily_production_hardening_plan.md`
**前置**：doc 33 Tier 0 已完成（audit canary 通过、release record 验证通过、tag `v0.1.0-tier0` 已推送）
**目标层级**：Tier 0 范围内加固 —— 不升级 tier，不引入 DirectAPI / UI / 闭环自动化
**产出形态**：先规划后实施（本文件即规划，已批准后实施）

---

## 1. 目标与范围

让 audit / extend / compose 三流都达到「Codex 单用户本地日常投产」，并补齐投产必备但 doc 33 未覆盖的可用性保障。

完成此规划后，项目应达到：

- 三流各自有一次真实 Codex 循环跑通并通过 gate（不止 audit）
- 一键 canary 回归脚本，src 改动后能快速判断止血线是否还在
- 覆盖三流的 operator runbook
- 干净的工作区 / 产物治理，.pytest-tmp 与 .taskflow 不入库，canary 工作区入库固化、用户工作区不入库

---

## 2. Context：doc 33 之后的真实投产缺口

Tier 0 已声明 production ready，但「ready」只建立在 **audit canary** 之上。勘察暴露三个缺口，若直接当「三流可日常投产」使用会静默退化而无人发现：

1. **extend / compose 从未 Codex 实操跑通**。`novels/` 下只有 `tier0-canary`，三流端到端只在 pytest 单元覆盖（`tests/test_novel_cli.py` 用合成 response），没有一次像 audit canary 那样的真实 staged prompt→respond→gate 循环。代码通过测试 ≠ Codex 循环能跑完。
2. **无回归门**。当前验证是 doc 31 的多步手敲命令序列，无一键脚本。src 改动后无法快速判断「止血线是否还在」，投产信心无机制保障。
3. **工作区噪声淹没**。`.gitignore` 不忽略 `.pytest-tmp-*`（400+ 目录）和 `.taskflow/`；`novels/tier0-canary/` 实际运行工作区被纳入版本控制。投产后每跑一次 novel 就多一堆未跟踪文件，工作区失控。

---

## 3. 不做事项

| 事项 | 原因 |
|---|---|
| DirectAPI / provider 调用 | 项目设计即不调 API，operator 写 response 文件 |
| UI / Web 界面 | Codex 单用户本地，不需 UI |
| 闭环自动化 | doc 30/32 已显式 disallowed |
| 改 workflow 核心代码 | src 已通过 1248 测试；加固不以「加固」为名改 workflow 代码。若步骤实操暴露真实 bug，停下报告单独决策，不混入加固 commit |
| 新 immutable checkpoint（新 tag） | 加固在 v0.1.0-tier0 范围内，新 tag 会暗示 tier 升级 |

---

## 4. 实施步骤

### 步骤 1：Extend Canary 实操

按 audit canary 模板，对 extend 流做真实 Codex 循环：

1. 准备 extend canary 输入（复用 `canary_inputs/tier0_canary_input.txt` 或新建 extend 专用短篇），放入隔离工作区 `novels/tier0-extend-canary/`
2. `novel extend tier0-extend-canary --input <path>` → 预期 `[WAITING]` rebuild
3. 用 rebuild response 模板 materialize → `novel respond ... --slot-id rebuild` → `novel resume`
4. `[WAITING]` continue → 生成 continue response → respond → resume
5. `[WAITING]` review → 用 route=pass 的 review response → respond → resume
6. `novel gate tier0-extend-canary --json`

**通过标准**：gate `ok=true`、`review_route=pass`、`next_workflow` 为 extend 流预期、`blocking_pending_count=0`。

**决策点**：若 extend gate 的 `next_workflow` 与 audit 不一致（extend 是 Rebuild→Continue→Review），停下确认 pass 标准是否需按流差异化定义，不假设统一字段。

### 步骤 2：Compose Canary 实操

同步骤 1 对 compose 流（Initialize→Continue→Review）：

1. `novel compose tier0-compose-canary`（默认 WorkSpec 或带 `--workspec`）
2. `[WAITING]` continue → continue response → respond → resume
3. `[WAITING]` review → pass review response → respond → resume
4. `novel gate tier0-compose-canary --json`

**通过标准 / 决策点**：同步骤 1。

### 步骤 3：补 persist canary 产物 + evidence

参照 doc 33 步骤 4/5，对 extend/compose canary：

- 保存 gate JSON 到 `docs/00_project/releases/tier0-extend-canary-gate.json`、`tier0-compose-canary-gate.json`
- 用 `novel-release-record ... --generate-canary-evidence --canary-workspace novels/tier0-extend-canary` 生成 evidence
- **不覆盖**已有 audit evidence

### 步骤 4：canary 回归脚本

新建 `scripts/tier0_canary_regression.py`，一键执行：

- 跑 audit / extend / compose canary：把 `canary_inputs/` 下已固化的 response 文件喂回 `novel respond`，验证 staged 路径与 gate 仍 pass（**重放模式**，不重新生成）
- 每流末尾 `novel gate --json`，断言 4 项标准
- 汇总 exit 0 / 非 0，打印每流 PASS/FAIL

**设计取舍**：重放 vs Codex 重新生成 —— 采用**重放模式**。理由：回归门要快且稳定，response 内容质量不是回归门职责；重放已通过 evidence 的 response 已足够覆盖「代码改动是否破坏 staged 路径」。

排除的更简单做法：只跑 pytest。排除原因：pytest 用合成数据，不经过 `novel respond` 真实物化与 gate，无法覆盖 CLI 层回归。

**决策点**：是否跑长文 `--range/--batch-size` 路径？默认不跑（慢），加 `--long-form` 开关才跑。

### 步骤 5：operator runbook

新建 `docs/00_project/35_operator_runbook.md`，覆盖：

- 三流各自完整 Codex 循环命令（audit/extend/compose 的 WAITING→respond→resume→gate 序列）
- 各流预期 staged slot（audit: rebuild/review；extend: rebuild/continue/review；compose: continue/review）
- 常见失败处置：input hash mismatch、response 文件已存在、prompt_hash 不匹配、gate 非 pass
- 断点续跑：`novel resume` 语义按流说明（audit 重跑同命令；extend/compose `--resume`）
- 长文用法与 outline 注入触发条件（30+ 章）

### 步骤 6：工作区 / 产物治理

更新 `.gitignore`：

```
.pytest-tmp-*/
.pytest-tmp/
.taskflow/
```

canary 工作区入库策略：保留 audit canary 入库（doc 32 evidence 引用其 sha256），新增 extend/compose canary 也入库供回归重放；普通用户工作区不入库。规则：`novels/` 入库仅限 `tier0-*-canary/`。

排除的更简单做法：整个 `novels/` 入库。排除原因：用户日常小说工作区不应进版本库，会爆炸。

### 步骤 7：文档同步 + 三流加固 evidence

- 更新 `docs/00_project/03_current_status.md`、`30_production_readiness_checklist.md`、`README.md`、`AGENTS.md`：声明三流日常投产就绪
- 在 `docs/00_project/releases/` 补一份三流加固 evidence `tier0-three-flow-canary-evidence.json`，作为 doc 33 release 的补充证据
- **不打新 tag、不覆盖原 release record `tier0-release.json`**

### 步骤 8：验收

- 一键回归脚本 exit 0
- 三流 gate 均 pass
- 全量 pytest 仍 1248 passed
- `git status` 干净（无 .pytest-tmp/.taskflow 噪声）

---

## 5. 关键文件

- 新建：`scripts/tier0_canary_regression.py`、`docs/00_project/35_operator_runbook.md`
- 新建 canary 产物：`novels/tier0-extend-canary/`、`novels/tier0-compose-canary/`、`canary_inputs/tier0_extend_*_response.json`、`canary_inputs/tier0_compose_*_response.json`
- 改：`.gitignore`、`docs/00_project/03_current_status.md`、`30_production_readiness_checklist.md`、`README.md`、`AGENTS.md`
- 复用：`novel` CLI（`src/novel_cli.py` 的 `_run_audit`/`_run_extend`/`_run_compose`/`_run_resume` 已就绪，无需改）、`novel-release-record --generate-canary-evidence`、`novel pending/respond/gate`

---

## 6. 已澄清决策点（实施前已定）

| 决策点 | 已选定 |
|---|---|
| 回归脚本模式 | 重放已有 response |
| canary 工作区入库范围 | 三流 canary 入库，用户工作区不入库 |
| 新 immutable checkpoint | 不再加新 tag |

---

## 7. 验收标准总览

| 检查项 | 通过标准 |
|---|---|
| extend canary | gate 4 项标准通过 |
| compose canary | gate 4 项标准通过 |
| 回归脚本 | `python scripts/tier0_canary_regression.py` exit 0 |
| 工作区治理 | `.gitignore` 含 .pytest-tmp/.taskflow；canary 工作区入库、用户工作区不入 |
| 测试基线 | 全量 pytest 仍 1248 passed |
| 文档 | status / checklist / README / AGENTS / runbook 已同步三流投产 |

---

## 备注

- 本规划假设 doc 33 的核心代码与文档一致。若步骤 1/2 实操暴露 `novel` CLI 或 workflow 在 Codex 真实循环下的 bug，应停下来单独报告，不在加固 commit 里混改 workflow 代码。
- 所有 canary response 文件内容使用项目已有模板（附录 B/C 同 doc 33），不调用任何 LLM API。
