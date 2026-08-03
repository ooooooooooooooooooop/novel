# 时间域设计方案（TimeBook 先验模型 · 横向域版）

## Purpose

时间不是续写的补丁，而是与风格/合规/评测**平级的横向域**。本方案把时间能力建成贯穿全流程的域：一个**持久先验 TimeBook** + 一个**时间审计引擎** + 一套**各流程消费点**。核心契约与 `StyleProfile`/`--retrieval` 一致——**没有 TimeBook，所有行为与今天逐字节相同**。功能齐全但不给日常流程加工程复杂度。

---

## 1. 全景图：时间域如何贯穿全流程

```
                     TimeBook（persist，每部小说一个，跨流程共享）
                        /     |       \        \        \       \
                 compose    audit   rebuild   extend   rubric   list
                (创建时建立) (审存量) (重建锚)  (向前推进) (评测)  (查看)
                   │          │        │        │
              workspec.time  timeline  rebuild   continue 注入
              初始锚/跨度     _report   .time    【时间上下文】
                             +FACTTRACK        +FACTTRACK
```

- **建立**：compose 从 `workspec.time` 初始化 TimeBook 初稿
- **校准**：audit / rebuild 对既有文本提取章节时间锚，校准 TimeBook
- **推进**：extend 续写时注入【时间上下文】锚定当前位置
- **验证**：audit / extend 共享时间审计引擎（FACTTRACK v2）
- **报告**：audit 产出 `timeline_report.json`（一等产物，与 audit_report 并列）
- **查看**：`novel time` / `novel list` 展示每部小说当前叙事时间

---

## 2. TimeBook（持久先验，全字段可选）

路径：`novels/<名>/output/time/time_book.json`（对齐 `output/style/style_profile.json`）。

```json
{
  "schema_version": 1,
  "initial": {"date": "2001-01-23", "lunar": "除夕", "loc": "某城"},
  "anchors": [
    {"chapter": "第N章", "date": "2001-01-22", "lunar": "腊月廿九", "tod": "入夜", "loc": "某城"}
  ],
  "era": [
    {"year": 2001, "events": ["入世", "申奥成功"], "note": "液晶/手机出海窗口"}
  ],
  "timelines": [
    {"id": "past", "name": "前世", "ends": "2010-06", "note": "主角先知时效终点"}
  ],
  "rules": [
    "某城(南半球)1月为盛夏，另一城为寒冬"
  ]
}
```

- `initial`：起点设定（compose 建立；audit/rebuild 校准）
- `anchors`：章节时间锚点表（续写准星 + 单调校验源），数组空=不注入
- `era`：年度时代背景（参考层，可架空），数组空=不注入
- `timelines`：多时间线（前世/今生、闪回段），`ends` 是先知时效边界
- `rules`：软时间规则（季节/历法/节气）
- 全部字段 `Optional`，缺省即"该功能关闭"，序列化向后兼容

---

## 3. 时间审计引擎（FACTTRACK v2，可复用）

抽成独立引擎，被 audit / rebuild / extend 三处调用，不再只挂在 reconcile 内部。

`time_audit.py::run_time_audit(objects, time_book=None) -> list[ReviewIssue]`

| 检测 | 触发条件 | 判断 |
|---|---|---|
| 现有 3 项（死亡后活跃/过期持有/否定重叠） | 无条件（schema 无关） | 维持现状 |
| **4 状态时间回退** | `anchors` 非空 | `anchors[i].date > anchors[i+1].date` → `timeline_error` |
| **5 先知逾期** | `timelines[].ends` 或伏笔 `expires_at` | 带 `expires_at` 且仍 active 的伏笔，锚点日期 ≥ 过期点 → `timeline_error` |
| **6 季节/历法违反** | `rules` 含季节/历法声明 | 锚点月份与声明冲突（如南半球 1 月=盛夏被写成寒冬）→ 警告 |

- `time_book=None` → 仅现有 3 项，行为与现状逐字节一致
- 检测全部 `warning`（非 blocking），不引入新门禁

---

## 4. 各流程的时间职责

| 流 | 时间职责 | 产物 | 无 TimeBook 时 |
|---|---|---|---|
| **compose** | `workspec.time` 可选字段 → 初始化 TimeBook 初稿（起点/跨度/timelines） | `workspec.time` + 初稿 | 无该字段 = 今天行为 |
| **audit** | 对既有全文跑时间审计：FACTTRACK + 锚提取 + 时间线一致性 | `timeline_report.json`（一等产物） | 仍产报告，检测退化为现有 3 项 |
| **rebuild** | 重建对象时顺带提取章节时间锚（复用 chunking），写入 rebuild package | `rebuild_package.time` | 无额外字节 |
| **extend** | continue 注入【时间上下文】 + FACTTRACK v2 | prompt 段 + issues | 注入空串，字节不变 |
| **rubric** | 可选：有 timeline_report 时加"时间一致性"评测维 | rubric 8→9 维 | 不增维，保持 8 维 |
| **list / `novel time`** | 展示每部小说当前叙事时间/时间线状态 | list 行 / time 报告 | 显示"未设定" |

---

## 5. 续写/创作注入【时间上下文】（软锚）

- `ContinueUnit.build_prompt` 新增 `time_context: str = ""`（默认空串），extend 与 compose 共用
- 注入内容（紧凑）：
  ```
  【时间上下文】
  上章: 第N章 2001-01-22(腊月廿九)入夜 某城
  本章: 第N+1章 2001-01-23 除夕 某城(南半球盛夏)
  时代背景(2001): 入世、申奥成功
  时间规则: 某城1月盛夏/另一城寒冬
  ```
- 位置：继【写作风格】之后、【已发生事件时间线】之前
- 无 TimeBook → 空串，prompt 字节与今天逐字节相同（回归测试锁死，镜像 `test_continuation_anchors.py::test_timeline_default_unchanged_prompt`）

---

## 6. `novel time` 命令（单遍管理面）

```
novel time <名> [--input X.txt] [--rebuild] [--check] [--status]
```

- `--rebuild`：从既有文本提取章节锚草稿（复用 chunking + 首段 regex 日期/农历/时段），更新 TimeBook
- `--check`：跑时间审计引擎（单调性/先知/季节），输出 `timeline_report.json`
- `--status`：展示当前叙事时间/最新锚/时代背景
- 内置 2000–2010 中国宏观时间表（领域知识，对齐 `web_fiction.py`），按年份填充 `era`
- 单遍（对齐 compliance/rubric 先例），无 response 阶段，无残留状态；手写/编辑 JSON 同样支持

---

## 7. 分级与零成本契约

| 功能 | 级别 | 用不到时的行为 |
|---|---|---|
| 章节锚表 + 【时间上下文】注入 | **核心** | 无 TimeBook → 空串，字节不变 |
| 现有 FACTTRACK 3 检测进 extend 流 | **核心** | 当前语料零产出，不破测试 |
| audit `timeline_report.json` | **核心** | 检测退化为现有 3 项，报告照产 |
| rebuild 锚提取 | 增强 | 无额外字节 |
| `novel time` / list 查看 | 增强 | 不跑就不存在 |
| 检测4 时间回退 / 检测5 先知逾期 | 增强 | `time_book=None` → 不跑 |
| compose `workspec.time` 建立 | 增强 | 无该字段 = 今天行为 |
| rubric 时间维 | 先置 | 无报告 → 不增维 |
| 检测6 季节/历法 | 先置 | 无 `rules` 声明 → 不跑 |
| compliance 涉史、非线性时间、人物年龄演化 | 先置 | 独立立项 |

---

## 8. 阶段路线（横向推进）

| 阶段 | 内容 | 大小 | 风险 | 先决 |
|---|---|---|---|---|
| **P1** | 现有 FACTTRACK 3 检测挂进 extend 流 | ~3 行 | 极低 | 无 |
| **P2** | TimeBook schema + rebuild 锚提取（复用 chunking） | 中 | 低 | P1 |
| **P3** | audit 产出 `timeline_report.json`（审存量，横向核心） | 中 | 低 | P2 |
| **P4** | 【时间上下文】注入 extend + compose（软锚） | 中 | 低 | P2 |
| **P5** | `novel time` CLI + list 显示 + compose `workspec.time` | 中 | 低 | P3 |
| **P6** | FACTTRACK v2：检测4/5（时间回退/先知逾期） | 中 | 低-中 | P2 |
| **P7** | 检测6 季节/历法 | 中 | 中（warning 可关） | P6 |
| P8+ | rubric 时间维、compliance 涉史、非线性时间、人物年龄 | 高 | 高 | 后置 |

顺序逻辑：P1 关缺口 → P2 立地基 → P3 审存量（audit 是时间天然主场）→ P4 保续写准星 → P5 建管理面 → P6/7 加检测。

---

## 9. 测试与基线契约（对齐项目纪律）

- 基线契约：加测试后同步 `tests/test_cli_runtime_contract.py::EXPECTED_TEST_BASELINE` 和 `tests/test_release_record.py::EXPECTED_BASELINE`（两处）+ 12 个 docs 数字
- 新测试：
  - `time_book` 缺省时 `build_prompt` 字节不变（镜像 continuation_anchors 范式）
  - 检测4/5/6：有/无 `time_book` 两种行为各断言一次
  - `novel time` 单遍、`anchors` 单调校验、空提取静默降级
  - audit `timeline_report.json` 产物契约
  - compose `workspec.time` 缺省回退
- 序列化：全字段 `Optional`，旧 TimeBook 无字段可反序列化

---

## 10. 反冗长清单（防止"方案做出来反而变重"）

- [x] 无 TimeBook → 注入空串、检测不跑、命令无残留——零成本
- [x] 不碰 `NarrativeState.current_time`、不碰 `serialization.py` layer map——无 schema 迁移
- [x] 锚提取复用 rebuild 的 chunking，不新起一套解析
- [x] `novel time` 单遍（对齐 compliance/rubric），无 LLM response 阶段
- [x] 时间审计引擎抽为 `run_time_audit(objects, time_book=None)`，一处实现三处调用
- [x] 检测全部 `warning`（非 blocking），review 可 pass
- [x] 时代背景是参考层，非硬事实，可架空——不给续写加"史实答辩"负担
- [x] 先知时效只加一个可选字段（伏笔 `expires_at`），有 `validity_interval` 向后兼容先例
