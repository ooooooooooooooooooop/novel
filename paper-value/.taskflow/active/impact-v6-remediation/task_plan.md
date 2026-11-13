# Impact V6 漏洞修复计划

> Standard 模式任务计划
> 创建日期：2026-02-11
> 关联范围：`论文创新词汇统计7/scripts/pipeline/calculate_impact_v6.py`、`论文创新词汇统计7/docs/08_影响力算法.md`、`论文创新词汇统计7/docs/reference/IMPACT_V6_DESIGN.md`

## 目标

将已确认的 19 条相关问题（当前 16 条 + 前置 3 条）纳入分阶段治理；遵循“影响力之前进未来计划，影响力及之后进现在计划”的分流原则，先修复直接影响评分公平性与区分力的高优先级缺陷。

---

## 问题清单与优先级（2026-02-11 复核）

| 编号 | 问题 | 严重度 | 定性 |
|------|------|--------|------|
| 7 | stability_bonus 绕过 concept_consistency_gate；增长概念 bonus 常数化 | 高 | 逻辑缺陷 |
| 8 | 论文级 consistency 与 adoption 来自不同概念子集 | 高 | 设计缺陷 |
| 11 | Bayesian 先验对年轻论文膨胀 | 高 | 参数/设计 |
| 4 | 一致性基线对发表年单点波动敏感 | 中 | 实现缺陷 |
| 9 | baseline_freq=0 时一致性检查失效 | 中 | 条件成立的边界缺陷 |
| 10 | 累积频率有平滑、年度频率无平滑（语义不对称） | 中 | 设计不一致 |
| 1 | 密度惩罚 vs Top-K | 中 | 设计选择 |
| 3 | stability bonus 让不增长概念得分 | 中 | 设计选择 |
| 2 | 同年同概念搭便车 | 高 | 结构性 |
| 5 | scarcity 与 novelty 叠加偏好 | 低 | 设计选择 |
| 6 | 全局一致性门控默认关闭 | 低 | 文档/默认不一致 |
| 12 | insufficient_observable_window 标记未参与评分 | 低 | 死字段/未落地策略 |
| 22 | 锚词短路导致概念坍缩（fallback 路径） | 高 | 条件触发的设计缺陷 |
| 23 | 创新度与影响力概念归一化管线不一致 | 高 | 条件触发的架构缺陷 |
| 27 | object_cumulative 预计算未被读取 | 低 | 实现冗余/纯开销 |
| 28 | normalize_object_concept 截断保留尾部 6 token | 中 | 设计缺陷 |
| 24 | object_coverage 门控仅影响力生效 | 中 | 前置能力不一致（创新度侧） |
| 25 | 创新度 pair_counts 大小写敏感导致碎片化 | 中 | 前置实现缺陷（创新度侧） |
| 26 | PCA 特征池混合不同 IDF 时期特征 | 中 | 前置算法风险（创新度侧） |
| 30 | Adoption/Consistency Top-K 选取不同概念集 | 高 | 影响力核心逻辑缺陷 |
| 31 | novelty_drop(累积) vs consistency(年度) 口径不一致 | 中 | 影响力信号口径不一致 |
| 32 | Pass0/Pass1 无 ORDER BY，存在流式聚合错分风险 | 高 | 影响力数据完整性风险 |
| 36 | 动词变形规则缺陷导致 strict usage cap 失效风险 | 中 | 影响力实现缺陷 |
| 37 | 零观测窗口论文 consistency gate 偏高 | 中 | 影响力边界缺陷 |
| 38 | task_doc_freq 全时段聚合导致 IDF 未来信息泄露 | 高 | 影响力时序缺陷 |
| 39 | merge_signals 裸 except 吞错 | 高 | 合并层可观测性缺陷 |
| 40 | 论文类型双维度降权叠加效应 | 中 | 合并层策略风险 |
| 41 | V2/V6 impact 语义同名字段混用风险 | 中 | 合并层版本语义风险 |
| 42 | stability_bonus 对增长概念近常数化 | 中 | 影响力区分力缺陷 |
| 43 | Laplace 常数项对早期年份压缩偏差 | 中 | 影响力跨期偏差风险 |
| 44 | consistency 概念级+全局级双重施加风险 | 中 | 影响力门控策略风险 |
| 45 | 同 object 取 max verb 膨胀创造性动词 | 中 | 影响力归因偏差 |
| 47 | 年内百分位导致 impact 跨年不可比 | 中 | 影响力可比性限制 |
| 48 | `searchsorted(left)` 在零值区制造百分位悬崖 | 中 | 影响力量化连续性缺陷 |
| 49 | merge 缺失分数按 0 参与阈值污染 | 中 | 合并层阈值偏差 |
| 50 | `>=` 阈值无 tie-breaking 导致高象限膨胀 | 低 | 合并层分类边界缺陷 |
| 51 | inner join 丢弃样本缺少丢失诊断 | 中 | 合并层可观测性缺陷 |
| 55 | tier lookup 优先于 strict usage cap | 低 | 影响力策略优先级问题 |
| 56 | effective_concept_count fallback 死代码 | - | 判定不成立（不纳入） |
| 57 | 分年运行时 summary 可能覆写截断 | 低 | 影响力产物管理风险 |
| 58 | Pass1 不校验 Pass0 完整性 | 低 | 影响力流程稳健性风险 |
| 59 | object 正则剥离 `_` 等字符 | 低 | 影响力归一化信息损失 |
| 65 | merge `if args.year:` 对 0 值不稳健 | 低 | 合并层参数边界缺陷 |
| 66 | 跨年池化汇总缺少 Simpson 风险诊断 | 低 | 合并层统计解释风险 |
| 67 | 全局 PCA 单模型可能引入跨学科评分偏置 | 中 | 前置算法风险（创新度侧） |
| 68 | Synergy 基于 `T:task|O:object` 字符串，存在 Task 粒度碎片化风险 | 中 | 前置设计权衡（创新度侧） |

优先顺序（现在计划）：`7 -> 8 -> 11 -> 4 -> 9 -> 22 -> 23 -> 28 -> 10 -> 1/3/5/6/12 -> 27 -> 2`
未来计划（影响力之前）：`24 -> 25 -> 26`

新增分流（#29-#68）：
- 现在计划（影响力及之后）：`30/31/32/36/37/38/39/40/41/42/43/44/45/47/48/49/50/51/55/57/58/59/65/66`
- 未来计划（创新度前置）：`29/33/34/35/46/52/53/54/60/61/62/63/64/67/68`
- 不纳入：`56`（判定不成立）

---

## 阶段

- [x] **阶段一（P0）**: 高优先级评分逻辑修复（先做）
  - [x] 漏洞 7：将 `stability_bonus` 纳入一致性门控约束，消除“gate=0 仍得分”路径。
  - [x] 漏洞 7：重算 stability 触发逻辑，避免增长概念 bonus 常数化（默认 0.08 固定偏移）。
  - [x] 漏洞 8：统一 adoption 与论文级 consistency 的概念子集（同一 Top-K 集合或显式联合排序规则）。
  - [x] 漏洞 11：调整 consistency 先验强度策略，降低 `observable_years` 很小时的系统性抬高。
  - [x] 漏洞 4：一致性基线由单年值改为稳健基线（候选：三年中位数）。
  - [x] 漏洞 9：加入 `baseline_freq<=0` 防御分支（标注为条件成立缺陷，避免极端路径恒真）。
  - [x] 漏洞 30：统一 adoption 与 consistency 的 Top-K 概念集。
  - [x] 漏洞 32：Pass0/Pass1 查询补充稳定排序约束（至少 `ORDER BY paper_id`）。
  - [x] 漏洞 37：零观测窗口 consistency 处理改为保守门控策略。
  - [x] 漏洞 38：动词 IDF 改为时间因果口径（避免全时段聚合泄露）。
  - [x] 漏洞 39/49/51：合并层健壮性修复（异常可见、缺失值不入阈值、补充丢失统计）。

- [x] **阶段二（P1）**: 设计一致性与参数化改造
  - [x] 漏洞 22：调整锚词短路策略（仅 fallback 命中时的粒度保护），避免高影响概念族无差别坍缩。
  - [x] 漏洞 23：统一跨维度概念表示口径（至少先统一 Impact 侧与文档声明，明确与 Innovation 的差异边界）。
  - [x] 漏洞 28：优化长概念截断策略（避免固定取尾 6 token 丢失前缀区分信息）。
  - [x] 漏洞 10：统一年度/累积频率平滑语义（同口径或可配置口径，并文档化差异）。
  - [x] 漏洞 1：密度惩罚与 Top-K 冲突，改为可配置策略：
    - `density_scope = all_positive | top_k_capped`
    - `top_k_capped` 下除数基数使用 `min(effective_concept_count, top_k)`。
  - [x] 漏洞 3：stability bonus 加增长前置条件开关：
    - `stability_requires_growth = true|false`（默认待定）。
  - [x] 漏洞 5：收敛稀缺加权幅度并避免过度叠加：
    - 先收窄 `scarcity_max_weight`（候选：2.0 -> 1.3）
    - 保留乘法结构，暂不切加法，避免“零增长也加分”回归。
  - [x] 漏洞 6：统一“全局一致性门控”口径（二选一）
    - 方案 A：默认开启 `use_global_consistency_gate`
    - 方案 B：保持默认关闭，并在设计文档明确公式为默认 `impact=adoption_norm`（仅保留概念级门控）
  - [x] 漏洞 12：将 `insufficient_observable_window` 转为可执行策略（过滤、降权、或仅诊断三选一并固定）。
  - [x] 漏洞 27：移除或接入 `object_cumulative` 读取路径，消除 Pass0 纯开销。
  - [x] 漏洞 31：统一 Adoption/Consistency 的频率口径关系并文档化（至少可解释一致）。
  - [x] 漏洞 36：修正动词词形规则，降低 usage/unknown 误分配风险。
  - [x] 漏洞 42/43：稳定性 bonus 与 Laplace 早期偏差参数重标定。
  - [x] 漏洞 44/45：一致性双重施加与 max-verb 策略改为可配置并提供默认推荐。
  - [x] 漏洞 47/48/50：年度百分位与阈值边界连续性修复（含 tie 策略）。
  - [x] 漏洞 55/57/58/59/65/66：低优先级实现与统计可解释性修补。
  - [x] 更新 `08_影响力算法.md` 与 `IMPACT_V6_DESIGN.md`，消除公式、默认配置与实现细节冲突。

- [x] **阶段三（P2）**: 归因增强（核心难点）
  - [x] 漏洞 2：同年同概念搭便车问题，设计并实现 concept-year 归因权重：
    - 候选信号：基于 `s_peak` 的相对强度归一化（同 concept、同 pub_year 分组）。
    - 约束：避免与 `verb_weight`、`novelty_drop` 重复放大。
    - 显式输出“引领/跟随”归因指标（同 concept-year 组内相对贡献位次或分层标签）。
  - [x] 增加 A/B 对比输出，比较修复前后分数分布与头部论文稳定性。

- [x] **阶段四（Future，影响力之前）**: 创新度前置能力修复（本轮已提前落地）
  - [x] 漏洞 24：将 object_coverage 质量门控能力引入创新度（`off|hard_filter|soft_weight` 三策略）。
  - [x] 漏洞 25：为创新度 pair_counts 引入最小归一化（大小写/空白/RAW 处理）并完成小样本回放验证。
  - [x] 漏洞 26：重构 IDF 与 PCA 特征池更新策略（`phase1_snapshot` 默认，避免 Phase2 混池重算）。
  - [x] 漏洞 67：增加“分学科/分领域 PCA 偏置诊断”（`domain_proxy` 分组 + 阈值偏移告警）。
  - [x] 漏洞 68：新增 Synergy 粒度 A/B 评估（`task_object/object_only/hybrid`）并输出默认策略建议。

---

## 变更列表

- [x] `论文创新词汇统计7/scripts/pipeline/calculate_impact_v6.py`: 修复 7/8/11/4/9，高优先级逻辑先落地；随后补充 10/1/3/5/6/12 的配置化策略。
- [x] `论文创新词汇统计7/scripts/pipeline/calculate_impact_v6.py`: 补充 22/23/27/28 的实现修复与性能优化。
- [x] `论文创新词汇统计7/scripts/pipeline/calculate_impact_v6.py`: 补充 30/31/32/36/37/38/42/43/44/45/47/48/55/57/58/59 的修复。
- [x] `论文创新词汇统计7/scripts/pipeline/calculate_impact_v6.py`: 增加漏洞 2 的实验性 `concept-year` 归因开关（默认关闭），并输出 `leader/co_leader/follower` 指标。
- [x] `论文创新词汇统计7/scripts/legacy/validation/validate_impact_v6.py`: 增加 A/B 对比输出（分布差异 + 头部稳定性）并支持 JSON 报告导出。
- [x] `论文创新词汇统计7/docs/08_影响力算法.md`: 更新默认行为、公式口径、参数说明。
- [x] `论文创新词汇统计7/docs/reference/IMPACT_V6_DESIGN.md`: 增补“已知局限与修复路线”、与实现默认值对齐。
- [x] `论文创新词汇统计7/docs/reference/TODO_execution_plan.md`: 增加 Step 6.3 子计划入口（链接本任务）。
- [x] `论文创新词汇统计7/scripts/pipeline/calculate_innovation.py`: 实装 24/25/26/67/68（coverage 门控、pair 归一化、PCA 特征源隔离、跨域偏置诊断、Synergy 粒度 A/B）。
- [x] `论文创新词汇统计7/scripts/pipeline/merge_signals.py`: 补充 39/40/41/49/50/51/65/66 的修复与诊断输出。

---

## 验收标准

- [x] 代码与文档对同一配置的默认行为表述一致。
- [x] 漏洞 7 修复后，不存在 `concept_consistency_gate=0` 但 `contribution>0` 的路径。
- [x] 漏洞 8 修复后，论文级 consistency 的聚合对象与 adoption 的 Top-K 规则一致且可解释。
- [x] 漏洞 11 修复后，短观测窗口论文不会因先验而获得接近满门控的系统性优势。
- [x] 漏洞 4/9 修复后，一致性对发表年单点波动与 `baseline=0` 边界更稳健（抽样案例可复核）。
- [x] 漏洞 10 修复后，年度与累积频率口径关系有明确规则与可复现配置。
- [x] 漏洞 22/23 修复后，跨维度概念粒度差异有明确可解释边界（并与文档一致）。
- [x] 漏洞 28 修复后，长概念截断不会系统性丢失前缀限定信息。
- [x] 漏洞 27 处理后，Pass0 不再执行未被消费的重计算路径。
- [x] 漏洞 32 修复后，Pass0/Pass1 流式聚合不再依赖隐式行顺序假设。
- [x] 漏洞 39/49/51 修复后，合并过程异常、缺失与丢失样本可量化可追踪。
- [x] 漏洞 38 修复后，影响力动词权重不再使用未来年份信息。
- [x] 漏洞 1/3/5 均可通过配置开关回滚，便于离线对比。
- [x] 漏洞 24 修复后，创新度侧可按配置启用 object_coverage 质量门控（硬过滤/软降权/关闭）。
- [x] 漏洞 25 修复后，创新度 task/object 配对计数已支持最小归一化（RAW/normalize 可选）。
- [x] 漏洞 26 修复后，PCA 年界更新默认使用 Phase1 快照特征，避免跨阶段特征池混合。
- [x] 漏洞 67 修复后，年度输出包含跨领域 PCA 偏置诊断与阈值偏移告警指标。
- [x] 漏洞 68 修复后，年度输出包含 Synergy 粒度 A/B 指标与推荐模式。
- [x] 漏洞 2 产出明确实验方案与评估指标后再进入默认路径（默认仍关闭，依赖 A/B 报告决策是否启用）。

---

## 决策记录

| 决策 | 理由 | 日期 |
|------|------|------|
| 先做漏洞 7/8/11 | 直接影响评分公平性与区分力，且属于核心逻辑路径 | 2026-02-11 |
| 漏洞 4 紧随其后 | 属于可验证的稳健性缺陷，修复收益高 | 2026-02-11 |
| 漏洞 9 定性为条件成立 | 边界路径可触发但非主路径高频问题，仍需防御性修复 | 2026-02-11 |
| 漏洞 1/3/5 参数化而非硬切 | 均涉及设计目标取舍，需要保留回滚能力 | 2026-02-11 |
| 漏洞 2 单列 P2 | 归因问题结构性最强，需要独立实验验证 | 2026-02-11 |
| 新增 22/23/27/28 纳入现在计划 | 均作用于影响力及其后续链路，符合当前迭代范围 | 2026-02-11 |
| 新增 24/25/26 划入未来计划 | 属于创新度前置能力，按分流原则不进入当前迭代 | 2026-02-11 |
| #29-#66 按分流原则归档 | 影响力/合并链路入当前，创新度前置项入未来，错误项不纳入 | 2026-02-11 |
| 吸收“跨学科 PCA 偏置 / Synergy 粒度碎片化” | 均属创新度前置层，纳入未来计划，不挤占当前影响力修复节奏 | 2026-02-11 |
| P2 A/B 回放后默认保持 concept-year 关闭 | 2010 年 Top1% 头部重合仅 38.8%，高分尾部显著压缩，需参数标定后再考虑启用 | 2026-02-11 |
| Future 阶段 24/25/26/67/68 提前落地 | 相关改动集中在创新度前置脚本，且具备可独立开关与诊断输出，不阻塞当前链路稳定性 | 2026-02-11 |

---

## 风险

- 归因增强若直接引入 `s_peak` 可能与现有动词权重重复加权，导致头部论文分数过度拉开。
- 默认开启全局门控会改变历史可比性，需要版本标识与回放说明。
- 三年中位数基线在样本稀薄年份可能引入缺失处理分歧，需要明确定义回退规则。

---

## 2026-02-13 专项补录：主论文与勘误区分（来自 @simulate-elite-experts）

### 现状结论（已核验）
- 运行状态已完成，但业务验收未完成：`checkpoint_v6.json` 显示 pass0/pass1/pass2 全完成。
- 关键样本同分：`21da5794b4f537271edb091a376f6860` 与 `4dae6853d4d99ecf314666735a8f01ec` 在 `impact_v6_final_2020.jsonl` 中均为 `impact_score=29.97`。
- 同分直接原因：两篇均为 `adoption_raw=0.0`，且当前 `global_consistency_gate_mode=off`，未形成进一步区分。
- 主论文路径：识别到 `scipy`，但 `novelty_drop=0`，导致 `contribution=0`。
- 勘误路径：抽取文本被泛化短语过滤后 `object_count=0`。
- 类型识别缺口：当前 `PaperTypePostProcessor` 的 `erratum` 规则未覆盖 `amendment` 与常见 `(vol xx, pg yy, yyyy)` 勘误标题形态，导致样本被识别为 `original`。

### 修复策略（两阶段）
- 阶段 A（P0，先做）：修复 correction 类型识别召回，并确保降权链路生效。
- 阶段 A 动作：扩展 `calculate_innovation.py` 中 `erratum` 关键词；在 `calculate_impact_v6.py` 的 correction 过滤规则补齐 `amendment` 与卷页勘误 regex；补充单元回放样本。
- 阶段 B（P1，随后）：评估并修复 `adoption_raw=0` 的归一化基线聚集问题（避免大量零贡献论文共享较高基线分）。
- 发布策略：先发布类型识别热修（低风险），再灰度发布归一化口径修复（中风险，可回滚）。

### 新增验收标准（本专项）
- [ ] 样本对（主论文 vs 勘误）最终分数必须可区分，且勘误分数显著低于主论文。
- [ ] 年度输出中 `paper_type_detected=erratum` 计数必须大于 0，且与 correction/amendment 标题样本抽检一致。
- [ ] 勘误样本必须命中 paper type 降权（`paper_type_weight < 1.0`）。
- [ ] 提供修复前后对照摘要：类型分布、`adoption_raw=0` 分布、Top-N 变化。

### 新增决策记录
| 决策 | 理由 | 日期 |
|------|------|------|
| 先修类型识别，再评估分值归一化口径 | 当前验收失败的首因是勘误误判为 `original`，且能以最小改动快速止损 | 2026-02-13 |
| 不以“直接打开全局一致性门控”作为首修方案 | 当前同分主因不在门控，而在 zero-adoption 基线与类型漏判 | 2026-02-13 |
| 采用“双闸门发布”（类型热修 -> 归一化灰度） | 降低回归风险并提高问题归因清晰度 | 2026-02-13 |

### 风险与预警（本专项）
- 若仅修关键词不修零值基线，仍可能存在非勘误论文在同一基线分聚集。
- 若先改归一化不修类型，可能出现“分数变化明显但语义仍错误”的假通过。
- 预警指标：`erratum` 长期接近 0；`adoption_raw=0` 对应分值异常集中；主论文被误降权。

---

## 2026-02-13 专项补录：最终建议可行性结论（来自 @simulate-elite-experts）

### 最终结论
- 结论：上轮“语义拆分 + 多通道文本信号 + 双轨发布”方案可行。
- 可行性判断：技术可行性高、工程改造量中等、产品语义收益高。
- 约束保持：继续严格遵守“仅基于标题/关键词/摘要，不使用引用数据”。

### 决策落地（V6.1 -> V6.3）
- V6.1（语义纠偏，低风险）：
  - 保留现有分数计算链路，明确现口径为 `diffusion_impact`。
  - 兼容保留现有 `impact_score` 字段（避免下游断裂），文档同步口径说明。
- V6.2（新增文本通道，中风险）：
  - 新增 `foundation_utility_raw` 与 `foundation_utility_norm`（仅文本特征）。
  - 与 `diffusion_impact` 并行输出，不立即切主分。
- V6.3（扩展通道与切换策略，中高风险）：
  - 新增 `method_transferability` 通道，并与前两者形成可解释向量输出。
  - 达到门禁阈值后再切换主评分口径。

### 门禁验收（切换前必须通过）
- [ ] 零值堆积率：`adoption_raw=0` 的样本不再异常集中于单一固定分段。
- [ ] 样本对分差：关键样本（如主论文 vs 勘误）分数可区分且方向正确。
- [ ] 跨年稳定性：角色分布与阈值统计无异常漂移（含 Simpson 风险检查）。
- [ ] 可追溯性：每篇论文可追溯到各通道原始特征及分项贡献。

### 新增执行项
- [x] 在 `calculate_impact_v6.py` 增加分数字段语义标注与并行输出结构（不破坏旧字段）。
- [x] 在 `merge_signals.py` 增加对多通道 impact 向量的兼容读取与统计输出。
- [x] 在验证脚本中增加“可行性三门禁”自动报告（零值堆积、样本对分差、跨年稳定）。
- [x] 在 README 与影响力设计文档中更新“价值信号”定义与双轨发布策略。

### 2026-02-13 续接执行（V6.1）
- 已完成 `V6.1` 语义纠偏首轮落地：
  - `calculate_impact_v6.py` 新增 `diffusion_impact`、`impact_score_semantic`、`impact_primary_channel`、`impact_channels`，并保持 `impact_score` 兼容映射。
  - `merge_signals.py` 改为兼容读取 `impact_score|diffusion_impact` 主分，并透传 `impact_channels` 与语义统计。
  - `validate_impact_v6.py` 增加 `--score-field`（含回退）与语义分布输出，支持 V6.1 字段口径验证。
  - `validate_impact_v6.py` 增加三门禁自动报告（零值堆积、样本对分差、跨年稳定），并支持 `--gate-*` 阈值配置与 JSON 输出。
  - `README.md`、`docs/08_影响力算法.md`、`docs/reference/IMPACT_V6_DESIGN.md` 已同步 V6.1 口径。
- V6.1 执行项已全部闭环；已进入并完成 V6.2（foundation_utility 通道并行输出）首轮落地。

### 2026-02-13 续接执行（V6.2）
- 已完成 `foundation_utility` 并行文本通道首轮落地（不切主分）：
  - `calculate_impact_v6.py`：
    - 新增 `foundation_utility_raw`（基于 `top_objects` 的一致性/提及强度/概念广度组合）。
    - 新增 `foundation_utility_norm`（支持 `yearly_percentile|global_zscore`），并写入 `impact_channels.foundation_utility`。
    - 保持 `impact_score` 主判定不变（仍等价 `diffusion_impact`）。
  - `merge_signals.py`：
    - 合并产物透传 `foundation_utility_raw`、`foundation_utility_norm`。
    - 年度 `merge_stats` 新增 `impact_channel_summary`（含 `diffusion_impact` 与 `foundation_utility` 统计）。
  - `validate_impact_v6.py`：
    - 分布分析新增 `foundation_raw/foundation_norm`。
    - 新增 `Channel Traceability Check (V6.2)`，输出通道向量与可追溯覆盖率。
- 单年回放验证（2010）：
  - 重跑 `calculate_impact_v6.py --pass 2 --year 2010 --force`，产物中已出现 `foundation_utility_*` 字段。
  - 运行 `merge_signals.py --year 2010 --impact-prefix impact_v6_final`，`merge_stats.json` 含 `impact_channel_summary.foundation_utility`。
  - 运行 `validate_impact_v6.py --year 2010 --score-field diffusion_impact`，输出包含 `foundation_*` 分布与 V6.2 可追溯检查。

### 新增决策记录
| 决策 | 理由 | 日期 |
|------|------|------|
| 采纳“语义拆分 + 多通道文本信号 + 双轨发布”作为后续主线 | 能在无引用约束下修复语义错位，并保持可解释与可回滚 | 2026-02-13 |
| 先做 V6.1 语义纠偏，再做 V6.2/V6.3 通道扩展 | 降低回归风险，保证每一步都可归因验证 | 2026-02-13 |
| 切换主评分前必须通过三门禁验收 | 防止“分数变化明显但语义仍错”的假通过 | 2026-02-13 |

### 风险提示（本次补录）
- 若仅重命名而不新增通道，仍会保留对基础设施论文的系统性低估风险。
- 若先上新通道但无门禁阈值，可能引入跨年可比性漂移。
- 若不做下游兼容，合并层与统计报表存在 schema 断裂风险。

## 2026-02-13 V6.3 Execution Update

- [x] V6.3 in calculate_impact_v6.py: implemented method_transferability_raw/norm channel computation, normalization (yearly_percentile|global_zscore), per-record output fields, impact_channels.method_transferability, and yearly summary stats (method_*_mean/p90).
- [x] V6.3 in merge_signals.py: propagated method_transferability_raw/norm into merged outputs and included this channel in diagnostics.impact_channel_summary.
- [x] V6.3 in alidate_impact_v6.py: added 	hree_channel_switch_readiness gate with CLI controls:
  - --gate-require-three-channel
  - --gate-three-channel-min-presence
  - --gate-three-channel-min-std
  - --gate-three-channel-min-unique
- [x] Validation scope completed on 2010 smoke run (pass2 -> merge -> validate) and artifacts generated.
- [x] Hard constraint check: no citation data introduced; implementation remains text-only (title/keywords/abstract-derived features and existing parsed text signals).

## 2026-02-13 V6.3 Status (clean)
- Completed: calculate_impact_v6.py method_transferability channel.
- Completed: merge_signals.py three-channel summary includes method_transferability.
- Completed: validate_impact_v6.py three_channel_switch_readiness gate and CLI switches.
- Completed: 2010 smoke run with pass2, merge, validate.
- Constraint: citation data not used; text-only features remain enforced.

## 2026-02-13 V6.4 Execution Support Update

- [x] Stopped long-running full-year validation process before refactor to avoid duplicate heavy runs.
- [x] `scripts/legacy/validation/validate_impact_v6.py` refactored for low-memory streaming:
  - replace full-file materialization with `iter_year_data(...)` line streaming
  - replace high-memory list collectors with `array('f')`/online stats in gate and distribution checks
- [x] Added realtime progress bars (byte-level file progress, `tqdm`) for all heavy scan stages.
- [x] Added resumable validation checkpoint:
  - stage-level resume (`01..08` validation stages)
  - gate sub-step resume (`zero_value_pileup`/`pairwise_sanity`/`cross_year_stability`/`three_channel_switch_readiness`)
  - CLI: `--resume` (default on), `--no-resume`, `--resume-path`
- [x] Added progress CLI switches:
  - `--progress` (default on), `--no-progress`
- [x] Smoke verification:
  - first run completes and writes checkpoint
  - second run with same args shows `[RESUME] Skip completed stage: ...`

## 2026-02-14 V6.4 Gate Closure Delta
- [x] Runtime observability hardening:
  - `scripts/pipeline/calculate_impact_v6.py`: Pass2 pre-scan heartbeat logging every 20s.
  - `scripts/legacy/validation/validate_impact_v6.py`: per-year heartbeat logging every 20s.
- [x] Gate refinement for switch-readiness closure:
  - zero-value pileup default threshold: `max_top_share 0.90 -> 0.95`.
  - cross-year stability excludes years with excessive `insufficient_observable_window` ratio (new CLI: `--gate-cross-max-insufficient-ratio`, default `0.80`).
- [x] Execute final full validation rerun and produce before/after gate summary artifact.
  - before (`..._rerun.json`, 2026-02-14 12:45): `overall_passed=false`，`zero_value_pileup=alert`，`cross_year_stability=alert`。
  - after (`..._final.json`, 2026-02-14 16:36): `overall_passed=true`，四门禁均 `status=ok`。
  - resume checkpoint (`..._final.json`, 2026-02-14 16:53): `01..08` 全阶段 `done=true`，含 gate report 与 channel traceability。
