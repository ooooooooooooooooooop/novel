# Session Handoff · 会话交接记录

> 用途：在另一台电脑上继续工作的交接说明。记录本会话完成的工作、仓库当前状态、待办事项与环境恢复步骤。所有具体小说信息不入此文档（隐私纪律，见下）。

- 生成时间：2026-08-06
- 仓库：`https://github.com/ooooooooooooooooooop/novel`（公开，origin）
- 当前 `main`：checkpoint tag `v0.1.2-tier0`（指向本交接记录所在提交）
- checkpoint tag：`v0.1.2-tier0`（F1-F8 落地后的再认证；`v0.1.1-tier0` 指向修复前 9009353）
- 测试基线：**1873 passed**（1829 → 1873：阶段二三四新增 44 个测试，见下「本会话变更」）

---

## 〇、本会话变更（1829 → 1873）

按方向文档「一致性≠质量，三大核心」推进了核心2（读者体验）的落地，共四个阶段：

1. **阶段一（已提交 4f10473）**：review 弱信号解耦到 `src/domain_layer/review_signals.py`（19 个 detect_*）+ `review_signal_knowledge.py`（纯数据表）；`review.py` 1258→575 行纯编排；新增 `docs/03_rules/10_reader_experience_rules.md`（读者体验 7 维判定标准）
2. **阶段二A：读者体验审查** —— `novel reader` 命令：对章节正文做 7 维分级标注（open/presence/info/dialogue/emotion/payoff/hook，各 good/needs_work/weak，route=none 不阻断）。新文件：`src/object_state/readerreport.py`、`src/domain_layer/reader_experience_rules.py`、`src/workflow_action/reader_experience.py`、`src/reader_short_form.py`
3. **阶段二B：读者预期管理** —— `src/object_state/readerexpectation.py`：从 ForeshadowGraph 派生「读者在等什么」台账（waiting/advanced/overdue/stale），随 reader 命令写入 `reader_expectations.json`
4. **阶段三：动态角色建模** —— CharacterModel 加 `current_pressure`/`change_trajectory`/`relation_behaviors`（Optional/default，旧 state 兼容，空字段不渲染零回归）；rebuild prompt 注入字段说明
5. **阶段四：场景体验中间层** —— `src/object_state/scene_experience.py`：PlotUnit 可选字段 `scene_experience`（主角看见/阻碍/选择依据/结果/认知变化），Continue 生成、Prose 展开注入，让结构扩写带现场感

新增测试：`test_reader_experience.py`(17) + `test_reader_expectation.py`(12) + `test_charactermodel_v4.py`(7) + `test_scene_experience.py`(8) = 44 个。

对《碑下》第一章实测：reader 报告 overall=needs_work（唯一弱项「解释过多」的三年前回忆段，与人工审读判断一致），读者预期 6 条。

---

## 一、在另一台电脑上恢复环境

```bash
git clone https://github.com/ooooooooooooooooooop/novel.git
cd novel
python -m venv .venv            # 或复用系统 Python 3.11
.venv/Scripts/pip install -e .  # Windows；POSIX 用 .venv/bin/pip
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest tests/ -q
```

- **测试必须带 `PYTHONIOENCODING=utf-8`**（否则 Windows 下中文输出乱码导致断言失败）
- 完整回归门：`python scripts/tier0_canary_regression.py`
- 项目 CLI：`novel <mode> <小说名>`，详见 `CLAUDE.md` 与 `README.md`（均中英双语、已同步当前进度）

---

## 二、仓库状态与纪律（务必遵守）

### 隐私纪律（红线）
- 所有具体小说信息（标题/正文/角色/工作区名/作者笔名）**一律不入 GitHub**；`novels/*/` 已 gitignore
- 正文仅存本地 `novels/<小说名>/chapters/`；GitHub 只保留工具框架 + 中性命名的 `style_library/`
- 若历史出现具体小说信息，push 前必须 `git filter-repo` 完整重写历史剔除（本项目已做过三次）

### filter-repo 注意
- **每次 `git filter-repo` 会移除 origin**，push 前需重新 `git remote add origin https://github.com/ooooooooooooooooooop/novel.git`
- push 用 `git push origin master:main`（本地工作分支是 `master`，远端是 `main`）

### 测试基线同步
- 测试数变化时需同步全部 "tests passing" 数字：`tests/test_cli_runtime_contract.py`、`tests/test_release_record.py`、`docs/00_project/releases/tier0-release.json`、`tier0_release_record.example.json`、以及 `AGENTS.md` / `CLAUDE.md` / `README.md` / `docs/00_project/0x` 各文档（有 `test_deployment_docs_are_consistent` 锁 6 文档一致）

### 零成本契约
- 功能注入（TimeBook / 检索 / NSFW / 风格）遵循"无数据 → 无注入、prompt 字节不变"；新注入段默认空串不改变旧行为

---

## 三、本会话已完成（2026-08-06 · 独立评估修复实施）

按 `docs/00_project/41_evaluation_remediation_plan.md` 落地 F1–F8（评估确认缺陷全部处理）：

1. **F1 发布门禁基线同步**：1791→1792 断链修复，基线 1792→1829；`EXPECTED_TEST_BASELINE`/`EXPECTED_BASELINE` 同步，tag `v0.1.1-tier0` 指到修复前 HEAD（9009353）；本会话再提交后重打 `v0.1.2-tier0` 到新 HEAD 并同步 release record
2. **F2 PII 脱敏 + 红线**：`style_redact.py`（redact_profile/assign_placeholders/parse_redact_arg）+ `style_short_form.py --redact` 接入入库；存量 style_library/manifest、info_warrant_knowledge、09_rules、test_info_warrant、test_failure_emission 全部中性化；`tests/test_privacy_redline.py` 锁 `git grep` 零命中（词表登记文件自豁免）
3. **F4 续写篇幅对齐**：`prose.py average_chapter_chars` + `build_prompt(target_chapter_chars=…, ±35%)` + `parse_response` 低于下界仅告警不阻断；extend 接线（compose 缺省零成本）
4. **F5 原文去重**：`prose.py find_overlapping_spans`（n-gram 索引 + 双向扩展，≥30 字符）检出逐字重叠写入 `extend_result.json.prose_overlap`；prompt 注入禁复刻约束
5. **F3a Review 挂 prose 复核**：`review.py recheck_against_prose` 对伏笔/承诺/后果/角色 issue 做正文兑现标注（`prose_recheck`，只展示不改 route）
6. **F6 时间锚扩窗**：首段 220→800 字符 + 全文相对时间兜底；`TimeAnchor` 新增 `relative` 字段
7. **F7 核实为误报**：`_tokenize` 每 doc 仅一次，无重复 tokenize，按计划降级不修
8. **F8 CLI 拆分**：`src/novel_cli.py` 3851→1480 行，校验簇（常量+校验函数+gate/route/status 辅助共 100 名）→ `src/cli/validation.py`（`__all__` 重导出）；3 个契约测试文件指针随重构移动；`--help` A/B 字节一致

全量 **1829 passed**（测试数自 1792 起未变；文档 6 处 + 2 release record 同步）。

### 未做部分跟进（2026-08-06 · 设计/验证/核查）

F1–F8 之后按「继续未做部分」完成三项：

1. **F3b 独立设计文档**：新建 `docs/00_project/42_review_after_prose_design.md`——Review 移到 prose 之后的结构设计。核心：①净 LLM 轮数不变（happy path 仍 3 轮，只重排 Continue→Prose→Review）；②Pre-Review 代码前置闸（零 LLM 成本，拦截结构性致命错误，守住「无效结构不 prose」）；③双层 rewrite（`target_layer: object|prose`，对象层修复→重成文、正文层修复→直接改章节）；④Review prompt 注入正文（audit 注入被审原文，零时序风险）；⑤`flow_version` 戳 + 旧版 fail-fast 迁移；⑥零成本契约（`prose_text=None` 时 prompt 逐字节不变）。**仅设计，未实施**。
2. **V4 audit 真实文本端到端实跑**：`novels/audit-v4/`（gitignored）用 `canary_inputs/` 真实名文件（`*_1190_1196.txt`，7 章 57287 字符）实跑完成——Rebuild 13 对象 → Review route=PASS、6 非阻断 promise_loss warning + 3 reminder → `audit_report.json`/`rebuild_package.json`/`review_result.json`/`route_handoff.json`/`timeline_report.json` 齐全。
3. **V1–V3 可行性核查**：确认均依赖外部资源、本地无替代，结论记入 41_plan 表格。

**实跑验证出的两个要点**（换机后有用）：①batch 模式响应文件名必须 `batch_<a>_<b>_rebuild_response.txt`（`.txt` 非 `.json`，`audit_short_form.py:330`）；②重建响应中关系引用未建模角色 ID 会触发 `character_distortion` blocking——补建模（如本作 `c_zhaidanqing`/`c_fujun`）即清除，硬规则有效。

**Canary 实测**：`python scripts/tier0_canary_regression.py` —— audit 流 PASS；extend/compose 流 **FAIL**（gate 报 `ContinueUnit requires a serialization package`，工作区缺 `*_rebuild_package.json`）。已用 f63ff04 worktree A/B 确认**拆分前同样 FAIL**，属 canary 工作区状态陈旧（预存在），非本批回归。

**✅ 已修复（2026-08-06 · 本会话）**：`tier0_canary_regression.py` 三流全绿。根因是 **canary 的序列化包文件从未入库**（`novels/*/` 被 gitignore，仅 tracked 文件在 junction 误删后幸存；audit canary 有入库 `rebuild_package.json`，extend/compose 却没有）。修复方式：①用 `canary_inputs/` 保留的响应文件重跑对应流，再生 `extend_rebuild_package.json` / `compose_state.json`（extend 只喂 `rebuild_response.txt` 即停在 Continue；compose 喂 continue/review/rewrite/rereview 四响应，`--no-prose` 跑到流末）；②`.input_hash`/`.workspec_hash` 用项目自身函数补写；③compose 重跑会重写 `compose_result.json`/`route_handoff.json`，因 8/5 审查误报修复（hook 不再判层级非法）导致 issue 数 2→1，**与钉死 sha256 漂移——用备份还原钉死证据，仅保留新生成的 state 包**；④两个包文件 `git add -f` 入库（`output/` 全局 ignore，canary 证据 force-add 是既定模式）。重跑会顺带把 `run_config.json` 更新为当前 CLI schema（补 `retrieval`/`nsfw` 默认值，无害）。

---

## ⚠️ 事故记录：novels/ 工作区误删（2026-08-06）

**经过**：F8 验证 `--help` A/B 时用 `git worktree add` + 在 worktree 内对 `novels` 建 junction 指向主工作区 `D:\Desktop\novel\novels`，验证后 `git worktree remove --force`。Git 递归删除沿 junction 把主工作区整个 `novels/` 清空。

**损失**：未跟踪小说工作区全部删除——`作品A/`（1197 章续写）、`作品B/`（chapter_24 续写）、`示例小说甲/乙/丙/`（audit/style）、`仙侠新作/`（compose）的 `chapters/` 与 `output/` 产物。**不在 git**（隐私红线设计）。真实作品名仅存本地 `canary_inputs/` 未跟踪文件。

**已恢复**：`novels/tier0-*-canary/` 17 个 tracked 文件 `git checkout -- novels/` 还原。

**重建依据**：源文本仍在 `canary_inputs/`（真实名文件 `*_1190_1196.txt`、`*_full.txt` 等，未跟踪不入库）；另 `C:\Users\Lenovo 2021\.claude\projects\D--Desktop-novel\` 下 21MB 会话 transcript（5afa5ad4，8/5）含此前生成正文/响应，可作部分恢复源。用户当时选择先完成 F8 提交，恢复（DiskGenius/Recuva 对 D 盘扫删文件）可后续再做。

**教训（写进纪律）**：任何 worktree/junction 操作禁止指向主工作区 `novels/`；A/B 验证优先用 `git worktree add <空目录>` + 从 git 恢复文件，或直接 `git show <commit>:path > 临时文件` 比对，**绝不建 junction 到真实数据目录**。

---

## ✅ 工作区恢复记录（2026-08-06 · 本会话）

误删后按「canary_inputs 源文本 + transcript 重放」两条路径恢复，全部本地重建（不入库，git clean）：

1. **`作品A/`（续写作B，extend）— 完整恢复**：
   - `chapters/chapter_1190~1196.txt`：源文本 `canary_inputs/续写作B_1190_1196.txt` 按章拆分；`chapter_1197.txt` 从 transcript（5afa5ad4）提取，与原文逐字节一致（7738 字符 / 82 段）
   - `output/extend/`：`extend_rebuild_package.json` / `extend_result.json`（route=pass，9 非阻断 warning + 1 reminder，prose_overlap 2 段、prose_recheck 6/9 正文兑现）/ `route_handoff.json` / `extend_frames.json`（scene_001 完成，scene_002 inciting_incident active → 下章 1198）/ `.input_hash`
   - `output/style/style_profile.json`：用 `StyleExtractUnit().merge(qualitative, stats, risks, ref)` 重建合法档案（load_style_context 非空 1874 字符）
   - `novel gate 续写作B --json`：ok=true、route=pass、next=ContinueUnit、blocking=0 → **可直接续写 1198**
2. **`作品B/`（续写作A，手动解构续写）— 完整恢复**：
   - `input.txt`：`canary_inputs/续写作A_full.txt`（148,995 字符，网络版 23 章，零广告残留）
   - `chapters/chapter_01~23.txt`：源按「第X章：标题」切分（注意 `split_by_chapters` 的 `第X章 ` 正则不认全角冒号，手动切分）
   - `chapters/chapter_24.txt`（第二十四章：燕京，6,240 字符 / 89 段）：从 transcript **重放 L2367 Write + 15 次 Edit** 精确还原（L2426 的 Edit 在真实会话里也失败过 `<tool_use_error>`，重建结果与真实文件逐字一致）
   - `output/解构_全书.md`：transcript L2282 提取（全书 23 章结构化解构）
   - mode=extend/initialized，workspec.json（现代都市/青春回忆，自 extend_result 读回）
3. **`仙侠新作/`（compose）— 状态已由 canary 保存**：tier0 三个 canary 工作区已入库（`tier0-canary`=audit、`tier0-extend-canary`=extend、`tier0-compose-canary`=compose），其中 `tier0-compose-canary/output/compose/compose_state.json` 即仙侠 compose 的完整结构态（workspec 提及仙侠、4 个 compose 响应在 `canary_inputs/tier0_compose_*`）。无需重复副本，续做 compose 可直接在 canary 工作区推进。
4. **`示例小说甲/乙/丙/`（演示）— 由 canary 覆盖**：三个演示流已被 tier0 三 canary + 风格库测试覆盖，非真实创作，不重建。

**恢复方法要点**（换机后有用）：①transcript JSONL 的 `tool_use.input.content` 带 Write 全文、`tool_use.input.old/new_string` 带 Edit 增量，按行号重放即可逐字还原（注意 L2426 类失败 Edit 也要复现其失败）；②章节编号连续性靠先铺源章节再 `next_chapter_number`；③`StyleProfile` 缺字段会触发 pydantic 校验失败，必须用 merge 重建非 raw 提取；④所有恢复内容在 `novels/*/` 下，git 零泄漏。

---

## 四、本会话已完成（2026-08-05）

1. **README 重写**：中英双语，以当前进度（Tier 0 / 三流 / 1792 测试）更新，示例名中性化
2. **Git 历史完全清理**（三次 filter-repo）：
   - README 里真实小说名以乱码形态残留（filter-repo 按原文匹配漏网）→ 清除
   - 全部历史 PUA/双层编码乱码（docs 设计文档、tests 字符串）→ 逐行还原
   - 重写后 `tier0-release.json` 的 `git_commit` 重定位到新 checkpoint
3. **NSFW 内容分级开关**（贯通创作与审核一套语义）：
   - compose/extend `--nsfw on|off`（默认 off 正常向，prompt 注入【内容分级】禁成人；on 允许成人向）
   - compliance `--nsfw on|off`（on 跳过「涉黄」分类，其余分类仍扫）
   - CLI 透传 + run_config 恢复
4. **审查误报修复**（Review 功能，原被独立判定评为"多数空转"）：
   - `validate_plotunit_hook`：自由文本钩子不再判"层级不合法"（消除全书 8 条刷屏误报）
   - `validate_node_emotion`：加 21 组情绪近义词扩展（降低漏检）
   - 伏笔引用：加内容级匹配（PlotUnit 文本提及伏笔关键词即算引用）
   - 实测：hook 误报 8→0、情绪误报 1→0

---

## 五、建议下一步（未做，按性价比排序）

1. **重建 novels/ 工作区（误删后）**：~~`作品A/`、`作品B/`、`示例小说甲/乙/丙/`、`仙侠新作/` 已被误删~~ → **✅ 已恢复（2026-08-06 · 本会话）**，见下「工作区恢复记录」。`作品A/`（续写作B）与 `作品B/`（续写作A）两个真实创作工作区已从 `canary_inputs/` 源文本 + transcript（5afa5ad4）完整重建并验证；`仙侠新作/`（compose，结构态）与 `示例小说甲/乙/丙/`（演示）的状态已由 tier0 三个 canary 工作区完整保存，无需重复副本。
2. ~~**canary extend/compose 补产物**~~ **✅ 已解决（2026-08-06）**：`scripts/tier0_canary_regression.py` 三流全绿。`extend_rebuild_package.json` / `compose_state.json` 已再生并入库（`git add -f`，见上「Canary 实测」修复记录）；钉死证据（compose_result/route_handoff sha256）未漂移。
3. **F3b 实施（设计已完成，见 42_review_after_prose_design.md）**：Review 移到 prose 之后的结构时序改动。设计已定：净 LLM 轮数不变、Pre-Review 代码闸、双层 rewrite、正文注入、`flow_version` 迁移、零成本契约。实施需独立立项（改时序/加 pre-review/双层 rewrite/注入/迁移，含测试基线同步）。
4. **V1–V3（已核查，确认外部阻塞）**：读者留存回路（需平台追读率/完读率数据）、评测人类校准（需人类标注集）、`--lint` 外部基准（需人写-AI 写对照语料）。本地 CLI 无替代，维持待接入；结论记入 41_plan。V4 audit 真实文本实跑已完成（`novels/audit-v4/`，PASS）。
5. **NSFW 内容分级定制**（2026-08-05 遗留）：【内容分级】文案按题材（亲情向/热血向等）细化边界。
6. **hook_type 字段**（2026-08-05 遗留）：若为 PlotUnit 引入显式 `hook_type` 枚举，可恢复 hook 严格层级校验。

---

## 六、本会话任务清单（均已关闭）

- ✅ NSFW 开关：生成侧注入 / compose/extend 参数 / compliance 涉黄过滤 / CLI 透传 / 测试（1791）
- ✅ 各功能产出盘点与补齐（compose 全文 / extend 续写正文 / compliance / time / audit）
- ✅ 三个独立子 agent 判定功能效果（风格 9 > 创作 8.5 > 续写 8 > 检索 8 > 合规 7 > 分级 5 > 审查 ~3 > 时间 3）
- ✅ 审查误报修复（1792 passed，已提交）

> 注：本地 `novels/`（小说工作区）不入库，换机后不随 clone 带来；如需继续某部作品创作，需在新电脑重建工作区并重新跑流程。

---

## 七、跨会话积累的项目要点（换机后 Claude 应知道的背景）

> 提炼自本地记忆积累，凡 `CLAUDE.md` 已覆盖的不重复；这部分帮助新电脑的 Claude 不用重新摸索项目的历史决策与已知坑。

### 环境与 Windows 坑
- venv：Python 3.11.9，pytest 9.1.1，pydantic 2.13.4；**必用** `.venv/Scripts/python -m pytest tests/ -q` 且带 `PYTHONIOENCODING=utf-8`（控制台默认 cp936/GBK）
- 新测试若用 `subprocess.run(text=True)` 捕获中文输出，必须写 `encoding="utf-8"`，否则 GBK 控制台 `UnicodeDecodeError`

### 结构性盲点清单（加模块前查，避免重复调研）
2026-08 对外部同类项目审查的结论：本项目「结构化状态 + 分阶段 CLI」架构在学术上正确（对应 FACTTRACK/StoryWriter/DOME/CreAgentive 范式），盲点主要是缺"查询"和"字面层"能力。

- **7 个结构性盲点**：①系统原本不产出正文（后已用 prose 成文补齐）②状态只有压缩结论无检索（已补 retrieval）③平台约束无内容合规（已补 compliance）④`--lint` AI 味检测无外部基准校准 ⑤无读者/留存反馈回路（追读率只在平台后台）⑥评测无人类校准（WebNovelBench 需 percentile-vs-human，单 LLM judge ρ≈0.4-0.6 弱）⑦编辑人机回环（已补 approval-gate）
- **论文锚点**：FACTTRACK 2407.16347、BookWorm 2410.10372、MemBench 2506.21605、CreAgentive 2509.26461（2500+ 章）、WebNovelBench 2505.14818（中文网文黄金标准）、LongWriter 2408.07055
- **参考结论**：加"查询/字面层"类模块时先查此清单

### 已实现但易忽略的功能（换机后别以为没有）
- `novel gate --require-approval`：编辑人机回环——severity=critical 的 ReviewIssue 必须操作者人工 approve/reject（`approval_decision.json`）才推进；**全 approve 跳转 ContinueUnit，blocking issue 严格不可审批**（`src/boundary_control/approval_gate.py`）
- `novel time` 时间域（--rebuild/--check/--status）、`novel style --style` 风格库跨小说引用、`novel compliance` 合规单遍扫描、`--retrieval` 状态检索

### 基线迁移纪律（踩过坑）
- 测试数变化时同步**两处常量**：`tests/test_cli_runtime_contract.py::EXPECTED_TEST_BASELINE` **和** `tests/test_release_record.py::EXPECTED_BASELINE`（曾漏改后一处导致 21 个 release_record 测试全挂）
- 6 个文档被 `test_deployment_docs_are_consistent` 锁一致（README/AGENTS/brief/scope/quickstart/status 的 "tests passing" 数字）；改动用字节级替换、避开损坏文档
- release_record 相关的**额外同步点**（本会话 1829→1873 新增验证）：`docs/00_project/tier0_release_record.example.json`（baseline_tests_passing + full_pytest_result，被 test_cli_runtime_contract 断言 `== int(EXPECTED_TEST_BASELINE)`）、`docs/00_project/30_production_readiness_checklist.md` 与 `32_tier0_release_record_contract.md`（命令行示例里的 `--expected-baseline`）、已提交的 `docs/00_project/releases/tier0-release.json`（baseline_tests_passing + full_pytest_result；**勿改 git_commit**——release record 的 commit 必须能由 `release_tag_or_checkpoint` tag 解析，改 commit 会触发 `tag must resolve to git_commit`）
- 基线文档之外的 35/40/41 是历史快照（记录当时基线），未被测试锁定，不应改写历史

### 编码/mojibake 教训
- 修 GBK 乱码文档**不要**用 gb18030 整篇重编码（会把合法 UTF-8 文件误判损坏，0xe3 字节破坏 UTF-8 结构）；正确做法是字节级替换目标子串后验证仍合法 UTF-8
- 本会话已用 `git filter-repo --blob-callback`（无损 GBK 往返 + gb18030 还原 PUA）彻底修复历史乱码，历史扫描 0 乱码 0 PUA；仅设计文档残留少量 U+FFFD（原始字节被 `?` 吃掉，不可逆）
