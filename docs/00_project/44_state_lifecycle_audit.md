# 44 · State Lifecycle Audit — 跨章节状态生命周期审计

> 状态：**审计结论 + 两轮修复已落地（2026-08-08）**——§5 标注的修复（Post-Prose Review / CharacterUpdate 写回门禁 / 文风接续锚点拆分 / **Draft-Commit 分离 / Post-Prose 修订 A/B 台账 / misinformation 生命周期**）均已实现并测试；真实作品《碑下》ch7/ch8 经新流程实跑验证。
> 触发：方向文档要求验证候选根因「跨章节状态缺乏统一生命周期管理」，并对所有跨章节字段明确创建者/修改者/消费者/生命周期/失效/替换/追加/删除/降级/调和/陈旧检测。
> 方法：读代码（以实际行为为准，不看文档宣称）+ 真实长程作品《碑下》状态与正文取证。
> 结论预览：根因**部分成立**——不是「所有状态缺生命周期」，而是**一类具体错误反复出现：语义上属于 Current/Consumable 的字段，被写成只追加（Accumulating）或无条件覆盖，且无清理/过期路径**。近 9 轮修复（R1-R9）正是逐个字段打补丁（staged 响应、锚点、伏笔线程、知识、压力）。本审计把它们归到统一框架下，并指出仍缺生命周期的字段。

---

## 1. 为什么做这个审计

方向文档的候选根因：

> 跨章节状态缺乏统一生命周期管理。

近 9 轮真实故障全部指向同一类模式：

| 轮 | 故障 | 本质 |
|---|---|---|
| R1 | 上一章 staged 响应被下一章复用 → 整章重复 | **Consumable 未被消费**（响应文件生命周期） |
| R3 | 文风/续写锚点锁死原书首章 | **Current 未跟随推进**（锚点选择） |
| R4 | 已兑现伏笔仍标 active → promise_loss 误报 | **Consumable 未推进**（伏笔线程状态） |
| R6 | 角色已知信息仍存『不知道X』 | **Current 未更新**（knowledge_state） |
| R7 | 已解决压力仍残留注入 | **Current 当作 Accumulating**（current_pressure 只追加不清理） |
| R9 | ch5 整章复制 ch4 | **Consumable 泄漏**（响应文件 + 落盘闸门） |

这些不是互不相关的 bug，是同一个语义错误在不同字段上的重复：**把「当前值」当「累积记录」存，把「一次性凭证」当「永久事实」存。**

本审计验证该判断，并把字段归类，标出哪一类真正污染未来生成。

---

## 2. 审计对象与方法

对象：所有跨章节存在的状态字段（数据源：`src/object_state/*`、`src/workflow_action/*`、`src/boundary_control/response_file.py`）。

对每个字段回答 9 问（创建者 / 谁允许改 / 谁消费 / 生命周期 / 何时失效 / 何时替换 / 何时只追加 / 何时应删除 / 何时应降级 / 谁负责 reconcile / 怎么检测 stale），然后归入 7 类：

```
Immutable    = 定义后不变（spec 层）
Accumulating = 只追加、不失效（历史/轨迹）
Current      = 表示"此刻"，应随叙事替换
Replaceable  = 一次性覆盖即可，但需先验证旧值语义
Expiring     = 过时不失效即为污染
Consumable   = 一次性凭证，用后应消费/删除
Derived      = 由别处计算可得，重复存储是冗余
```

**审计原则（方向文档）**：优先修会真实污染未来生成的问题；不要为了完整性给所有字段加复杂生命周期系统。

---

## 3. 逐字段审计表

### 3.1 NarrativeState（运行快照）

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| `state_id` | Immutable | Continue | 无 | 引用 | 每次 Continue 生成新 state_id，链式。 |
| `current_time/location` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `active_characters` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `current_situation` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `primary_goal` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `active_conflicts` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `emotional_temperature` | Current | Continue | Continue | prompt | 随推进替换，OK。 |
| `public_information` | Accumulating | Continue | Continue | prompt | **可疑**：会无限累积；无过期路径。`current_facts_in_scope` 存在但未用于裁剪 `public_information`。低污染（prompt 截断容忍），列为观察。 |
| `hidden_information` | Accumulating | Continue | Continue | prompt | 同上。 |
| `private_information_map` | Current | Continue | Continue | prompt | 秘密→知情者，随推进替换。 |
| `open_questions` | Current | Continue | Continue | prompt | 随推进替换。 |
| `active_suspense_items` | Current | Continue | Continue | prompt | 随推进替换。 |
| `current_goals` | Current | Continue | Continue | prompt | 随推进替换。 |
| `linked_open_threads` / `current_facts_in_scope` | Derived | Continue | Continue | 检索 | 与 ForeshadowGraph/FactLedger 冗余，检索层已软 boost。 |

**结论**：NarrativeState 整体是 Current/Replaceable，每次 Continue 生成新 state，天然被替换，生命周期 OK。唯一污染风险是 `public/hidden_information` 无限累积——但在当前规模（6 章）未造成问题。

### 3.2 CharacterModel（长期角色模型）—— **问题集中地**

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| `identity` | Immutable | Rebuild | （无机制） | prompt | 不随叙事改（身份定位），OK。 |
| `outer_goal` | **Current** | Rebuild/Continue | CharacterUpdate `goal`（无条件覆盖） | prompt | **问题**：`apply_update_to_character` 无条件替换，忽略 permanence/confidence；真实《碑下》值 = "外在目标从『留在宪碑司』推进到『查明…』——三年隐忍…"，**存的是变更日志不是当前目标**（见 §4.2）。 |
| `inner_need` | Immutable | Rebuild | （无机制） | prompt | 内在需求不随单场景改，OK。 |
| `fear` | **Current** | Rebuild | CharacterUpdate `fear`（无条件覆盖） | prompt | **问题**：同 outer_goal；《碑下》值 = "恐惧再次升级：不仅墨痕在蔓延…"——**含「升级」日志措辞**。 |
| `flaw/strength` | Immutable | Rebuild | （无机制） | prompt | 稳定标签，OK。 |
| `secret` | Current | Rebuild/Continue | Continue | prompt | 随揭示替换，OK。 |
| `stance` | **Current** | Rebuild | **无任何更新机制** | prompt | **问题**：CharacterUpdate 维度无 stance；`reconcile_knowledge/pressure` 不碰 stance。立场变化后无 reconcile 路径。真实现象：靠 Rebuild 整包重建才更新，resume 模式不更新。 |
| `arc_stage` | Accumulating | Rebuild/Continue | Continue | prompt | 阶段标记，可替换可累积。 |
| `self_image` | **Current** | Rebuild | CharacterUpdate `self_image`（无条件覆盖） | prompt | **问题**：同 outer_goal；《碑下》4 次 identity 级重写在 6 章内发生（destabilize→shift→destabilize→shift），**单场景轻易重定义人**。 |
| `knowledge_state` | Current | Rebuild/Continue | R6 review reconcile | prompt | 已修（R6）：review 声明 learn/drop_unknown。仍缺：无证据门槛（声明即写入）。 |
| `misinformation` | Current | Rebuild | **无清理机制** | prompt | **问题**：错误信念被事实击穿后无移除路径；《碑下》值 = "一度怀疑自己看见旧字只是眼花（后自我纠正）"——**已是过去式，仍存为当前错误信念**（见 §4.4）。 |
| `relations` | Current | Rebuild/Continue | （无 reconcile） | prompt | **问题**：关系实际改变后无更新机制（R6 只处理 knowledge）。CharacterUpdate `relation` 维度明确"仅记录不写回"。 |
| `current_pressure` | **Current** | CharacterUpdate/Continue | R7 review reconcile | prompt | **已修（R7）**：review 声明 resolve 移除。但 CharacterUpdate `pressure` 维度仍无条件追加，且 review 声明无证据门槛。 |
| `change_trajectory` | **Accumulating** | CharacterUpdate | CharacterUpdate `trajectory` | prompt | 语义正确（累积轨迹）。**问题**：《碑下》条目含"变化轨迹从『…』推进到『…』——他不再…"**自我引用字段名**，把轨迹描述写成了轨迹数据。 |
| `relation_behaviors` | Current | Rebuild/Continue | （无 reconcile） | prompt | 同 relations。 |

### 3.3 FactLedger / FactEntry

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| `entries[].statement` | Immutable(后确认) | Rebuild/Continue | Review confirm | prompt | OK。 |
| `entries[].confirmed` | Consumable→Immutable | Continue(admit 即 true) | Review | prompt | **问题**：Continue 产 new_facts 直接 confirmed=true，绕过 Review；conflict 事实同存不互斥。 |
| `entries[].validity_interval` | Expiring | Rebuild/Continue | — | prompt 渲染 | **问题**：有有效期声明但**无任何过期回收机制**——过期事实仍注入。`check_temporal_contradictions` 只检测不清理。 |
| `entries[].known_by` | Current | Rebuild/Continue | — | prompt | 知情者列表，无 reconcile。 |

### 3.4 ForeshadowGraph / ForeshadowEntry

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| `current_status` | **Consumable** | Rebuild/Continue | R4 review reconcile | prompt(promise_loss) | **已修（R4）**：review 声明 set_status。仍缺：无证据门槛。 |
| `advancement_nodes/narrowing_events/payoff_nodes` | Accumulating | Continue | Continue | — | 轨迹累积，OK。 |
| `expiry_risk/expires_at` | Expiring | Rebuild | — | FACTTRACK v2 | 有检测（逾期）但无自动失效。 |

### 3.5 TimeBook（spec，非状态）

Immutable spec 层；`--rebuild` 显式重建。生命周期 OK（零成本契约）。

### 3.6 Frame / Cursor（NarrativeFrameUnit）

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 |
|---|---|---|---|---|---|
| `current_frame_id` / scene cursor | **Consumable** | FrameUnit.build_frame | `advance_cursor` | Continue prompt | OK：章节周期后自动推进。 |
| frame 内 scene 状态（active/done） | Current | Continue | advance_cursor | prompt | OK。 |

### 3.7 Style context / StyleProfile（spec，非状态）

Immutable spec 层，`novel style` 提炼，注入 consume。生命周期 OK。

### 3.8 Continuity context（excerpt / prev_chapter_tail）

| 字段 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| 锚点（最近 K 章原文） | **Current** | 文件系统 | append_generated_chapters | Continue/Prose prompt | **已修（R3）**：锚点跟随已生成章。**新问题**：同一锚点段同时承担「接续连续性」与「文风模仿」——见 §4.5 Self-Imitation Drift。 |
| `prev_chapter_tail` | **Consumable** | 文件系统 | — | Prose prompt | OK（取末章尾）。 |

### 3.9 staged prompt / response（ResponseFileBoundary）

| 项 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| `*_response.txt` | **Consumable** | operator | — | 流程解析 | **已修（R1）**：reset_consumed_responses 清周期响应。 |
| CYCLE_RESPONSE_FILES | — | 代码 | — | — | 需随新流程新增槽位同步。 |

### 3.10 ChoiceLedger / AuthorKernel / CharacterUpdate（sidecar，非 stable serialization）

| 项 | 类 | 创建者 | 允许改 | 消费者 | 生命周期 / 问题 |
|---|---|---|---|---|---|
| ChoiceLedger entries | **Accumulating** | author_selection | — | consolidation | OK（sidecar）。 |
| AuthorKernel 原则 | Current | consolidation | consolidation | author_selection | **问题**：`maybe_consolidate_and_save` 只追加、无失效/去重；真实台账 37 条含 3× 重复逻辑更新（见 §4.3）。 |
| CharacterUpdate.status | **Consumable** | 提案 | — | — | **问题**：`apply=True` 后 status 从不置 applied，全部停留 proposed（见 §4.3）。 |
| CharacterUpdate.permanence/confidence | — | 提案 | — | 写回决策 | **问题**：**声明了但不生效**——docstring 写"≥阈值且 permanence=long 才 auto-apply"，`apply_update_to_character` 无条件覆盖（见 §4.2）。 |

---

## 4. 真实取证（《碑下》6 章，非自构造）

### 4.1 正文层：同章对白逐字重复

`chapter_6.txt` 中同一段对白几乎逐字出现两次：

> "你说过，你三年前走进宪碑司，是因为没有地方可去。""是。""那为什么，你会认得一个死了三年的名字？林烬，你到底是来找这块碑的，还是来找那个人的？"

（第一次在中部，第二次在尾部，仅一处措辞略异。）**这正是 post-prose 审查要抓的正文层冗余**——而当前 Review 在成文前（`extend_short_form.py` Step 3 Review 先于 Step 6 Prose），`review.py build_prompt` 无正文参数，**永远看不到这段重复**。这是「Review 与正文脱节」的直接证据。

### 4.2 长期字段存变更日志（Current 当 Accumulating 存）

真实 CharacterModel（`extend_rebuild_package.json`）：

- `outer_goal`："外在目标从『留在宪碑司（目的未明）』推进到『查明名字与记忆里那个已死之人的关系…』——三年隐忍的真实目的开始明确并驱动行动"
- `fear`："恐惧再次升级：不仅墨痕在蔓延，而且『看得越深烧得越狠』——他怕的不是暴露…"

两个字段都**内嵌了自身变化的日志（"从X到Y"、"再次升级"）**，而不是干净的当前状态。来源：`character_updates.json` 中 LLM 提案的 `proposed_after` 就是这种措辞，`apply_update_to_character` 原样写入（`fear`/`goal`/`self_image` 无条件替换）。后果：后续 prompt 看到的是演进叙述而非当前驱动力，信息密度低且措辞自指。

### 4.3 CharacterUpdate 声明不生效

真实台账 37 条（`character_updates.json`）：

- 全部 `status="proposed"`——即使 apply 写回了 CharacterModel，status 从不置 `applied`；
- **同一逻辑更新重复 2~3 次**（如 c001 self_image "midpoint 觉醒" 3 次、c002 goal "追查与旧案同源" 3 次）——`append_character_updates` 只追加不去重；
- permanence=medium、confidence=0.75 的 fear 更新照常覆盖长期字段——**门禁完全没生效**，而 `CharacterUpdate.confidence` 的 docstring 明确写着「≥阈值且 permanence=long 才 auto-apply」。

### 4.4 misinformation 永久残留

c001 `misinformation` = "一度怀疑自己看见旧字只是眼花（后自我纠正）"——**已被自我纠正、明确标注"后"，仍是"错误信念"**。无移除路径。

### 4.5 锚点段同时承担接续与文风

`excerpt.py` 头注释"供接续与文风模仿"，`load_recent_excerpts(continuation_text)`（continuation_text = 原书 + 已生成章）。Continue prompt 段名【原文锚点与文风样例】。**已生成章进入文风样例** → AI102 模仿 AI101 而非人类原文 → Self-Imitation Drift 的机制在代码里成立（章节数足够多时必然发生）。

---

## 5. 结论：根因判定 + 本轮修什么

### 根因判定（部分成立）

「跨章节状态缺乏统一生命周期管理」作为一句话成立，但**更精确的表述是**：

> **系统没有"状态生命周期"这一概念层，导致每个字段的生命周期靠一次性打补丁实现；已打的补丁（R4/R6/R7）有效，但补丁没覆盖的字段（stance/misinformation/relations/outer_goal/fear/self_image 的写回门禁、CharacterUpdate 声明）仍在污染。**

真正污染未来生成的**四类**问题（按影响排序）：

1. **正文从未被审查**（Review 在成文前，无正文注入）→ 正文层缺陷（对白重复、AI 味、风格漂移）无人发现。→ **本轮修（Post-Prose Review）**。
2. **CharacterUpdate 无条件覆盖长期身份字段**（fear/outer_goal/self_image），且 `status`/去重/门禁全部失效 → 单场景重定义人 + 字段存变更日志。→ **本轮修（写回门禁）**。
3. **文风锚点用已生成章**（Self-Imitation Drift 机制成立）→ 长程风格漂移。→ **本轮修（拆 Continuity/Style 锚点）**。
4. **stance / misinformation / relations 无生命周期**（不改 = 不污染但也不对）→ **本轮不自动全改**（方向文档要求先找证据；§4.4 已有 misinformation 证据，但修法需要 LLM 声明语义，属下一轮）。在审计中登记为下一轮候选。

### 已修的（R1-R9）不再重做

staged 响应消费（R1）、锚点跟随已生成章（R3）、伏笔线程状态（R4）、知识 reconcile（R6）、压力 resolve（R7）、落盘重复闸门（R9）——均已验证，不重复。

### 建议的分类骨架（供后续字段接入）

```text
Immutable    = identity / inner_need / flaw / strength / secret / TimeBook / StyleProfile
Accumulating = change_trajectory / advancement_nodes / ChoiceLedger / FactLedger（历史事实）
Current      = outer_goal / fear / self_image / stance / current_pressure / knowledge_state /
               misinformation / relations / relation_behaviors / NarrativeState 各字段 / anchor
Consumable   = staged response / frame cursor / foreshadow current_status / 知情者已知断言
Replaceable  = （Current 的写入方式，替换前需语义验证）
Expiring     = FactEntry.validity_interval（有声明无回收，低优先）
Derived      = linked_open_threads / current_facts_in_scope（检索层冗余，低优先）
```

### 未做但已登记的下一轮候选（不无限膨胀）

1. **relations / stance 的 reconcile**：已有证据方向（misinformation 已修，R6/R7 模式可复用），先确认真实污染频率再补（类似 R4/R6/R7 的 Review 声明语义）。
2. **FactEntry.validity_interval 过期回收**：过期事实不再注入；需"当前叙事时间"基准。
3. **public/hidden_information 无限累积**：随 `current_facts_in_scope` 裁剪。
4. **CharacterUpdate 提案证据跨时间**：`confidence` 只是模型自评，不等于历史证据——长期字段应逐步要求「本场证据 + 之前轨迹 + 与既有 self_image 冲突」聚合，而非单次判断（先监测真实高置信长期改写频率，有证据再动）。

### 本轮新增的生命周期认识（Draft/Commit）

Post-Prose 闭环暴露一个更基础的生命周期边界：**正文本身**也分 Draft 与 Committed 两态。
- Draft（`output/prose_draft.txt`）：staged，Review 前/未 PASS 时存在；下游不消费。
- Committed（`chapters/chapter_N.txt`）：Review PASS 后提交；continuity/excerpt/reader/state 只认这个。
- 旧实现把 prose 直接写进 chapters/ 再审查，导致「未接受的正文对下游可见」+「重跑把刚落盘 draft 误当上一章」（已用 is_same_as_last 打过补丁，本轮用 Draft/Commit 分离根治）。
- 附带收益：修订时 original/revision 天然保留（A/B 台账），Review Precision 可测。

---

## 6. 关联

- 本审计驱动本轮三处实现：`review.py` prose_text 注入（42 设计 §3.1/§4.3）、`character_updates.py` 写回门禁（方向第八节）、`excerpt.py`/`continuation.py` 锚点拆分（方向第六节）。
- 设计依据：`docs/00_project/42_review_after_prose_design.md`。
- 真实作品：《碑下》`novels/碑下/`（本地，gitignored）。
