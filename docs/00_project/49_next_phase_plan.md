# 49. 下一阶段计划：G7 计分合同封死 + 主线确定性层 + A1 研究轨隔离

状态：**实施中（阶段 1 计分合同已封死，2026-08-15）**
更新日期：2026-08-15

## 0. 定位

G7 是未来 A1/Q2A 零人工闭环层中「自动审美终裁」子能力的资格门，**不是项目总目标的必要条件**。
项目总目标是「以叙事状态为核心、可审查、支持续写/重建/重写的小说系统」；Tier 0
（operator-in-the-loop staged CLI）是当前有效生产路径。G7 失败只表示该子能力未资格化，
不表示小说系统失败。

本计划分三条轨 + 一条横切纪律：

- **Track A — 主线**：Tier 0 生产 + 确定性层（六职责）。
- **Track B — 计分合同封死**：可逆、独立验收，最先执行（阶段 1）。
- **Track C — G7 双模型研究轨**：隔离、一次性资源、预注册驱动（阶段 2–4）。
- **横切 — 证据完整性纪律**：holdout 一次性、哈希锁、只读验证、禁止测量漏洞。

## 1. 阶段 1：计分合同封死（Track B，已完成）

> 冻结口径统一前，任何新 G7 PASS 都不构成有效生产证据。以下为封死后的**冻结口径**。

### 1.1 冻结口径（已落地为测试锁定）

1. **准确率**：弃权（no_difference）= 错，计入分母；分母 = 全部样本（含弃权与耗尽）。
   分类型同口径（分母 = 该 tag 全部样本）。
2. **协议耗尽**（ReviewQualityExhaustedError）= 错，计入分母；记 `predicted="unreviewable"`
   预测（含 reason），绝不静默排除。
3. **位置一致性**：空评返回 0.0（旧实现返回 1.0 是测量漏洞）；耗尽计为「不一致」并入分母；
   采样禁止前缀，`>0` 时按 tag 确定性分层。
4. **per-tag 门**：holdout 清单中每个 tag 都必须有有效评估，缺失 = FAIL（旧实现只检查
   「实际留下预测」的 tag，全弃权/耗尽 tag 虚过）。

### 1.2 改动文件

- `src/object_state/qualitythresholds.py`：`JudgePreferencePrediction.predicted` 增加
  `unreviewable` + `reason`；`AccuracyReport` / `HoldoutReport` 增加 `unreviewable_count`；
  字段描述对齐冻结口径。
- `src/workflow_action/auto_calibrate.py`：`compute_accuracy` 弃权/耗尽入分母（Wilson 用 n）；
  `run_preference_judge` 耗尽记错预测；`measure_position_consistency` 空评=0.0、耗尽入分母、
  新增 `_stratified_position_sample`（禁止前缀）；`run_holdout` per-tag 全覆盖门 + 默认
  position 全量。
- `src/auto_calibrate_short_form.py`：`--position-sample` 默认 0（全部）；summary 增加
  `unreviewable_count`。
- `src/novel_cli.py`：`--position-sample` 帮助文本对齐新语义。
- `tests/test_auto_calibrate.py`：改写 2 条锁定旧宽松行为的测试，新增混合弃权、耗尽入分母、
  空评=0、分层采样、整 tag 弃权 FAIL 测试。**保留**既有污染划分 skip 守卫。
- `tests/test_auto_calibrate_cli.py`：未改（`--position-sample 2` 在新分层语义下仍然有效）。
- **基线合同同步（+4 测试 → 2825）**：`tests/test_cli_runtime_contract.py` / `tests/test_release_record.py`
  的基线常量与 provenance、6 个强制文档 + `30_checklist` + `32_contract` + `README`/`AGENTS`/`CLAUDE` +
  `tier0_release_record.example.json` 的基线数字。**未触碰**冻结的 `releases/tier0-release.json`
  （2301 历史证据，未被断言）及文档中的 2301 历史引用。

### 1.3 验证

- 定向：`tests/test_auto_calibrate.py` + `tests/test_auto_calibrate_cli.py` → 33 passed, 1 skipped。
- 全量回归：见本文件「验证记录」节（后台运行，完成后回填）。

## 2. 阶段 2：G7 预注册（Track C，等待授权后冻结）

> 预注册文件在**任何数字之前**写死。当前为草稿，未冻结。两个决策点待拍板：
> (a) 协议选型；(b) 模型调用预算。

### 2.1 协议选型（建议）

- **主选**：单候选内容无关评审 + 确定性程序比较（`src/workflow_action/preference_review.py`，
  已实现；k3 在 A/B+B/A 竞赛中 position_consistency=1.0 实证）。
- **备选**：route A 内容哈希规范化序 + 输出重映射。
- **排除**：槽位式 A/B 协议（两模型 position 0.34/0.43，数学上够不到 0.90）。

### 2.2 冻结内容（预注册必填）

- 协议：单候选 + 程序比较；生产与 G7 使用完全相同的机制。
- meta 规则：**Gemini 默认**；DeepSeek 仅在 (a) Gemini 弃权/耗尽、(b) 预注册窄规则
  （硬轴 violated 冲突、锚点无效、粗体裁族命中）时介入。特征全部顺序无关。
  禁止按 12 细粒度 tag 拟合；禁止直接相信模型自报 confidence。
- 错误语义：阶段 1 冻结口径。
- position 测量：**两次独立协议执行**，禁止按内容键缓存复用（那是测量漏洞）。
- 成功判据（进 holdout 的门）：calibration 嵌套 CV 总体 ≥ 0.68、粗体裁族 ≥ 0.55、
  calibration position ≥ 0.95、无静默排除。
- 停止判据：g ≥ 0.70（max_accuracy = 1−0.5g < 0.65 不可达）；分歧桶所需精度达不到；
  DeepSeek 无实质增益。

## 3. 阶段 3–4：calibration 嵌套 CV + 单次 holdout（Track C）

- **阶段 3**（只用 v2 划分 103 cal 对）：按 prompt_id 分组嵌套 CV，三路比较
  （Gemini-only / canonical Gemini / canonical Gemini + 低自由度元决策），产出联合表
  （四桶 + 一致/分歧覆盖率 g + 逐粗体裁桶）。
- **门禁**：联合表满足 2.2 成功判据才进阶段 4。
- **阶段 4**（35 holdout 对一次性资源）：只跑预注册胜出协议一次，只读验证 0.65/0.50/0.90。
  达标 → G8 90 章无人 Canary；不达标 → 封存 35 对，G7 维持诚实失败。

## 4. 阶段 5：主线确定性层 + A1 隔离（Track A）

- **确定性六职责对抗性注入测试（首批已交付）**：`tests/test_temporal_adversarial.py`（+7）
  向 FactLedger 注入已知违例验证 `check_temporal_contradictions`——死亡后活跃/过期持有/
  时间否定三类全检出 + 干净台账零误报 + 3 个负控制。
- **确定性防火墙不变量（第二批已交付）**：`tests/test_consistency_firewall_adversarial.py`（+5）——
  viability 幂等、needs_premise 的 required_premise 提及承诺内容、reveal 意译负控制/逐字正控、
  时间检出顺序无关。
- **六职责其余门禁核对（2026-08-15）**：人物一致性（character_updates 37 测）、世界合法性
  （world_background_check）、状态变化有效性（scene_experience_guard/state_necessity）、
  事务提交失败停止（falsify_blocking/contract_violations + runner fail-stop 编排）均已被既有
  测试覆盖，无重复必要。
- **Tier 0 证据核对（2026-08-15）**：`python scripts/tier0_canary_regression.py` → **PASS**
  （audit/extend/compose 三流 `novel gate` 全过）。extend/compose 序列化包缺口已按
  `30_production_readiness_checklist.md` 记录于 2026-08-06 解决，工作树确认。
- 主线结论：**确定性六职责 + Tier 0 三流回归均已闭环**；剩余 Known Limitations 为刻意边界
  （DirectAPI/闭环自动化/Tier 1 未就绪），不属于主线待办。
- Tier 0 回归与缺失证据补齐（extend/compose canary 工作区的
  `extend_rebuild_package.json` / `compose_state.json`，见 AGENTS.md Known Limitations）。
- A1 隔离归档：G7 失败记录不可变保留、标注失效/未资格化；污染划分只读归档。
- 验收证据升级：一致性轴对抗性测试 + 操作者审查有效性（audit-pass/ab）为项目级验收证据；
  G7 降级为 A1 子能力资格门。

## 5. G7 实机侦查结论（2026-08-15，真实模型调用）

在授权"不考虑预算、deepseek/Gemini 任选"后，对两模型做了**实机侦查**（真实代理调用，v2 划分）：

- **deepseek-v4-flash（经本地代理 127.0.0.1:15721）——修正结论（2026-08-15 实机）**：
  "不可用"是**误判**。正确配置 = profile UA + **max_tokens≥20000** + 不关思考（DeepSeek 官方文档
  证实思考默认开、max_tokens 是预算杠杆）；8000 预算仍偶发只出 thinking 无 text、20000 稳出。
  10 对探针（v2 划分，封死合同）：**已评估对评审质量 5/7=0.714（过 0.68 门）**，但**协议损失
  ~30%**——其中 2× 代理 502/503（15721 对 deepseek 长响应不稳定，基础设施问题）+ 1× 锚点捏造。
  严格口径总分 **0.5，不过 Phase 1 门**。结论：deepseek **评审能力可用、运营可靠性不足**。
- **Gemini（经当前代理）**：代理**按固定 provider 路由、不按模型名**——请求 `gemini-3.6-flash`/
  `gemini-3.6-pro` 均返回 `deepseek-v4-flash`。直连 Google `generativelanguage.googleapis.com`：
  key 有效但生成被拒（flash 系 403 项目拒绝 / pro 系 429 配额耗尽）。
- **Gemini（直连 8317 网关 `gemini-3.6-flash-high`，v2 划分，封死合同，2026-08-15）**：
  calibration 103 对全量测量——**overall_accuracy 0.4272（wilson_low 0.336）**、
  **position_consistency 0.5049**、per-tag 12 类中 9 类 < 0.55（辩论稿 0.0、科普 0.17、
  议论文 0.27）。**15/103 对协议不合规**（单候选评审锚点捏造 ~20 + 仲裁 decisive_anchor
  两处皆无 20 + 非 JSON 2），严格单次调用合同下计为不可评=错。调用 808 次，**holdout 零触碰**。
- **裁决（按预注册停止判据）**：两模型在 v2 划分 + 封死合同下均未过 Phase 1 门
  （overall≥0.68 且 position≥0.95）——deepseek 评审能力可用（已评估 0.714）但代理/锚点
  合规造成 ~30% 协议损失（总分 0.5）、Gemini 0.427/0.505 决定性失败。**G7 攻关正式停止，
  保留人工终裁**；35 对 holdout 封存未动用。外部数字（Gemini 0.69）在本协议/口径/划分下不复现。
- **结论**：锁定两模型在当前环境**均不过 G7 Phase 1 门**（deepseek 评审能力 0.714 但运营可靠性
  不足、Gemini calibration 0.427/position 0.505）。
  G7 维持诚实失败；自动审美终裁未资格化，人工终裁生效。此结论以实机证据为准，取代仓库内不可
  复现的外部数字（0.34/0.69/0.58）。
- **已关闭的路径**：cc-switch 切换已不再需要（Gemini 经 8317 直连已实测）。

## 6. 横切：证据完整性纪律

- holdout = 一次性资源，任何开发/调试不得触碰。
- 所有基准/划分/policy/profile 输入 SHA-256 锁（loader 已实现）。
- prompt/正文只落哈希凭证；凭证/正文不入 Git。
- 阈值只从 calibration 冻结；holdout 只读；协议变更须重预注册 + 新 holdout 集。
- 任何「通过测量漏洞获得 PASS」的企图 → 作废该轮证据。

## 7. 验证记录

- 基线（改动前）：2820 passed, 1 skipped。
- 阶段 1 定向（改动后）：tests/test_auto_calibrate.py + test_auto_calibrate_cli.py → 33 passed, 1 skipped。
- 阶段 1 全量回归：2824 passed, 1 skipped（收集 2825；基线合同 +4 同步，冻结基线 2821→2825）。
- **Track A 首批对抗性注入**：tests/test_temporal_adversarial.py → 7 passed（注入三类违例全检出 + 干净台账零误报 + 3 负控制）。
- **Track A 第二批防火墙不变量**：tests/test_consistency_firewall_adversarial.py → 5 passed（viability 幂等 / required_premise 内容 / reveal 意译负控制+逐字正控 / 时间检出顺序无关）。
- **全量回归（Track A 二批后）**：2836 passed, 1 skipped（收集 2837；基线合同 +5 同步，冻结基线 2832→2837）。
- **双模型实测 provenance（阶段 0 排查结论）**：用户提供的 DeepSeek/Gemini 实测
  （0.34 / 0.69 / 0.43 / 0.58 / 一致桶 0.50）在仓库内**不可复现**——两个仓库（skills、
  novel-main）均无对应 harness、无 Gemini 冻结 profile、无 joint 联合表记录；
  `novels/a1-calibrate/output/` 仅存 deepseek-v2 单模型证据目录。结论：这些数字只作
  **方向参考**，不得作为任何门槛判定的证据；Track C 的一切数字须在本仓库、v2 划分、
  冻结 profile 上重新测量。实机侦查结论见第 5 节。

## 8. 研究纪要：全自动「大神级」的三项门槛（2026-08-16）

> 状态：**研究结论（未进入实施）**。本节把「G7 失败」放回更大的框架——G7 只是
> 「全自动大神级」这道题的**三项门槛之一（终裁品味）**，而且是用最弱的工具做最难的一项。
> 三项门槛性质完全不同（工程 / 模型 / 判断），必须分开处理，不能再用同一套「门禁」逻辑去套。

### 8.1 三项门槛总览

| 门槛 | 能不能自动 | 卡点 | 解法 | 关键来源 |
|---|---|---|---|---|
| ① 长程因果架构 | ✅ 能（工程问题） | next-token 奖励流畅、惩罚不一致 | 确定性状态机 + 确定性校验 + 重写闭环（本项目已在正路） | NCP-Bench 2026 |
| ② 世界观原创 | ❌ 今天不能（模型问题） | base model 原创性 < 人类；原创/质量此消彼长；next-token 短视 | 换更强 base model / 换生成范式（非喂原文/搭架构） | Beyond Memory 2025；Roll the Dice 2025 |
| ③ 终裁品味 | ⚠️ 部分能，硬上限 ~78%（判断问题） | 最好自动裁判 ~78% 人类一致，且是「平均偏好」非「专家尾部」 | 专家标注 reward model（数据稀缺）+ 盲评测量改进 | LitBench 2026 |

### 8.2 ① 长程因果架构 —— 能自动，且本项目走对了方向

- **NCP-Bench（"Can LLM Agents Stick to the Script?"）**：20 轮后最强模型 GPT-5.2 只保得住 42%
  环境；事实冲突率 40–68%；**人类叙事者 19 个对抗干预全化解，每一个 LLM 都失败**。
- 根因不是上下文长度，而是**「next-token 训练目标奖励流畅文本，哪怕它与前面的事实矛盾」**；
  加 LLM 记忆（HiAgent）只治标（回合数 22→30，但引入新冲突）。
- **这恰恰验证了本项目的架构**：不指望模型不矛盾，而是把状态做成确定性第一公民
  （FactLedger / ForeshadowGraph / CharacterModel）+ 跑确定性 `fact_conflict` 检查 → 强制重写。
  这是把「模型系统性会失败」转成「测试期可拒绝、可重试的错误」。
- **结论**：长程因果**自动可解**，方向已对；剩下的不是「要人」，是把确定性检查器的覆盖率做严
  （既有的 `temporal_adversarial` / `consistency_firewall_adversarial` 测试即此方向）。

### 8.3 ② 世界观原创 —— 今天不能自动，但卡点可命名、解法可定位

- **Beyond Memory（原创性—质量边界）**：**部分 base LLM 生成文本比网上人类文本更不新颖**；
  原创性与质量**此消彼长**；**推理期 prompt 是弱杠杆**；但 scale + post-training 能同时提升两者。
- **Roll the Dice（ICML 2025）**：next-token 预测是「短视」的，开放型创造需要多 token / 扩散范式。
- **AutoWorldBuilder（多智能体世界构建）**：能从 1–2 句提示生成 95% 自洽、56–103 概念的世界，
  但两处硬伤——**概念网络只有节点没有边**（序列/塔罗那种「推导关系」没建模）、
  **只被自身 Auditor 验证、无人类质量验证**。
- **结论**：原创性天花板**焊死在 base model 训练里**，喂原文/改 prompt/搭架构都撬不动；
  只有「换更强 base model」或「换生成范式」两条路，且都不在系统推理期能做的范围。

### 8.4 ③ 终裁品味 —— 最深的一项，硬上限 ~78%，且大神级在它够不到的地方

- **LitBench（可靠评价创意写作）**：最好开箱裁判 Claude-3.7-Sonnet **73%** 人类一致；
  专门训练的 reward model **78%**（43,827 对训练、2,480 对测试、Reddit 众包标注）。
- **两个致命点**：(a) 78% 是**平均偏好**，大神级是**专家尾部判断**——区分「优秀 vs 大神」比
  「好 vs 坏」难得多，裁判在尾部接近随机；(b)「验证比生成容易」的不对称**对小说不成立**——
  无客观 ground truth，reward model 只能逼近平均人类偏好，够不到专家品味。
- **Huang 论证延伸到评价侧**：被自身能力封顶的裁判，很难可靠识别**高于自己水平**的作品；
  而大神级按定义就在模型水平之上。
- **两条真实（但不彻底）的路**：① 专家标注的 reward model（LitBench 证明训练有用 73%→78%，
  但换成「大神编辑」标注数据极稀缺）；② 盲评测量改进（「AI 故事能骗过读者，直到知道是 AI」的
  标注效应提示：部分品味差是**测量污染**而非能力差）。
- **结论**：G7 必败的原因在此——用开箱裁判（Gemini 0.427 / DeepSeek 0.714，连 73% 线都不到）
  做「大神级终裁」，是最弱工具做最难的事。

### 8.5 三项是一条因果链，不是并列三堵墙

**终裁品味是前两项的守门员**：即使长程因果和原创都解决，没有品味就无法 SELECT 出
「哪个原创是好原创」。三者性质分别为**工程 / 模型 / 判断**，必须分开处理：

- 工程（长程因果）→ 确定性层，继续做严即可，不需要人。
- 模型（原创）→ 换 base model / 换生成范式，属选型问题。
- 判断（品味）→ 短期留人做「大神级」终裁；自动层只负责「拒绝明显平庸」的粗筛。

### 8.6 来源

- NCP-Bench（长程一致基准）：https://arxiv.org/html/2608.08160v1
- Beyond Memory（原创性—质量边界）：https://arxiv.org/abs/2504.09389
- Roll the Dice（超越 next-token 创造极限）：https://mlanthology.org/icml/2025/nagarajan2025icml-roll/
- AutoWorldBuilder（多智能体世界构建）：https://arxiv.org/html/2607.09403v1
- LitBench（可靠评价创意写作）：https://aclanthology.org/2026.eacl-long.362/
- Igniting Creative Writing（LLM-as-judge vs 多智能体奖励）：https://aclanthology.org/2025.emnlp-main.868/
- AI 故事标注效应：https://indianexpress.com/article/books-and-literature/ai-written-stories-fool-readers-study-devalue-artificial-intelligence-10832020/

## 9. 任务清单：① 长程因果 + ③ 终裁品味（2026-08-16）

> 状态：**待执行**。只含 ① ③ 两项；② 世界观原创单独研究后再决定是否入列。

### 9.1 ① 长程因果：补 NCP-Bench 失败模式对抗测试

- [ ] **T1-1 枚举现状**：读 `src/domain_layer/review_signals.py`，列出全部 `detect_*` 检测器，
      建立「NCP-Bench 4 类失败模式 → 现有检测器」映射表。
- [ ] **T1-2 定位缺口**：重点确认「抹掉已完成动作（forcibly rewriting reality）」是否有对应
      检测器；其余三类（事实矛盾 / 过早披露 / 忽略承诺）确认已被 fact_conflict /
      reveal_validation / promise_loss 覆盖。
- [ ] **T1-3 补检测器**：仅对确认的缺口补确定性 `detect_*`（复用现有检测器写法，不引入新抽象）。
- [ ] **T1-4 补对抗测试**：每个缺口配一条对抗注入测试 + 一个干净负控制（复用
      `test_temporal_adversarial.py` / `test_consistency_firewall_adversarial.py` 模式）。
- [ ] **T1-5 回归 + 基线合同**：全量回归，基线常量与 provenance 同步。

### 9.2 ③ 终裁品味：G7 退役 + 盲评上位

- [ ] **T3-1 确认生产 loop 现状**：`blind_eval` / `pass_audit` 是否已在生产 loop
      （audit→extend）内被调用，还是仅 experiment 层（查 `novel_cli.py` /
      `orchestration.py` + 诡秘之主样章 output 里的 ab_judge 产物）。
- [ ] **T3-2 G7 退役**：`auto_calibrate` gate 不再作为「大神终裁」；失败记录不可变保留、
      标注未资格化（对齐第 5 节裁决）。
- [ ] **T3-3 定位三层品味守门员**：确定性粗筛（`_hard_rules` + 域检测器）→ 多裁判盲评
      相对改善（`blind_eval` + `pass_audit`）→ 人盲评 vs 原文（大神终裁）。明确每层
      回答「绝对 / 相对」哪类问题。
- [ ] **T3-4 验收**：把「blind_eval 多裁判共识 + pass_audit 漏检率」作为项目级质量验收
      证据，取代 G7 的冻结阈值 PASS/FAIL。
