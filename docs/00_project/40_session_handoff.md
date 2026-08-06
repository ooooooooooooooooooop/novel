# Session Handoff · 会话交接记录

> 用途：在另一台电脑上继续工作的交接说明。记录本会话完成的工作、仓库当前状态、待办事项与环境恢复步骤。所有具体小说信息不入此文档（隐私纪律，见下）。

- 生成时间：2026-08-06
- 仓库：`https://github.com/ooooooooooooooooooop/novel`（公开，origin）
- 当前 `main`：checkpoint tag `v0.1.2-tier0`（指向本交接记录所在提交）
- checkpoint tag：`v0.1.2-tier0`（F1-F8 落地后的再认证；`v0.1.1-tier0` 指向修复前 9009353）
- 测试基线：**1829 passed**

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

**Canary 实测**：`python scripts/tier0_canary_regression.py` —— audit 流 PASS；extend/compose 流 **FAIL**（gate 报 `ContinueUnit requires a serialization package`，工作区缺 `*_rebuild_package.json`）。已用 f63ff04 worktree A/B 确认**拆分前同样 FAIL**，属 canary 工作区状态陈旧（预存在），非本批回归。恢复方式：对 `tier0-extend-canary`/`tier0-compose-canary` 重跑完整 [WAITING] 响应循环补产物。

---

## ⚠️ 事故记录：novels/ 工作区误删（2026-08-06）

**经过**：F8 验证 `--help` A/B 时用 `git worktree add` + 在 worktree 内对 `novels` 建 junction 指向主工作区 `D:\Desktop\novel\novels`，验证后 `git worktree remove --force`。Git 递归删除沿 junction 把主工作区整个 `novels/` 清空。

**损失**：未跟踪小说工作区全部删除——`作品A/`（1197 章续写）、`作品B/`（chapter_24 续写）、`示例小说甲/乙/丙/`（audit/style）、`仙侠新作/`（compose）的 `chapters/` 与 `output/` 产物。**不在 git**（隐私红线设计）。真实作品名仅存本地 `canary_inputs/` 未跟踪文件。

**已恢复**：`novels/tier0-*-canary/` 17 个 tracked 文件 `git checkout -- novels/` 还原。

**重建依据**：源文本仍在 `canary_inputs/`（真实名文件 `*_1190_1196.txt`、`*_full.txt` 等，未跟踪不入库）；另 `C:\Users\Lenovo 2021\.claude\projects\D--Desktop-novel\` 下 21MB 会话 transcript（5afa5ad4，8/5）含此前生成正文/响应，可作部分恢复源。用户当时选择先完成 F8 提交，恢复（DiskGenius/Recuva 对 D 盘扫删文件）可后续再做。

**教训（写进纪律）**：任何 worktree/junction 操作禁止指向主工作区 `novels/`；A/B 验证优先用 `git worktree add <空目录>` + 从 git 恢复文件，或直接 `git show <commit>:path > 临时文件` 比对，**绝不建 junction 到真实数据目录**。

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

1. **重建 novels/ 工作区（误删后）**：`作品A/`（1197 章续写）、`作品B/`（chapter_24 续写）、`示例小说甲/乙/丙/`、`仙侠新作/` 已被误删。源文本在 `canary_inputs/`（真实名文件 `*_1190_1196.txt`、`*_full.txt`，未跟踪），重跑管线可重建；或从 `C:\Users\Lenovo 2021\.claude\projects\D--Desktop-novel\` 21MB transcript（5afa5ad4）提取此前生成正文/响应。
2. **canary extend/compose 补产物**：`scripts/tier0_canary_regression.py` 当前 audit PASS、extend/compose FAIL（工作区缺 `*_rebuild_package.json`，预存在）。对 `tier0-extend-canary`/`tier0-compose-canary` 重跑完整 [WAITING] 响应循环补产物即可全绿。
3. **F3b（Review 移到 prose 后）**：结构时序改动，独立立项（见 41_plan）。
4. **V1–V4 补验证**：读者留存回路 / 评测人类校准 / `--lint` 外部基准 / audit 流实跑（需外部资源，见 41_plan，非代码缺陷）。
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

### 编码/mojibake 教训
- 修 GBK 乱码文档**不要**用 gb18030 整篇重编码（会把合法 UTF-8 文件误判损坏，0xe3 字节破坏 UTF-8 结构）；正确做法是字节级替换目标子串后验证仍合法 UTF-8
- 本会话已用 `git filter-repo --blob-callback`（无损 GBK 往返 + gb18030 还原 PUA）彻底修复历史乱码，历史扫描 0 乱码 0 PUA；仅设计文档残留少量 U+FFFD（原始字节被 `?` 吃掉，不可逆）
