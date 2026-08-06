# Automatic Novel Narrative System · 自动小说叙事系统

An automatic novel narrative system that parses narrative structure, maintains narrative state, plans story progression, and reviews generated results.

一个自动小说叙事系统：解析叙事结构、维护叙事状态、规划故事推进、审查生成结果。

> **Tier 0 production-ready** — local staged CLI, operator-in-the-loop · **1829 tests passing** · checkpoint tag `v0.1.2-tier0`

---

## Project / 项目简介

The long-term goal is a system that can parse narrative structure, maintain narrative state, plan story progression, review generated results, and support rebuilding, continuation, rewriting, and later implementation work.

长期目标是让系统能够：解析叙事结构、维护叙事状态、规划故事推进、审查生成结果，并支持重建（Rebuild）、续写（Continue）、改写（Rewrite）及后续的落地实现工作。

The repository contains both a complete design layer (`docs/`) and a running implementation layer (`src/`). This is a current-state description, not a permanent restriction on later phases.

仓库同时包含完整的设计层（`docs/`）和可运行的实现层（`src/`）。这是当前状态的描述，而非对后续阶段的永久限制。

## Current Status / 当前状态

The repository is **Tier 0 production-ready — three-flow daily-production hardened**. All three implementation slices are code-complete and validated end-to-end:

仓库已达 **Tier 0 生产就绪 —— 三条流水线日常生产硬化**。三个实现切片全部代码完成并通过端到端验证：

- **Audit / 审核** (`audit_short_form`): Rebuild + Review pipeline — 从已有文本重建对象状态并审查
- **Extend / 续写** (`extend_short_form`): Rebuild + Continue + Review pipeline — 从已有文本续写
- **Compose / 创作** (`compose_short_form`): WorkSpec + Initialize + Continue + Review pipeline — 从创作规格写新作

Tier 0 生产就绪判定（2026-07-28 宣布）：

- production tier: `local staged CLI v0`（本地分阶段 CLI v0）
- full pytest baseline: 1829 tests passing（完整回归基线 1829 个测试通过）
- release record: `docs/00_project/releases/tier0-release.json`
- immutable checkpoint: git tag `v0.1.2-tier0`
- extend / compose canaries 均通过 `novel gate` 同四标准；聚合证据在 `docs/00_project/releases/tier0-three-flow-canary-aggregation.json`
- one-command regression gate: `python scripts/tier0_canary_regression.py`

Tier 0 边界仍然生效：

- DirectAPI 供应商调用未实现；闭环全自动仍未放开
- Tier 0 不是公开产品形态；release record 不替代 release tag / 不可变 checkpoint
- response 文件必须由操作者或 Codex 落地，脚本不自动调用模型

## 独立评估修复（2026-08-06）

2026-08-06 独立第三方评估（工程 + 读者陪审团双视角）确认 Top 缺陷后，按
`docs/00_project/41_evaluation_remediation_plan.md` 落地 F1–F8：

- **F1** 发布门禁基线同步（1791→1829，git_commit/tag 对齐）
- **F2** 风格库/源码/文档/测试 PII 脱敏 + `test_privacy_redline.py` 红线断言
- **F4** 续写篇幅对齐：prompt 注入章均目标（±35%），parse_response 低于下界仅告警不阻断
- **F5** 续写原文去重：`find_overlapping_spans` 检出 ≥30 字符逐字重叠写入 `prose_overlap`
- **F3a** Review 挂 prose 复核：伏笔/承诺/后果/角色 issue 做正文兑现标注（不改 route）
- **F6** 时间锚扩窗：首段 220→800 字符 + 全文相对时间兜底（TimeAnchor.relative）
- **F7** 核实为误报（`_tokenize` 每 doc 仅一次），按计划降级不修
- **F8** `novel_cli.py` 拆分：校验簇 → `src/cli/validation.py`（3851 → 1480 行）

基线：**1829 tests passing**（测试数自 1792 起同步 6 文档 + 2 release record）。

## Features / 功能特性

- **三流完成**：audit（审核）、extend（续写）、compose（创作）
- **领域层**：genre formula、hook taxonomy、情绪弧模板、结构节点-情绪映射、关键节点钩子质量要求、平台约束、genre 规则
- **长程编排**：NarrativeFrameUnit 维护 book/arc/chapter/scene 层级
- **增量续写**：`--resume` 模式从保存状态继续，自动推进 scene cursor
- **长文章节级处理**：`chunking` 切章节、`reconcile` 跨章合并、`audit_report` 生成报告；支持 `--range`、`--batch-size`、`--max-chapters`、input hash 校验
- **结构概览**：OutlineUnit `--outline-only`；30+ 章长文 audit / extend 自动作为 Rebuild 结构先验
- **结构一致性**：Reconcile 用 outline 检查角色与 genre 一致性；`check_temporal_contradictions` 做时间矛盾检测（死亡后仍活跃 / 过期事实仍被持有 / 时间感知否定）
- **信息凭证一致性**：六通道谱系（亲历/转述/书面/公开/推断/记忆）+ P1-P4 凭证约束；`iss_info_*` 弱信号（转述产亲历细节 / 转述时效 / 知识域翻转）
- **事实时间有效性**：`FactEntry.validity_interval`，`to_prompt_line` 渲染 `(第三章~第五章)` 后缀；旧 state 可反序列化
- **写作风格**：`novel style` 提炼 StyleProfile（量化分析 + LLM 质性提炼），compose/extend 注入续写 prompt；`--lint` 做 AI 味检查；风格库 `--name` 另存 / `--style` 跨小说引用
- **状态检索**：以当前 NarrativeState 为 query，从 FactLedger/ForeshadowGraph 检索 top-k 相关条目注入 Continue prompt；零依赖 TF-IDF/关键词；`--retrieval on|off`（默认 on，空语料/空 query 静默降级字节不变）
- **时间域**：TimeBook 先验模型 + `novel time` 管理（--rebuild 锚提取 / --check 时间线报告 / --status）；FACTTRACK v2 检测时间回退 / 先知逾期 / 季节历法违反；Continue 以【时间上下文】段注入
- **零成本契约**：无 TimeBook → 无注入、无检测、无产物，prompt 字节与旧版逐字节相同（回归测试锁死）
- **统一入口**：`novel` 命令管理 `novels/<小说名>/` 工作目录，并调用 audit / extend / compose / style / compliance / rubric / time staged CLI
- **CLI 拆分**：`src/novel_cli.py` 编排层（NovelArgumentParser / 各流 dispatch / run_config 恢复）保留，常量 + staged JSON/list/gate/approval 校验簇拆入 `src/cli/validation.py`（`__all__` 重导出）；命令名/参数/默认值/退出码/`--help` 逐字节不变
- **内容合规**：`novel compliance` 单遍扫描，产出合规报告（风险等级/位置锚点/严重级/替换建议）
- **NSFW 内容分级开关**：compose/extend `--nsfw on|off`（默认 off 正常向，注入禁成人内容分级；on 允许成人向）+ compliance `--nsfw on|off`（on 跳过「涉黄」分类扫描）贯通创作与审核一套语义
- **离线评测**：`novel rubric` 导出 WebNovelBench 8 维本地 rubric（装配时间一致性后 9 维）

## Install / 安装

```bash
pip install -e .
```

## Usage / 使用

The preferred entry point is `novel`, a thin wrapper around the Codex-native staged workflows. It creates `novels/<name>/`, copies the input into that workspace, writes intermediate files under `novels/<name>/output/<mode>/`, and calls the underlying short-form script.

首选入口是 `novel` —— 围绕 Codex 分阶段工作流的统一封装。它在 `novels/<小说名>/` 下创建工作区、复制输入、在 `output/<mode>/` 写中间文件，并调用底层脚本。章节正文统一写入 `novels/<小说名>/chapters/`。

**Codex 分阶段循环**（所有有 response 阶段的命令通用）：

1. 运行 `novel <mode> <小说名> [参数]`
2. 若打印 `[WAITING]`，读取它指定的 prompt 文件，按提示生成 JSON 响应
3. 保存到对应的 response 文件，重跑同一命令
4. 重复直到脚本正常退出，报告产物路径与 route / issues 概要

### Audit 审核已有文本

```bash
novel audit 示例小说甲 --input 示例小说甲.txt
novel audit 示例小说甲 --input 示例小说甲.txt --range 1-50 --batch-size 5   # 长文分章
novel audit 示例小说甲 --outline-only                                        # 仅结构概览
```

### Extend 续写已有文本

```bash
novel extend 示例小说乙 --input 示例小说乙.txt
novel extend 示例小说乙 --input 示例小说乙.txt --nsfw on   # 允许成人向（默认 off 正常向）
```

- 三次重跑（Rebuild → Continue → Review）；章节正文写入 `novels/示例小说乙/chapters/chapter_<编号>.txt`
- 续写从原文章节后一编号续起，篇幅对齐原文章均，参考原文语感与意象系统

### Compose 从 WorkSpec 创作

```bash
novel compose 仙侠新作
novel compose 仙侠新作 --workspec workspec.json
novel compose 仙侠新作 --nsfw on    # 允许成人向（默认 off 正常向）
```

### Style 写作风格提炼

```bash
novel style 示例小说丙 --input 示例小说丙.txt                    # 提炼 → 自动入库
novel style 示例小说丙 --input 示例小说丙.txt --name 克制风       # 另存为命名档案
novel style 示例小说丙 --style 克制风 --lint                  # 引用库档案做禁忌词 lint
novel style 某作 --style-search "人物:衬托"                     # 检索风格库档案
```

### Compliance 内容合规扫描

```bash
novel compliance 某作 --input 某作.txt --platform 通用
novel compliance 某作 --input 某作.txt --sensitive off      # 关闭词库扫描
novel compliance 某作 --input 某作.txt --nsfw on            # 跳过涉黄分类（成人向作品）
novel compliance 某作 --input 某作.txt --lexicon custom.json # 合并自定义词库
```

### Rubric 离线评测 rubric 导出

```bash
novel rubric 某作
```

### Time 时间域管理

```bash
novel time 某作 --input 某作.txt --rebuild   # 提取时间锚点，生成 time_book.json
novel time 某作 --input 某作.txt --check     # 产出时间线报告
novel time 某作 --status                     # 打印 TimeBook 状态
```

### 任务查看与断点续跑

```bash
novel list
novel resume 示例小说甲
novel pending <name> --json      # 只读列出待处理 prompt/response 槽位
novel respond <name> --response-file response.json   # 落地已有响应文件
novel gate <name> --json         # 只读编排门卫判定
```

### 常用开关

```bash
novel compose 新作 --retrieval off   # 关闭状态检索注入（默认 on）
novel --help && novel audit --help   # 查看各子命令帮助
pytest tests/ -q                     # 跑完整回归测试
```

## Core Objects / 核心对象

- `WorkSpec` — 创作规格（genre/theme/tone/platform/时间）
- `WorldModel` — 世界模型
- `CharacterModel` — 角色模型
- `NarrativeState` — 叙事状态
- `PlotUnit` — 情节单元（含 `formula_node` 结构节点关联）
- `FactLedger` — 事实账本（含 `validity_interval` 时间有效性）
- `ForeshadowGraph` — 伏笔图
- `ReviewIssue` — 审查问题
- `StyleProfile` — 写作风格档案（spec，非状态；`--name` 存风格库）
- `TimeBook` — 时间域先验模型（spec，非状态；全字段 Optional，缺省零成本）

## Core Judgments / 核心判断

- State first, text second. 状态先行，文本其后。
- Facts must be separated from inference. 事实必须与推断分离。
- A `PlotUnit` is only valid if it causes meaningful state change. `PlotUnit` 只有在引发有意义的状态变化时才有效。
- `Review` is the routing hub of the operational workflows. `Review` 是运营工作流的路由枢纽。
- Formal `Rewrite` should be issue-driven, not feeling-driven. 正式 `Rewrite` 应由问题驱动，而非感觉驱动。

## Workflow Map / 工作流

- `Rebuild` — reconstruct object state from existing text / 从已有文本重建对象状态
- `Review` — judge validity, classify failures, route next action / 判定有效性、分类失败、路由下一动作
- `Continue` — generate the next valid progression / 从当前状态生成下一个有效推进
- `Rewrite` — apply minimal repair based on formal issues / 基于正式问题做最小修复

## Privacy & Repository Discipline / 隐私与仓库纪律

All concrete novel information — titles, prose, characters, workspace names, author pen names — stays **out of this repository**. GitHub holds only the tooling framework (code, tests, scripts, rule docs, run configs, and the neutral style-library accumulation).

所有具体小说信息（标题、正文、角色、工作区名、作者笔名）一律不进入本仓库。GitHub 仅保留工具框架（代码、测试、脚本、规则文档、运行配置、中性命名的风格库积累）。

- Novel workspaces live locally under `novels/<name>/` and are gitignored（`novels/*/` 已入 `.gitignore`，canary 证据目录反向放行）；正文仅存本地
- Writing-style accumulation may be committed as neutral files under `style_library/<name>.json`（不含小说名/作者笔名/机器路径）
- If novel-specific content ever lands in git history, rewrite the history with `git filter-repo` before pushing（本项目已按此执行并 force-push）

## Read First / 新手指引

New to the repository? Read in this order:

1. `AGENTS.md`
2. `docs/00_project/02_agent_quickstart.md`
3. `docs/00_project/03_current_status.md`
4. `docs/00_project/29_automation_readiness_boundary.md`
5. `docs/00_project/30_production_readiness_checklist.md`
6. `docs/00_project/31_tier0_canary_runbook.md`
7. `docs/00_project/32_tier0_release_record_contract.md`

## Tests / 测试

```bash
pytest tests/ -q
```

Baseline: **1829 tests passing**（Windows 下测试请带 `PYTHONIOENCODING=utf-8`）。
