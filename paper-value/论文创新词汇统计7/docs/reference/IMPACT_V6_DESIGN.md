# Impact Signal V6 设计文档

> **版本**：6.2
> **最后更新**：2026-02-13
> **状态**：已实现（持续修复中）
> **前置依赖**：创新度 V2 计算流程（`calculate_innovation.py`）

---

## 0. 实现对齐（2026-02-11）

以下为当前代码默认行为（`scripts/pipeline/calculate_impact_v6.py` + `merge_signals.py`），用于覆盖旧文档中与实现不一致的口径：

- 全局一致性门控默认关闭：`global_consistency_gate_mode=off`（可选 `legacy_ratio` / `residual_soft`）
- Adoption/Consistency 频率口径显式配置：
  - `novelty_freq_source = cumulative|yearly`（默认 `cumulative`）
  - `consistency_freq_source = yearly|cumulative`（默认 `yearly`）
- 年度/累积频率平滑默认使用 `laplace_adaptive`，并支持 `*_vocab_scale` 自适应词表规模，降低早期年份压缩偏差
- 稳定性 bonus 重标定：
  - `stability_bonus_growth_power`（默认 `0.6`）
  - `stability_bonus_max_ratio`（默认 `0.5`，限制 bonus 相对 growth_component 的上限）
- 同 object 动词聚合默认 `object_verb_weight_mode=blended`（`blend_alpha=0.65`），不再默认 `max-verb`
- 严格动词策略中 usage cap 作为硬上限，不再被 tier 权重绕过
- Pass2 默认采用 `adoption_norm_mode=global_zscore`（跨年可比）；回退模式 `yearly_percentile` 默认 `adoption_rank_method=mid`
- V6.1 语义纠偏：当前主分通道显式命名为 `diffusion_impact`，`impact_score` 保留为兼容别名
- Pass2 输出新增语义字段：
  - `impact_score_semantic = "diffusion_impact"`
  - `impact_primary_channel = "diffusion_impact"`
  - `impact_channels = {"diffusion_impact": <score>}`
- V6.2 并行文本通道：新增 `foundation_utility_raw` / `foundation_utility_norm`
  - 仅基于标题/关键词/摘要抽取链路中的文本特征（`top_objects` 的持续性、提及强度、概念广度）
  - 与 `diffusion_impact` 并行输出，不切换主分
- merge 分类默认 `rank_top_share`（按目标占比选高分，边界 tie 用 secondary + paper_id 打破），替代 `>= 阈值` 的高象限膨胀路径
- merge 汇总新增 Simpson 风险诊断（`cross_year_diagnostics.simpson_check`）
- Pass1 新增实验性 `concept-year` 归因回写能力（默认关闭）：
  - 按同年同概念组聚合 `s_peak`（可配置 seed 字段）并计算相对份额权重
  - 输出 `concept_year_relative_share`、`concept_year_attribution_weight`、`concept_year_role`
- 提供 A/B 对比报告工具：`scripts/legacy/validation/validate_impact_v6.py --compare-prefix-a --compare-prefix-b`
- 提供 V6.1 三门禁自动报告（默认启用）：零值堆积、样本对分差、跨年稳定（支持 `--gate-*` 阈值与输出配置）
- 提供 V6.2 通道可追溯检查：验证 `impact_channels` 完整性与每通道文本特征可追溯覆盖率
- 提供主分切换评估工具：`scripts/legacy/validation/evaluate_primary_channel_switch.py`
  - 支持候选：`foundation_utility`、`method_transferability`、`blend_v1`
  - 输出切换就绪报告（coverage / dispersion / zero-pileup / pairwise），默认仅评估不切换主分
  - 支持进度条与断点续传（`--progress`、`--resume`、`--resume-path`）
- 运行稳健性：
  - Pass1 会校验 Pass0 对目标年份的完整覆盖
  - Pass2 汇总文件按年份 merge 写入，不再分年运行时覆盖截断

---

## 1. 设计动机

### 1.1 V5 的根本缺陷

V5 的影响力计算依赖**跨论文概念字符串匹配**：

```
源论文 RPU → 提取 object_lemma → 在后续论文的 object_lemma 中精确查找
```

这一机制存在结构性脆弱：

| 失败模式 | 示例 | 后果 |
|----------|------|------|
| RPU 整句过长 | `"an overview of the capabilities and development practices of sci py 1 . 0"` | 无任何后续论文使用完全相同的 object_lemma → 匹配为 0 |
| 套话高频 | `"an amendment to this paper"` | 2550 篇勘误共享同一 object_lemma → 虚假高分 |
| 同义不同形 | 源论文: `"describe scipy"`, 后续: `"use scipy solver"` | 人可识别为同一概念，字符串完全不同 → 匹配失败 |

V5 后续引入的 `normalize_object_concept()` 和锚定词表本质上是用手工规则弥补字符串匹配的缺陷，不可扩展。

### 1.2 创新度为什么成功

创新度 V2 的 6 维特征和 3 个信号（s_peak、s_synergy、s_bonus）全部是**频率统计量**，不依赖跨论文精确匹配：

```
s_peak = -log2( P(task, object) )   ← 联合概率的信息量
```

无论概念如何表述，它在历史语料中都有一个可度量的频率。这使创新度对概念表示质量的要求远低于影响力。

### 1.3 核心洞察

**创新度和影响力可以用同一个统计量的时间变化来度量：**

- **创新度**（发表时）：概念在历史中有多罕见？ → `novelty(concept, at_pub)` 高 = 新颖
- **影响力**（发表后）：概念在后续是否变得不再罕见？ → `novelty(concept, at_current)` 下降 = 被采纳

```
Novelty Drop = novelty(concept, at_pub) - novelty(concept, at_current)
```

**如果一个概念从罕见变为常见，这就是影响力的直接证据。**

不需要跨论文字符串匹配——只需要观察**同一个统计量在时间轴上的变化**。

---

## 2. 核心指标：Novelty Drop（新颖度衰减）

### 2.1 定义

对论文 P（发表年 Y），其 RPU 集合 `{(task_i, object_i)}`：

```
novelty_at_pub(i)     = -log2( P(object_core_i | 截至 Y 年的累积数据) )
novelty_at_current(i) = -log2( P(object_core_i | 截至当前年的全量数据) )

novelty_drop(i) = max(0, novelty_at_pub(i) - novelty_at_current(i))
```

其中 `P(object_core | data)` 是该 object_core 在累积语料中的文档频率：

```
P(object_core, up_to_year) = (count_papers_with(object_core, up_to_year) + 1)
                            / (total_papers(up_to_year) + V)
```

采用 Laplace 平滑，与创新度 s_peak 的计算方式一致。

### 2.2 直觉

```
novelty_drop = log2( freq_at_current / freq_at_pub )
```

即概念频率的**对数增长倍数**。

| freq_at_pub | freq_at_current | novelty_drop | 含义 |
|-------------|-----------------|--------------|------|
| 0.0001% | 0.01% | 6.6 bits | 频率增长 100 倍，强影响力 |
| 0.0001% | 0.001% | 3.3 bits | 频率增长 10 倍，中等影响力 |
| 0.01% | 0.01% | 0 bits | 频率未变，无影响力 |
| 1.0% | 1.5% | 0.6 bits | 本已常见，微弱增长 |
| 0.0001% | 0.0001% | 0 bits | 始终罕见（超前但未被采纳）|

### 2.3 数学性质

1. **非负性**：`max(0, ...)` 确保仅计入频率增长，忽略概念消亡
2. **对数尺度**：大幅抑制基数效应——从 1 篇增到 100 篇的 novelty_drop 与从 100 篇增到 10000 篇相同
3. **相对频率**：分母是 total_papers，自动消除年度论文数膨胀的影响
4. **平滑一致**：Laplace 平滑与创新度的 s_peak 公式完全一致，保证度量可比

### 2.4 与 V5 Diffusion 的本质区别

| 维度 | V5 Diffusion | V6 Novelty Drop |
|------|-------------|-----------------|
| 运算性质 | 计数（post_papers） | 频率比（对数尺度） |
| 匹配机制 | 跨论文 object_lemma 精确匹配 | 同一统计量的时间差分 |
| 概念表示 | object_lemma（原始文本 lemma） | object_core（抽象层） |
| 基础设施 | 独立的 temporal_stats.db | 复用创新度的频率统计 |
| 对概念质量的要求 | 极高（完全一致才匹配） | 中等（频率变化即可检测） |
| 归一化 | 需要额外的百分位归一化 | 对数比天然归一化 |

---

## 3. 与创新度的关系

### 3.1 共享概念表示

V6 使用与创新度**完全相同的概念表示**层级：

```python
# 创新度 calculate_innovation.py line 1983-1984
t = rpu.get('task_core') or rpu.get('task')
o = rpu.get('object_core') or rpu.get('object')
```

V6 同样使用 `(task_core, object_core)` 作为概念的基本表示单元。这确保：

- 创新度和影响力度量的是同一组概念
- 上游概念表示的改进同时惠及两个维度
- 不引入额外的匹配/对齐层

### 3.2 复用的基础设施

| 组件 | 创新度中的用途 | V6 中的用途 |
|------|---------------|------------|
| `verb_innovation_weights` | 动词权重 (get_verb_weight) | 同一权重表，加权 novelty_drop |
| `PaperTypePostProcessor` | 论文类型检测 + 降权 | 同一检测器，过滤勘误/综述 |
| object_core / task_core | s_peak 的计算单元 | novelty_drop 的计算单元 |
| Laplace 平滑 | P(task, object) 估计 | P(object_core) 估计 |
| 百分位归一化 | score_v2 年度排名 | diffusion_impact（兼容别名 impact_score）年度排名 |

### 3.3 创新度信号的桥接作用

创新度已经为每篇论文计算了 `s_peak`（RPU 级别的 task×object 联合新颖度）。V6 的 novelty_drop 可以直接利用 `s_peak` 作为 `novelty_at_pub` 的参考：

```
s_peak(at pub)  ≈ novelty_at_pub     ← 创新度已计算
s_peak(at current) → 需要新增计算      ← V6 新增
```

但 V6 的 Adoption 信号在**对象级**（object_core）而非**配对级**（task × object）操作，理由与 V5 一致：传播的是概念本身，不是研究操作。

---

## 4. 两个信号

### Signal A: Adoption Magnitude（概念采纳强度）

**问题**：论文引入的概念在后续变得多普遍？

```python
def adoption_magnitude(paper, freq_table):
    """
    对论文 P（发表年 Y），计算其概念的频率增长。
    """
    rpus = paper.get_all_rpus()
    contributions = {}

    for rpu in rpus:
        obj_core = rpu.get('object_core') or rpu.get('object')
        task_core = rpu.get('task_core') or rpu.get('task')

        if not obj_core or obj_core.startswith('RAW:'):
            # RAW 标记表示抽象失败，降级使用 object_lemma
            obj_core = rpu.get('object_lemma') or obj_core
            if not obj_core:
                continue

        # 频率查询
        freq_at_pub = freq_table.get_cumulative_freq(obj_core, up_to=paper.pub_year)
        freq_at_current = freq_table.get_cumulative_freq(obj_core, up_to=CURRENT_YEAR)

        # Novelty Drop（对数频率比）
        # novelty = -log2(freq), drop = novelty_pub - novelty_current = log2(freq_current / freq_pub)
        if freq_at_current > freq_at_pub:
            n_drop = math.log2(freq_at_current / freq_at_pub)
        else:
            n_drop = 0.0

        # 动词权重
        verb_w = get_verb_weight(task_core)

        # 同一 object_core 取最大贡献
        contrib = verb_w * n_drop
        if obj_core not in contributions or contrib > contributions[obj_core]['value']:
            contributions[obj_core] = {
                'value': contrib,
                'novelty_drop': n_drop,
                'verb_weight': verb_w,
                'freq_at_pub': freq_at_pub,
                'freq_at_current': freq_at_current,
            }

    # Top-K 聚合
    top_contribs = sorted(contributions.values(), key=lambda x: x['value'], reverse=True)[:TOP_K]
    return sum(c['value'] for c in top_contribs), top_contribs
```

**权重组合示例**：

| 场景 | verb_w | freq_pub | freq_cur | n_drop | 贡献 | 解读 |
|------|--------|----------|----------|--------|------|------|
| propose + 概念从罕见→常见 | 1.5 | 0.001% | 0.1% | 6.6 | **10.0** | 首创者高功劳 |
| use + 概念从罕见→常见 | 0.8 | 0.001% | 0.1% | 6.6 | **5.3** | 应用者功劳减半 |
| propose + 概念已常见 | 1.5 | 1.0% | 1.5% | 0.6 | **0.9** | 非首创，功劳小 |
| describe + 套话 | 0.3 | 0.5% | 0.5% | 0.0 | **0.0** | 无影响力 |


### Signal B: Adoption Consistency（采纳持续性）

**问题**：概念的采纳是昙花一现还是持续经典？

```python
def adoption_consistency(paper, freq_table):
    """
    度量概念采纳的时间持续性。

    对于每个 object_core，检查发表后每一年的年度频率
    是否不低于发表当年的年度频率。
    """
    rpus = paper.get_all_rpus()
    observable_years = CURRENT_YEAR - paper.pub_year

    if observable_years <= 0:
        return 0.0

    consistencies = {}

    for rpu in rpus:
        obj_core = rpu.get('object_core') or rpu.get('object')
        if not obj_core:
            continue
        if obj_core in consistencies:
            continue

        # 发表当年的年度频率（基线）
        baseline_freq = freq_table.get_yearly_freq(obj_core, paper.pub_year)

        # 发表后每年是否达到或超过基线
        sustained_years = 0
        for y in range(paper.pub_year + 1, CURRENT_YEAR + 1):
            yearly_freq = freq_table.get_yearly_freq(obj_core, y)
            if yearly_freq >= baseline_freq:
                sustained_years += 1

        consistencies[obj_core] = sustained_years / observable_years

    if not consistencies:
        return 0.0

    # 取 Top-K object 的加权平均
    top_items = sorted(consistencies.items(), key=lambda x: x[1], reverse=True)[:TOP_K]
    return sum(v for _, v in top_items) / len(top_items)
```

**数值性质**：

| consistency | 含义 |
|-------------|------|
| ≈ 1.0 | 每年都至少保持发表年的使用率（持续经典）|
| 0.4–0.6 | 部分年份下降（衰退但有余温）|
| ≈ 0.0 | 发表后立刻消亡（昙花一现）|

**与 V5 Persistence 的区别**：

| | V5 Persistence | V6 Consistency |
|---|---|---|
| 度量 | 二值：该年是否有≥1篇论文使用 | 频率比：该年使用率是否≥发表年 |
| 标准 | 存在即算 | 维持强度才算 |
| 问题 | 只要出现 1 次就算"活跃"，灵敏度低 | 要求实际使用强度不衰减，更严格 |

---

## 5. Impact 公式

### 5.1 核心公式

```
Impact = Adoption_norm × Consistency_gate
```

语义不变：Adoption 决定影响力的上限，Consistency 决定该上限是否可信。

### 5.2 Adoption_norm（规模归一化）

```python
adoption_raw = adoption_magnitude(paper)  # 加权 novelty_drop 之和

# 年度百分位归一化 → [0, 100]
adoption_norm = percentile_within_year(adoption_raw)
```

不需要 V5 的 `log(D+1)` 步骤，因为 novelty_drop 本身已经是对数尺度。

### 5.3 Consistency_gate（持续性门控）

```python
consistency = adoption_consistency(paper)  # [0, 1]
threshold = 0.5

consistency_gate = min(consistency / threshold, 1.0)  # [0, 1]
```

| consistency | gate | 效果 |
|-------------|------|------|
| ≥ 0.5 | 1.0 | 持续经典，不打折 |
| 0.25 | 0.5 | 衰退中，打五折 |
| 0.0 | 0.0 | 昙花一现，归零 |

### 5.4 最终得分

```python
diffusion_impact = adoption_norm * consistency_gate  # [0, 100]
impact_score = diffusion_impact                      # 兼容别名（V6.1）
```

### 5.5 示例

| 场景 | adoption_norm | consistency_gate | impact | 解读 |
|------|-------------|-----------------|--------|------|
| 概念从罕见→常见 + 每年持续 | 90 | 1.0 | **90** | 教科书级影响力 |
| 概念从罕见→常见 + 很快消退 | 90 | 0.3 | **27** | 曾经很火但昙花一现 |
| 概念微弱增长 + 持续使用 | 30 | 0.9 | **27** | 小众经典 |
| 概念已常见 + 无变化 | 5 | 0.8 | **4** | 常规工作，正确低分 |
| 套话/勘误 | 0 | — | **0** | 频率未变，自然归零 |

---

## 6. 与四象限分类的天然对齐

```
                 Impact ≥ P70      Impact < P70
Innovation  ┌────────────────┬────────────────┐
≥ P70       │   Pioneer      │ Ahead-of-time  │
            ├────────────────┼────────────────┤
<  P70      │   Diffuser     │   Routine      │
            └────────────────┴────────────────┘
```

V6 与四象限的对应关系：

| 象限 | novelty_at_pub | novelty_drop | 解读 |
|------|---------------|--------------|------|
| **Pioneer** | 高（创新度高） | 大（影响力高） | 新颖且被广泛采纳 |
| **Ahead-of-time** | 高（创新度高） | 小（影响力低） | 新颖但未被采纳 |
| **Diffuser** | 低（创新度低） | 中等 | 非首创但参与了概念传播 |
| **Routine** | 低（创新度低） | 小 | 常规工作 |

**Diffuser 的处理**：novelty_at_pub 低意味着概念发表前已有一定基数。如果该论文发表后概念仍有显著频率增长（novelty_drop > 0），说明该论文参与了传播过程。由于基数已高，对数增长倍数天然较小，Diffuser 的 impact 分数会低于 Pioneer，这符合预期。

---

## 7. 实现架构

```
Pass 0: 构建对象频率表 (~1 hour)
├── 输入: rpu_database.db
├── 对每条 RPU:
│     - 提取 object_core (降级: object_lemma → object)
│     - 提取 task_core (降级: task_lemma → task)
├── 统计:
│     - object_freq_yearly(object_core, year) → paper_count
│     - total_papers(year) → count
│     - 累积频率表 (cumulative)
├── 输出: impact_freq_stats.db
│     - object_yearly: (object_core, year, paper_count)
│     - object_cumulative: (object_core, up_to_year, cumulative_freq)
│     - total_papers: (year, count, cumulative_count)
└── Checkpoint: pass0_complete

Pass 1: 计算 Novelty Drop + Consistency (~3 hours)
├── 输入: rpu_database.db + impact_freq_stats.db
├── 对每篇论文 (年 Y):
│     For each RPU:
│       - 查询 cumulative_freq(object_core, Y)
│       - 查询 cumulative_freq(object_core, current_year)
│       - novelty_drop = max(0, log2(freq_current / freq_pub))
│       - contrib = verb_weight × novelty_drop
│     adoption_raw = Top-K(contribs)
│     consistency = yearly_freq trajectory analysis
├── 输出: impact_signals_{year}.jsonl
│     - adoption_raw, consistency, details
└── Checkpoint: pass1_years[]

Pass 2: 归一化 + 输出 (~30 min)
├── 输入: impact_signals_{year}.jsonl
├── 年度百分位归一化 → adoption_norm
├── Consistency gate
├── diffusion_impact = adoption_norm × consistency_gate
├── foundation_utility_raw = f(top_objects.consistency, mentions, object_count)
├── foundation_utility_norm = percentile_or_global_zscore(foundation_utility_raw)
├── impact_score = diffusion_impact  (兼容别名)
├── impact_channels = {"diffusion_impact": ..., "foundation_utility": ...}
├── 论文类型后处理 (PaperTypePostProcessor)
└── 输出: impact_final_{year}.jsonl
```

### 7.1 数据库 Schema

```sql
-- impact_freq_stats.db

CREATE TABLE object_yearly (
    object_core TEXT NOT NULL,
    year INTEGER NOT NULL,
    paper_count INTEGER DEFAULT 0,
    PRIMARY KEY (object_core, year)
);

CREATE TABLE total_papers (
    year INTEGER PRIMARY KEY,
    count INTEGER DEFAULT 0,
    cumulative_count INTEGER DEFAULT 0
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_obj_yearly_core ON object_yearly(object_core);
CREATE INDEX idx_obj_yearly_year ON object_yearly(year);
```

### 7.2 累积频率计算

```python
def get_cumulative_freq(object_core, up_to_year):
    """计算截至 up_to_year 的累积文档频率"""
    cum_count = sum(
        paper_count
        for year, paper_count in object_yearly[object_core].items()
        if year <= up_to_year
    )
    cum_total = total_papers_cumulative[up_to_year]

    # Laplace smoothing (与创新度一致)
    return (cum_count + 1) / (cum_total + VOCAB_SIZE_ESTIMATE)
```

### 7.3 概念表示降级策略

```
优先级: object_core > object_lemma > normalize_object_concept(object)

if object_core exists and not starts with "RAW:":
    use object_core                          # 最佳：抽象层有效
elif object_lemma exists:
    use normalize_object_concept(object_lemma)  # 中等：lemma 级归一化
else:
    use normalize_object_concept(object)      # 最差：原始文本归一化
```

当 object_core 为 `RAW:` 前缀或明显异常（coverage < 0.2）时，降级到下一层级。

---

## 8. 输出格式

```json
{
  "paper_id": "21da5794b4f537271edb091a376f6860",
  "pub_year": 2020,

  "adoption_raw": 4.82,
  "adoption_norm": 73.5,

  "consistency": 0.80,
  "consistency_gate": 1.0,

  "diffusion_impact": 73.5,
  "impact_score": 73.5,
  "impact_score_semantic": "diffusion_impact",
  "impact_primary_channel": "diffusion_impact",
  "foundation_utility_raw": 0.91,
  "foundation_utility_norm": 81.2,
  "impact_channels": {
    "diffusion_impact": 73.5,
    "foundation_utility": 81.2
  },

  "observable_years": 5,
  "object_count": 3,

  "top_objects": [
    {
      "object_core": "scipy",
      "task_core": "provide",
      "verb_weight": 0.3,
      "freq_at_pub": 0.00008,
      "freq_at_current": 0.00036,
      "novelty_drop": 2.17,
      "contribution": 0.65,
      "sustained_years": 4,
      "consistency": 0.80
    }
  ]
}
```

---

## 9. V5 → V6 对比

| 维度 | V5 | V6 |
|------|-----|-----|
| **核心度量** | 后续论文计数 (post_papers) | 频率对数比 (novelty_drop) |
| **匹配方式** | 跨论文 object_lemma 精确匹配 | 同一概念的频率时间差分 |
| **概念表示** | object_lemma | object_core（降级到 object_lemma） |
| **与创新度的关系** | 独立流程，独立数据 | 共享概念表示和频率基础设施 |
| **对 RPU 质量的要求** | 极高（必须跨论文匹配） | 中等（频率变化即可检测） |
| **勘误/套话处理** | 需要手工 GENERIC_PHRASES 列表 | 套话频率不变 → novelty_drop 自然为 0 |
| **稀缺性权重** | 手工 1/(prior+1) | 对数频率比天然包含稀缺性 |
| **归一化** | log(D+1) + 百分位 | 百分位（novelty_drop 已是对数尺度） |
| **持续性度量** | 二值活跃年比例 | 频率维持比例（更严格） |
| **Pass 数** | 4 | 3 |

### 9.1 SciPy 案例的对比预测

论文: "SciPy 1.0: fundamental algorithms for scientific computing in Python" (2020)

**V5 结果**: impact = 0.00（object_lemma 整句无匹配）

**V6 预测**（假设 object_core 降级到 normalize_object_concept → "scipy"）:
- freq_at_pub("scipy", 2020) ≈ 0.00008（4 篇 / ~50K 累积论文）
- freq_at_current("scipy", 2025) ≈ 0.00036（27 篇 / ~75K 累积论文）
- novelty_drop = log2(0.00036 / 0.00008) = log2(4.5) ≈ 2.17 bits
- verb_weight("provide") = 0.3
- contribution = 0.3 × 2.17 = 0.65
- 百分位归一化后 → 非零 impact_score

**V6 对勘误论文的预测**:
- object_core = "an amendment to this paper" → 高频套话
- freq_at_pub ≈ freq_at_current（频率几乎不变）
- novelty_drop ≈ 0 → impact = 0（无需手工过滤）

---

## 10. 已知限制

| 限制 | 说明 | 缓解方向 |
|------|------|---------|
| **上游 RPU 质量** | object_core 提取失败（RAW 前缀/乱码碎片）时，V6 同样无法产生有效信号 | 改进 core 抽象层；降级策略可部分缓解 |
| **工具类论文** | 使用者往往不在正文中显式提及工具名称，导致 RPU 覆盖率低 | 补充标题/关键词作为概念来源（后续版本） |
| **RPU 稀疏** | 部分论文仅提取到 1-2 条 RPU，Top-K 聚合信息不足 | 与标题概念融合扩充候选集 |
| **因果模糊** | 概念频率增长不一定因为某篇特定论文 | 与 V5 相同，接受为代理信号 |
| **近期论文** | 可观测窗口不足（< 2 年），频率变化尚未充分显现 | 标记为 `insufficient_observable_window` |
| **概念消亡** | max(0, ...) 截断会忽略负面影响（概念被废弃） | 设计选择：影响力仅度量正向采纳 |

### 10.1 V6 无法修复的问题

V6 改进的是**影响力度量方法**（从字符串匹配到频率统计），但以下问题属于上游，需要在 RPU 提取层和 core 抽象层解决：

- 论文 RPU 提取条数过少（如 SciPy 仅 2 条）
- object_core 映射错误（如 "nd c" 乱码碎片）
- 描述性论文（综述/工具介绍）的 RPU 全是自述而非方法论贡献

---

## 11. 验证方法

### 11.1 标志性论文检验

| 论文 | 预期 adoption_norm | 预期 consistency | 预期 impact |
|------|-------------------|-----------------|-------------|
| Attention Is All You Need (2017) | 极高 | ≈ 1.0 | 极高 |
| AlphaFold2 (2021) | 高 | 高 | 高 |
| SciPy 1.0 (2020) | 中等 | 高 | 中等 |
| 典型勘误论文 | ≈ 0 | — | ≈ 0 |
| "an amendment" 类勘误 | ≈ 0 | — | ≈ 0 |

### 11.2 分布验证

- Impact 分布应呈长尾（少数高影响，多数低影响）
- 勘误论文应集中在 0 附近（无需手工过滤即自然归零）
- 年度 P70 阈值应相对稳定

### 11.3 回归测试

与 V5 结果对比：
- Top 1000 重合度（期望 60-80%，允许合理调整）
- 已知问题论文修复率（勘误假阳性消除、工具论文零分修复）

---

## 12. 明确排除的信号

继承 V5 的时间因果约束：

| 信号 | 原因 | 归属 |
|------|------|------|
| Early Adoption | 测"发表时概念处于什么阶段" | → Innovation |
| First Bridge | 测"是否首次连接" | → Innovation |
| 发表当年的稀缺性 | 发表时信号 | → Innovation |

**它们只作为概念生成资格，不属于影响力。**

---

## 13. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-02-05 | 初版设计（Louvain 社区检测） |
| 2.0 | 2026-02-05 | 重构：时间响应 + 桥接信号 |
| 3.0 | 2026-02-05 | 从"因果归因"转向"扩散位置"范式 |
| 3.1 | 2026-02-06 | 参数优化 |
| 4.0 | 2026-02-06 | 哲学重构：Impact = 严格发表后信号 |
| 5.0 | 2026-02-06 | IU 重定义：从 combo 改为 object，task 作为权重 |
| **6.0** | **2026-02-10** | **方法论重构**：从字符串匹配改为频率时间差分，复用创新度基础设施 |
| **6.1** | **2026-02-13** | **语义纠偏**：主分显式命名为 `diffusion_impact`，`impact_score` 保留兼容别名并输出 `impact_channels` |
| **6.2** | **2026-02-13** | **并行文本通道**：新增 `foundation_utility_raw/norm` 并纳入 `impact_channels`，不切换主分 |

### V6.0/V6.1/V6.2 核心变更

1. **度量方法**：从跨论文字符串匹配改为同一概念的频率对数比（Novelty Drop）
2. **概念表示**：从 object_lemma 升级为 object_core（与创新度共享表示层）
3. **基础设施复用**：verb_weight、PaperTypePostProcessor、Laplace 平滑等与创新度一致
4. **持续性度量**：从二值活跃年比例改为频率维持比例
5. **勘误处理**：从手工过滤列表改为频率不变 → 自然归零
6. **架构简化**：从 4 Pass 简化为 3 Pass
7. **输出语义显式化（V6.1）**：`diffusion_impact` 成为主语义字段；`impact_score` 仅为兼容映射
8. **并行通道扩展（V6.2）**：新增 `foundation_utility` 文本特征通道，与 `diffusion_impact` 共同构成可解释向量

### 一句话总结

> **影响力 = 概念从罕见变为常见的程度。novelty_drop 度量这个变化，与创新度共享同一套频率基础设施。**
