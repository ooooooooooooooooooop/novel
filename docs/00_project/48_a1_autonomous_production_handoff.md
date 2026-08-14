# 48. A1 自动叙事生产实施交接

状态：**恢复实施中（k3 provider 承重墙后重跑 G7/G8，未达到 A1/Q2A 生产验收）**  
更新日期：2026-08-14  
基线提交：`7c5222f61c2f7516d16db18b0b6c25afebf63ce1`（k3 承重墙 + 内容无关评审）

## 0. 恢复实施完成更新（2026-08-12）

**结论：A1/Q2A 未达到生产验收；发布记录与新 tag 依 §7 保留（withheld）。**  
诚实状态表述：**合同和 Provider 承重墙已完成，自动生产系统未完成**（§7 末行）。

- G0–T7 均已实现并运行：AutonomousRunner + `novel auto`、可信停止 Canary（G3 真机 run，stop 后零生成调用）、语义接缝、自动新前提、PlotUnit 多候选 + 多版正文 + EvaluatorPrecommit + JudgeClaim、匿名 A/B/B/A 换位竞赛 + 帕累托前沿、长程对账、自动校准（真实 WP_bench 冻结 split，165 calibration / 43 holdout）。
- **G7 门 FAILED（冻结阈值不降）**：真实 holdout overall 0.8837≥0.65 ✓、分类型全部 ≥0.5 ✓、**position consistency 0.5 < 0.9 ✗**（唯一未达标维）。deepseek-v4-flash 评审器把候选名命到「甲」槽位而非内容 → 换位不稳定。证据：`novels/a1-calibrate/output/calibrate-auto/holdout_report.json`（met=false）。**2026-08-14 曾用 kimi k3（thinking_disabled，judge 三角色）重跑 full calibration（165 cal + 43 holdout + 20 position 采样，`novels/a1-calibrate/output/calibrate-kimi-k3-full/`）——但其 165/43 划分是污染划分（见 §2.1 split 事实纠正），该校准证据只读保留并视为失效，G7 阈值需在 v2 划分（split_manifest_v2.json/c45cd6ad，103 cal/35 holdout）上重冻结（任务 #11）；deepseek 证据已备份 `.private_backup/`。**
- **G8 无人 Canary（deepseek 时代 0/90 章，k3 已解锁）**：deepseek-v4-flash 冻结生成 temp0.7 → 该模型任何 cap 都只出 thinking 块、无 text 块（smoke1/smoke2 ProviderSchemaError）；temp0.0+max20000 解锁产出但端点在 120s 超时（smoke3 TimeoutError）与 5xx（smoke4 HTTPError）；即便生成成功，G7 位置偏置使 A/B 淘汰赛必然 `quality_exhausted`（G6 夹具锁定）。**2026-08-14 换 k3 后全链端到端无人提交 PASS（diag3：`novels/canary-contemporary-officialdom/output/kimi-gen-diag3/`，chapter_1 committed，24 calls / $0.55，status=completed）——viability→plan→precommit→4 prose 候选（全过 falsify+seam 硬闸）→fact/character/reader 三评审→A/B+B/A tournament（position_consistency=1.0）→reader gate pass→commit。G8 的 90 章 Canary 在 G7 holdout 通过后即可运行。**
- **G9 实现级验证通过**：完整 pytest **2817 passed**（2026-08-14 k3 承重墙基线 2806 → M1 单次调用契约重写 + deepseek_active bundle 重建入口 7 测试 + M1 生产调用链回归 1 测试 = 2814 → M1b upstream_url 调用前校验 +1 adapter mismatch 测试 + 2 builder env 注入/缺失失败测试 = 2817）、Tier 0 三流回归 PASS、隐私扫描干净（novels/runtime/.taskflow 证据全部 gitignored）、Tier 0/Q1 发布记录与 tag 哈希字节不变。单命令 `scripts/a1_release_validation.py` 聚合全部证据并裁决（exit 1，`runtime/a1_gate_result.json`）。
- **发布**：Q2A/A1 release record + 不可变 tag **未生成**（G7/G8 未达 §7）；不触碰任何旧记录/tag。
- 实施记录与全部真实证据留在 gitignored 本地 `.taskflow/active/autonomous-high-quality-production/`（已归档）；框架改动已提交，证据不入 GitHub。

## 1. 结论先行

本轮只完成了 G0、T1/G1 和 T2/G2；T3 尚未写入代码，T3-G9 均未验收。

当前成果证明了两件事：

- A1 可以在不改变 Tier 0 staged CLI 语义的前提下，拥有独立的严格状态机、预算和自动决策合同。
- 项目已有一条经过真实最小调用验证的单次 Provider 通路，调用失败不会自动重试或切换 Provider，凭证、prompt、正文和思维块不进入审计文件。

当前成果**没有证明**自动系统能生产高质量小说，也没有证明评审器具有人类偏好分辨力。多候选正文、语义接缝、评审预承诺、换位盲评、长程校准、三类 30 章 Canary 和统一发布门均尚未完成。

## 2. 已完成工作

### 2.1 G0 自动预检

原先把 profile、policy 和公开基准数据推给操作者补齐的做法已撤销。系统自动完成了：

- 冻结 Provider 配置的安全引用；凭证不复制到仓库或运行证据。
- 冻结一次运行不可变的候选数、章节数、调用数、token、费用和时间上限。
- 冻结公开许可的人类写作偏好集，以及按 prompt 隔离、零交叉的 calibration/holdout 划分。
- 冻结三类公版中文作品的 30 个唯一 revision 和 SHA-256，作为人类文本分布参考。
- 核对 Tier 0 release record 与旧 tag，未修改旧发布证据。

本地冻结策略上限为 2,500 calls、30M input tokens、15M output tokens、10 USD、三类各 30 章。冻结价格下 token 双上限的理论费用为 8.40 USD，不穿透费用上限。

G0 的 profile、policy、数据和证据位于 gitignored 目录，只能作为本机证据，不能提交 GitHub。**2026-08-14 恢复实施后 G0 报告已针对 k3 provider 重生成**（`runtime/g0_report.json`，status=pass），当前 profile/policy canonical SHA-256 为：

- kimi k3 provider profile：`8fa66f1f2a2baadda66ec0a3de7a344bc77ad24cb33ebe931447103c503a8884`
- canary policy（plot_candidates=2，$25/genre）：`92a6bbcd798a467e1f6a3380a752742116aaebec751046b398d7f58ca91c8765`
- calibrate policy（plot_candidates=4，$20）：`7025a022280ab0edf0b9f88f632d74f86e97e5db15ffb15122c962592d11bc9d`

**split 事实纠正（2026-08-14，以文件字节为准）**：旧划分 `split_manifest.json`
（SHA `20864f824a91acfd406ee2cf72ecceb576141900b1b9ef4cffed79fbcc6bd560`，165 cal /
43 holdout，tag_regex=小说|故事|童话|剧本|角色扮演）是**污染划分**——被 A1 早期轮次用于
协议调参，不得再作 G7 holdout。无交叉 v2 划分在 `split_manifest_v2.json`
（SHA `c45cd6ad1640fb9688aba6bdb65973bc886237ca3f3b7d7555c9d86390f9ac01`，103 cal /
35 holdout，文学非虚构 tag，由 `scripts/build_split_manifest_v2.py` 生成，与旧划分
68 个 prompt_id 零交叉）。**上文 G0 冻结的 20864f82 是污染划分：只读保留为历史证据并
视为失效，不得沿用；G7 阈值需在 v2 划分上重冻结（见任务 #11）。**

### 2.2 T1/G1：合同、状态机和决策优先级

已新增：

- `AutonomousPolicy`、`ProviderProfile`
- `AutonomousRun`、`AutonomousUsage`
- `AutonomousDecision`、`ProviderCallAudit`
- 终态不可逆的运行状态转换
- calls/input/output/cost 四轴预算扣减
- A1 自动决策优先级

决策优先级固定为：

`Provider/Schema/Evidence error > viability stop > needs_premise > 必需评审轴/manual > 硬门禁 > 候选选择`

只有 `accepted` 可以提交正文并推进 NarrativeFrame。`manual` 在 A1 中是非法结果，必须进入 `evaluation_incomplete`；系统不会等待人工选稿。

### 2.3 T2/G2：真实 Provider 与调用审计

已实现 `AnthropicMessagesProvider`：

- 复用现有 `DirectAPIInterface` 请求/响应合同。
- 直接调用 Anthropic Messages 兼容端点，不引入 Provider SDK。
- 每次调用只执行一次 `urlopen`，无网络重试、无 Provider fallback。
- 构造时核对当前 Provider ID、名称、实际模型和 failover 状态。
- 调用前按请求字节上界和最大输出 token 硬检查预算；调用后按真实 usage 和冻结价格精确记账。
- 审计只保存模型身份、token、费用、时间和 prompt/response SHA-256；不保存凭证、prompt、正文、思维块或原始错误详情。
- A1 的自动调用开关独立于 Tier 0，未修改 Tier 0 的 `PENDING_AUTOMATION_PROVIDER_CALLS_IMPLEMENTED=False` 和 `CLOSED_LOOP_ALLOWED=False`。

真实调用证据：

- 第一次 adapter smoke 因 Python 默认 User-Agent 被上游拒绝，产生一份失败审计；没有重试同一次调用。
- 在 profile 中显式冻结兼容 User-Agent 后，另起一次 smoke，单次成功：103 input tokens、18 output tokens、成本 0.00001946 USD。
- 三个请求模型别名实际都落到同一个模型。不得把别名当成模型多样性；后续事实、人物、读者三个隔离角色能否担任评审，必须由冻结 holdout 准确率、分类型下界和 A/B 换位稳定率证明。

## 3. 本轮代码范围

以下文件属于本轮 A1 实现，恢复后应作为一个独立变更集处理：

- `src/object_state/autonomous.py`
- `src/object_state/__init__.py` 中新增的 A1 对象导出
- `src/workflow_action/autonomous_decision.py`
- `src/provider_adapter.py`
- `tests/test_autonomous_contracts.py`
- `tests/test_provider_adapter.py`

不要将工作区其他改动自动归入 A1。尤其不要使用 `git add -A`；校准工具、基线文档、release record、CLI 既有改动和其他未跟踪规格均有独立来源与提交边界。

## 4. 验证状态

已经运行并通过：

```powershell
python -m pytest tests/test_autonomous_contracts.py tests/test_provider_adapter.py -q
```

结果：`26 passed`。

在 A1 改动之前，完整基线为 `2470 passed`。A1 改动之后尚未重跑完整 pytest，因此不能声称当前工作区全绿，也不能调整 2470 发布基线。

恢复后至少依次运行：

```powershell
python -m pytest tests/test_autonomous_contracts.py tests/test_provider_adapter.py -q
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests -q
```

在 G9 之前，新增测试数量不得写回 Tier 0 既有 release record；A1 必须使用新的 Q2A/A1 release record 和新 tag，旧 tag 不移动。

## 5. 已知事实、风险和未闭合问题

### 事实

- 当前真实 Provider 角色共用同一个实际模型。
- Provider profile、策略、基准和真实调用审计均留在 gitignored 本地证据目录。
- 真实最小调用可用，真实凭证未进入源码、测试、日志或本文档；测试只使用显式假值。
- T3 的 `AutonomousRunner` 和 `novel auto` 尚未创建；本轮只完成了设计勘察，没有相关源码改动。

### 风险

- Provider 身份核验目前依赖本机代理数据库结构和外部设置文件；迁移环境时必须先重跑 G0，不能静默换 Provider。
- 单一实际模型可能无法达到冻结的人类偏好 holdout 门；若未达标，应使 G6/G7 失败，不得降低阈值或用角色别名伪装多样性。
- 当前公开偏好集只用于开发校准/holdout；它不能替代项目真实连续章节 Canary，也不能证明普通读者愿意持续阅读。
- G0 报告引用哈希已陈旧，未重生成前不能作为发布证据。

## 6. 精确恢复入口

恢复实施时，不重新设计 T0-T9；按以下顺序继续：

1. 重生成 G0 报告，验证 profile/policy/两类数据 manifest 的当前 SHA-256，并确认 Tier 0 证据未变。
2. 实现 `AutonomousRunner` 与 `novel auto`，显式传入 policy/profile；运行目录拒绝覆盖，失败运行不得进入后续上下文。
3. 先过可信停止 Canary：viability 在任何规划/正文调用前裁决；`stop` 后正文生成调用必须为零。
4. 实现 `needs_premise` 自动搜索和 `premise_exhausted`，不存在 `[WAITING]` 或转人工路径。
5. 实现事件指纹和语义接缝，阻断同一事件重演，同时保留文学歧义。
6. 实现不同状态变化的 PlotUnit 候选、多版正文、不可修改的 EvaluatorPrecommit 和带正文锚点的单轴 JudgeClaim。
7. 实现匿名 A/B 与 B/A、位置一致性、硬轴淘汰、帕累托前沿；无稳定赢家进入 `quality_exhausted`。
8. 完成 calibration/holdout 严格隔离、10/20/30 章长程对账和三类各 30 章无人 Canary。
9. 实现单命令 A1 发布验证，完整回归、隐私扫描、旧 tag 核对全部通过后，才生成新的 Q2A/A1 release record 和不可变 tag。

## 7. 后续验收口径

A1 只有同时满足以下条件才算完成：

- 无 `[WAITING]`、`manual`、人工响应或人工选稿。
- `stop` 优先，停止后零正文生成调用。
- Provider/Schema/预算/证据错误无重试、无 fallback、无状态污染。
- 所有硬事实冲突为零；所有必需质量轴已武装。
- 评审器达到冻结 holdout 总体与分类型下界，A/B 换位稳定率达到预注册阈值。
- 三个冻结类型各连续 30 章通过，并完成 10/20/30 章正文重建对账。
- 完整 pytest、Tier 0 回归、隐私门、A1 Canary 聚合和统一发布命令全部通过。
- 生成独立 A1 发布记录与新 tag；任何旧 release record 或 tag 均未改写。

在这些证据出现之前，应使用“合同和 Provider 承重墙已完成，自动生产系统未完成”的表述。
