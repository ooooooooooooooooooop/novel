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
- 结构一致性：audit Reconcile 阶段使用 outline 检查角色与 genre 一致性
- 统一入口：`novel` 命令管理 `novels/<小说名>/` 工作目录，并调用 audit / extend / compose staged CLI
- 测试：1248 passed

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

### Codex 提示词（直接复制使用）

审核小说：
执行以下循环直到脚本完成：1. 运行 novel audit 示例小说甲 --input 示例小说甲.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说甲/output/ 中最终产物的 route 和 issues 数量

续写小说：
执行以下循环直到脚本完成：1. 运行 novel extend 示例小说乙 --input 示例小说乙.txt 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/示例小说乙/output/ 中最终产物的 route 和 PlotUnit 概要

从零创作：
执行以下循环直到脚本完成：1. 运行 novel compose 仙侠新作 2. 如果脚本打印 [WAITING]，读取它指定的 prompt 文件，按 prompt 要求生成 JSON 响应，保存到对应 response 文件 3. 重跑同一命令 4. 重复 2-3 直到脚本正常退出 5. 报告 novels/仙侠新作/output/ 中最终产物的 route 和 PlotUnit 概要

把上面提示词中的小说名、输入文件路径替换为实际值即可。长文加 --range 1-50 --batch-size 5。

查看与断点续跑：

```bash
novel list
novel resume 示例小说甲
```

## 核心对象

`WorkSpec`, `WorldModel`, `CharacterModel`, `NarrativeState`, `PlotUnit`, `FactLedger`, `ForeshadowGraph`, `ReviewIssue`

- PlotUnit 新增 `formula_node`：关联结构模板节点（如 climax），用于情绪推荐与钩子质量检查
- WorkSpec 新增 `platform`：目标平台标识（如 web_novel_daily），用于平台约束注入

## 注意事项

- 所有入口脚本在 response 文件缺失时会提示 `[WAITING]` 并正常退出，不会报错
- 重新运行同一脚本即可继续
- 测试：`pytest tests/ -q`
