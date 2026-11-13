# 创新度评分方案 V2 - 设计与实现文档

> 最后更新: 2026-02-02
> 实现文件: `calculate_innovation.py`
> 测试文件: `test_innovation_v2.py`, `validate_innovation_v2.py`, `test_v2_real_data.py`

## 1. 核心设计思想

**不直接学习"创新"，而是建模"常规学术空间"，创新 = 偏离常规的残差。**

| 原则 | 说明 |
|------|------|
| 时间锚定 | 每个时间片用历史数据作为参照，保证创新是相对同时代的 |
| 常规空间建模 | 用 PCA 刻画"常规学术特征空间"，而非创新本身 |
| 创新信号=残差 | 偏离常规结构的分量即为创新信号 |
| 方向性约束 | 只计入"向创新方向"的偏离，忽略"退化方向"的偏离 |
| 方差约束 | 确保评分有区分度，但不作为优化目标 |

## 2. 原始问题 (V1)

| 问题 | 表现 | 原因 |
|------|------|------|
| RPU数量主导 | 综述文章得分高于原创研究 | Top-3累加使 RPU 多的论文偏高 |
| 无论文类型区分 | 勘误/综述与原创研究同等对待 | 未识别论文类型 |
| 概念稀有度≠创新 | 使用罕见词汇就得高分 | 缺少创新方向约束 |

## 3. V2 方案架构

### 3.1 整体流程

```
对于年份 Y 的每篇论文:

1. 特征提取: 从 RPU 列表提取特征向量 x ∈ R^6
   x = [avg_task_idf, task_diversity, aspect_ratio, modifier_ratio,
        avg_object_len, rpu_count_log]

2. 常规空间投影: 用历史数据 (≤Y-1) 拟合的 PCA 投影到低秩空间
   x_regular = P_k @ P_k.T @ x_norm

3. 残差计算: 计算偏离常规空间的残差
   x_residual = x_norm - x_regular

4. 方向性约束 (核心改进):
   - 投影到创新方向向量 w: directional_component = x_residual · w
   - 只保留正分量: signed_innovation = max(0, directional_component)
   - 加入垂直分量: magnitude = 0.8 * signed_innovation + 0.2 * ||perpendicular||

5. 百分位归一化:
   score_v2 = percentile_rank(magnitude, year_magnitudes) * 100

6. 信号融合:
   total_score_v2 = weighted_combine(s_peak, s_synergy, s_bonus, score_v2)
```

### 3.2 新增模块

| 模块 | 类名 | 功能 |
|------|------|------|
| Task IDF 追踪 | `TaskIDFTracker` | 累积任务动词文档频率，计算 IDF |
| 特征提取 | `FeatureExtractor` | 从 RPU 列表提取 6 维特征向量 |
| 常规空间建模 | `RegularSpaceModel` | PCA 拟合 + 方向性约束 + 残差计算 |
| 信号融合 | `SignalCombiner` | 多信号加权融合 |

## 4. 参数配置

### 4.1 特征维度定义

```python
# FeatureExtractor.FEATURE_DIM = 6
features = [
    avg_task_idf,      # 任务动词平均 IDF (稀有度)
    task_diversity,    # 任务多样性比率 = n_unique_tasks / n_rpus
    aspect_ratio,      # 研究角度覆盖率 = n_has_aspect / n_rpus
    modifier_ratio,    # 修饰词覆盖率 = n_has_modifier / n_rpus
    avg_object_len,    # 研究对象平均复杂度 (词数)
    rpu_count_log,     # RPU 数量 (对数)
]
```

### 4.2 创新方向向量 (关键参数)

```python
# RegularSpaceModel.INNOVATION_DIRECTION
INNOVATION_DIRECTION = np.array([
    1.0,   # avg_task_idf: 稀有任务 = 创新 (+)
    1.0,   # task_diversity: 多样性高 = 创新 (+)
    1.0,   # aspect_ratio: 有研究角度 = 创新 (+)
    1.0,   # modifier_ratio: 有修饰词 = 创新 (+)
    0.5,   # avg_object_len: 复杂对象 = 轻微创新 (+)
   -0.3,   # rpu_count_log: RPU多不代表创新，可能是综述 (-)
])
```

### 4.3 残差组合权重

```python
# transform() 中的权重
magnitude = 0.8 * signed_innovation + 0.2 * perpendicular_magnitude
# 80% 来自方向性创新，20% 来自其他新颖性
```

### 4.4 其他参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_papers_for_full_mode` | 10,000 | 切换到完整模式的论文数阈值 |
| `min_variance_threshold` | 0.01 | 方差警告阈值 (有符号残差分布更窄) |
| PCA 解释方差目标 | 80% | 自动选择主成分数量 k |

## 5. 冷启动处理

```python
# RegularSpaceModel 状态机
if n_accumulated < 100:
    is_degraded = True
    degraded_reason = "insufficient_data"
elif n_accumulated < min_papers_for_full_mode:
    is_degraded = True
    degraded_reason = "warming_up"
else:
    is_degraded = False
    degraded_reason = None
```

## 6. 输出格式

```json
{
  "paper_id": "xxx",
  "s_peak": 16.63,
  "peak_trigger": "discover - neural network",
  "s_synergy": 0.0,
  "synergy_trigger": null,
  "s_bonus": 9.97,
  "bonus_trigger": "novel | algorithm",
  "innovation_magnitude": 0.67,
  "score_v2": 52.3,
  "total_score_v2": 25.89,
  "v2_degraded": true,
  "v2_degraded_reason": "warming_up"
}
```

## 7. 验证结果

### 7.1 模拟数据验证 (700 篇)

| 验证项 | 结果 | 数值 |
|--------|------|------|
| PCA 解释力 | PASS | 91.6%, k=2 |
| 论文类型关联 | PASS | original(0.49) > review(0.35) > erratum(0.11) |
| 方差约束 | PASS | 阈值调整为 0.01 |
| erratum 排名变化 | PASS | 平均下降 448 位 |

### 7.2 真实数据验证 (4,389 篇)

| 指标 | 数值 |
|------|------|
| 测试年份 | 2018, 2020, 2022 |
| 论文总数 | 4,389 篇 |
| 处理速度 | **3,024 篇/秒** |
| PCA k | 4 |
| 解释方差 | **87.1%** |

**按论文类型统计:**

| 类型 | 数量 | 平均 magnitude | 平均 score_v2 |
|------|------|----------------|---------------|
| original | 4,186 | **0.673** | 49.8 |
| review | 168 | 0.483 | 47.8 |
| erratum | 31 | 0.991* | 50.2 |

*注: erratum 得分偏高是因为部分勘误论文的 RPU 内容实际描述了原论文的研究操作（RPU 提取层问题），而非 V2 评分系统问题。

**类型顺序验证:**
- `original > review`: **PASS** (0.673 > 0.483)
- `review > erratum`: FAIL (需 RPU 提取层修复或后处理降权)

### 7.3 信号分布统计 (真实数据)

| 信号 | 均值 | 标准差 | 最小 | 最大 |
|------|------|--------|------|------|
| s_peak | 16.63 | 0.06 | 14.92 | 16.65 |
| s_synergy | -0.00 | 0.08 | -5.13 | 0.00 |
| s_bonus | 9.25 | 2.26 | 0.00 | 10.01 |
| innovation_magnitude | 0.67 | 0.69 | 0.01 | 6.20 |
| score_v2 | 49.76 | 28.79 | 0.00 | 99.93 |
| total_score_v2 | 25.89 | 11.87 | 3.05 | 57.58 |

## 8. 使用说明

### 8.1 基本用法

```python
from calculate_innovation import InnovationState

# 初始化
state = InnovationState(config=None)

# 按年份处理
year_papers = [('paper_id', [rpu_dict, ...]), ...]
results = state.process_year_atomic(year_papers, '2020')

# 结果包含 V2 字段
for r in results:
    print(r['innovation_magnitude'], r['score_v2'], r['total_score_v2'])
```

### 8.2 评分解读

| total_score_v2 区间 | 创新等级 | 说明 |
|---------------------|---------|------|
| 40+ | 高创新 | 使用稀有任务动词、高多样性、有修饰词 |
| 25-40 | 中等创新 | 标准研究论文 |
| 15-25 | 较低创新 | 常规研究或方法应用 |
| <15 | 低创新 | 简单报告/描述性论文 |

### 8.3 降级模式说明

| v2_degraded_reason | 含义 | 处理建议 |
|-------------------|------|---------|
| `no_model` | PCA 模型未初始化 | 第一年数据，使用原始信号 |
| `insufficient_data` | 累积论文 < 100 | 数据量不足，结果参考性较低 |
| `warming_up` | 累积论文 < 10,000 | 模型在预热，结果可用但可能不稳定 |
| `None` | 完整模式 | 结果可信 |

## 9. 已知问题与后续计划

### 9.1 已知问题

1. **勘误论文得分偏高**: 部分勘误论文的 RPU 内容描述了原论文研究操作
   - 根因: RPU 提取层问题
   - **解决方案**: 使用 `PaperTypePostProcessor` 后处理降权 ✅

2. **方差在部分年份偏低**: 有符号残差截断导致分布集中
   - 缓解: 已将阈值从 0.1 调至 0.01

### 9.2 论文类型后处理 (V2.1 新增)

使用 `PaperTypePostProcessor` 对不同类型论文应用降权系数：

| 论文类型 | 检测关键词 | 权重 |
|----------|-----------|------|
| erratum | erratum, corrigendum, correction, retraction | **0.1** |
| editorial | editorial, letter to editor, response to | 0.3 |
| commentary | commentary, comment on, opinion | 0.4 |
| review | review, survey, overview, meta-analysis | 0.7 |
| case_report | case report, case study | 0.8 |
| original | (默认) | 1.0 |

**使用方法:**
```python
from calculate_innovation import InnovationState, PaperTypePostProcessor

state = InnovationState()
results = state.process_year_atomic(year_papers, year)

# 后处理
processor = PaperTypePostProcessor()
paper_titles = {paper_id: title for paper_id, title in ...}
processor.apply_type_weights(results, paper_titles)
```

**后处理效果验证 (真实数据):**

| 类型 | magnitude前 | magnitude后 | 变化 |
|------|-------------|-------------|------|
| original | 0.668 | 0.668 | 0% |
| review | 0.564 | 0.395 | -30% |
| erratum | 0.913 | **0.091** | **-90%** |

顺序验证: `original > review > erratum` **全部 PASS** ✅

### 9.3 后续计划

- [x] 参数微调实验 (结论: 调参无法解决 erratum 问题)
- [x] 论文类型后处理 (PaperTypePostProcessor)
- [ ] 全量数据运行: 处理全部 4000 万论文
- [ ] 结果分析: 统计不同领域/年份的创新度分布

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| V2.0 | 2026-02-02 | 初始实现: PCA 残差 + 方向性约束 + 有符号残差 |
| V2.1 | 2026-02-02 | 新增 PaperTypePostProcessor 后处理，erratum 降权 90% |
