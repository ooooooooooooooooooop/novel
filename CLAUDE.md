# Automatic Novel Narrative System

## 这是什么

自动小说叙事系统的概念地基和运行切片。能解析叙事结构、维护状态、推进故事、审查结果。

## 当前状态

- 三流完成：audit（审核）、extend（续写）、compose（创作）
- 领域层：genre formula、hook taxonomy、情绪弧模板、结构节点-情绪映射、关键节点钩子质量要求、平台约束、genre 规则
- 长程编排：NarrativeFrameUnit 维护 book/arc/chapter/scene 层级（B4 已采纳并实现）
- 增量续写：`--resume` 模式支持从保存状态继续，自动推进 scene cursor
- 长文章节级处理：`chunking` 切章节、`reconcile` 跨章合并、`audit_report` 生成报告；audit/extend 入口支持 `--range`、`--batch-size`、`--max-chapters`、input hash 校验
- 结构概览：OutlineUnit 提供 `--outline-only` 模式，并已接入长文 audit / extend 主管线（30+ 章时作为 Rebuild 结构先验）
- 结构一致性：audit Reconcile 阶段使用 outline 检查角色与 genre 一致性；`check_temporal_contradictions` 做时间矛盾检测（死亡后仍活跃 / 过期事实仍被持有 / 时间感知否定）
- 事实时间有效性：`FactEntry.validity_interval`（ValidityInterval，None=始终有效），to_prompt_line 渲染 `(第三章~第五章)` 后缀；旧 state（无该字段）可反序列化
- 写作风格：`novel style` 提炼 StyleProfile（量化分析 + LLM 质性提炼），compose/extend 注入续写 prompt；`--lint` 做 AI 味检查；风格库（`--name` 另存 / `--style` 跨小说引用）
- 状态检索：以当前 NarrativeState 为 query，从 FactLedger/ForeshadowGraph 检索 top-k 相关条目注入 Continue prompt（【相关事实检索】段）；零依赖 TF-IDF/关键词（档 1）；`--retrieval on|off` 开关（默认 on，空语料/空 query 静默降级字节不变）
- 统一入口：`novel` 命令管理 `novels/<小说名>/` 工作目录，并调用 audit / extend / compose / style / compliance / rubric staged CLI
- 测试：1540 passed

## 怎么用（在 Codex 中）

### 准备

```bash
pip install -e .
```

### Audit 流（审核已有文本）

```bash
novel audit 示例小说甲 --input 示例小说甲.txt
```

- 第一次运行生成 `novels/示例小说甲/output/rebuild_prompt.txt` → 你生成响应保存到对应 response 文件 → 重跑
- 第二次生成 review prompt → 保存 review response → 重跑
- 完成，产物在 `novels/示例小说甲/output/`

长文用法：

```bash
novel audit 示例小说甲 --input 示例小说甲.txt --range 1-50 --batch-size 5
novel audit 示例小说甲 --outline-only   # 仅产出结构概览
```

### Extend 流（续写）

```bash
novel extend 示例小说乙 --input 示例小说乙.txt
```

- 三次重跑（Rebuild → Continue → Review）
- 产物：`novels/示例小说乙/output/extend_result.json`

### Compose 流（从 WorkSpec 创作）

```bash
novel compose 仙侠新作
novel compose 仙侠新作 --workspec workspec.json
```

- 两次重跑（Continue → Review）
- 产物：`novels/仙侠新作/output/compose_result.json`

### Style 流（写作风格提炼）

```bash
novel style 示例小说丙 --input 示例小说丙.txt
novel style 示例小说丙 --input 示例小说丙.txt --tone 克制 --genre 仙侠 --lint
```

- 两次重跑（量化分析 → LLM 提炼 → 合并）
- 产物：`novels/示例小说丙/output/style/style_profile.json`；`--lint` 额外产出 `style_lint_report.json`
- compose/extend 的 Continue 会自动读取 `output/style/style_profile.json`，以【写作风格】段注入续写 prompt（无档案时不注入，输出字节不变）

风格库（命名复用，跨小说）：

```bash
novel style 示例小说丙 --input 示例小说丙.txt --name 克制风      # 另存到 novels/_style_library/克制风.json
novel style 示例小说丙 --style 克制风 --lint                 # 引用库档案做禁忌词 lint（跳过提炼）
novel compose 新作 --style 克制风                        # 新小说注入库档案
novel extend 续作 --style 克制风                         # 续写注入库档案
```

- `--name NAME` 把提炼结果另存为命名档案到 `novels/_style_library/<name>.json`
- `--style NAME` 引用库中已有档案：style 流跳过提炼直接按禁忌词 lint；compose/extend 的 Continue 注入该档案
- 未指定 `--style` 时 compose/extend 回落到小说自身的 `output/style/style_profile.json`

### 状态检索（compose / extend 的 Continue 注入）

```bash
novel compose 新作 --retrieval off   # 关闭检索注入
novel extend 续作 --retrieval on     # 显式开启（默认即 on）
```

- 以当前 NarrativeState 为 query，从 FactLedger / ForeshadowGraph 检索 top-k 相关条目，以【相关事实检索】段注入续写 prompt
- `--retrieval on|off`（默认 on，对齐 compliance `--sensitive` 开关先例）；`--retrieval off` 是运行时回滚旋钮
- 零依赖（纯 stdlib）TF-IDF/关键词：中文无分词走字符 2-gram，实体 ID 原样精确匹配；`current_facts_in_scope` 软 boost、伏笔仅取 `linked_open_threads` 交集
- 静默降级：空 query / 空语料 / 全零分返回空串，此时 prompt 字节与旧版逐字节相同（回归测试锁死）

### Compliance 流（内容合规扫描）

```bash
novel compliance 某作 --input 某作.txt --platform 通用
novel compliance 某作 --input 某作.txt --sensitive off      # 关闭词库扫描
novel compliance 某作 --input 某作.txt --lexicon custom.json # 合并自定义词库
```

- **单遍扫描**（纯代码，无 response 阶段）：扫已有正文，产出 `compliance_report.json`（含 `route: "pass"`、risk_level、max_severity、位置锚点、分类、严重级、替换建议）
- `--platform 通用|番茄|起点|晋江`（默认 通用，未知回退通用）；`--sensitive on|off`（默认 on，off 时跳过词库扫描、platform 政策检查仍跑）
- `--lexicon FILE` 合并自定义敏感词条目（与内置词库去重）
- 章节字数下限：并入平台政策检查，每章去空白字符数低于平台 `chapter_length_target` 下限时产出 `compliance_chapter_length_<n>` warning issue（`--sensitive off` 时仍检查；route 保持 pass）
- prose 模式扫输入 .txt；无正文场景降级 object 模式扫 PlotUnit 字段（genre/hook/conflict）
- 注意：词库命中是风险提示不是平台封禁保证

### Rubric 流（WebNovelBench 8 维本地评测 rubric 导出）

```bash
novel rubric 某作
```

- **单遍导出**（纯代码，无输入文件 / 无 response 阶段）：产出 `novels/某作/output/rubric/rubric.json`
- 把 ReviewUnit domain rules + `web_fiction.py` 领域知识按 WebNovelBench 8 维（arXiv:2505.14818）映射，`offline:true`
- 诚实标注：角色一致性 / 跨场景衔接 strong，意境 / 语境 moderate，修辞 weak（负向代理），感官 / 角色平衡 / 对白独特 none（LLM-judge 维，对象层无正文文本）

### Codex 提示词（直接复制使用）

审核小说：
执行以下循环直到脚本完成：1. 运行 novel audit 示例小说甲 --input 示例小说甲.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说甲/output/ 中最终产物的 route 和 issues 数量

续写小说：
执行以下循环直到脚本完成：1. 运行 novel extend 示例小说乙 --input 示例小说乙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说乙/output/ 中最终产物的 route 和 PlotUnit 概要

从零创作：
执行以下循环直到脚本完成：1. 运行 novel compose 仙侠新作 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/仙侠新作/output/ 中最终产物的 route 和 PlotUnit 概要

提炼写作风格：
执行以下循环直到脚本完成：1. 运行 novel style 示例小说丙 --input 示例小说丙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说丙/output/style/style_profile.json 的 tone_labels、POV 和 stats 概要

把上面提示词中的小说名、输入文件路径替换为实际值即可。长文加 --range 1-50 --batch-size 5。

查看与断点续跑：

```bash
novel list
novel resume 示例小说甲
```

## 核心对象

`WorkSpec`, `WorldModel`, `CharacterModel`, `NarrativeState`, `PlotUnit`, `FactLedger`, `ForeshadowGraph`, `ReviewIssue`

- StyleProfile：写作风格档案（spec，非状态），随 `novel style` 产出，compose/extend 以「已确认先验」消费；`--name` 另存为命名库档案（`novels/_style_library/`），`--style` 跨小说引用
- PlotUnit 新增 `formula_node`：关联结构模板节点（如 climax），用于情绪推荐与钩子质量检查
- WorkSpec 新增 `platform`：目标平台标识（如 web_novel_daily），用于平台约束注入

## 注意事项

- 所有入口脚本在 response 文件缺失时会提示 `[WAITING]` 并正常退出，不会报错
- 重新运行同一脚本即可继续
- 测试：`pytest tests/ -q`
