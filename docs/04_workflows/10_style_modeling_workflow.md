# 写作风格建模 SOP（novel style）

**文档编号**：`docs/04_workflows/10_style_modeling_workflow.md`
**适用层级**：Tier 0 —— local staged CLI v0，operator-in-the-loop
**运行时**：`FileExchangeInterface`，response 文件由操作者/Codex 手动物化，不调用任何 LLM API
**前置**：`pip install -e .`，`novel style --help` 可用

本文档定义「为一部小说建立写作风格档案」的正式流程。**每部新书在 compose/extend 前，应先按本 SOP 建档案**，否则续写无风格先验、易自由发挥。

---

## 1. 风格档案是什么

`StyleProfile`（`novels/<名>/output/style/style_profile.json`）是「这部作品以什么风格写成」的规格（spec，不是状态）。由两部分合并：

- **量化（纯代码，词典规则引擎）**：句式指标（句长/长短句/对话占比/弱化副词等 16 项）+ **v2 叙事维度指标**（景物/感官/场景转换/心理/内独白/动作/叙述句占比，共 11 项，`schema_version=2`）
- **质性（LLM 提炼，response-file 循环）**：调性/视角/节奏/句式习惯/修辞偏好/情绪呈现/闭环物象/章末钩子/禁忌词 + **v2 叙事维度质性**（环境/景物描写、场景转换与过渡、心理与内视角、叙事节奏与结构 4 字段）

v2 后档案带 `schema_version: 2`；旧 v1 档案（无此字段）自动视为 v1，**可继续反序列化，不升级不报错**。

---

## 2. 输入准备（S1）

| 检查项 | 验收标准 |
|---|---|
| 全文 txt | 分章 ≥ 10 章、总字数 ≥ 2 万，UTF-8 无 BOM |
| 章节格式 | 每章以「第X章 标题」起行（对齐 `split_by_chapters`） |
| 代表性 | 覆盖首/中/末，含至少一处环境描写、一处心理、一处对话 |

> 字数过少或章节过少时，量化指标方差大，验收时注意跨书对比可能失真。

---

## 3. 运行流程（S2-S4）

### S2 首次运行（量化 + 提炼 prompt）

```bash
novel style 某作 --input 某作.txt [--tone 克制] [--genre 都市]
```

脚本先做量化分析并打印全部指标（含 v2 叙事维度行），然后生成 `style_extract_prompt.txt` 并打印 `[WAITING]`。

量化输出应含（v2 后新增）：

```
- 景物名词密度: X/千字 | 景物句占比: X.XX
- 感官动词密度: X/千字
- 场景转换计数: X | 时间标记密度: X/千字
- 心理动词密度: X/千字 | 心理句占比: X.XX | 内独白句占比: X.XX
- 动作动词密度: X/千字 | 动作句占比: X.XX
- 叙述句占比: X.XX
```

### S3 物化 response

读取 `style_extract_prompt.txt`，按【输出格式】生成严格 JSON，保存到 `style_extract_response.txt`。

**v2 契约**：12 个必填字段（tone_labels/genre_guess/narrative_pov/pacing_description/sentence_habits/rhetorical_preferences/show_dont_tell_notes/closed_loop_objects/chapter_end_hook_notes/taboo_words/style_references/confidence_gaps）+ **4 个可选字段**：

| 字段 | 要求 |
|---|---|
| `environment_notes` | 环境/景物手法（白描/借景抒情/写实）+ 功能（交代时空/烘托情绪/转场），各 ≥ 1 条 |
| `scene_transition_notes` | 场景切换方式（显式标记/无痕切换/时间跳转）+ 段落衔接 |
| `psychology_notes` | 心理密度判断 + 直接/间接内独白 + show-don't-tell 深化 |
| `rhythm_notes` | 叙述/对话/动作/描写配比 + 事件推进方式（章末钩子已在 chapter_end_hook_notes） |

4 可选字段各 ≥ 2 条非空。缺省会被补空列表（旧 12 字段 response 仍可解析，向后兼容）。

### S4 复跑合并

```bash
novel style 某作 --input 某作.txt          # 读已物化 response，合并产出 style_profile.json
novel style 某作 --input 某作.txt --name 风格名   # 另存到 novels/_style_library/<风格名>.json 供跨小说复用
```

`style_profile.json` 应含 `"schema_version": 2`。

---

## 4. 验收（S5）

| 验收点 | 标准 |
|---|---|
| schema 版本 | `schema_version == 2` |
| 质性字段 | 4 个 v2 质性字段各 ≥ 2 条非空 |
| 量化字段 | stats 含全部 11 个 v2 叙事维度键，且非全零 |
| 同类型可比 | 与同类型书对比 `scenery_density_per_1000`、`psych_verb_density_per_1000`、`action_sentence_ratio`、`narration_sentence_ratio` 落同量级 |
| 转场合理带 | `scene_transition_count / 章节数` ∈ 合理带（都市 2-5、仙侠 1-3） |
| 异常回查 | 跨书偏差 > 10× → 疑 sampling/提炼，回查章节采样与 response |

> 阈值是**文档指导值**，不是代码 lint。量化密度是启发式，语义分类（白描/借景抒情/无痕切换）以 LLM 质性字段为准。

---

## 5. 注入回归（S6）

```bash
novel compose 某作 --style 风格名   # 跨小说引用库档案
novel compose 某作                 # 回落到 <book>/output/style/style_profile.json
```

- 续写 prompt 中【写作风格】段**恰好出现 1 次**，无【写作风格画像】内层头（双层段头已修复）
- 本地档案（非 `--style`）命中生效：`compose` 的 output_dir 会自动解析到 `<book>/output/style/style_profile.json`
- 空档案注入与旧版逐字节相同（静默降级契约）

---

## 6. 常见失败

| 症状 | 根因 | 处置 |
|---|---|---|
| `style_extract_response.txt` 解析失败（缺字段/多字段） | response 不满足 12 必填 + 4 可选契约 | 对照【输出格式】补/删字段，重新物化后复跑 |
| 量化全零 | 输入文本过短或词表未命中 | 换更长的全文输入；检查词表 `src/domain_layer/style_lexicon.py` 是否覆盖文体 |
| 跨书对比失真 | 采样未覆盖首/中/末 | 检查输入 txt 章节完整性 |
| `load_style_context` 返回空 | 档案不在 `<book>/output/style/style_profile.json` 或未建 | 先按 S1-S4 建档案，或 `--style` 引用库档案 |
