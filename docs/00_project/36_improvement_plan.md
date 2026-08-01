# 项目完善计划（Improvement Plan）

## Purpose

基于 2026-08-01 对外部同类项目的盲点审查（结论存于 memory `blindspot-review-2026-08`），把「本项目有什么没有考虑到的」落成可执行的分阶段完善计划。

本文档记录三项已拍板的方向决策，并给出 Phase 1（合规模块）的完整落地规格。后续 Phase 的实现应以本文档为锚点。

---

## 1. 已拍板的方向决策（2026-08-01）

| 决策点 | 结论 | 影响 |
|---|---|---|
| **正文生成** | 作为**独立 Track** 单独立项，不并入本期各 Phase | 架构哲学级改动（`frame.py:94` 明确不产出 PlotUnit prose），对 1416 基线冲击需单独评估 |
| **目标平台** | **通用中文平台**（不锁死番茄/起点/七猫任一） | 平台政策表按「通用」设计 + 可插拔词库，具体平台条目作参考不阻塞 |
| **敏感词过滤** | 做成**开关**（可用可关） | 合规模块 `--sensitive off` 关闭词库扫描；`--lexicon FILE` 支持自定义词库导入 |

其它保留决策：

- 系统不产出正文（`frame.py:94` 的有意设计）保持不变，正文仍由人在对话里手写；Phase 1 合规的 prose 模式只扫**输入 .txt**，不改正文生成
- 读者反馈回路（追读率/章末留存）不做——平台护城河，独立工具拿不到数据；只做「钩子质量 → 留存假设」映射
- 一键发布/平台对接不做——超出本地 CLI 范围

---

## 2. 优先级矩阵

| 项 | 对应盲点 | 成本 | 收益 | 风险 | 排期 |
|---|---|---|---|---|---|
| 内容合规模块 | #3 | 中 | 高（封号/锁章风险） | 低 | **Phase 1（本期落地）** |
| FactLedger 时间矛盾检测 | #2 | 低-中 | 高（强化现有 reconcile） | 低 | Phase 2 |
| 状态检索层 | #2 | 高 | 高（长文必崩） | 中-高 | Phase 3 |
| lint/评测校准 | #4 #6 | 中 | 中 | 中 | Phase 4 |
| 编辑人机回环 | #7 | 低 | 中 | 低 | Phase 5 |
| 正文生成 | #1 | 极高 | 极高（方向性） | 极高 | **独立 Track** |

排序逻辑：按价值排、按风险实施。Phase 1 自包含、不碰状态机、快赢建立动量；Phase 3 学术证据最强但工程最深，靠后。

---

## 3. 跨阶段纪律（每阶段必须遵守）

- **基线契约**：加测试后同步 `tests/test_cli_runtime_contract.py::EXPECTED_TEST_BASELINE` **和** `tests/test_release_record.py::EXPECTED_BASELINE`（**两处**，漏一处全挂）+ 12 个 docs 数字（教训来自 style-module 的 1248 事故）
- **序列化向后兼容**：改 stable_memory 层类型（Phase 2 的 FactLedger 加字段），旧 state 必须可反序列化
- **Windows cp936**：所有新脚本读写文件带 `encoding="utf-8"`，subprocess 调子进程用 `PYTHONIOENCODING=utf-8`
- **不碰状态机**：新模块（compliance/retrieval）按 spec/先验消费，对齐 `StyleProfile`/`BookOutline` 先例——独立 CLI 产物、独立持久化、不进 `serialization.py` layer map / type map
- 每阶段独立交付、可回滚，不跨阶段纠缠

---

## 4. Phase 1 — 内容合规模块（本期落地）

**目标**：把「敏感词/404/涉政涉黄 + 平台政策」变成系统能力，对齐 `novel style` 先例。敏感词**做成开关**（通用中文词库可关），平台目标为**通用中文**。

### 4.1 CLI 设计

```
novel compliance <novel> --input X.txt [--platform 通用] [--sensitive on|off] [--lexicon FILE]
```

- 默认 `--sensitive on`（通用中文词库扫描）；`--sensitive off` 跳过词库扫描（只剩平台政策检查，不依赖词库也能跑）
- `--lexicon FILE` 导入自定义词库（JSON），与内置词库合并
- `--platform 通用`（默认）或具体平台名；具体平台条目不存在时回退通用
- 产出 `novels/<名>/output/compliance/compliance_report.json`

### 4.2 mode 契约接入点（对齐 style 先例的 4 处耦合）

- `novel_cli.py:62` `VALID_MODES` 加 `"compliance"`
- `novel_cli.py:70` `LIST_ROW_MODES = {*VALID_MODES, "unknown"}` 自动跟随
- `novel_cli.py:1225` `_expected_gate_package_name` 加 `"compliance": "compliance_report.json"`
- `novel_cli.py:1245` `_expected_final_result_name` 加 `"compliance": "compliance_report.json"`
- 新增 `_run_compliance`（参照 `_run_style`）：拼子进程命令调 `compliance_short_form.py`，带 `--output-dir novels/<名>/output/compliance`，`--platform`/`--sensitive`/`--lexicon` 传入
- `_run_resume` 加 `compliance` 分支（参照 style 分支）
- `_build_parser` 加 `compliance` 子解析器（`--input`、`--platform`、`--sensitive`、`--lexicon`）

### 4.3 文件清单

| 文件 | 职责 | 对齐先例 |
|---|---|---|
| `src/domain_layer/compliance_knowledge.py` | 敏感词库（可关）+ 通用平台政策表 | `style_knowledge.py` |
| `src/domain_layer/compliance_rules.py` | 词库/平台访问函数 | `style_rules.py` |
| `src/workflow_action/compliance.py` | ComplianceUnit（prose 扫描 / object 平台检查） | `style.py` |
| `src/compliance_short_form.py` | compliance CLI 入口（response-file 循环） | `style_short_form.py` |
| `src/novel_cli.py` | 接入 compliance mode | `_run_style` |
| `tests/test_compliance_*.py` | 约 20 用例 | `test_style_*.py` |

### 4.4 数据模型（`src/domain_layer/compliance_knowledge.py`）

对齐 `web_fiction.py`/`style_knowledge.py` 的 TypedDict 惯例：

```python
class SensitiveEntry(TypedDict):
    word: str
    category: str          # 涉黄 | 涉政 | 涉黑 | 涉赌 | 涉毒 | 迷信 | 暴力 | 未成年人 | 宗教民族 | 性别对立
    severity: str          # block（封号级）| high | medium | low
    note: str              # 语境说明

# 通用中文敏感词库（开源 Sensitive-lexicon 导入 + 自建分类）。
# 全量渲染为开关：--sensitive off 时整个词库不参与扫描。
SENSITIVE_LEXICON: dict[str, list[SensitiveEntry]] = {
    "涉黄": [...], "涉政": [...], "涉黑": [...], "涉赌": [...], "涉毒": [...],
    "迷信": [...], "暴力": [...], "未成年人": [...], "宗教民族": [...], "性别对立": [...],
}

# 通用中文平台政策表（目标平台 = 通用中文，具体平台条目作参考不阻塞）
PLATFORM_POLICY: dict[str, dict] = {
    "通用": {
        "description": "通用中文平台基准",
        "chapter_length_target": "2000-3000",
        "update_frequency": "daily 4000+",
        "ai_direct_output": "禁止"      # 起点 2025-04 起封 AI 直出；番茄 2026 封 855 账号
        "redline_categories": ["涉黄","涉政","涉黑","涉赌","涉毒","侮辱英雄先烈"],
        "source": "platform_policy_research_2026-08",
    },
    "番茄": {...}, "起点": {...}, "晋江": {...},   # 参考条目，不存在时回退通用
}
```

### 4.5 ComplianceUnit（`src/workflow_action/compliance.py`）

两种模式，对齐 `style.py` 的「纯代码 lint + response-file 循环」先例：

- **prose 模式**：对输入 .txt 扫敏感词——命中词/分类/严重级/段落位置锚点（行号+上下文片段）/替换建议/封号风险分级。纯代码、无 LLM、可离线
- **object 模式**：对 PlotUnit 字段（genre/hook/conflict）做平台政策字段检查（弱但可用）；无正文场景下不至于空转

`--sensitive off` 时 prose 模式跳过词库扫描（platform 政策检查仍跑）。

### 4.6 验收标准

- `novel compliance 某作 --input X.txt --platform 通用` 产出带位置锚点 + 分类 + 严重级 + 替换建议的报告；分级与平台条款挂钩
- `--sensitive off` 时词库扫描跳过，报告标记 `sensitive_scan=off`
- `--lexicon FILE` 自定义词库合并生效
- 无正文场景降级 object 模式不报错
- 新增 28 测试，基线 1312 → 1340

### 4.7 风险与边界

- **词库来源有误报**：需人工校准层；`note` 字段带语境说明，`sample_snippets` 供人工复核
- **不能保证「过检=不封」**：平台审核是黑箱，本模块是风险降低不是保证，文档必须写明
- 词库内容从公开词库导入（`Sensitive-lexicon`），本模块只做接入与分类，不自行生成敏感词

---

## 5. Phase 2-5（后续，本文档记录方向，不做落地规格）

### Phase 2 — FactLedger 时间有效性 + 矛盾检测（FACTTRACK，已落地，2026-08-01）

`FactEntry` 加 `validity_interval {valid_from, valid_until}`（可选，默认 None=始终有效）；`reconcile.py` 新增 `check_temporal_contradictions`（角色死亡后仍活跃/物品易主后仍在原处/已揭示秘密仍标记 hidden）；序列化向后兼容。学术依据：FACTTRACK `arXiv:2407.16347`——唯一有实证的矛盾检测机制。

### Phase 3 — 状态检索层（已落地，2026-08-01）

档 1（零依赖）：纯 TF-IDF/关键词，以当前 NarrativeState 为 query 取 FactLedger/ForeshadowGraph top-k；档 2（语义）：bge-small-zh 余弦检索（后续）。`build_prompt` 加 `retrieval_context` 可选注入（第 11 参，默认 `""`），**API 层默认 off 时与现状字节相同**（回归测试锁死，style 先例同款防回归手段）；CLI 层默认 on + `--retrieval on|off` 开关（对齐 compliance `--sensitive`），loader 静默降级（空语料/空 query/全零分 → `""` 字节不变）。落地：`src/boundary_control/retrieval_metrics.py`（纯 stdlib TF-IDF/关键词引擎）+ `src/workflow_action/retrieval.py`（RetrievalUnit/load_retrieval_context）。新增 49 测试，基线 **1367 → 1416**。学术依据：BookWorm/MemBench/ENGRAM。

### Phase 4 — lint/评测校准

`--lint` 加外部基准（朱雀 AI 检测免费 API，马良先例）双报告标分歧；ReviewUnit domain rules 按 WebNovelBench 8 维映射成可导出 rubric。离线降级为仅本地规则。

### Phase 5 — 编辑人机回环

`novel gate` 支持 `--require-approval`——severity=critical 的 issue 必须人工 approve/reject 才推进（对齐 webnovel-writer blocking gate / InkOS 人工 gate）。

---

## 6. 独立 Track — 正文生成

不并入本期 Phase，但方向已定：参照 `LongWriter`（`arXiv:2408.07055`）的 AgentWrite 拆解（plan → write 子任务，突破 4000 字天花板），在现有对象层（PlotUnit/NarrativeFrameUnit）基础上加**章级 prose 输出**。对架构哲学（`frame.py:94` 声明）和 1416 基线的冲击需单独立项评估，本文档不做落地规格。

---

## 7. 明确不做

- 读者反馈回路（平台护城河）
- 一键发布/平台对接（超出本地 CLI 范围）
- DirectAPI provider calling（维持 Tier 0 边界）
- 商业级多用户协作（超出当前单用户 staged CLI 范围）

---

## 8. 变更记录

- 2026-08-01：本文档创建。基于盲点审查；用户拍板三项方向决策（正文生成独立 Track / 通用中文平台 / 敏感词开关）；Phase 1 合规模块落地规格定稿。
- 2026-08-01：Phase 2 落地（FactLedger 时间有效性 + 矛盾检测，1367 tests）。
- 2026-08-01：Phase 3 落地（状态检索层，1416 tests）。
