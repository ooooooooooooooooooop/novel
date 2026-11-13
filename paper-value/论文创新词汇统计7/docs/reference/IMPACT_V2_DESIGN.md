# Impact Signal V5 设计文档

> **版本**：5.0
> **最后更新**：2026-02-06
> **状态**：设计重构，待实现

---

## 核心理念

### 影响力的唯一定义

> **Impact = 论文发表后，它引入的学术信息单元（IU）在后续学术系统中被【多少人】【持续多久】真正使用。**

关键约束：
- **严格时间因果**：只统计发表之后发生的变化
- **外生验证**：变化必须来自"他人使用"，而非作者自循环
- **可累积性**：影响可以随时间增长、衰减或消失
- **可比性**：不同论文、不同年份、不同领域可统一标度比较

### Impact 与 Innovation 的彻底分离

| 维度 | Innovation（创新性） | Impact（影响力） |
|------|---------------------|-----------------|
| 时间锚点 | 发表时 | **严格发表后** |
| 核心问题 | "你是不是第一个？" | "别人是否因你而改变？" |
| 测量对象 | 作者的领先性 | 社群的跟随行为 |

**任何只依赖发表时信号的指标，不属于 Impact。**

---

## Impact Unit（IU）定义

Impact 不直接测"论文"，而测论文释放的 **Impact Units（IU）**。

### V5.0 核心改动：IU = Object（概念）

> **传播的是概念本身，不是研究操作。**

| 版本 | IU 定义 | 问题 |
|------|---------|------|
| V4.0 | combo = task × object | task 导致同一概念被分裂统计 |
| **V5.0** | **object（概念）** | task 作为权重因子，不参与匹配 |

### 设计理由

1. **传播主体是概念**：后续论文采纳的是 "transformer"，不是 "propose transformer" 这个操作
2. **减少稀疏性**：同一概念的不同操作（propose/apply/improve）合并统计
3. **保留动作语义**：task 不丢弃，而是作为权重因子区分贡献类型

### IU 定义

```python
# V5.0: IU = 归一化后的 object
impact_unit = lemmatize(object.lower().strip())

# 示例
"neural networks" → "neural network"
"Transformer model" → "transformer model"
```

### Task 权重表

Task 不参与匹配，而是决定贡献权重：

| Task 类别 | 动词 | 权重 | 理由 |
|----------|------|------|------|
| **创造** | invent, pioneer, propose, discover, devise | 1.5 | 首创者应获更多功劳 |
| **开发** | develop, design, implement, build, create | 1.2 | 实现者有贡献 |
| **改进** | improve, enhance, extend, optimize | 1.1 | 改进者有一定贡献 |
| **应用** | apply, use, employ, utilize, adopt | 0.8 | 应用者功劳较小 |
| **分析** | analyze, study, examine, investigate | 0.6 | 分析者功劳更小 |
| **描述** | describe, report, present, show, review | 0.3 | 描述者几乎无功劳 |

```python
TASK_WEIGHTS = {
    # 创造类
    "invent": 1.5, "pioneer": 1.5, "propose": 1.5, "discover": 1.5, "devise": 1.5,
    # 开发类
    "develop": 1.2, "design": 1.2, "implement": 1.2, "build": 1.2, "create": 1.2,
    # 改进类
    "improve": 1.1, "enhance": 1.1, "extend": 1.1, "optimize": 1.1,
    # 应用类
    "apply": 0.8, "use": 0.8, "employ": 0.8, "utilize": 0.8, "adopt": 0.8,
    # 分析类
    "analyze": 0.6, "study": 0.6, "examine": 0.6, "investigate": 0.6,
    # 描述类
    "describe": 0.3, "report": 0.3, "present": 0.3, "show": 0.3, "review": 0.3,
}

def get_task_weight(task):
    task_lemma = lemmatize(task.lower())
    return TASK_WEIGHTS.get(task_lemma, 1.0)  # 默认 1.0
```

---

## 两个核心信号（仅发表后）

### Signal A: Diffusion（扩散强度）

**问题**：论文的 IU（概念）后来被多少人、多广泛地使用？

**V5.0 改进**：
- 匹配键：object（概念），不再用 task × object
- 权重：task_weight × scarcity_weight
- 聚合：Top-3（避免 RPU 数量偏倚）

```python
def diffusion_score(paper):
    """
    V5.0: 基于 object 的扩散计算

    核心改动：
    1. 匹配键 = object（概念），不是 combo
    2. task 作为权重因子
    3. Top-3 聚合
    """
    rpus = paper.get_all_rpus()

    # 按 object 分组，取每个 object 的最高 task_weight
    object_contributions = {}

    for rpu in rpus:
        # 1. 归一化 object
        obj = lemmatize(rpu.object.lower())

        # 2. task 权重
        task_w = get_task_weight(rpu.task)

        # 3. 稀缺性权重
        prior_papers = count_papers_with_object_before(obj, paper.pub_year)
        scarcity_w = 1.0 / (prior_papers + 1)

        # 4. 发表后采用数
        post_papers = count_papers_with_object_after(obj, paper.pub_year)

        # 5. 贡献值
        contrib = task_w * scarcity_w * post_papers

        # 6. 同一 object 取最大贡献
        if obj not in object_contributions or contrib > object_contributions[obj]:
            object_contributions[obj] = contrib

    # 7. Top-3 聚合（避免 RPU 数量偏倚）
    top_contribs = sorted(object_contributions.values(), reverse=True)[:3]
    return sum(top_contribs)
```

**权重组合示例**：

| 场景 | task_w | scarcity_w | post | 贡献 | 解读 |
|------|--------|------------|------|------|------|
| 首发 + propose | 1.5 | 1.0 | 50000 | **75000** | 首创者最高功劳 |
| 首发 + apply | 0.8 | 1.0 | 50000 | **40000** | 应用者功劳减半 |
| 第10个 + propose | 1.5 | 0.1 | 45000 | **6750** | 跟风者功劳大减 |
| 第100个 + describe | 0.3 | 0.01 | 40000 | **120** | 几乎无功劳 |

**聚合方式**：Top-3 Sum（取贡献最高的 3 个 object）

---

### Signal B: Persistence（持续性）

**问题**：论文的 IU（概念）活了多久？是持续经典还是昙花一现？

**核心指标：Survival Ratio**

```
Survival Ratio = N_active_years / N_observable_years

其中：
- N_active_years：发表后，该 object 被至少一篇论文使用的年份数
- N_observable_years：从发表到当前的可观测年份总数
```

**V5.0 改进**：匹配键改为 object，与 Diffusion 一致。

```python
def persistence_score(paper):
    """
    V5.0: 基于 object 的持续性计算
    """
    rpus = paper.get_all_rpus()
    observable_years = current_year - paper.pub_year

    if observable_years <= 0:
        return 0.0

    # 按 object 分组
    object_persistence = {}

    for rpu in rpus:
        obj = lemmatize(rpu.object.lower())

        if obj in object_persistence:
            continue  # 每个 object 只计算一次

        # 1. task 权重
        task_w = get_task_weight(rpu.task)

        # 2. 稀缺性权重
        prior_papers = count_papers_with_object_before(obj, paper.pub_year)
        scarcity_w = 1.0 / (prior_papers + 1)

        # 3. 统计发表后有多少年被使用
        active_years = 0
        for year in range(paper.pub_year + 1, current_year + 1):
            if object_used_in_year(obj, year):
                active_years += 1

        survival_ratio = active_years / observable_years

        # 4. 加权贡献
        contrib = task_w * scarcity_w * survival_ratio
        object_persistence[obj] = contrib

    # Top-3 聚合
    top_contribs = sorted(object_persistence.values(), reverse=True)[:3]
    return sum(top_contribs)
```

**数值性质**：
| Survival Ratio | 含义 |
|----------------|------|
| ≈ 1.0 | 几乎每年都被使用（持续经典）|
| 0.3–0.5 | 间歇性存活（小众但稳定）|
| ≈ 0.0 | 昙花一现或未被采纳 |

**一句话总结**：衡量一个概念活了多久，而不是火得多大。

---

## 明确排除的信号

以下信号属于 **Innovation**，**不得进入 Impact**：

| 信号 | 原因 | 归属 |
|------|------|------|
| Early Adoption | 测"发表时概念处于什么阶段" | → Innovation |
| First Bridge | 测"是否首次连接" | → Innovation |
| 发表当年的稀缺性 | 发表时信号 | → Innovation |

**它们只作为 IU 生成资格，而非影响力本身。**

---

## Impact 公式

### 核心公式

```
Impact = Diffusion_norm × Persistence_gate
```

**语义**：Diffusion 决定影响力的上限，Persistence 决定这个上限是否可信。

### Diffusion_norm（规模归一化）

```python
Diffusion_norm = percentile_year(log(D_raw + 1))  # → [0, 100]
```

**两步正则化**：
1. `log(D+1)`：压缩极端爆款，保留相对差距
2. `percentile_year`：消除年度规模膨胀，保证跨年排序一致

### Persistence_gate（可信度门控）

```python
avg_survival = P_raw / sum_weight  # 加权平均 survival_ratio → [0, 1]
P_gate = min(avg_survival / threshold, 1.0)  # → [0, 1]
```

**参数**：
- `threshold = 0.5`：combo 需在可观测窗口一半以上时间活跃才不打折
- 这是"绝对标准"，不是相对排名

**效果**：
| avg_survival | P_gate | 含义 |
|--------------|--------|------|
| ≥ 0.5 | 1.0 | 持续经典，不打折 |
| 0.25 | 0.5 | 昙花一现，打五折 |
| 0.1 | 0.2 | 很快消亡，打八折 |

### 示例

| 场景 | D_norm | P_gate | Impact | 解读 |
|------|--------|--------|--------|------|
| 首发+热门+持续 | 90 | 1.0 | **90** | 教科书级影响力 |
| 首发+热门+昙花一现 | 90 | 0.3 | **27** | 火过，但不配"经典" |
| 首发+冷门+持续 | 30 | 0.9 | **27** | 小众经典 |
| 跟风者 | 10 | 0.8 | **8** | 正确地被惩罚 |

---

## 实现架构

```
Pass 0: 预处理 (~30 min) [V5.0 新增]
├── 输入: rpu_database.db
├── 对每个 RPU:
│     - 计算 object_lemma = lemmatize(object)
│     - 计算 task_lemma = lemmatize(task)
├── 输出: rpu_database.db (新增列)
│     - object_lemma, task_lemma
└── Checkpoint: pass0_complete

Pass 1: 时序统计 (~1 hour)
├── 输入: rpu_database.db
├── 扫描全部 RPU，按 object_lemma + year 统计
├── 输出: temporal_stats.db
│     - object_yearly(object_lemma, year) → rpu_count, paper_count
│     - total_papers(year) → count
└── Checkpoint: pass1_complete

Pass 2: Diffusion + Persistence 计算 (~3 hours)
├── 输入: temporal_stats.db + papers
├── 对每篇论文：
│     - 提取 unique objects
│     - 计算 task_weight × scarcity_weight × post_adoption
│     - Top-3 聚合
├── 输出: impact_signals_{year}.jsonl
│     - diffusion_raw, persistence_raw
│     - object 级别详情
└── Checkpoint: pass2_complete

Pass 3: 归一化 + 输出 (~30 min)
├── 输入: impact_signals + innovation_v2_output
├── 年度百分位归一化
├── 加权组合 impact_score
├── 派生 impact_role（与 Innovation 联动）
└── 输出: impact_final_{year}.jsonl
```

### 数据库 Schema 变更

```sql
-- Pass 0: 新增列
ALTER TABLE rpu ADD COLUMN object_lemma TEXT;
ALTER TABLE rpu ADD COLUMN task_lemma TEXT;
CREATE INDEX idx_rpu_object_lemma ON rpu(object_lemma);

-- Pass 1: 时序统计表（V5.0 改用 object_lemma）
CREATE TABLE object_yearly (
    object_lemma TEXT NOT NULL,
    year INTEGER NOT NULL,
    rpu_count INTEGER DEFAULT 0,
    paper_count INTEGER DEFAULT 0,
    PRIMARY KEY (object_lemma, year)
);
CREATE INDEX idx_object_yearly_year ON object_yearly(year);
```

---

## 输出格式

```json
{
  "paper_id": "xxx",
  "pub_year": 2015,

  "diffusion_raw": 121750,
  "diffusion_norm": 92.3,

  "avg_survival": 0.85,
  "persistence_gate": 1.0,

  "impact_score": 92.3,
  "impact_role": "Pioneer",

  "details": {
    "object_count": 5,
    "top_objects_count": 3,
    "observable_years": 10,
    "top_objects": [
      {
        "object": "transformer",
        "object_lemma": "transformer",
        "task": "propose",
        "task_weight": 1.5,
        "prior_papers": 0,
        "scarcity_weight": 1.0,
        "post_papers": 50000,
        "diffusion_contrib": 75000,
        "active_years": 9,
        "survival_ratio": 0.9,
        "persistence_contrib": 1.35
      },
      {
        "object": "self-attention",
        "object_lemma": "self-attention",
        "task": "introduce",
        "task_weight": 1.5,
        "prior_papers": 0,
        "scarcity_weight": 1.0,
        "post_papers": 30000,
        "diffusion_contrib": 45000,
        "active_years": 9,
        "survival_ratio": 0.9,
        "persistence_contrib": 1.35
      }
    ]
  }
}
```

---

## 分类标签派生

### 四象限分类（与 Innovation 联动）

```
             Impact >= P70    Impact < P70
Innovation   ┌──────────────┬──────────────┐
>= P70       │   Pioneer    │ Ahead-of-time│
             ├──────────────┼──────────────┤
<  P70       │   Diffuser   │   Routine    │
             └──────────────┴──────────────┘
```

| 标签 | 含义 |
|------|------|
| **Pioneer** | 创新 + 被跟随 |
| **Ahead-of-time** | 创新但未被跟随（可能超前） |
| **Diffuser** | 不创新但被广泛采纳（传播枢纽） |
| **Routine** | 常规学术工作 |

---

## 与旧设计的对比

| 方面 | V3.x | V4.0 | V5.0 |
|------|------|------|------|
| 定义 | 扩散结构中的位置 | 发表后扩散强度 | **概念的扩散强度** |
| IU | combo | combo | **object** |
| Task | 匹配键 | 匹配键 | **权重因子** |
| 聚合 | Σ all | Σ all | **Top-3** |
| 核心信号 | 3个（混合时态） | 2个（严格发表后） | 2个（严格发表后） |

---

## 验证方法

### 1. 标志性论文检验

| 论文 | 预期 | 验证点 |
|------|------|--------|
| AlphaFold2 | 高 Diffusion + 高 Persistence | 概念被广泛采纳 |
| 早期 CRISPR | 高 Diffusion | 基因编辑概念爆发 |
| 方法论综述 | 高 Diffusion, 中 Persistence | 传播但非原创 |

### 2. 分布验证

- Impact 分布应呈长尾（少数高影响，多数低影响）
- 年度 P70 阈值应相对稳定

### 3. 敏感性分析

- α, β 在 0.4-0.6 范围内变动，Top 1000 重合度 > 80%

---

## 已知限制

| 限制 | 说明 | 缓解措施 |
|------|------|---------|
| Object 质量 | 抽取的 object 可能是碎片 | Phase 6 优化 |
| Lemmatization | 科学术语可能 lemma 错误 | 使用 scispacy 或自定义词典 |
| 因果模糊 | 无法证明"因为这篇论文" | 接受为代理信号 |
| 近期论文 | 观察窗口不足 | 标记 insufficient_data |
| 自引 | 未排除作者自引 | 后续可加过滤 |
| 同名异义 | 不同领域的同名概念混淆 | 可加领域前缀 |

---

## 一句话总结

> **传播的是概念，不是操作。影响力 = 概念被多少人采纳 × 持续多久。**

Impact = 基于 object（概念）的扩散强度，task 决定贡献权重，Top-3 聚合避免偏倚。

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-02-05 | 初版设计（Louvain 社区检测） |
| 2.0 | 2026-02-05 | 重构：时间响应 + 桥接信号 |
| 3.0 | 2026-02-05 | 从"因果归因"转向"扩散位置"范式 |
| 3.1 | 2026-02-06 | 参数优化：调整权重 |
| 4.0 | 2026-02-06 | 哲学重构：Impact = 严格发表后信号，移除 Early Adoption |
| **5.0** | **2026-02-06** | **IU 重定义**：从 combo 改为 object，task 作为权重 |

### V5.0 核心变更

1. **IU 重定义**：Impact Unit 从 `combo (task × object)` 改为 `object（概念）`
2. **设计理由**：传播的是概念本身，不是研究操作；task 导致同一概念被分裂统计
3. **Task 角色转变**：从匹配键变为权重因子，区分创造/开发/应用/描述等贡献类型
4. **聚合方式**：从 Sum All 改为 Top-3，避免 RPU 数量偏倚
5. **新增 Pass 0**：预处理阶段，计算 object_lemma 和 task_lemma

### V5.0 vs V4.0 对比

| 维度 | V4.0 | V5.0 |
|------|------|------|
| IU 定义 | combo (task × object) | **object** |
| Task 作用 | 匹配条件 | **权重因子** |
| 匹配稀疏性 | 高（同义动词分裂） | **低** |
| 聚合方式 | Σ all | **Top-3** |
| 预处理 | 无 | **Pass 0 (lemmatization)** |
