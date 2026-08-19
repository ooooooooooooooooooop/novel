# GoldenMasterCorpus Schema

## 文档目的

本文件定义研究性“黄金母版语料库”（Golden Master Corpus）的锚库条目、来源治理、held-out 生命周期、结构距离衰减和消费接口。

黄金母版语料库只服务于信号 3“结构锚与独特性”的评估；经明确隔离的摘要接口可供信号 1“局内后果”选择器读取结构先验，但不得取代局内后果计算。它不是训练语料、作者模仿库、生产资格证明或自动终审依据。

本设计遵守 ADR-16 的边界：默认关闭、仅限 off-by-default 研究设计、不实现 DirectAPI、不改变现有生产门禁和 tier 边界。它只规定数据与治理接口，不宣称系统已经具备无人值守生产资格。

主要约束：

- 只允许公开或本地使用合法的数据来源；
- 只保留中性聚合统计，不保留书名、作者名、正文、工作区名、机器路径或可逆识别信息；
- `held_out=true` 的锚点只做评估，不能进入训练、校准或在线反馈；
- 关闭锚库时不读取、不计算、不注入，不改变旧版 prompt 字节和既有排序；
- 锚距离、局内后果奖励和自身一致性必须分开报告，不能压成审美总分。

---

## 1. 对象名称

- 对象名：`GoldenMasterCorpus`
- 条目名：`GoldenMasterAnchorEntry`
- 快照名：`GoldenMasterSnapshot`
- 目标：为结构对位、独特性和奖励漂移审计提供不可变、可追溯但不泄露来源身份的统计锚。
- 当前状态：design-only，默认关闭。

一个锚点条目是由合法来源材料在本地确定性计算后形成的、不可直接还原原文的结构统计记录。条目不保存原始文本，也不允许保存能够直接定位原始作品或作者的字段。

---

## 2. 顶层结构

```json
{
  "schema_version": "1.0",
  "anchor_id": "agm-7f2c9a10",
  "source_category": "public_licensed_aggregate",
  "track": "escalation",
  "statistical_fingerprint": {
    "scene_length_chars": {
      "p10": 420,
      "p50": 980,
      "p90": 1860
    },
    "scene_transition_rate": 0.28,
    "information_release_interval": {
      "p25": 1,
      "p50": 2,
      "p75": 4
    },
    "hook_interval": {
      "p25": 2,
      "p50": 4,
      "p75": 7
    },
    "consequence_lag": {
      "p25": 0,
      "p50": 1,
      "p75": 3
    },
    "dialogue_ratio": 0.36,
    "action_ratio": 0.31,
    "environment_ratio": 0.18,
    "stage_position": 0.62
  },
  "normalization": {
    "version": "robust-z-v1",
    "scale_source": "frozen_training_excluded_reference"
  },
  "included_at": "2026-08-19",
  "held_out": true,
  "held_out_status": "frozen",
  "status": "held_out_frozen",
  "provenance": {
    "source_count_bucket": "10-49",
    "license_class": "public_or_locally_lawful",
    "privacy_check": "passed",
    "content_retention": "aggregate_only"
  }
}
```

---

## 3. 字段定义总表

| 字段名 | 类型 | 必填 | 字段分类 | 说明 |
|---|---|---:|---|---|
| `schema_version` | string | 是 | 硬字段 | 锚点 schema 版本 |
| `anchor_id` | string | 是 | 标识字段 | 中性、不可复用的锚点 ID |
| `source_category` | enum string | 是 | 溯源字段 | 来源治理类别，不含来源身份 |
| `track` | enum string | 是 | 结构字段 | 结构比较轨道 |
| `statistical_fingerprint` | object | 是 | 派生字段 | 归一化后的统计槽位集合 |
| `normalization` | object | 是 | 版本字段 | 标准化方法及冻结尺度版本 |
| `included_at` | date | 是 | 时间字段 | 纳入锚库的日期，不代表原始材料日期 |
| `held_out` | boolean | 是 | 权限字段 | 是否属于不可训练的评估保留集 |
| `held_out_status` | enum string | 是 | 权限字段 | held-out 的冻结、污染或退役状态 |
| `status` | enum string | 是 | 生命周期字段 | 当前治理状态 |
| `provenance` | object | 是 | 溯源字段 | 仅允许中性治理元数据 |

### 3.1 字段约束

- `anchor_id` 不得编码书名、作者名、原始路径、URL、章节标题或可逆的来源顺序；创建后不得复用。
- `source_category`、`track`、槽位定义、归一化版本和距离参数均属于冻结设计的一部分，不能由运行时按候选结果调整。
- `included_at` 只表示进入当前快照的时间；不保留原始材料的出版时间或精确采集时间。
- `held_out=true` 是用途边界，不是“高质量”标签；此时 `held_out_status` 必须是 `frozen`、`invalidated_by_contamination` 或 `retired`。
- `held_out=false` 时 `held_out_status` 必须是 `not_held_out`；污染不得通过把 `held_out` 改回 `false` 来掩盖。
- `provenance` 只能使用粗粒度数量区间、许可类别、隐私检查结果和算法版本，不得携带可定位来源的组合。

---

## 4. 结构轨道与统计指纹槽位

### 4.1 轨道

`track` 表示结构比较的独立分组。初始允许值：

- `opening`
- `escalation`
- `reversal`
- `payoff`
- `transition`
- `mixed`

轨道必须在建库前固定。新增、删除或重新解释轨道属于 schema 或研究设计变更，不得由选择器运行时自行改变。每个轨道独立计算并独立聚合，避免样本较多的轨道获得隐含更高权重。

### 4.2 通用槽位

| 槽位 | 类型/范围 | 说明 |
|---|---|---|
| `scene_length_chars` | 分位数对象 | 场景长度的稳健分布，不保存单场景文本 |
| `scene_transition_rate` | `[0, 1]` | 场景之间发生地点、时间或目标转换的比例 |
| `information_release_interval` | 非负整数分位数 | 新信息释放之间的相对间隔 |
| `hook_interval` | 正整数分位数 | 钩子或悬置事件之间的相对间隔 |
| `consequence_lag` | 非负整数分位数 | 选择到可见后果之间的章节或场景滞后 |
| `dialogue_ratio` | `[0, 1]` | 对话占比 |
| `action_ratio` | `[0, 1]` | 可观测行动占比 |
| `environment_ratio` | `[0, 1]` | 环境与现场信息占比 |
| `stage_position` | `[0, 1]` | 结构单元在所属轨道中的相对位置 |

比例槽位的分类规则必须固定。`dialogue_ratio + action_ratio + environment_ratio` 不要求等于 1，因为允许心理、叙述和转场等其他类别；但不得按候选结果动态改变分类规则。

### 4.3 缺失槽位

缺失槽位必须显式记录为缺失，不得用零填充。距离计算只在双方均有值的槽位上进行，并将有效维度比例作为置信度修正项。

当有效维度低于预先冻结的 `v_min` 时：

- 不生成锚距离；
- 不生成信号 3 结构奖励；
- 不用零分伪装成“距离很远”；
- 记录 `insufficient_fingerprint` 诊断。

---

## 5. 来源清单与隐私规则

### 5.1 来源准入清单

来源必须同时满足：

1. 来源公开，或操作者能够证明本地使用合法；
2. 许可允许本地统计分析；
3. 不要求将原文、作者信息或来源定位信息提交到共享仓库；
4. 能在本地完成隐私检查；
5. 最终产物可以限制为中性聚合统计；
6. 可以记录许可类别，而不记录可识别的作品或作者身份。

初始允许的 `source_category`：

- `public_licensed_aggregate`：公开且许可允许研究使用，最终只保留聚合统计；
- `public_domain_aggregate`：公开领域材料，且本地使用符合适用法律；
- `local_lawful_aggregate`：操作者拥有合法使用权的本地材料，处理后只提交中性聚合；
- `synthetic_structural_reference`：人工构造的结构参考，不来自具体作品。

未知来源类别、许可状态不明、用途不明或无法证明隐私中性的来源，必须拒绝处理。来源清单只表达类别和许可状态，不列具体标题、作者、URL、路径或原始文件名。

### 5.2 禁止字段

以下信息不得进入锚库、文档、日志、共享证据或提交记录：

- 书名、章节标题、作者名或笔名；
- 正文、句子、段落、可搜索片段或 n-gram；
- 角色名、地点名、专有名词和机器路径；
- 原始 URL、下载地址、内部文件名或仓库名；
- 精确来源计数，以及可通过计数反推来源的组合；
- 可用于重新识别单一作品或作者的异常统计；
- 原始文本 hash、逐章 hash 或其他可逆关联标识。

允许保留的来源元数据仅限于中性类别、粗粒度数量区间、许可类别、隐私检查结果和算法版本。`source_count_bucket` 只能使用足够宽的区间，例如 `10-49`、`50-99`、`100+`；若区间仍会暴露单一来源，应提高最小聚合阈值或拒绝纳入。

### 5.3 隐私失败行为

以下任一情况必须拒绝或隔离：

- 检测到禁止字段；
- 许可状态无法确认；
- 聚合样本过小，可能暴露单一来源；
- 统计槽位能与外部信息组合形成稳定识别；
- 正文、作者或路径写入中间产物；
- 隐私检查结果为未知或失败。

处理顺序：

1. 拒绝该批次进入锚库；
2. 不生成部分可消费的锚点；
3. 将原始输入和中间产物限制在本地隔离区；
4. 删除或人工清理共享目录中的违规副本；
5. 只记录不含敏感值的失败类别；
6. 恢复准入前重新进行隐私审查。

隐私失败不得通过“仅保留一部分字段”自动降级为可用条目，因为部分统计组合仍可能泄露来源。

---

## 6. Held-out 治理

### 6.1 用途边界

`held_out=true` 的锚点只用于：

- 结构距离评估；
- 信号 3 的离线比较；
- 选择器行为审计；
- 长期奖励漂移监控；
- 独立实验报告。

held-out 锚点不得用于：

- 训练生成器；
- 训练或调参选择器；
- 在线更新奖励权重；
- 生成可直接复制的结构模板；
- 通过候选反馈反向暴露单个锚点坐标；
- 自动授予生产资格或“大神级”认证。

### 6.2 训练隔离

训练数据清单和 held-out 数据清单必须在生命周期上分离。评估代码只能读取 held-out 的中性指纹接口，不得读取任何原始材料。

若无法证明训练过程未接触 held-out 数据，该批次不得作为有效评估锚，并标记为：

```text
held_out_status = invalidated_by_contamination
```

`held_out_status` 的允许值为：

- `not_held_out`：条目不属于评估保留集；
- `frozen`：已冻结、只可用于评估；
- `invalidated_by_contamination`：无法证明训练隔离，永久失去评估资格；
- `retired`：不再参与新评估，但保留历史引用。

污染后的锚点不得通过重新命名、重新计算或把 `held_out` 改回 `false` 恢复资格。

### 6.3 变更门禁

以下变化必须经过 ADR-level 决策：

- 新增或删除来源类别；
- 修改 held-out 成员；
- 将非 held-out 数据改为 held-out；
- 改变归一化方法；
- 改变统计槽位定义；
- 改变距离函数或衰减参数；
- 改变信号 3 的消费接口；
- 将 held-out 数据用于训练、校准或在线反馈；
- 修改“默认关闭”或“只做研究”的边界。

普通配置提交不能绕过上述门禁。变更裁定至少要说明：变更原因、受影响的历史实验、是否重算基线、污染和回滚方案、零成本契约影响以及隐私和独立验证影响。

---

## 7. 距离衰减的公式化定义

### 7.1 槽位标准化

对候选结构 `x` 和锚点 `a` 的每个数值槽位 `j`，先使用冻结尺度标准化：

```text
z_j(v) = (v_j - median_j) / max(scale_j, ε)
```

其中：

- `median_j` 和 `scale_j` 来自冻结的、与 held-out 隔离的参考分布；
- `ε > 0` 防止尺度为零；
- 不得使用当前候选批次重新估计尺度；
- 不得为了提高某个候选分数而改变尺度。

### 7.2 截断距离

单槽位距离定义为：

```text
δ_j(x, a) = min(1, |z_j(x) - z_j(a)| / c_j)
```

其中 `c_j` 是预先声明的截断常数。截断避免极端槽位支配总分，也避免选择器通过制造单一异常值操纵距离。

候选与锚点的加权距离定义为：

```text
d(x, a) = Σ(j ∈ V) w_j · δ_j(x, a) / Σ(j ∈ V) w_j
```

其中：

- `V` 是双方都有值的有效槽位集合；
- `w_j ≥ 0` 且由冻结配置声明，且所有启用槽位必须满足 `Σ(j) w_j > 0`；
- `c_j > 0`；
- 当有效槽位比例低于预先冻结的 `v_min` 时，距离无效；本设计声明 `v_min = 0.5`；
- 距离范围为 `[0, 1]`。

### 7.3 距离衰减与防贴锚游戏化

单个锚点的结构对位权重定义为：

```text
r(x, a) = exp(-λ · d(x, a))
```

其中 `λ > 0` 在实验开始前固定。距离越远，对位权重越低，但该值不直接等同于文学质量。

为避免反复贴近单一锚点，最终结构对位分数不得使用全库最大值，也不得允许单个锚点贡献无限增长。建议使用分轨道、截尾、等权聚合：

```text
R_track(x) = trimmed_mean(
  clip(r(x, a), r_min, r_max)
  for a in A_track
)
```

```text
R_anchor(x) = mean(R_track(x) for track in enabled_tracks)
```

其中：

- 每个轨道先独立聚合，再进行宏平均；
- 轨道样本数不改变轨道权重；
- `trimmed_mean` 去除预先声明比例的极端值；
- `r_min`、`r_max`、截尾比例和 `λ` 在快照中固定，且 `0 ≤ r_min ≤ r_max ≤ 1`；
- 若某轨道没有达到最小有效锚点数，则该轨道无效；若没有有效轨道，整个结果为 `unavailable`，不以零分替代；
- `clip` 限制单点影响；
- 消费方不返回单个锚点的命中排名、坐标或可逆距离细节。

### 7.4 反投机不变量

距离衰减必须同时满足：

1. **单锚点封顶**：单个锚点不能单独决定候选排序；
2. **重复不增益**：复制同一结构统计不能通过增加条目数提高分数；
3. **分轨道平衡**：不能只优化最容易命中的轨道；
4. **固定尺度**：候选不能改变标准化参考分布；
5. **隐藏坐标**：消费方只能获得聚合分数和置信度；
6. **批次去重**：相同或近似相同的候选指纹只计一次；
7. **自身一致性分离**：与自身已提交文本的自一致分数不得并入锚点距离；
8. **最低有效维度**：缺失大量槽位的候选不得以缺失换取高分；
9. **长期审计**：持续观察结构分数、局内后果奖励和候选多样性的关系。

信号 3 至少独立报告：

```text
anchor_alignment
anchor_distance
self_consistency
distribution_novelty
fingerprint_coverage
```

### 7.5 输出映射与置信度

为避免接口字段只有名称没有计算含义，固定如下映射：

```text
anchor_alignment(x) = R_anchor(x)
anchor_distance(x) = 1 - R_anchor(x)
fingerprint_coverage(x) = W_valid(x) / W_declared
self_consistency(x) = exp(-μ · d_self(x, committed_history))
distribution_novelty(x) = clip(
  (anchor_distance(x) - d_low) / (d_high - d_low),
  0,
  1
)
confidence(x) = fingerprint_coverage(x)
  · min(1, n_valid_anchors / n_min_anchors)
```

其中：

- `W_valid` 是候选与当前快照共有且通过范围检查的槽位权重之和，`W_declared > 0` 是快照声明的全部槽位权重之和；
- `d_self` 使用同一标准化、截断和加权距离函数比较候选与最近已提交指纹；没有已提交历史时 `self_consistency = null`；
- `μ > 0`、`d_low`、`d_high` 和 `n_min_anchors` 在快照中固定，且 `0 ≤ d_low < d_high ≤ 1`、`n_min_anchors > 0`；
- `distribution_novelty` 是相对锚库的偏离测量，不是单独的质量奖励；超出冻结距离带不会无限增益，必须与局内后果、硬门禁和候选多样性一起解释；
- 有效锚点不足、`W_declared = 0` 或距离无效时，相关字段为 `null`，状态为 `insufficient_fingerprint` 或 `unavailable`，不得伪装成零分。

不得将这些字段压成一个不可解释的“审美总分”。

---

## 8. 与信号 1/3 选择器的消费接口

以下接口是设计接口，不代表当前系统已经实现。

### 8.1 信号 1：局内后果选择器

信号 1 只关心候选 rollout 造成的状态后果。黄金母版只能提供可选的结构先验摘要，不得取代局内后果计算：

```text
Signal1SelectorInput {
  candidate_id: NeutralId
  state_before: NarrativeStateSummary
  state_after: NarrativeStateSummary
  open_promises_before: PromiseSummary[]
  open_promises_after: PromiseSummary[]
  consequence_events: ConsequenceSummary[]
  hard_gate_result: HardGateResult
  optional_anchor_context: AnchorContext | null
}
```

```text
Signal1SelectorOutput {
  candidate_id: NeutralId
  viability: float
  promise_progress: float
  consequence_quality: float
  future_choice_space: float
  hard_gate_penalty: float
  anchor_context_used: boolean
  status: "design_only" | "disabled" | "unavailable"
}
```

约束：

- `viability`、`promise_progress`、`consequence_quality` 和 `future_choice_space` 分开计算；
- 硬门禁失败不得被锚点分数抵消；
- 锚点上下文为空时，信号 1 仍按原有状态后果逻辑运行；
- 不得把锚点对位解释为局内后果；
- 选择器不得读取 held-out 原文或单锚点明细。

### 8.2 信号 3：结构锚与独特性选择器

```text
Signal3SelectorInput {
  candidate_id: NeutralId
  fingerprint: StatisticalFingerprint
  track: Track
  submitted_history_fingerprint: StatisticalFingerprint | null
  anchor_snapshot_id: NeutralId
  mode: "disabled" | "design_only" | "research"
}
```

```text
Signal3SelectorOutput {
  candidate_id: NeutralId
  anchor_alignment: float | null
  anchor_distance: float | null
  self_consistency: float | null
  distribution_novelty: float | null
  fingerprint_coverage: float
  confidence: float
  status: "disabled" | "insufficient_fingerprint" | "design_only" | "research"
}
```

约束：

- `anchor_snapshot_id` 只标识冻结快照，不暴露来源；
- `anchor_alignment` 与 `self_consistency` 必须分开报告；
- `distribution_novelty` 不能通过随机扰动直接获得高分；
- 信号 3 只能进入研究性 Pareto 排序或离线报告；
- 信号 3 不得单独阻断章节提交，也不得授予认证；
- 未启用时，调用方获得 `status="disabled"`，而不是隐式零分。

---

## 9. 与本地 130+ 作者合集汇合

本地已有的 130+ 作者合集可以作为统计指纹计算输入，但不改变黄金母版的隐私和 held-out 规则。

汇合流程只允许：

1. 在本地对合法材料进行确定性统计；
2. 按预先声明的类别和轨道计算指纹；
3. 进行最小聚合阈值检查；
4. 删除或隔离原始文本、作者信息和路径；
5. 只把中性聚合统计纳入候选锚点集合；
6. 再由治理流程决定其中哪些条目可成为 held-out 锚点。

本地合集不得被解释为：

- 作者模仿授权；
- 作者模型生产输入；
- 生成器训练集；
- 生产资格证明；
- 自动终审数据；
- 作品或作者身份索引。

文档、日志和共享证据中只能使用如下中性形式：

```text
source_category = local_lawful_aggregate
source_count_bucket = 100+
track = reversal
privacy_check = passed
```

不得出现任何具体标题、作者、作品、路径或可逆的来源组合。本地原始材料和逐来源映射只留在受控本地隔离区，不作为共享或提交产物。

---

## 10. 生命周期与快照

### 10.1 状态

锚点条目建议使用以下状态：

```text
candidate
privacy_review
approved_aggregate
held_out_frozen
invalidated
retired
```

正常转移为：

```text
candidate → privacy_review → approved_aggregate → held_out_frozen
```

任何状态均可转为 `invalidated`。`held_out_frozen` 不得直接回到训练或校准状态。`retired` 只表示不再参与新评估，不抹去历史快照的审计引用。

### 10.2 快照不可变

选择器只能引用不可变的 `anchor_snapshot_id`。每个快照必须固定：

- 锚点成员；
- 轨道集合；
- 槽位定义；
- 标准化版本；
- 距离参数；
- 截尾和封顶参数；
- 隐私检查结果；
- 生成时间；
- 研究状态。

更新锚库必须生成新快照，不得覆盖旧快照。历史实验必须保留快照引用，以保证结果可解释。快照变更、成员变更和参数变更均遵循 ADR-level 变更门禁。

---

## 11. 零成本契约与关闭行为

黄金母版及信号 3 默认关闭。

当功能关闭、快照不存在、隐私检查失败、指纹不足或模式不是研究模式时：

- 不读取锚库；
- 不计算距离；
- 不注入锚点上下文；
- 不改变候选 prompt；
- 不改变现有排序；
- 不新增输出文件；
- 不改变旧版状态序列化；
- 不改变提交门禁；
- prompt 字节必须与关闭前基线逐字节相同。

关闭路径不是“分数为零后继续”，而是“不存在该能力”。任何新增开关都必须配套关闭路径回归测试。该文档本身不新增代码，因此本交付只记录契约，未声称回归测试已执行。

---

## 12. 长期预警挂钩

锚距离与奖励分必须作为独立时间序列监控。预警只发出诊断信号，不自动调权、不自动恢复启用。

当以下任一关系持续达到预先声明的观察窗口时，应发出 warning：

```text
anchor_distance ↑ 且 signal1_reward ↑
anchor_alignment ↑ 且 consequence_quality ↓
signal1_reward ↑ 且 candidate_diversity ↓
```

建议接口：

```text
AnchorRewardDivergenceWarning {
  window_id: NeutralId
  window_size: integer
  anchor_distance_trend: "up" | "down" | "flat"
  signal1_reward_trend: "up" | "down" | "flat"
  divergence_score: float
  candidate_diversity: float
  action: "warn_and_audit"
}
```

预警触发后：

1. 暂停使用相关研究奖励路径；
2. 检查候选是否集中贴近单一结构区域；
3. 检查距离衰减、轨道权重和缺失槽位处理；
4. 对比信号 1 的局内后果与信号 3 的独立报告；
5. 检查 draft-vs-committed 漂移和自身一致性；
6. 不得通过在线调参消除预警；
7. 若确认存在游戏化，废弃受影响快照并回到关闭状态。

预警本身不证明选择器已经失效，但调查完成前不得把奖励提升解释为质量提升。预警记录只能包含中性窗口 ID、趋势、聚合分数和处置状态，不得记录具体作品、作者或路径。

---

## 13. 中性最小示例

以下示例只展示结构统计，不对应任何具体作品、作者或原始文本：

```json
{
  "anchor_id": "agm-2b91c4e0",
  "source_category": "synthetic_structural_reference",
  "track": "reversal",
  "statistical_fingerprint": {
    "scene_transition_rate": 0.22,
    "information_release_interval": {
      "p50": 2,
      "p75": 4
    },
    "consequence_lag": {
      "p50": 1,
      "p75": 3
    },
    "dialogue_ratio": 0.41,
    "stage_position": 0.57
  },
  "included_at": "2026-08-19",
  "held_out": true,
  "held_out_status": "frozen",
  "status": "held_out_frozen"
}
```

该示例只能说明字段形态、结构轨道、统计槽位和治理状态，不能说明任何具体作品的风格、作者选择或文本内容。

---

## 14. 非目标与实施边界

本文件不实现：

- 语料下载或抓取；
- 许可判断自动化；
- 原始文本解析器；
- 统计指纹提取器；
- 训练集与评估集自动切分；
- 信号 1 或信号 3 选择器；
- 在线奖励；
- DirectAPI；
- 自动认证；
- 生产级无人值守创作。

在实现这些能力之前，必须分别提供用户裁定、对应 ADR 或批准记录、隐私失败测试、held-out 污染测试、关闭路径字节回归测试、长期奖励背离预警测试以及与现有生产门禁的隔离证明。

## 一句话总结

黄金母版语料库是一个默认关闭、仅保存隐私中性聚合统计的 held-out 结构评估锚；它通过冻结快照、分轨道距离衰减和长期背离预警，为信号 1 与信号 3 提供可审计接口，但不进入训练、不替代局内后果、不授予生产或审美资格。
