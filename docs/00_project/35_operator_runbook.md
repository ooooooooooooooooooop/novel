# Operator Runbook — Tier 0 Three-Flow Daily Production

**文档编号**：`docs/00_project/35_operator_runbook.md`
**适用层级**：Tier 0 —— local staged CLI v0, operator-in-the-loop（Codex 或同构 CLI）
**运行时**：`FileExchangeInterface`，response 文件由操作者/Codex 手动物化，**不调用任何 LLM API，不闭环自动化**
**前置**：`pip install -e .`，`novel --help` 可用

本手册覆盖 audit / extend / compose 三流在 Codex 循环中的日常投产操作、各流预期 staged slot、断点续跑语义、长文用法，以及实操验证过的常见失败处置。

---

## 1. 通用循环约定

所有三流共享同一 staged 模型：

1. `novel <mode> <name> --input <path>`（compose 省略 `--input`）
2. 脚本若需 response，打印 `[WAITING] Generate response to: <response_path>` 后**正常退出**（不会报错）
3. 操作者读取它指名的 prompt 文件，按 prompt 的【输出格式】生成 JSON 响应，保存到匹配的 `<slot>_response.txt`
4. `novel respond <name> --slot-id <slot> --prompt-hash <hash> --response-file <src.json> --json` 物化响应
5. `novel <mode> <name>` 重跑，脚本读取已物化响应，推进到下一 staged slot，或打印下一个 `[WAITING]`
6. 重复直到脚本打印 `complete: PASS` 并写出最终产物（`*_result.json` + `route_handoff.json`）
7. `novel gate <name> --json` 取只读 gate verdict

**关键：response 必须保存为独立 source 文件再喂给 `novel respond`，不能直接写到 staged `<slot>_response.txt`。** staged 响应由 `novel respond` 物化，直接手写会被拒绝（见 §6）。

---

## 2. Audit 流（审核已有文本）

`audit` 从已有文本重建对象状态并评审：**Rebuild → Review**。

```bash
novel audit <name> --input <input.txt>
# [WAITING] rebuild_prompt.txt
novel pending <name> --require-automation-ready --json   # 取 rebuild slot 的 prompt_hash
novel respond <name> --slot-id rebuild --prompt-hash <h> --response-file <rebuild_src.json> --json
novel audit <name> --input <input.txt>                   # 推进到 review
# [WAITING] review_prompt.txt
novel pending <name> --json                              # 取 review slot 的 prompt_hash
novel respond <name> --slot-id review --prompt-hash <h> --response-file <review_src.json> --json
novel audit <name> --input <input.txt>                  # 完成
novel gate <name> --json
```

预期 staged slot：`rebuild` → `review`。
最终产物：`audit_report.json`、`review_result.json`、`route_handoff.json`、`rebuild_package.json`（存放 `<name>/output/audit/`）。

---

## 3. Extend 流（续写已有文本）

`extend` 从已有文本重建状态后生成下一个 PlotUnit 并评审：**Rebuild → Continue → Review**。

```bash
novel extend <name> --input <input.txt>
# [WAITING] rebuild_prompt.txt
novel respond <name> --slot-id rebuild --prompt-hash <h> --response-file <rebuild_src.json> --json
novel extend <name> --input <input.txt>                  # 推进到 continue（保存 extend_rebuild_package.json）
# [WAITING] continue_prompt.txt
novel respond <name> --slot-id continue --prompt-hash <h> --response-file <continue_src.json> --json
novel extend <name> --input <input.txt>                  # 推进到 review
# [WAITING] review_prompt.txt
novel respond <name> --slot-id review --prompt-hash <h> --response-file <review_src.json> --json
novel extend <name> --input <input.txt>                  # 完成
novel gate <name> --json
```

预期 staged slot：`rebuild` → `continue` → `review`。
最终产物：`extend_result.json`、`extend_rebuild_package.json`、`extend_frames.json`、`route_handoff.json`。

**continue response 格式**：`{plotunit, new_state, new_facts, confidence_gaps}`。`plotunit.input_state_ref` 必须填 prompt 给出的当前状态 id（rebuild 重建后的真实 `state_id`，通常见 prompt 的【当前叙事状态】/输出示例）。

### ⚠ Extend 续跑语义陷阱（实操确认）

`novel resume <name>` 对 extend 的语义是 **`--resume` 跳过 Rebuild 从 continue 继续**，它要求已存在 `extend_rebuild_package.json`。

- 若 Rebuild 刚 respond 完、package **尚未保存**：`novel resume` 会报错 `--resume requires saved state file: extend_rebuild_package.json`。
- 正确推进：Rebuild respond 后**重跑 `novel extend <name> --input`**（不带 resume），脚本会读 `rebuild_response.txt`、保存 package、生成 `continue_prompt.txt`。
- `novel resume`（`--resume`）仅用于 continue 阶段中断后跳过 Rebuild 续跑。

---

## 4. Compose 流（从 WorkSpec 创作）

`compose` 从 WorkSpec 初始化 stub 状态后生成首个 PlotUnit 并评审：**Initialize → Continue → Review（→ Rewrite → Re-Review 若有 blocking）**。

```bash
novel compose <name>                       # 用默认 WorkSpec
novel compose <name> --workspec <ws.json>  # 或指定 WorkSpec
# [WAITING] compose_continue_prompt.txt
novel respond <name> --slot-id compose_continue --prompt-hash <h> --response-file <continue_src.json> --json
novel compose <name>                      # 推进到 review
# [WAITING] compose_review_prompt.txt
novel respond <name> --slot-id compose_review --prompt-hash <h> --response-file <review_src.json> --json
novel compose <name>                      # 若无 blocking issue → 完成；若有 blocking → [WAITING] compose_rewrite
```

预期 staged slot：`compose_continue` → `compose_review`，（有 blocking 时）`compose_rewrite` → `compose_rereview`。
最终产物：`compose_result.json`、`compose_state.json`、`compose_frames.json`、`route_handoff.json`。

### ⚠ Compose 续跑语义陷阱（实操确认）

`novel resume <name>` 对 compose 的语义是 **`--resume` 跳过 Initialize 从 continue 继续**，要求已存在 `compose_state.json`。

- 与 extend 同理：continue 阶段中断后用 `novel resume` 可跳过 Initialize；但首跑或 review 通过后的推进不应误用 resume。

### ⚠ Compose Initialize 生成的 stub 状态 id（实操确认）

`compose` 默认 WorkSpec 走 Initialize，生成 stub 对象。stub NarrativeState 的 `state_id` 为 **`ns_initial`**，不是文本里的 `s001` 之类。

- continue response 的 `plotunit.input_state_ref` **必须填 `ns_initial`**（prompt 的输出格式示例里已给出该值）。
- 填错会触发 Review 的 hard rule `weak_progression`（blocking）：`PlotUnit input_state_ref does not exist in current NarrativeState objects`，进入 Rewrite 分支。
- 修复方式：要么重发 continue response 改对（需删 staged continue_response 重做，见 §6 孤儿文件），要么走 Rewrite：发一条 `target_type=PlotUnit, field=input_state_ref, action=replace, old_value=<错值>, new_value=ns_initial` 的 fix，再 Re-Review。

### ⚠ Review route 以代码判定为准（实操确认）

三流的 Review 阶段调用 `review.resolve_route(issues, route)`——即使你在 `review_response.txt` 里写 `"route": "pass"`，只要 `_hard_rules` 或 `_domain_rules` 检出 **blocking** issue，route 会被改写为 `rewrite`。

- 无 blocking issue 时，`resolve_route` 会把 `rewrite` 归为 `pass`（"Route is rewrite but no blocking issues — treating as pass"）。
- 有 blocking issue 时必须走 Rewrite → Re-Review 循环，不能假设手写 `route=pass` 就直接通过。

### Rewrite / Re-Review 格式

- rewrite response 是 **JSON 数组**，每条 fix 含 `target_type / target_id / field / action(add|remove|replace) / new_value / old_value(可选) / reason`。字段支持点号路径（如 `entries.0.confirmed`）。
- 若无可行修复，返回空数组 `[]`。
- compose 的 review_objects 中各类型对象唯一时，`target_id` 可省略由唯一性匹配；多实例时须给 `target_id`。

---

## 5. Gate 通过标准（三流统一）

`novel gate <name> --json` 必须同时满足：

| 字段 | 通过值 |
|---|---|
| `ok` | `true` |
| `review_route` | `pass` |
| `next_workflow` | `ContinueUnit` |
| `blocking_pending_count` | `0` |

三流通过此 gate 即视为该流 staged 循环在当前代码下未退化。一键回归见 `scripts/tier0_canary_regression.py`。

### 5.1 人工审批 Gate（可选，Phase 5）

`novel gate <name> --require-approval` 让 severity=critical 的 ReviewIssue 必须获得操作者人工 approve/reject 才推进（默认 `novel gate` 不带 flag，行为不变）：

```bash
novel gate <name> --require-approval            # 需在 output/ 放 approval_decision.json
novel gate <name> --require-approval --json     # 输出 17 字段审批 gate JSON
```

`approval_decision.json`（操作者手写，gate 只读校验）形状：

```json
{
  "decision": "approve",
  "critical_issue_ids": ["iss_critical_1"],
  "operator_note": "编辑接受该设定偏离，后续伏笔已补",
  "decided_at_utc": "2026-08-01T12:34:56Z"
}
```

语义：

- **无 open critical** → 原样通过（等价于默认 gate，仅多出 4 个审批字段）。
- **缺工件 / reject / approve 未覆盖全部 critical id** → 阻塞（exit 1）。
- **approve 覆盖全部 critical id 且无 blocking issue** → 放行并**跳转 ContinueUnit**（人工绿灯=放行续写）。
- **blocking issue 严格不可审批**：即便 approve 工件覆盖全部 critical id，任何 open blocking issue 仍使 gate 失败。
- 审批 gate 输出独立的 17 字段契约（13 标准字段前缀 + `approval_required` / `critical_issue_ids` / `approval_decision` / `approval_ok`），默认 gate JSON 不变。

---

## 6. 常见失败处置

| 症状 | 根因 | 处置 |
|---|---|---|
| `response_source mtime must not be older than prompt_path` | 复用的 response source 文件 mtime 早于本轮新生成的 prompt 文件 | 把模板 response 复制到一个**新生成**的 source 文件（`cp templates/X.json my_src.json`，mtime 自然为当前），再用它 respond。不要 touch 篡改时间戳 |
| `pending response slot not found: <slot>` | 上一次 respond 在 JSON 校验阶段失败但 staged `<slot>_response.txt` 已被物化，slot 不再 pending（孤儿文件） | 删除孤儿 `novels/<name>/output/<mode>/<slot>_response.txt`，让该 slot 重新 pending，再用 fresh source 重 respond。**不要保留孤儿直接推进**——会跳过完整物化校验 |
| `--resume requires saved state file: <pkg>` | 误用 `novel resume` 推进 Rebuild/Initialize 之后、package 保存之前的阶段 | 改用普通 `novel <mode> <name>` 重跑（无 resume）让其读已物化响应并保存 package |
| `input hash mismatch` | `--input` 指向的文件内容与本工作区 `.input_hash` 记录不一致 | 确认用的是同一份输入；若有意换输入，需用新 `<name>` 开新工作区 |
| `prompt_hash` 不匹配 | `respond` 传入的 `--prompt-hash` 与当前 prompt 文件不同 | 用 `novel pending <name> --json` 重新取该 slot 的 `prompt_hash` |
| gate `review_route=rewrite` 或 `blocking_pending_count>0` | 仍有 blocking issue 未闭环 | 走 Rewrite → Re-Review 直到 blocking 清零（compose 常见 `input_state_ref` 不存在之类 hard rule） |
| `response file already exists` 类写入拒绝 | FileExchange 不覆盖已物化的 staged 文件 | 见上「孤儿文件」处置；不要手工覆盖 `*_response.txt` |

**纪律**：不要手动覆盖任何 `*_response.txt` / 最终产物文件。staged 文件由 `novel respond` / workflow 命令物化；手动改会破坏物化合约与 hash 证据。

---

## 7. 长文用法（audit / extend）

```bash
novel audit <name> --input <long.txt> --range 1-50 --batch-size 5 --max-chapters 200
novel audit <name> --outline-only      # 仅产出结构概览，跳过详细 Rebuild
```

- `--range A-B`：限定第 A 到 B 章
- `--batch-size N`：每批 N 章一个 Rebuild batch（每 batch 独立 `*_rebuild_prompt/response`）
- `--max-chapters N`：无 `--range` 时章数硬上限
- `--outline-only`：仅 OutlineUnit 结构概览
- **30+ 章自动触发 outline 注入**：chapter-wise 路径会先跑 OutlineUnit 作为 Rebuild 先验（额外 `outline_prompt.txt` / `outline_response.txt` / `outline_result.json`）
- input/WorkSpec hash 记录在 mode output 目录；rerun 内容不一致即报错

---

## 8. 日常工作流速记

- 新小说：`novel <mode> <name> --input <txt>` 建工作区（`novels/<name>/`）
- 查进度：`novel list`、`novel pending <name>`
- 断点续跑：`novel resume <name>`（语义随流不同，见 §3/§4 陷阱说明）
- 只读 verdict：`novel gate <name>`、`novel gate <name> --json`
- 回归自检：`python scripts/tier0_canary_regression.py`（exit 0 即三流基线未退化）

### 8.1 写作风格建模 SOP（novel style，v2）

**每部新书在 compose/extend 前，先按 `docs/04_workflows/10_style_modeling_workflow.md` 建风格档案**，否则续写无风格先验、易自由发挥。

```bash
novel style 某作 --input 某作.txt [--tone 克制] [--genre 都市]   # 量化 + 提炼 prompt → [WAITING]
# 物化 style_extract_response.txt（12 必填 + 4 可选 v2 字段）
novel style 某作 --input 某作.txt                                  # 合并 → style_profile.json（schema_version=2）
novel style 某作 --input 某作.txt --name 风格名                     # 另存风格库供跨小说复用
```

v2 要点：

- 量化新增 11 个叙事维度指标（景物/感官密度、场景转换计数、时间标记密度、心理动词、内独白句占比、动作动词、叙述句占比）
- 质性新增 4 个可选字段：`environment_notes` / `scene_transition_notes` / `psychology_notes` / `rhythm_notes`
- 续写 prompt 的【写作风格】段**恰好 1 次**，无【写作风格画像】内层头（双层段头已修复）；本地档案命中 `<book>/output/style/style_profile.json`
- 旧 v1 档案不升级可继续反序列化（`schema_version` 缺省视为 1）

---

## 9. 边界（Tier 0 不做）

- DirectAPI / provider 调用：不实现，response 由操作者/Codex 手动物化
- 闭环自动化：disallowed，无自动 route 推进、无 retry、无 fallback provider
- UI / Web：不存在，Codex 单用户本地
- 回归脚本不重放写入（audit canary 是不可变 evidence 基线，sha256 被 `docs/00_project/releases/` 锁定）；`novel respond` 物化路径回归由 1773-test pytest 的 `tests/test_novel_cli.py` 覆盖
