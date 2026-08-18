# ADR-14：AuthorTemplate 证据先验（proposed）

状态：proposed，待总控与用户裁定。本文不是生产资格批准。

## 决定
新增 `AuthorTemplate` 作为证据驱动、可追溯的中性选择先验。它不替换 `AuthorKernel` 或 `AuthorModelV3`，不做生产硬门禁、自动终裁或身份/人格推断；当前仅允许 prior、shadow 与 tie-break 实验。

## 两条血脉职责

| 血脉 | 负责 | 不负责 |
|---|---|---|
| AuthorKernel | 既有选择结构、挑战、长期演化与生成注入 | 不被模板字段覆盖 |
| AuthorModelV3 | 跨作品证据、状态演化、资格与留一验证 | 不被模板绕过资格要求 |
| AuthorTemplate | 从显式 ChoiceLedger 蒸馏可审计候选、检索与测量 | 不写回 Kernel，不作终裁 |

## 字段映射

| Template 字段 | 来源/性质 | 约束 |
|---|---|---|
| `hard_facts` | ledger 计数与显式记录 | 只能写可回溯事实 |
| `principles` | `value_conflicts`/tradeoff/selected_candidate/hindsight 的确定性分组 | 每条必须有 decision_id + 中性 source_id |
| `inference_notes` | 算法说明 | 不得成为身份断言 |
| `style_references` | 可选 StyleProfile 引用 | 仅资格/风格参考，不生成选择原则 |
| `measurement_evidence` | 可选 twin report 引用 | 仅测量证据 |
| `kernel_reference` | 可选 Kernel 存在性引用 | 不混入原则字段 |
| `runtime` | 生成算法与状态 | 与事实/推断分离 |

## 迁移路径

1. 继续按原流程生产 Kernel/V3。
2. 用明确输入蒸馏 Template，保存到根 `author_templates/`。
3. 先做 list/show/search 与离线 shadow/tie-break 比较。
4. 经过总控批准、独立证据与长程验证后，才讨论有限消费；本包不接入生产门禁。

## 证据与隐私铁律

无 supporting choice 就不产生 principle。source 只能是中性 basename-safe 标识；不写入正文、作品名、路径、作者名或身份断言。Style/twin/kernel 只能作为引用或测量来源，不能虚构选择原则。候选模板只能报告“记录显示的模式”，不能声称某个主体是什么样的人。
