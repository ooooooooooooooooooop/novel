# Q1 Reader-Credible Serial — 交接文档（Phase 0–3）

> 交接时间：2026-08-10 16:31。交接人：Claude Code 会话。接收人：下一位操作者/Agent。
> 冻结基线：**2414 tests passing**（2026-08-10 实跑，210.00s）。未推送前先 push。

---

## 1. 当前状态一句话

Q1 改造已完成 **Phase 0–3**（质量基线 / 正文事实硬一致性 / 事务式提交 / 续写可行性与读者契约），
全部提交在本地 `main`（3 个未推送 commit），**现停在批准点 ③（移动失败正文前）**。

未推送 commit：

- `9c5ace9` Q1 Phase 0/1——失败基线探针 + ProseEvidence 提取与跨章硬一致性门禁
- `fa7d568` Q1 Phase 2——事务式提交与版本化运行（run manifest 作为唯一提交记录）
- `1b09735` Q1 Phase 3——续写可行性与读者契约

---

## 2. 批准点检查表（红线的暂停位置）

| # | 批准点 | 状态 |
|---|---|---|
| ① | Q1 需求与架构设计完成后 | ✅ 已过（Phase 0 前） |
| ② | flow v3 数据迁移前 | ✅ 已停（Phase 2 达成后停止）——未对任何真实工作区执行 `novel migrate` |
| ③ | 移动现有失败正文前 | ⛔ **现在停在此**（Phase 5 的门槛） |
| ④ | 真实作品重新生成前 | 未到 |
| ⑤ | 创建 Q1 标签前 | 未到 |

**Phase 4（单章与滑动窗口读者门禁）在批准点 ③ 之前，无批准点门槛，可直接继续。**
批准点 ③ 之后才需要操作者批准。

---

## 3. 已完成内容（Phase 0–3）

### Phase 0 — Q1 质量基线

- 三批现有结果哈希冻结为本地失败基线（`.taskflow/active/reader-credible-serial/failure_baselines.json`）
- 8 类合成夹具 + 探针测试 `tests/test_q1_phase0_baseline.py`（10 项）——证明现有流程错误放行
- 规格文档 `docs/00_project/45_reader_credible_serial_generation.md`
- 基线 2301 → 2311

### Phase 1 — 正文事实与跨章硬一致性

- `src/object_state/prose_evidence.py`：ProseEvidencePackage，EvidenceKind 十类，每条断言带正文证据锚点
- `src/workflow_action/prose_evidence.py`：代码提取器（时间/实体状态/道具身份/元文本/选择后果等，零 LLM）
- `src/workflow_action/prose_reconcile.py`：双路核对（硬一致性 blocking + 窗口核对）
- 8 类夹具全部被新门禁阻断且命中正确 issue_type；合法时间跳跃/回忆/闪回标记负对照通过
- 基线 2311 → 2341

### Phase 2 — 事务式提交与版本化运行

- `src/object_state/run_manifest.py`：run manifest（run|seed、五态、源/前章/草稿/事实/状态前后/帧哈希、artifacts sha256）
- `src/boundary_control/chapter_commit.py`：ChapterCommitBoundary（原子提交、recover 只认完整提交、孤儿扫描、拒写未管理覆盖）
- `novel migrate --to-flow 3 --preserve-old` / `novel inspect-run [--json]`
- failpoint 崩溃恢复测试证明无半提交（tests/test_chapter_commit.py 21 项）
- 基线 2341 → 2386

### Phase 3 — 续写可行性与读者契约

- **续写可行性（R1）** `src/workflow_action/continuation_viability.py`：
  `analyze_continuation_viability` 确定性信号（no_active_frame / open promises / 终止型节点 /
  契约 ending_conditions）→ continue / needs_premise / stop；信号冲突 deterministic=False 走 staged；
  stop/needs_premise 时写 `viability_report.json` 并跳过 Continue；continue 注入【续写可行性】note
- **读者契约（R3）** `src/object_state/readercontract.py` + `src/workflow_action/reader_contract.py`：
  ReaderContract sidecar（`output/<mode>/reader_contract.json`，不入 serialization 白名单）；
  forbidden_drifts 确定性子串命中阻断 Selector 候选（`contract_violation` blocking）；
  Continue/Proposals 注入【读者契约】段（continuation.py 拥有段头防双头）
- **SceneExperience 强制**：v3 Pre-Review 闸关键单元必须携带选择依据/可见后果，缺失映射 blocking
  missing_consequence / motivation_gap
- `novel contract` CLI（`src/contract_short_form.py`）：--default 零 LLM / staged prompt→response→save / 检查
- 测试：test_continuation_viability(7) + test_reader_contract(14) + test_phase3_flow(7) = 28 新增
- 基线 2386 → 2414
- 零成本契约全程：flow v2 逐字节不变（回归测试锁死）

---

## 4. 关键命令（新增/变更）

```bash
novel contract 某作 --default                # 零 LLM 确定性初始读者契约
novel contract 某作                          # 已存在→检查摘要；无契约→staged prompt
novel contract 某作 --edit                   # 重开 staged 编辑
novel migrate 某作 --to-flow 3 --preserve-old # flow v2→v3 显式迁移（Phase 2）
novel inspect-run 某作 [--json]              # 只读巡检提交记录
```

flow v3 工作流（compose/extend 内部自动）：viability 闸 → Continue → Pre-Review（含
SceneExperience 闸）→ Prose → Review → 事务提交。

---

## 5. 剩余工作（Phase 4–6，规划见 45 号规格 + task_plan.md）

### Phase 4 — 单章与滑动窗口读者门禁（无批准点门槛，可直接做）

- 复用 ReaderExperienceUnit；新增 SerialReaderUnit + ReaderQualityGatePolicy
- 每章单章 + 相邻章审查；每 3 章窗口审查；每 5 章阶段审查
- 不从生成章更新 StyleProfile（防自我模仿漂移）
- 门禁：续写作A式重复闭环第二次即阻断；连续三章不得重复同一心理结论；关键读者维度 weak 不得提交

### Phase 5 — 三条现有内容的恢复（**先停在批准点 ③，操作者批准后才动**）

- 旧正文先哈希 + 可恢复备份，再移出活动 chapters/，不原地修改
- 续写作A（可信边界 ch23）：先可行性判断；不允许再围绕同一通电话/顿悟展开；第一轮只生成一章
- 续写作B（可信边界 ch1196）：从原始可信正文重新 Rebuild，不复用生成章增量；重点锁定票根/角色甲恢复/角色乙/建邺人事/时间日期
- 仙侠新作：第一章作失败基线不原地修补；重生成前先解决故事前提（一甲子一期保留、师父离开原因改）

### Phase 6 — 验证、校准与发布（**停在批准点 ⑤ 前**）

- 自动测试 / 合成 Canary（5 章 compose + 5 章 extend + stop 样本）/ 本地私有 Canary
- 人类读者校准（隐藏来源连续阅读，零事实矛盾等硬标准）
- Q1 发布门槛：基线无回归、三流 Canary 通过、合成夹具全阻断、真实信息未入 Git、
  operator-in-the-loop、创建独立 Q1 证据记录 + 不可变 tag（不改写 v0.1.2-tier0）

---

## 6. 隐私与红线（每次 push 前核对）

- `novels/*/`、`.taskflow/` gitignored；`style_library/` 允许中性积累
- 隐私红线测试 `tests/test_privacy_redline.py` 锁定 tracked 文件不含真实实体名/机器路径
- **注意**：git 历史旧版本可能仍含真实作品名/角色名（Phase 2 progress.md 已记录）——如需
  彻底清除须用 `git filter-repo` 重写历史再 force-push（CLAUDE.md 隐私纪律）
- 冻结存档 `docs/00_project/releases/tier0-release.json` 保持 2301 自校验，不改写

## 7. 测试与基线

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q   # 2414 passed（Windows GBK 需 utf-8）
python scripts/tier0_canary_regression.py            # 三流 canary 回归（PASS）
python -m pytest tests/test_privacy_redline.py -q    # 隐私红线
```

基线契约文件：`tests/test_cli_runtime_contract.py`（EXPECTED_TEST_BASELINE）、
`tests/test_release_record.py`（EXPECTED_BASELINE）。新增测试后必须同步这些 + 10 份文档
（README/AGENTS/CLAUDE/00–03/30/32/tier0_release_record.example.json）。

---

## 8. 交接时的现场状态

- 工作树干净，main 上有 3 个未推送 commit（见 §1）
- 本地私有工作区（novels/）未迁移 flow v3、未移动失败正文、未重生成——符合批准点约束
- 会话工具：git push 若 GCM 无缓存凭证会在非交互 shell 静默挂起——需操作者 `! git push origin main` 触发认证
