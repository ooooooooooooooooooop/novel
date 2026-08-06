# 独立评估缺陷落地实施计划（Evaluation Remediation Plan）

## Purpose

基于 2026-08-06 独立第三方评估（工程 + 读者陪审团双视角），把评估确认的 Top 5 真实缺陷落成可执行、有 file:line 锚点、带验证标准的实施计划。

**本文档只列计划，不含实施代码。** 每条 Fix 均已对照活代码探明落点；执行者按「修改点 / 验证 / 守纪门」逐项落地。

**范围说明**：按「尽可能修复所有客观确认的缺陷」而非主观 Top5 展开。分两类——
- **F1–F8**：客观确认的缺陷（代码/证据锚定），全部落地
- **V1–V4**：评估「声称已实现但未验证」清单中**确实需要外部资源/数据**的项（读者留存回路、评测人类校准、lint 外部基准、audit 流实跑样本），代码侧无可修缺陷，属「补验证」而非「修缺陷」，单列不阻塞

## 守纪红线（每条 Fix 完成后必过）
- 基线数字变化须同步：`tests/test_cli_runtime_contract.py:14 EXPECTED_TEST_BASELINE`、`tests/test_release_record.py:30 EXPECTED_BASELINE`、6 文档（README/AGENTS/CLAUDE/03_current_status/tier0-release.json/tier0_release_record.example.json），有 `test_cli_runtime_contract.test_collected_test_baseline_matches_contract` 锁收集数
- 测试必带 `PYTHONIOENCODING=utf-8`（Windows cp936 控制台）
- 全量验证：`python scripts/tier0_canary_regression.py` + `pytest tests/ -q` 全绿
- **本批 Fix 均不改 novels/ 正文**，均为工具框架侧改动（可入库）

---

## 评估缺陷 → 修复映射总表

| Fix | 评估缺陷 | 评估维度 | 优先级 | 风险 | 类型 |
|---|---|---|---|---|---|
| F1 | 测试基线声称不符（1791≠1792） | D5 | P0 止血 | 中（动发布门禁） | 修缺陷 |
| F2 | 隐私红线被踩破（风格库/源码含真实角色名） | D7 | P0 红线 | 中（动风格库 schema） | 修缺陷 |
| F4 | 篇幅对齐无代码锁（2283–10730 漂移） | D10/D9 | P1 上架生死线 | 低（加 warning） | 修缺陷 |
| F5 | 续写搬运原文整段（AI 味唯一破绽） | D10/D9 | P1 | 低（prompt 约束） | 修缺陷 |
| F3a | Review 看不到正文（prose 已兑现伏笔仍报未推进）·保守 | D3/D10 | P2 最贵 | 中（只消噪声不改route） | 修缺陷 |
| F6 | 时间锚提取只扫首 220 字符，覆盖稀疏 | D3 | P2 | 低（改扫描范围） | 修缺陷 |
| F7 | retrieval 重复 O(N·d) tokenize，长文性能隐患 | D4 | P3 | 低（纯优化） | 修缺陷 |
| F8 | novel_cli.py 3851 行臃肿，可维护性 | D6 | P3 | 高（拆分需全面回归） | 修缺陷 |
| F3b | Review 移到 prose 后（结构性时序改动） | D3/D10 | P4 | 高（改时序，独立设计） | 结构性 |
| V1 | 读者/留存反馈回路未落地（盲点⑤） | D8 | — | 需平台后台数据 | 补验证 |
| V2 | 评测无人类校准（盲点⑥，单 LLM judge ρ≈0.4-0.6） | D8 | — | 需人类标注集 | 补验证 |
| V3 | --lint AI 味无外部基准校准（盲点④） | D8 | — | 需外部基准语料 | 补验证 |
| V4 | audit 流端到端本次无产出样本可验 | D2 | — | 需实跑一次 audit | 补验证 |

排序逻辑：F1/F2 是信誉与红线，先行；F4/F5/F6/F7 是「能上架/能跑稳」直接加分、低风险；F3a 杠杆高但改 review 判定，中单列会话；F8/F3b 高风险结构改动，最后。V1–V4 不属代码缺陷，列入待办但不进本批实施。

---

## F1 · 发布门禁测试修复（缺陷#1，D5）

**根因**：`tier0-release.json` 的 `release_tag_or_checkpoint: "v0.1.1-tier0"` 解析到旧 commit `da893a9`，HEAD 已前进到 `9009353`，而 `validate_tier0_release_record_git_checkpoint`（`src/boundary_control/release_record.py:1167-1171`）硬性要求 tag 解析到 `git_commit`。干净 checkout 上 `tests/test_release_record.py:1305 test_committed_release_record_combined_validation` 必红。

**这是「已在 handoff:107 记录过的坑又原样踩一次」**——基线迁移靠人肉纪律，缺工具。

### 方案 A（推荐，立即止血）
- 改 `docs/00_project/releases/tier0-release.json`：打新 tag（如 `v0.1.2-tier0`）指向当前 HEAD，把 `git_commit` 更新为 `git rev-parse HEAD`，`release_tag_or_checkpoint` 指向新 tag
- 保持 `release_record.py:1167` 的严格校验不变（这是正确的 invariant）

### 方案 B（结构性，推荐随 A 一起做）
- 新增 `scripts/sync_release_baseline.py`：一键完成 ①打 tag ②更新 tier0-release.json 的 git_commit ③重算 baseline 收集数写入两处常量 + 6 文档 ④跑 `--collect-only` 自检
- 把「改测试数必跑 sync 脚本」写进 CLAUDE.md 纪律段，替代「人肉同步 6 文档」

### 验证
- `pytest tests/test_release_record.py -q` 全绿（当前 1 failed → 0）
- `pytest tests/test_cli_runtime_contract.py::test_collected_test_baseline_matches_contract -q` 绿
- 全量 `pytest tests/ -q` 全绿，且文档自述「N passed」与实测一致

---

## F2 · 风格库 / 源码 PII 脱敏 + CI 红线（缺陷#2，D7）

**根因**：风格档案的质性字段（`narrative_pov`、`key_signatures`）把「以主角为锚」「配角的体量」原样入库。`git grep 主角 HEAD` 命中 6 个 tracked 文件：`style_library/manifest.json`、`style_library/style_001.json`、`src/domain_layer/info_warrant_knowledge.py`、`docs/03_rules/09_information_warrant_rules.md`、`tests/test_info_warrant.py`、`tests/test_failure_emission.py`。**与 CLAUDE.md「风格库中性命名、不含小说名/作者笔名」红线直接冲突。**

### 修改点
1. **脱敏工具**：新增 `src/domain_layer/style_redact.py`
   - `redact_profile(profile, entity_terms: list[str]) -> profile`：对 `narrative_pov` / `key_signatures` / 质性笔记字段做实体替换（角色名→`角色A/B…`、专名→`<专名>`），用占位符映射表
   - `entity_terms` 来源：提炼阶段的 `CharacterModel` 名 + WorkSpec 关键词，或 `--redact "主角,配角,<地名>"` 显式传入
2. **接入入库路径**：`src/style_short_form.py:298-306`（写 `style_library/<id>.json` + `upsert_style_manifest`）与 `src/workflow_action/style.py:686 upsert_style_manifest` 之前调用 `redact_profile`
3. **存量清洗**：重写 `style_library/style_001.json` / `style_001_v2.json` / `manifest.json` 为脱敏版
4. **历史信息源**：`info_warrant_knowledge.py:15`、`09_information_warrant_rules.md`、`test_info_warrant.py`、`test_failure_emission.py` 中的真实角色名替换为中性占位（这些是把真实事故复盘直接当注释/测试用例，属同类泄漏）
5. **CI 红线**：新增 `tests/test_privacy_redline.py`
   - 断言 `git grep <entity> HEAD`（entity 从风格库语料提取的角色名清单）在 `style_library/`、`src/`、`docs/`、`tests/` 的 tracked 文件中零命中
   - 注意：`git filter-repo` 不重写 HEAD 树内当前文件——必须先改文件内容再提交；历史深层的泄漏（`git log --all -p` 中 主角×32769）若需彻底清除，按 handoff:36 的 filter-repo 流程重写，**此步单独评估、不在本 Fix 默认范围**

### 验证
- `git grep 主角 HEAD -- style_library/ src/ docs/ tests/` → 空
- `pytest tests/test_privacy_redline.py -q` 绿
- 提炼一部含真实角色的作品 → 入库档案 `narrative_pov`/`key_signatures` 中无原角色名
- 守纪门：baseline 变化走 F1 sync 流程

---

## F4 · 续写篇幅对齐硬约束（缺陷#4，D10/D9）

**根因**：CLAUDE.md 自述「约 6,500 字符/章、对齐原文章均、不得明显偏短」，但全代码库 grep 不到任何数值锁。`src/workflow_action/prose.py:77` 仅软文案「篇幅与上下文风格匹配，不得明显偏短」，`prose.py:18 MIN_PROSE_CHARS=200` 下限形同虚设。实测漂移：`《示例万物》` 20→23 章 10730/5177/3663/2283，`示例官商 1198` 4458——主编陪审员（#4）判「上架即因注水彩蛋」。

### 修改点
1. **算原文章均**：`src/workflow_action/prose.py` 新增
   - `def average_chapter_chars(chunks) -> int`：对 `split_by_chapters` 产物按 `chapter_index` 取每章去空白字符数的均值（无空白处理复用 `parse_response:110` 的 `"".join(split())` 口径）
   - `CHAPTER_LEN_TOLERANCE = 0.35`（±35% 容忍带，先宽后紧）
2. **注入 prompt**：`prose.py:53 build_prompt` 加 keyword 参数 `target_chapter_chars: int | None = None`；非 None 时在【硬性约束】插一条「本章目标篇幅约 N 字符（去空白），允许 ±35%，不得明显偏短或注水」。**零成本契约：None 时 prompt 字节与旧版一致**
3. **落盘校验**：`prose.py:101 parse_response` 加 `target_chars: int | None = None`；`compact_len < target*(1-0.35)` 时打印 `WARNING prose short: X chars (target ~N)`——**只 warning 不 raise**，避免打断 [WAITING] 流
4. **接线 extend**：`src/extend_short_form.py:633-642`（build_prompt 调用）与 `:648 parse_response` 传入 `average_chapter_chars(chunks)`（`chunks` 在 `:224` 已在作用域）
5. **接线 compose**：`src/compose_short_form.py:542-550`——compose 无原文 chunks，取 `workspec.length_target` 与既有章均的较小参考，或显式 `target=None`（零成本）。**compose 侧默认 None，先只覆盖 extend 续写**

### 验证
- 新增 `tests/test_prose_length_target.py`：①target=None 时 build_prompt 字节 == 旧版（零成本回归锁）②target=6500 时 prompt 含目标篇幅行 ③parse_response 对 2200 字 + target 6500 打 warning 不 raise
- 实跑 extend：偏短章（<65% 章均）打印 warning
- 守纪门

---

## F5 · 续写意象 / 原文长段去重（缺陷#5，D10/D9）

**根因**：`《示例万物》 chapter_24.txt`（续写）把 `chapter_01.txt` 的「蟹青色套装、白衬衫、紫藤镶领、紫晶耳坠」段落近乎逐字复用，且「叙事者回忆」与「角色B口述」两视角各用一遍。这是「被 AI 味劝退读者（#7）唯一能一眼认出的破绽」，--lint（无外部基准，盲点④）拦不住。

### 修改点
1. **检测**：`src/workflow_action/prose.py` 新增 `find_overlapping_spans(draft: str, source: str, n: int = 30) -> list[str]`：滑窗取 draft 的连续 n 字符子串，命中 source 即记录。复用 `review.py:134 _bigram_jaccard` 的 bigram 思路做初筛降复杂度（draft 通常 <10k 字，O(len) 可接受）
2. **prompt 预防**（主）：`build_prompt` 已有 `excerpt_context`（`extend_short_form.py:638 load_recent_excerpts(text)`）——在【硬性约束】追加一条静态文案「衔接前章语感与意象，但不得逐字复用原文任意连续 30 字以上的描写；同一意象在不同视角下须变形重写，不得整段搬运」
3. **落盘报告**（辅）：`parse_response` 增加可选 `source_text`；检测到 overlap 时打印 `WARNING prose reuses N-span from source: "<片段>…"`，并把片段列表写入 `extend_result.json` 的 `prose_overlap` 字段——**只报告不阻断**，让人工/复核决定

### 验证
- 新增 `tests/test_prose_overlap.py`：①构造 draft 含 source 的 40 字相同段 → 检出 ②无 overlap → 空表 ③build_prompt 含去重约束文案
- 实跑 extend：对 `《示例万物》` 类输入检出「套装/耳坠」段
- 守纪门

---

## F3a · Review 挂 prose 复核（缺陷#3，D3/D10，最贵最后做）

**根因**：`review.py` 运行在 PlotUnit 层、prose 成文**之前**（`prose.py:3-4`「review 通过后新增成文」），`review.py:720/849` 诚实标注「对象层无正文」。导致「正文已兑现的伏笔仍被报未推进」——`示例官商 extend_result.json` 12 条 warning 中多条（伏笔未显式推进 / 张力未解）在 1197/1198 正文里实际已处理。review 信号与正文质量脱节，老粉陪审员（#9）被一堆 warning 吓出「要崩」误判。这是 handoff:69 自列的「建议下一步 #1」。

### 修改点
1. **复核函数**：`review.py` 新增 `recheck_against_prose(issues: list, prose_text: str) -> list`
   - 对 `family/category` 为「伏笔未推进 / 张力未解 / 无显式依据」类 issue，用 `_text_related`（`review.py:145`）+ `_foreshadow_keywords`（`review.py:181`）判断该 issue 指向的伏笔/事实是否在 `prose_text` 中被内容级引用
   - 命中 → 把该 issue 降级为 reminder 或标记 `resolved_in_prose: true`；未命中 → 原样保留
2. **接线 extend**：`src/extend_short_form.py:591-602`（写 `extend_result.json`）之前，若有 prose 正文（`chapter_text`），调用 `recheck_against_prose(issues, chapter_text)` 后重算展示
3. **顺序前提**：当前 prose 在 review **之后**生成——复核只能在 prose 落盘后做。两条实施路径：
   - **3a（保守，推荐先落地）**：复核只影响 `extend_result.json` 的**展示与标注**，不改 route（route 仍由 prose 前 review 决定）。价值：消噪声、让 route 信号可信，不动时序、风险最低
   - **3b（结构性）**：把 review 移到 prose 之后，或加「prose 后第二轮伏笔回收复核」——改时序，需独立设计评审，**不在本批默认范围**

### 验证
- 新增 `tests/test_review_prose_recheck.py`：①伏笔 issue + prose 含该伏笔关键词 → 标 resolved_in_prose ②prose 不含 → 原样 ③3a 路径下 route 不变
- 实跑：对 `示例官商 1197` 复核，12 条 warning 中 prose 已处理的被标注/降级
- 守纪门

---

## F6 · 时间锚提取覆盖稀疏（D3，时间域盲点补强）

**根因**：`src/workflow_action/timebook.py:70-71 _first_paragraphs(text, limit=220)` 只扫每章**前 220 字符**提日期/农历/时段；`extract_time_anchors`（:74-100）对每章 `head = _first_paragraphs(...)`。handoff:70 自承「示例作品时间标识稀疏，8 章只提取到 2 条夜里锚点」——锚点若出现在章中/章尾（如「转眼到了冬至」「三个月后」）会漏检，时间域检测 4/5/6 因锚稀而效力打折。

### 修改点
1. **扩扫描范围**：`timebook.py:70 _first_paragraphs` 的 `limit` 提高（如 220→800），或新增「首段 + 末段」双窗扫描——时间锚常出现在章首（破题）与章尾（收束/转场）
2. **补相对时间词**：`_LUNAR_KEYWORDS`/`_TOD_KEYWORDS`（:58-67）已有节气/时段；增加相对时间锚正则（「三个月后」「次日」「转眼」「年后」等），提取为 `rel` 字段（TimeAnchor 全 Optional，可扩展），供检测 4（时间回退）有更多锚可比对
3. **保持零成本契约**：`refresh_time_book_anchors`（:103-117）在无 TimeBook 时仍 no-op；本改动只提升「有 TimeBook 时」的锚密度，不改无 TimeBook 路径

### 验证
- 新增/更新 `tests/test_time_domain.py` 用例：①时间锚出现在章中/章尾（>220 字符后）能被提取 ②「三个月后」类相对词被识别 ③无 TimeBook 时仍零副作用
- 实跑一部时间标识密集的作品 `novel time --rebuild`，锚点数应显著高于改动前
- 守纪门

---

## F7 · retrieval 重复 tokenize 性能优化（D4）

**根因**：`src/boundary_control/retrieval_metrics.py retrieve()` 中 `doc_tfs = [_count_terms(_tokenize(text)) for ...]`（:76）每次调用对**全语料**重新 tokenize+计数；query 又单独 tokenize（:71）。长文续写时 FactLedger/ForeshadowGraph 语料随章数增长，每次 Continue 都 O(N·d) 重算，属隐性性能债（当前规模下未爆，但长文场景会放大）。这是评估 D4 探到的非阻断缺陷。

### 修改点
1. **可选缓存**：`retrieve()` 增加可选 `doc_cache: dict | None = None` 参数，键为 doc_id、值为预计算 `tf`；命中则跳过该 doc 的 tokenize。**保持纯函数语义**：默认 None 时行为逐字节不变（回归锁）
2. **调用方（RetrievalUnit）**：`src/workflow_action/retrieval.py:82-118 _build_documents` 构建 docs 时已在内存，可在同一实例生命周期内复用 tokenize 结果——但注意 retrieval.py 是「spec 消费、不进状态机」，缓存只做**单次 build 内**的局部优化，不引入跨调用状态
3. **替代更稳的做法**：若不想加参数，可在 `retrieve` 内部把 `zip(documents, doc_tfs)` 改为一次性预计算后复用，避免 `_tokenize` 在 `_count_terms` 外层重复调用——审阅 `:76` 与 `:94` 确认 `_tokenize` 是否被调两次（`:76` 一次，渲染 `:126` 不再 tokenize，实际只一次；**先核实是否真重复，避免误修**）

### 验证
- 先核实 `_tokenize` 实际调用次数（若只一次，本 Fix 降级为「微优化/不修」）
- 若确重复：新增基准测试（`tests/test_retrieval_metrics.py`）断言大语料下 retrieve 结果与改动前逐分一致（确定性排序 `:112`）
- 守纪门

**核实结论（2026-08-06 实施）**：`_tokenize` 每次 `retrieve()` 调用中只被调一次（query `:71` 一次、每个 doc `:76` 一次）；渲染路径 `:126/:134` 不再 tokenize。`load_retrieval_context` 每次运行只调 `retrieve` 一次（compose `:352` / extend `:448`）。**不存在重复 tokenize**——原判定是误报，按本 Fix 自身规则降级为「不修」，避免为不存在的缺陷引入 `doc_cache` 参数复杂度。

---

## F8 · novel_cli.py 臃肿拆分（D6）

**根因**：`src/novel_cli.py` 3851 行，是第二大源文件（release_record.py 1513）的 2.5 倍，统一入口塞了 audit/extend/compose/style/compliance/rubric/time/gate/list/resume 全部分支的路由+参数透传+run_config 恢复逻辑。评估 D4/D6 判其臃肿，长期维护成本高。

### 修改点
1. **按流拆子模块**：新增 `src/cli/` 目录，把各流的 argparse 定义与 dispatch 拆为 `cli/audit_cmd.py`、`cli/extend_cmd.py`、`cli/compose_cmd.py`、`cli/style_cmd.py`、`cli/compliance_cmd.py`、`cli/rubric_cmd.py`、`cli/time_cmd.py`、`cli/gate_cmd.py`；`novel_cli.py` 只留顶层 parser 注册与 main
2. **保持 CLI 契约不变**：所有命令名/参数/默认值/退出码逐字节不变——有 `test_cli_runtime_contract.py`、`test_runtime_args.py`、`test_novel_cli.py` 锁住行为，拆分时这些测试必须不改仍绿
3. **run_config 恢复逻辑**：抽取共用（`--resume`/range/batch-size/retrieval/nsfw 透传）为 `cli/_run_config.py`，消除各流重复

### 验证
- 全量 `pytest tests/ -q` 全绿（尤其 CLI 契约/参数/各流 e2e 测试）
- `novel --help`、`novel <flow> --help` 输出与拆分前一致
- 这是纯重构，不引入新行为、不改 baseline 数字（测试数不变）
- 守纪门

---

## F3b · Review 移到 prose 之后（结构性，独立设计评审）

**说明**：F3a 的 3b 路径——把 Review 从「prose 之前」移到「prose 之后」，让 review 能直接读正文做伏笔/事实回收判定，而非靠对象层代理信号（`review.py:720/849`「对象层无正文」）。这是根治「review 与正文脱节」的结构解，但改动 Rebuild→Continue→Review→Prose 的时序，影响 [WAITING] 重跑链、rewrite/re-review 分支、extend_result 产出时机。

**不在本批默认范围**：需独立设计文档（评审时序、与 rewrite 回环的交互、route 语义变化），建议单独立项。F3a（消噪声）先落地，F3b 作为后续演进。

---

## V1–V4 · 需外部资源的「补验证」项（非代码缺陷，不阻塞本批）

| 项 | 评估出处 | 需要的资源 | 建议 |
|---|---|---|---|
| V1 读者/留存反馈回路 | 盲点⑤，D8 | 平台后台追读率/完读率数据 | 平台护城河，本地 CLI 拿不到；如未来接入平台 API 再做 |
| V2 评测人类校准 | 盲点⑥，D8 | 人类标注集 + percentile-vs-human | WebNovelBench 需人类基线；先记录为已知限制 |
| V3 --lint 外部基准 | 盲点④，D8 | 外部「人写 vs AI 写」基准语料 | F5 的原文去重提示可部分缓解；纯外部基准需语料建设 |
| V4 audit 流实跑验证 | D2 未验证 | 跑一次真实 audit（已有文本） | 执行者随手跑一次 `novel audit <作品> --input <txt>` 确认端到端，非代码改动 |

---

## 落地顺序与依赖

```
F1 (止血, 无依赖)
 ├─ F2 (红线, 无依赖, 可与 F1 并行)
 ├─ F4 (低风险 prompt+warning, 无依赖)
 ├─ F5 (低风险 prompt+报告, 无依赖)
 ├─ F6 (低风险 扫描范围, 无依赖)
 ├─ F7 (低风险 优化, 无依赖, 先核实再动)
 └─ F3a (中, 改 review 判定语义, 单独会话聚焦)
      └─ F8 (高, 纯重构, 全回归锁, 靠后)
           └─ F3b (高, 结构时序, 独立立项)
```

- F1/F2/F4/F5/F6/F7 彼此独立、低风险，可并行
- F3a 单独会话做（聚焦 review 判定语义）；F8 纯重构、行为契约有测试锁；F3b 独立立项
- 每完成一条，跑全量验证 + 守纪门，再进下一条
- **预估测试增量**：F2 +1 文件、F4 +1、F5 +1、F6 更新既有、F3a +1；F7/F8 不增测试数（优化/重构）。baseline 1792 → 随之上升，每个改测试数的 Fix 提交时经 F1 sync 脚本同步

## 验收总门（全部 Fix 完成后）

1. `PYTHONIOENCODING=utf-8 pytest tests/ -q` 全绿，且文档「N passed」== 实测
2. `python scripts/tier0_canary_regression.py` 绿
3. `git grep 主角 HEAD -- style_library/ src/ docs/ tests/` 空
4. 重跑一次 `示例官商` extend：prose prompt 含篇幅目标 + 去重约束；`extend_result.json` 的 prose 已兑现伏笔被标注、warning 噪声下降
5. 时间标识密集作品 `novel time --rebuild` 锚点数高于改动前（F6 生效）
6. `novel --help` 及各流 `--help` 输出与 F8 拆分前一致（F8 若做）
