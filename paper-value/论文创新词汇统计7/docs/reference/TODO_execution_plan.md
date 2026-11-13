# 论文价值信号系统 - 执行计划

> **最后更新**：2026-02-09
> **当前状态**：Phase 1-5 全部完成 ✅，Phase 6 为后续优化计划

---

## Phase 1: 基础 RPU 抽取 ✅
- [x] **全量 DeBERTa 推理**
    - 产出：`paths.rpu_db_path`
    - 状态：完成

- [x] **抽取结果质量验证**
    - 脚本：`check_extraction_quality.py`
    - 状态：完成

---

## Phase 2: 双轨抽象层构建 ✅
- [x] **Step 2.1: 发现高频短语**
    - 脚本：`mine_phrases.py`
    - 产出：`phrase_table.json`
    - 状态：完成

- [x] **Step 2.2: 核心词归一化**
    - 脚本：`normalize_cores.py`
    - 产出：`core_mapping.json`
    - 状态：完成

- [x] **Step 2.3: 应用抽象层**
    - 脚本：`apply_abstract_layer.py`
    - 状态：完成

---

## Phase 3: 创新度信号计算 (V2) ✅

### Step 3.1: V2 创新度评分系统
- [x] **系统设计与实现**
    - 核心思想：建模"常规学术空间"，创新 = 偏离常规的残差
    - 设计文档：`INNOVATION_V2_DESIGN.md`
    - 实现文件：`calculate_innovation.py`
    - 状态：完成

- [x] **核心模块**
    - `TaskIDFTracker`: 任务动词 IDF 追踪
    - `FeatureExtractor`: 6 维特征提取
    - `RegularSpaceModel`: PCA 常规空间建模 + 方向性约束
    - `SignalCombiner`: 多信号加权融合
    - `PaperTypePostProcessor`: 论文类型后处理
    - `CountMinSketch`: 内存高效的近似计数
    - 状态：完成

### Step 3.2: 预跑测试与Bug修复
- [x] **性能测试与优化**
    - 测试脚本：`test_performance.py`
    - 整体速率：5751 篇/秒（2010-2012连续运行实测）
    - 状态：完成

- [x] **Bug修复**
    - `get_state_id` 性能问题：缓存 state_id，从 1592ms 降至 0.01ms/篇
    - synergy 负值未截断：添加 `max(0, mean_score)` 截断
    - 状态：完成

### Step 3.3: 内存优化与预热功能
- [x] **Count-Min Sketch (CMS) 内存优化**
    - `cooc_counts` 从 ~77GB 降到 256MB (固定)
    - 状态：完成

- [x] **模型预热功能 (`--warmup-to`)**
    - 实现：`run_v2_full.py` 中的 `warmup_state()` 函数
    - 状态：完成

### Step 3.4: 确定性修复 (2026-02-05)
- [x] **sklearn PCA 随机化问题**
    - 问题：默认 `svd_solver='auto'` 可能使用随机化 SVD
    - 修复：设置 `svd_solver='full', random_state=42`
    - 状态：完成

- [x] **Python hash() 随机化问题**
    - 问题：`CountMinSketch` 使用 `hash()` 在不同进程间不一致
    - 修复：改用 `hashlib.md5` 确定性哈希
    - 状态：完成

- [x] **SQL 查询顺序问题**
    - 问题：`SELECT` 没有 `ORDER BY`，返回顺序不保证
    - 修复：添加 `ORDER BY paper_id`
    - 状态：完成

- [x] **确定性验证**
    - 测试：2010 年两次从头运行
    - 结果：总分差异 = 0，Top 1000 重合度 = 100%
    - 状态：完成

### Step 3.5: 全量运行 (2026-02-05)
- [x] **运行全量创新度计算**
    - 脚本：`run_v2_full.py`
    - 数据量：40,318,181 篇论文 (2010-2025)
    - 实际耗时：4.45 小时 (2519 篇/秒)
    - PCA 最终状态：k=4, 解释方差 85.86%
    - 状态：**已完成**

### Step 3.6: 结果验证 (2026-02-05)
- [x] **验证脚本**：`validate_v2_results.py`
    - 年度趋势分析
    - 论文类型权重验证
    - 数据质量检查
    - 高分/低分论文抽检

- [x] **验证结果**

| 检查项 | 结果 |
|--------|------|
| 年度覆盖 | ✅ 2010-2025 完整（4031.8 万篇）|
| 分数分布 | ✅ 均值 28→41，符合历史积累预期 |
| 论文类型权重 | ✅ erratum(5.7) < editorial(13.8) < commentary(15.1) < review(26.4) < original(42.2) |
| 数据质量 | ✅ 无空值、无负分、无 PCA 降级 |
| 确定性 | ✅ 两次运行 100% 一致 |

**各年度处理统计：**

| 年份 | 论文数 | 均值 | 中位数 | 高分(>50)比例 |
|------|--------|------|--------|---------------|
| 2010 | 164.8万 | 28.42 | 28.44 | 10.56% |
| 2015 | 216.5万 | 40.34 | 39.97 | 37.56% |
| 2020 | 296.5万 | 40.82 | 40.11 | 38.34% |
| 2025 | 277.4万 | 41.62 | 40.90 | 39.48% |

**输出文件：**
- `innovation_output_dir/innovation_v2_{year}.jsonl` - 各年度结果（共 ~19GB）
- `innovation_output_dir/checkpoint.json` - 断点文件
- `innovation_output_dir/run_log.txt` - 运行日志

---

## Phase 4: 影响力信号计算 (V5) ✅
> **状态**：已完成 (2026-02-06)
> **设计文档**：`IMPACT_V2_DESIGN.md`（V5.0）
> **运行耗时**：Pass 1 (56m) + Pass 2 (3.2h) + Pass 3 (1.1h) + Pass 4 (1h)

### 核心理念（V5.0 IU 重定义）

> **Impact = 论文引入的概念（object）在后续学术系统中被【多少人】【持续多久】采纳。**

**V5.0 核心改动**：
- **IU 从 combo 改为 object**：传播的是概念，不是研究操作
- **Task 作为权重因子**：区分 propose/apply/describe 等贡献类型
- **Top-3 聚合**：避免 RPU 数量偏倚

### Impact 与 Innovation 的彻底分离

| 维度 | Innovation（创新性） | Impact（影响力） |
|------|---------------------|-----------------|
| 时间锚点 | 发表时 | **严格发表后** |
| 核心问题 | "你是不是第一个？" | "别人是否因你而改变？" |
| 测量对象 | 作者的领先性 | 社群的跟随行为 |

### 两信号体系（V5.0）

```
Impact = Diffusion_norm × Persistence_gate
```

| 信号 | 作用 | 公式 |
|------|------|------|
| **Diffusion** | 决定上限 | percentile(log(Σ task_w × scarcity_w × post_papers)) |
| **Persistence** | 决定可信度 | min(avg_survival / 0.5, 1.0) |

**权重体系**：
- `task_weight`：propose=1.5, develop=1.2, apply=0.8, describe=0.3
- `scarcity_weight`：1 / (prior_papers + 1)

### Step 4.0: 预处理 (V5.0 新增)
- [x] **任务**：计算 object_lemma 和 task_lemma
- [x] **工具**：简单规则 lemmatization（无需 spacy）
- [x] **输出**：运行时计算，无需预存

### Step 4.1: 时序统计
- [x] **脚本**：`calculate_impact_v2.py` (Pass 1)
- [x] **输出**：`impact_output_dir/temporal_stats.db`
    - 692,007 unique units, 880,565 unique combos
    - 状态：完成 (56.5m)

### Step 4.2: Diffusion + Persistence 计算
- [x] **脚本**：`calculate_impact_v2.py` (Pass 2-3)
- [x] **输出**：`impact_output_dir/impact_signals_{year}.jsonl`
- [x] **Bridge 信号**：78,464,476 unique pairs tracked
- [x] **状态**：完成 (3.2h + 1.1h)

### Step 4.3: Impact 计算 + 归一化
- [x] **脚本**：`calculate_impact_v2.py` (Pass 4)
- [x] **输出**：`impact_output_dir/impact_final_{year}.jsonl`
- [x] **公式**：`Impact = diffusion_norm × persistence_gate`
- [x] **状态**：完成 (1h)

### Step 4.4: 验证
- [x] **脚本**：`validate_impact_v2.py` (已更新适配 V5 字段)
- [x] **分布验证**：
    - impact_score: mean=14.65, P50=0.24, P90=66.70
    - persistence_gate: 41.1% zero, 16.5% high (>0.5)
    - Zero impact papers: 38.2%

### 分类标签派生（与 Innovation 联动）

```
             Impact >= P70    Impact < P70
Innovation   ┌──────────────┬──────────────┐
>= P70       │   Pioneer    │ Ahead-of-time│
             ├──────────────┼──────────────┤
<  P70       │   Diffuser   │   Routine    │
             └──────────────┴──────────────┘
```

### 不做的事
- ❌ 使用 combo (task × object) 作为匹配键 — V5.0 改为 object
- ❌ Σ all 聚合 — 改为 Top-3 避免 RPU 数量偏倚
- ❌ 因果归因（"论文 P 导致了增长"）— 无法可靠识别

---

## Phase 5: 结果整合与可视化
> **状态**：Phase 5 全部完成 ✅

- [x] **Step 5.1: 结果合并** ✅ (2026-02-09)
    - 脚本：`merge_signals.py`
    - 输出：`paper_signals_output_dir/paper_signals_{year}.jsonl`
    - 字段：innovation_score, impact_score, role, paper_type, etc.
    - 统计：40,318,181 篇 | Pioneer 10.8% | Ahead 19.2% | Diffuser 19.2% | Routine 50.8%

- [x] **Step 5.2: 分布分析** ✅ (2026-02-09)
    - 脚本：`analyze_distributions.py`
    - 输出：`analysis_output_dir/` (4张可视化图 + JSON)
    - **正交性验证**：Pearson r=0.044, Spearman ρ=0.048 (近乎正交)
    - **论文类型交叉**：只有 original 能成为 Pioneer/Ahead-of-time

- [x] **Step 5.3: 趋势可视化** ✅ (2026-02-09)
    - 脚本：`analyze_trends.py`
    - 输出：
      - `impact_evolution.png` - 影响力分布年度演化
      - `threshold_trends.png` - P70阈值趋势
      - `role_trends.png` - 四类比例趋势
      - `pioneer_analysis.png` - 先驱者特征分析
      - `summary_dashboard.png` - 综合仪表盘

---

## Phase 6: 后续优化计划

### 现在计划（影响力及之后）
> 收录规则：仅保留影响力阶段及其之后任务

#### Impact V6 逻辑修复（已立项）
> **优先级**：高 | **立项日期**：2026-02-11

- [ ] **Step 6.3: 漏洞修复与口径对齐**
    - P0（先做）：漏洞 7/8/11 + 漏洞 4/9（评分公平性、区分力、边界稳健性）
    - P0（增量并入）：漏洞 30/32/37/38 + 漏洞 39/49/51（影响力主链路与合并健壮性）
    - P1（一致性与参数化）：漏洞 22/23/28 + 漏洞 31/36/42/43/44/45 + 漏洞 10 + 漏洞 1/3/5/6/12（保留开关，支持 A/B 回放）
    - P1（统计边界）：漏洞 47/48/50 + 漏洞 55/57/58/59/65/66（可解释性与边界稳健性）
    - P1（实现优化）：漏洞 27（移除或接入 `object_cumulative`，消除纯开销）
    - P2（归因增强）：漏洞 2（同年同概念搭便车，独立实验，补充“引领/跟随”归因指标）
    - 当前优先顺序：7 -> 8 -> 11 -> 4 -> 9 -> 30 -> 32 -> 38 -> 39 -> 22 -> 23 -> 28 -> 10 -> 其余
    - 详细任务计划：`.taskflow/active/impact-v6-remediation/task_plan.md`

#### 影响力合并与阈值联调
> **优先级**：中 | **触发条件**：Step 6.3 P0 完成后

- [ ] **Step 6.4.1: 双维度论文类型降权评估**
    - 验证创新度与影响力同时应用 `paper_type_weight` 的联合作用（#14）
    - 评估是否需要只在单维度生效或重标定系数

- [ ] **Step 6.4.2: 年度阈值与交集样本偏移评估**
    - 评估年度内 P70 阈值对跨年可比性的影响（#19/#20）
    - 评估 `common_ids` 交集合并对阈值偏移的影响（#21）

### 未来计划（影响力之前）
> 收录规则：凡属于影响力之前的前置能力，暂放未来计划

#### RPU 抽取质量优化
> **优先级**：高 | **触发条件**：当前版本验证完成后
> **问题发现**：2026-02-06 人工抽检发现 RPU 抽取质量问题

**当前问题**：
- 抽取的 cores 包含文本碎片（如 "ha f", "000 unique", "nick ing"）
- 核心科学概念未被抽取（如 "protein structure", "CRISPR", "gene editing"）
- 影响 Bridge 信号的有效性

**待优化项**：
- [ ] **Step 6.0.1: 分词质量检查**
    - 检查 DeBERTa 分词器对科学术语的处理
    - 考虑使用科学领域专用分词器或后处理规则

- [ ] **Step 6.0.2: Core 归一化优化**
    - 检查 `core_mapping.json` 覆盖率
    - 添加更多科学术语的归一化规则
    - 过滤数字碎片、单字符、无意义片段

- [ ] **Step 6.0.3: RPU 抽取模型优化**
    - 评估 DeBERTa 模型在不同领域的表现
    - 考虑领域自适应微调

#### 论文类型识别优化（前置能力）
> **优先级**：中 | **触发条件**：基础功能稳定后

- [ ] **Step 6.1: 论文类型分类模型**
    - 当前方案：基于标题关键词匹配（简单但有误判）
    - 改进方案：使用期刊元数据 `document_type` 或训练分类模型

- [ ] **Step 6.2: 论文类型权重校准**
    - 基于引用数据验证权重合理性

#### 创新度前置一致性优化
> **优先级**：中 | **触发条件**：影响力主链路稳定后

- [x] **Step 6.5.1: object_coverage 门控对齐评估（#24）**
    - 已在创新度侧引入 `off|hard_filter|soft_weight` 三策略质量门控
    - 默认 `soft_weight`，支持配置回滚与离线 A/B

- [x] **Step 6.5.2: pair_counts 归一化修复（#25）**
    - 已支持 `pair_normalization_mode=raw|lower_compact`
    - 默认 `lower_compact`，统一大小写/空白/RAW 前缀处理

- [x] **Step 6.5.3: IDF 时间漂移与 PCA 池治理（#26）**
    - 已实现 `pca_feature_source=phase1_snapshot|phase2_recompute`
    - 默认 `phase1_snapshot`，避免 Year-Atomic Phase2 混池重算污染

- [ ] **Step 6.5.4: 增量前置问题归档（#29-#66）**
    - 未来计划：`#29/#33/#34/#35/#46/#52/#53/#54/#60/#61/#62/#63/#64/#67/#68`

- [x] **Step 6.5.5: 跨学科 PCA 偏置与 Synergy 粒度评估（#67/#68）**
    - 已输出分组阈值偏移诊断：`risk_alert/max_abs_threshold_shift_pp/group_rows`
    - 已输出 Synergy 粒度 A/B：`head_overlap/head_jaccard/pearson_corr/recommended_mode`
    - 保持不纳入：`#56`（经复核判定不成立）

---

## 核心文件清单

| 文件 | 用途 |
|------|------|
| `calculate_innovation.py` | V2 创新度计算核心实现 (含 CMS) |
| `run_v2_full.py` | 全量运行脚本 (断点续传 + 预热) |
| `validate_v2_results.py` | 结果验证脚本 |
| `compare_cms_results.py` | CMS 验证对比脚本 |
| `INNOVATION_V2_DESIGN.md` | 创新度 V2 设计文档 |
| `IMPACT_V2_DESIGN.md` | **影响力 V5 设计文档**（IU=object，task 加权，Top-3 聚合） |
| `core_mapping.json` | 概念映射表 |
| `phrase_table.json` | 高频短语表 |
| `verb_innovation_weights.json` | 动词锚点权重配置 |
| `test_sample_inspect.py` | 结果人工抽检工具 |

---

## 运行命令参考

```bash
cd <PROJECT_ROOT>

# === Innovation V2 ===
# 全量运行（从头开始）
python run_v2_full.py --years 2010-2025

# 断点续传（需要预热）
python run_v2_full.py --years 2021-2025 --warmup-to 2021

# 验证结果
python validate_v2_results.py --all-years
python validate_v2_results.py --year 2020 --sample 5

# === Impact V5 ===
# 全量运行
python calculate_impact_v2.py

# 断点续传
python calculate_impact_v2.py --resume

# 单年测试
python calculate_impact_v2.py --year 2015

# 验证结果
python validate_impact_v2.py --all-years
```
