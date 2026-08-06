# 42 · F3b 设计：Review 移到 prose 之后

> 状态：**仅设计，未实施**（独立设计评审项，见 `41_evaluation_remediation_plan.md` F3b 行）
> 关联：F3a 已落地（`recheck_against_prose`，对象层 issue 的正文兑现标注）；本文是其结构性演进——把 LLM Review 从「成文前对象层」移到「成文后读正文」，根治「review 与正文脱节」。
> 参考：`src/workflow_action/review.py`、`src/workflow_action/prose.py`、`src/extend_short_form.py`、`src/compose_short_form.py`、`src/audit_short_form.py`

---

## 1. 目标与动机

当前 Review 在三流中都运行在 **prose 成文之前**，只审对象层（Rebuild 对象 / Continue 的 PlotUnit）。代码自己承认这是代理信号：

- `review.py:774`「诚实标注：对象层无正文，这是代理信号，需在正文层确认（LLM 复核）」
- `review.py:903`「对象层无正文，命中仅是"可能"，正式阻断判断由 review prompt 的 LLM 承担」

**后果**：LLM 审查者看不到正文，无法真正判断
- 伏笔/承诺是否在正文中被自然兑现（`promise_loss` 靠对象层引用，看不到正文里的回收）；
- 事实/后果是否被正文写作抹平或坐实；
- 正文层独有的问题（风格漂移、AI 味、冗余、情绪温度、对白质量）**完全无人审查**——因为审查发生在成文前。

F3a 的 `recheck_against_prose` 是在成文后补一个 2-gram 相关性标注，**只展示、不改 route**，是缓解不是根解。

**F3b 目标**：把 LLM Review 移到 prose 之后，让审查直接读正文。对象层信号与正文证据并陈，`promise_loss`/`missing_consequence`/`fact_conflict`/`character_distortion` 等判定从「代理信号」升级为「正文兑现验证」，并新增正文层审查维度。

---

## 2. 现状时序（改前）

| 流 | 时序 | 说明 |
|---|---|---|
| audit | Rebuild → Review → (Rewrite → Re-Review) | 无 prose 阶段；Review 只看对象层，甚至不看被审核的原文 |
| extend | Rebuild → Continue → Review → (Rewrite → Re-Review) → Prose | Review 在成文前 |
| compose | Continue → Review → (Rewrite → Re-Review) → Prose | Review 在成文前 |

- 三流均有 `--no-prose`（extend/compose）保纯结构产物；audit 本就无 prose。
- route ∈ {pass, rewrite, block}（`review.py` `VALID_ROUTES`）；`resolve_route` 纠偏：blocking+pass→rewrite、非 blocking+rewrite→pass。
- blocking 判定 = severity ∈ {critical, blocking}（`reviewissue.py:170`）。
- RewriteUnit 对 **对象层** 打补丁（`apply_required_fixes(objects, fixes)`），随后 Re-Review 仍是对象层。

---

## 3. 设计总览

### 3.1 核心原则

1. **净 LLM 轮数不变**（happy path 仍 3 轮）：改前 Continue→Review→Prose 是 3 轮；改后 Continue→Prose→Review 也是 3 轮。只重排 + 注入正文，不新增审查轮。
2. **代码前置闸**（pre-review，零 LLM 成本）：prose 之前跑确定性代码规则（`_hard_rules`/`_domain_rules` 中对象层可判的部分），拦截结构性致命错误，避免为无效结构付出成文成本。**这是为了守住「无效结构不 prose」这一改前收益**——不能把 Review 整体后移而丢掉这个闸。
3. **后置全审**（post-review）：LLM 审查 + 全部代码规则，prompt 注入正文。正文层问题在此捕获。
4. **零成本契约**：无正文（audit / `--no-prose` / 旧工作区）时，Review prompt 与改前**逐字节相同**；有正文才注入【正文】段。回归测试锁死。
5. **rewrite 双层目标**：对象层修复（改 PlotUnit → 重新成文）与正文层修复（直接改章节正文）分开，各走各的再审查路径。

### 3.2 新时序

**extend**（改后）：
```
Rebuild → Continue → Pre-Review(代码,零LLM) → Prose → Review(代码+LLM+正文)
              │                                   │
              │ blocking                           ├─ pass → 完成
              │                                   └─ rewrite → Rewrite(双层) → Re-Prose/改正文 → Re-Review
              └→ Rewrite(对象层) → Re-Pre-Review →（通过后进 Prose）
```

**compose**（改后，无 Rebuild）：
```
Continue → Pre-Review(代码,零LLM) → Prose → Review(代码+LLM+正文) → [同 extend]
```

**audit**（改后，时序不变，只加正文注入）：
```
Rebuild → Review(代码+LLM+【正文上下文】) → (Rewrite → Re-Review)
```
audit 的「正文」就是被审核的源文本（已是成文），无需重排，只把原文（或相关章节片段）注入 Review prompt。这是同一原则在「正文已存在」流上的零时序风险落地。

---

## 4. 各阶段细化

### 4.1 Pre-Review（新增，代码前置闸）

- **输入**：Rebuild 对象 + Continue 的 PlotUnit（无正文）。
- **动作**：只跑对象层可判的确定性规则：
  - `_hard_rules` 中与正文无关者：`character_distortion`（未知 ID 关联，见 V4 实跑中 `c_zhaidanqing`/`c_fujun` 未建模即命中）、`fact_conflict`、`world_violation`、`timeline_error`、信息通道 P1-P4 中对象层可判项；
  - `_domain_rules` 中对象层可判项。
- **判定**：有 blocking → route=rewrite，进入**对象层** Rewrite（改前 Step 4 逻辑原样保留）→ 应用 → 重跑 Pre-Review（代码侧）→ 无 blocking 才放行 Prose。无 blocking → 直接 Prose。
- **不改**：不产生 LLM 轮次、不写 review_response、不产出 route 文件（或仅产出 `pre_review_result.json` 供审计）。其输出是过程性 gate，不是最终评审。
- **注意**：正文相关规则（F3a 的 2-gram prose 兑现、正文层问题）**不在** Pre-Review 跑——它们留到 post-Review 有正文时再跑。

### 4.2 Prose（位置前移）

- 从 Step 6（最后）移到 Step 4（Review 前）。逻辑本身不变（`prose.py build_prompt/parse_response/chapter_path/next_chapter_number`；F4 篇幅对齐、F5 原文去重继续生效）。
- `--no-prose` 时跳过，**保持旧版纯结构产物**：Pre-Review → Review（无正文，零成本）→ 完成。这样结构-only 用户不受 F3b 影响。

### 4.3 Review（后置全审）

- **位置**：Prose 之后。
- **输入**：对象层 + 刚生成的章节正文（`chapter_N.txt`）。
- **prompt**：`build_prompt(objects, context, prose_text=...)`。`prose_text` 缺省为 None 时，prompt 字节与改前一致（零成本契约，回归测试锁死）。
- **注入策略**：
  - 短流（单章 compose/extend）：注入本章全文（章均 6,500 字符量级，可接受）。
  - 长文/batch：沿用现有 batch 切分，每章正文注入对应 batch 的 Review prompt；正文超窗口时截断 + 用 `_prose_evidence` 式窗口对代码规则命中的 issue 取命中片段。
- **审查维度扩展**（在现有 5 维上）：
  - 对象层 5 维照旧（事实/角色/世界/承诺/状态）；
  - **新增正文层维度**：风格漂移（`style_drift`）、AI 味（`generative_indicia`）、冗余（`redundancy`）、情绪温度与预期不符、对白是否出戏。
  - 对每个对象层 issue，要求 LLM 对照【正文】判定：是否已被正文自然兑现/坐实/推翻——兑现则降级或撤销，坐实则升级。
- **F3a 去留**：`recheck_against_prose` **保留**，作为后置 Review 里的一条**确定性交叉核验**（不改 route，与 LLM 并行）：LLM 可能漏判，2-gram 兜底给出「对象层 issue 是否被正文提及」的机械证据。F3b 使它与 LLM 同场（都见正文），但职责互补：F3a 是确定性证据，LLM 是语义判定。`_PROSE_RECHECK_TYPES`（abrupt_payoff/promise_loss/missing_consequence/character_distortion）不变。

### 4.4 Rewrite 双层目标

**问题**：改后 Review 见正文，Rewrite 若只对对象层打补丁，则：
- 对象层修复必然使已生成正文失效 → 必须重新成文（Re-Prose）；
- 但有一类 issue 只在正文层（风格、AI 味、冗余、个别措辞），对象层无需动。

**设计**：Rewrite 响应 schema 的每个 fix 增加 `target_layer`（`object` | `prose`）：
- `object`（默认，兼容旧响应缺省视为 object）：走改前路径 `apply_required_fixes(objects, fixes)` → 以修复后对象**重新成文**（Re-Prose，覆盖 `chapter_N.txt`）→ Re-Review（带新正文）。
- `prose`：直接对 `chapter_N.txt` 做编辑（fix 携带原文定位片段 + 替换文本，复用 `prose.py` 已有的原文定位能力）→ 不重建对象 → Re-Review（带编辑后正文）。
- 混合：先 object 后 prose 顺序应用。

**循环保护**：现状是单趟 rewrite+re-review（无显式循环）。F3b 保持单趟，但加 `MAX_REWRITE_ITERATIONS = 3` 文档化上限：Re-Review 仍 blocking 且已达上限 → route=block（交人工）。未来若引入迭代回环，此上限即为护栏。

### 4.5 route 语义变化

| route | 改前 | 改后 |
|---|---|---|
| pass | 对象层无 blocking | 对象层 + 正文层均无 blocking |
| rewrite | 对象层需修复 | 对象层或正文层需修复（`target_layer` 区分），进入双层修复 |
| block | 结构性不可自动修复 | 同上；另含「rewrite 达迭代上限仍 blocking」|

`resolve_route` 逻辑不变（blocking+pass→rewrite 等），但 blocking 来源扩展为对象层 + 正文层合并。

---

## 5. [WAITING] 重跑链影响

改前 extend happy path：Continue → Review → Prose（3 个 [WAITING] 点）。
改后 extend happy path：Continue → Prose → Review（3 个 [WAITING] 点），**顺序变、数量不变**。

非 happy path 增加：
- Pre-Review 触发对象层 Rewrite：多 1 个 [WAITING]（Rewrite）→ 重跑直到 Pre-Review 通过。这在改前本就不存在（改前 Review 前无 gate，结构错直接 prose 了）；净增是**修正**而非负担。
- post-Review 触发双层 Rewrite：多 1 个 [WAITING]（Rewrite）+ Re-Review [WAITING]。改前同样有 Rewrite+Re-Review 两个点，数量不变，只是其后再无 Prose（已在 Review 前成文）。

**Codex 提示词更新**：`CLAUDE.md` / README 的续写/创作循环说明中，把「Review → Prose」顺序改为「Prose → Review」，并注明「先成文、后审查读正文」。audit 流提示词不变（只多一句「Review 会注入原文」）。

---

## 6. 产物与 schema 变化

- `extend_result.json` / `compose_result.json`：
  - `review` 段新增 `prose_context`（本次 Review 所用的正文来源/是否注入）；issue 的 `prose_evidence`（命中片段）随 issue 存；
  - `rewrite_applied` 拆为 `object_rewrites` / `prose_rewrites` 计数；`applied_fixes` 各 fix 带 `target_layer`。
- 新增过程产物：`pre_review_result.json`（Pre-Review 代码 gate 记录，供审计）。
- `audit_report.json`：issue 附 `prose_evidence`（audit 注入原文后）。
- 无新增常驻文件；`review_prompt.txt`/`review_response.txt`/`prose_prompt.txt`/`prose_response.txt` 命名不变（重跑链兼容）。

---

## 7. 兼容与迁移

1. **零成本契约**（最强兼容保证）：无正文 → prompt 字节不变。audit、`--no-prose`、旧工作区全部无感。
2. **旧工作区 mid-flow**：extend/compose 工作区若已存在改前生成的 `review_response.txt` 且 `prose_response.txt` 缺失（即停在「Review 后、Prose 前」），升级后按新时序会先看 Pre-Review 再看 Prose，但 review_response.txt 已存在会被新逻辑误读为「后置 Review 已完成」。
   - **迁移策略**：输出目录写入 `flow_version` 戳（`output/.flow_version`，本次 F3b 记 `2`）。检测到旧版本（`1`）且存在 `review_response.txt` 时，**fail-fast** 打印提示：将 `review_response.txt` 重命名/删除后重跑，流程自然落到「Pre-Review → Prose → Review」新顺序。重命名保留给人工比对，不静默删除。
   - 全新工作区无此问题（首次运行即写 `flow_version=2`）。
3. **`--no-prose` 用户**：Review 仍在（无正文注入），行为与改前 `--no-prose` 完全一致。
4. **audit**：时序零改动，只有 prompt 注入原文；旧 audit_report 无需迁移。

---

## 8. 验证计划

### 8.1 测试

| 测试 | 断言 |
|---|---|
| 零成本契约（新增/更新） | `build_prompt(objects, ctx, prose_text=None)` 与改前逐字节相同；audit、`--no-prose` 回归 |
| 时序契约（更新） | extend/compose 响应文件存在性检查按新顺序（Pre-Review→Prose→Review）；`flow_version` 旧版 fail-fast |
| 双层 rewrite（新增） | `target_layer=prose` 的 fix 改写章节文件、不重建对象；`object` fix 触发 Re-Prose；混合顺序正确 |
| Pre-Review gate（新增） | blocking 对象层 issue 阻止 Prose、先走对象层 Rewrite |
| prose 注入（新增） | prose_text 非空时 prompt 含【正文】段；窗口/截断不越界 |
| review 语义（更新） | 后置 Review 合并对象层 + 正文层 blocking，route 正确 |

预估测试增量：+2~3 文件（双层 rewrite、Pre-Review gate、flow_version 迁移），其余更新既有。改测试数时同步 `EXPECTED_TEST_BASELINE`/`EXPECTED_BASELINE` 与 6 文档（基线纪律，见 `40_session_handoff.md` 七）。

### 8.2 回归

1. `PYTHONIOENCODING=utf-8 pytest tests/ -q` 全绿，文档「N passed」同步；
2. `python scripts/tier0_canary_regression.py` 绿（canary 工作区需重跑完整 [WAITING] 循环补新时序产物）；
3. `git grep 主角 HEAD -- style_library/ src/ docs/ tests/` 空（隐私红线）；
4. 真文本实跑（如 `novels/audit-v4`）确认 Review prompt 含正文、`prose_evidence` 落盘、route 正确。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 无效结构先 prose 造成浪费 | Pre-Review 代码闸前置拦截（零 LLM 成本）；净 LLM 轮数不变 |
| 对象层修复后正文失效，Re-Prose 成本翻倍 | 双层 rewrite：只在确需动对象时才 Re-Prose；正文层 issue 直接改正文 |
| 正文注入超长（长文） | batch 沿用 + 窗口截断 + `_prose_evidence` 式命中片段 |
| 旧工作区误读 | `flow_version` 戳 + fail-fast 提示，不静默删改 |
| rewrite 回环爆炸 | 单趟 rewrite+re-review 不变；`MAX_REWRITE_ITERATIONS=3` 后 route=block |
| prompt 字节回归 | 零成本契约测试锁死（`prose_text=None` 逐字节相同） |

---

## 10. 范围界定（本设计**不**做）

- ❌ 不实施任何代码改动——本文仅设计，实施另立任务（改时序/加 pre-review/双层 rewrite/注入/迁移）。
- ❌ 不改三流之外的模块（retrieval、style、time、compliance 不受影响）。
- ❌ 不引入 prose 批量重构（一次仍生成单章）。
- ❌ 不引入读者/留存回路、人类评测校准（V1/V2 另项）。

---

## 11. 建议实施顺序（若立项）

1. `review.build_prompt` 加 `prose_text` 参数 + 注入段（零成本契约测试先行）；
2. `flow_version` 戳 + 旧版 fail-fast（兼容测试）；
3. extend/compose 时序重排（Pre-Review gate → Prose 前移 → 后置 Review），同步 Codex 提示词文档；
4. Rewrite `target_layer` 双层；
5. audit Review 注入原文（零时序风险，可与 3 并行）；
6. 全量回归 + canary 补产物 + 文档基线同步。

每步跑全量验证 + 守纪门再进下一条（对齐 `41_evaluation_remediation_plan.md` 落地顺序纪律）。
