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
- 信息凭证一致性：`09_information_warrant_rules.md` 定义"角色凭什么知道"（通道/时效/来源）；`info_warrant_knowledge.py` 存六通道谱系（亲历/转述/书面/公开/推断/记忆）+ P1-P4 凭证约束；review 弱信号检测 iss_info_channel（转述产亲历细节）/ iss_info_relay（转述时效）/ iss_info_scope（知识域翻转），与 `05_information_release_rules.md`（该不该知道）正交互补
- 事实时间有效性：`FactEntry.validity_interval`（ValidityInterval，None=始终有效），to_prompt_line 渲染 `(第三章~第五章)` 后缀；旧 state（无该字段）可反序列化
- 写作风格：`novel style` 提炼 StyleProfile（量化分析 + LLM 质性提炼），compose/extend 注入续写 prompt；`--lint` 做 AI 味检查；风格库（`--name` 另存 / `--style` 跨小说引用）
- 读者体验：`10_reader_experience_rules.md` 定义正文层 7 维判定标准（开头/现场感/解释/对白/情绪/反馈/钩子）；`novel reader` 做分级标注（good/needs_work/weak，route=none 不阻断）+ 派生读者预期台账（ReaderExpectationLedger：读者在等什么，waiting/advanced/overdue/stale）；与一致性审查（ReviewUnit 可阻断）并行分离
- 动态角色建模：CharacterModel 支持 current_pressure（当前压力）/ change_trajectory（变化轨迹）/ relation_behaviors（关系→行为差异，同一角色对不同人行为不同）；Optional/default 向后兼容，空字段不渲染零回归
- 场景体验中间层：PlotUnit.scene_experience（SceneExperience：主角看见/阻碍/选择依据/结果/认知变化五维），Continue 生成、Prose 展开注入，让结构扩写带现场感
- 状态检索：以当前 NarrativeState 为 query，从 FactLedger/ForeshadowGraph 检索 top-k 相关条目注入 Continue prompt（【相关事实检索】段）；零依赖 TF-IDF/关键词（档 1）；`--retrieval on|off` 开关（默认 on，空语料/空 query 静默降级字节不变）
- 时间域：TimeBook 先验模型（`novels/<名>/output/time/time_book.json`），`novel time` 管理（--rebuild 锚提取 / --check 时间线报告 / --status）；FACTTRACK v2 检测 4/5/6（时间回退 / 先知逾期 / 季节历法违反）；extend/compose 的 Continue 以【时间上下文】段注入上章/本章/时代背景/时间规则；rubric 装配时间一致性维（8→9 维）
- 零成本契约：无 TimeBook → 无注入、无检测、无产物，prompt 字节与旧版逐字节相同（回归测试锁死）
- 内容分级（NSFW 开关）：贯通创作与审核一套语义——compose/extend `--nsfw on|off`（默认 off 正常向：off 时 Continue prompt 注入【内容分级】禁成人内容硬规则，on 时注入成人向授权）；compliance `--nsfw on|off`（默认 off：on 时跳过「涉黄」分类扫描，其余分类仍扫）；build_prompt 的 nsfw_context 缺省空串零成本不注入
- 统一入口：`novel` 命令管理 `novels/<小说名>/` 工作目录，并调用 audit / extend / compose / style / compliance / rubric / time staged CLI
- 编辑人机回环：`novel gate --require-approval` 让 severity=critical 的 ReviewIssue 必须操作者人工 approve/reject（`approval_decision.json`）才推进；全 approve 跳转 ContinueUnit、blocking issue 严格不可审批（`src/boundary_control/approval_gate.py`）
- 章节正文目录：续写/创作的章节正文统一存 `novels/<小说名>/chapters/`（如 `chapters/chapter_1197.txt`），与 `output/` 系统产物分离；小说工作区一律不提交 GitHub（`novels/*/` 已入 `.gitignore`，canary 证据目录 `novels/tier0-*-canary/` 反向放行），GitHub 仅保留工具框架（代码/测试/脚本/规则文档/运行配置/风格库积累）
- 续写篇幅与原文参考：有原文时，原文按章拆分入 `chapters/chapter_01.txt` 起（保留章节标题行），续写从下一编号续（原文 23 章 → 续写从 `chapter_24` 起），目录内编号连续；续写章节篇幅对齐原文章均（参考值：《示例小说丁》约 6,500 字符/章），不得明显偏短；续写须参考原文语感、意象系统（杨柳/水/套装/信等）与事件细节，不能凭空脱离原文
- 隐私纪律：所有具体小说信息（标题、正文、角色、工作区名、作者笔名）一律不提交 GitHub；git 历史中如有此类内容，push 前须用 `git filter-repo --path-*` 完整重写历史剔除（本项目已按此重写并 force-push）；正文仅存本地 `novels/<小说名>/chapters/`；写作风格综合积累可入库，统一放仓库根 `style_library/<name>.json`（中性文件名，不含小说名/作者笔名/机器路径）
- 测试：2123 passed

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
- 产物：`novels/示例小说乙/output/extend_result.json`；章节正文（PlotUnit 展开成文）统一写入 `novels/示例小说乙/chapters/`，命名 `chapter_<编号>.txt`

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

风格库（自动入库 + 中性命名 + 相似度去重 + 检索）：

```bash
novel style 示例小说丙 --input 示例小说丙.txt                # 自动入库 → style_library/克制-官商-001.json
novel style 示例小说丙 --input 示例小说丙.txt --name 克制风    # 另存到 style_library/克制风.json
novel style 示例小说丙 --style 克制风 --lint               # 引用库档案做禁忌词 lint（跳过提炼）
novel style 某作 --style-search "人物:衬托"                # 检索库内档案 id（支持 "要素:手法" 语法，如 描写:白描 / 对白:潜文本）
novel style 示例小说丙 --input 示例小说丙.txt --force        # 入库时忽略相似度提示，强制新建
novel style 示例小说丙 --input 示例小说丙.txt --no-library   # 只提炼不写库
novel compose 新作 --style 克制-官商-001                  # 新小说注入库档案（id 或文件名均可）
novel extend 续作 --style 克制风                          # 续写注入库档案
```

- 自动入库：未指定 `--name` 时，提炼结果自动生成风格化中性 id `<tone>-<genre>-<seq>`（如 `克制-官商-001`），写入 `style_library/<id>.json` 并登记到 `style_library/manifest.json`（语义索引，跨小说检索/引用用）
- 相似度去重：入库前与库内档案算相似度（数值 60% + 分类 20% + 质性 20%），≥ 0.90 且未 `--force` 时提示 `--style <top_id>` 复用，不盲目新建，避免库无限扩张
- `--name NAME` 把提炼结果另存为命名档案到 `style_library/<name>.json`（同样登记 manifest）
- `--style NAME` 引用库中已有档案（两路解析：manifest.id 优先，其次物理文件名）：style 流跳过提炼直接按禁忌词 lint；compose/extend 的 Continue 注入该档案
- `--style-search QUERY` 在 manifest 上做关键词检索（tone/genre/POV/句式/手法笔记），列出候选 id 后退出；支持 `"要素:手法"` 语法（如 `人物:衬托`、`描写:白描`），不要求输入文本
- `--force` 忽略相似度去重提示强制新建；`--no-library` 只提炼不写库
- 未指定 `--style` 时 compose/extend 回落到小说自身的 `output/style/style_profile.json`
- 隐私：id 只含风格词，manifest 不含作品名/作者名/路径；风格库是允许入库的中性积累

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
novel compliance 某作 --input 某作.txt --nsfw on            # 跳过涉黄分类（成人向作品）
novel compliance 某作 --input 某作.txt --lexicon custom.json # 合并自定义词库
```

- **单遍扫描**（纯代码，无 response 阶段）：扫已有正文，产出 `compliance_report.json`（含 `route: "pass"`、risk_level、max_severity、位置锚点、分类、严重级、替换建议）
- `--platform 通用|番茄|起点|晋江`（默认 通用，未知回退通用）；`--sensitive on|off`（默认 on，off 时跳过词库扫描、platform 政策检查仍跑）
- `--nsfw on|off`（默认 off；on 时跳过「涉黄」分类扫描，其余分类仍扫；与 compose/extend 生成侧 `--nsfw` 联动——正常向作品扫描涉黄、成人向作品放行涉黄）
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
- 若有 `output/time/timeline_report.json`，自动装配时间一致性维（wnb_09），8 维 → 9 维

### Reader 流（读者体验审查：章节正文 7 维分级标注）

```bash
novel reader 某作 --input novels/某作/chapters/chapter_1.txt   # 对第一章做读者体验审查
novel reader 某作 --input ... --no-expectations                 # 跳过读者预期台账
novel reader 某作 --input ... --style 克制风                    # 引用风格库档案辅助判断
```

- **两遍式**（对齐 style：量化代理分析纯代码 + LLM 质性分级标注的 [WAITING] 循环）：产出 `novels/某作/output/reader_experience/reader_report.json`
- 7 维判定标准（`docs/03_rules/10_reader_experience_rules.md`）：开头拖沓 / 场景现场感 / 解释过多 / 对白自然 / 情绪落地 / 高潮反馈 / 章末钩子，每维 good/needs_work/weak 分级 + 位置锚点 + 诊断 + 改法方向
- **route 恒为 none 不阻断**——正文质量是连续光谱，供人工/精修参考（与一致性审查 ReviewIssue 可阻断分离）
- 默认自动派生读者预期台账：从该小说 `output/extend/extend_rebuild_package.json` 的 ForeshadowGraph 生成「读者在等什么」清单（waiting/advanced/overdue/stale），写入 `reader_expectations.json`
- 复用：`recheck_against_prose`（F3a 正文相关度）为雏形、`analyze_style_metrics` 量化代理、`load_style_context` 风格档案

### Time 流（时间域：锚提取 / 时间线报告 / 状态查看）

```bash
novel time 某作 --input 某作.txt --rebuild   # 提取时间锚点，生成 time_book.json（无则创建，有则校准）
novel time 某作 --input 某作.txt --check     # 产出 output/time/timeline_report.json
novel time 某作 --status                     # 打印 TimeBook 状态（novel list 亦展示 time_status）
```

- **单遍执行**（纯代码，无 response 阶段）：`--rebuild` 是显式管理命令（split_by_chapters 切章 + 提取章节时间锚点）；`--check` 跑 build_timeline_report 写出时间线报告
- TimeBook 存 `novels/某作/output/time/time_book.json`（全 Optional，schema_version / initial / anchors / era / timelines / rules）
- 零成本契约：无 TimeBook 时 audit/extend 自动校准是 no-op、无【时间上下文】注入、无时间检测、无文件产出，prompt 字节不变
- compose 从 `workspec.time`（date/lunar/loc）初始化 TimeBook 初稿（无该字段 / 已有 TimeBook 时零成本）
- FACTTRACK v2 检测 4/5/6（anchor 时间回退 / 伏笔时间线逾期 / 季节历法违反）并入 run_time_audit，全 warning 非阻断

### Codex 提示词（直接复制使用）

审核小说：
执行以下循环直到脚本完成：1. 运行 novel audit 示例小说甲 --input 示例小说甲.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说甲/output/ 中最终产物的 route 和 issues 数量

续写小说：
执行以下循环直到脚本完成：1. 运行 novel extend 示例小说乙 --input 示例小说乙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说乙/output/ 中最终产物的 route 和 PlotUnit 概要

从零创作：
执行以下循环直到脚本完成：1. 运行 novel compose 仙侠新作 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/仙侠新作/output/ 中最终产物的 route 和 PlotUnit 概要

提炼写作风格：
执行以下循环直到脚本完成：1. 运行 novel style 示例小说丙 --input 示例小说丙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说丙/output/style/style_profile.json 的 tone_labels、POV 和 stats 概要

时间锚提取与时间线报告：
执行以下循环直到脚本完成：1. 运行 novel time 某作 --input 某作.txt --rebuild 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/某作/output/time/time_book.json 的 anchors 数量和 era 概要。若需时间线报告再加 --check，读 output/time/timeline_report.json 的 issues 数量

把上面提示词中的小说名、输入文件路径替换为实际值即可。长文加 --range 1-50 --batch-size 5。

查看与断点续跑：

```bash
novel list
novel resume 示例小说甲
```

## 核心对象

`WorkSpec`, `WorldModel`, `CharacterModel`, `NarrativeState`, `PlotUnit`, `FactLedger`, `ForeshadowGraph`, `ReviewIssue`

- StyleProfile：写作风格档案（spec，非状态），随 `novel style` 产出，compose/extend 以「已确认先验」消费；`--name` 另存为命名库档案（`style_library/`），`--style` 跨小说引用
- TimeBook：时间域先验模型（spec，非状态），随 `novel time --rebuild` / compose workspec.time 产出，extend/compose 以【时间上下文】注入消费；全字段 Optional，缺省零成本
- PlotUnit 新增 `formula_node`：关联结构模板节点（如 climax），用于情绪推荐与钩子质量检查
- WorkSpec 新增 `platform`：目标平台标识（如 web_novel_daily），用于平台约束注入

## 注意事项

- 所有入口脚本在 response 文件缺失时会提示 `[WAITING]` 并正常退出，不会报错
- 重新运行同一脚本即可继续
- 测试：`pytest tests/ -q`
