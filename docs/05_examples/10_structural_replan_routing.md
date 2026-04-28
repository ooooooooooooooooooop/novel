# 示例：多 Issue 触发 Replan

## 文档目的
本文件提供一个结构性失败样例，用于验证以下情况能否稳定升级为 `Replan`：

- 当前存在多个正式 `ReviewIssue`
- 这些 issue 不是彼此孤立
- 它们共同指向同一结构弱点
- 局部 `Rewrite` 已不再是合理修法

它验证的是：

**系统何时应该停止局部修补，转而承认当前段落 / arc 方向已经偏了。**

本文件对应：

- `04_workflows/02_review_workflow.md`
- `04_workflows/04_rewrite_workflow.md`
- `07_decisions/03_workflow_order_decisions.md`
- `07_decisions/06_review_strategy_decisions.md`

---

## 1. 测试定位

这份样例不测试单个坏 scene，也不测试单个 reminder 超窗。

它测试的是更高一层的失败：

- 连续几个单元都没有把核心线程往前推
- 反而不断堆出旁支动作和局部关系噪声
- 审查已经能建出多个 formal issue
- 但这些 issue 其实都指向同一个问题：
  **当前 arc 的方向偏了**

此时如果还执着于逐个 `Rewrite`，通常只会继续制造更多补丁。

---

## 2. 测试前提

沿用当前 mock case：

- 作品：`残雪归宗`
- 当前关键线程：
  - `fg_001`：残魂 / 身世主线
  - `fg_002`：`c002` 是否保密

假设在 `pu_scene_015` 到 `pu_scene_017` 的连续推进里，系统犯了以下三种错误：

1. 主线承诺迟迟不推进
2. 支线试探不断重复，制造线程重复
3. 关系线继续前冲，开始脱离主线压力基础

这时问题已经不是某一场戏写坏，而是整个局部段落把资源用错了方向。

---

## 3. 当前已生成的正式问题

### 3.1 issue A：`promise_loss`

```json id="exrp10issueA"
[
  {
    "issue_id": "ri_arc_fg001_01",
    "issue_type": "promise_loss",
    "title": "残魂 / 身世主线在当前段落推进停滞过久",
    "summary": "从 pu_scene_015 到 pu_scene_017，主线没有新增有效证据、局势推进或答案范围收缩，核心承诺开始失去牵引力。",
    "object_type": "ForeshadowGraph",
    "object_id": "fg_001",
    "level": "arc",
    "plotunit_ref": "",
    "chapter_ref": "chapter_06",
    "scene_ref": "",
    "violated_rule": "核心承诺线程在连续推进中必须保持合理频率的推进或加压，不能长期停摆。",
    "supporting_facts": [],
    "contradictory_facts": [],
    "missing_elements": ["core_thread_advancement"],
    "evidence_note": "三个连续单元都把注意力放在局部试探和撤离噪声上，没有真正推进 fg_001。",
    "impact_scope": "arc",
    "affected_characters": ["c001"],
    "affected_threads": ["fg_001"],
    "affected_states": ["s_015_scene", "s_016_scene", "s_017_scene"],
    "downstream_risk": "若继续停滞，读者会逐渐失去对主线谜团的追踪感。",
    "suggested_fix_type": "arc_replanning",
    "suggested_fix_note": "需要重新安排当前段落的推进重心，而不是只修一句两句。",
    "rewrite_needed": false,
    "replanning_needed": true,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "non_blocking",
    "fix_order": 1,
    "status": "open",
    "created_at": "review_pass_scene017",
    "last_updated": "review_pass_scene017",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "这是结构性信号之一，不适合仅靠单 scene 改写解决。"
  }
]
```

### 3.2 issue B：`duplication_of_threads`

```json id="exrp10issueB"
[
  {
    "issue_id": "ri_arc_threaddup_01",
    "issue_type": "duplication_of_threads",
    "title": "当前段落重复堆叠 c002 立场试探线程",
    "summary": "多个连续单元都在重复制造“c002 到底站哪边”的相似试探，但没有提供新的结构价值，导致线程推进重复。",
    "object_type": "ForeshadowGraph",
    "object_id": "fg_002",
    "level": "arc",
    "plotunit_ref": "",
    "chapter_ref": "chapter_06",
    "scene_ref": "",
    "violated_rule": "同一承诺线程的重复激活若不带来新层级变化，会造成结构重复并挤占主线空间。",
    "supporting_facts": [],
    "contradictory_facts": [],
    "missing_elements": ["new_structural_value"],
    "evidence_note": "scene_015 到 scene_017 对 fg_002 的处理都停留在相似的模糊试探层，没有新证据、新代价或新站位。",
    "impact_scope": "arc",
    "affected_characters": ["c001", "c002"],
    "affected_threads": ["fg_002"],
    "affected_states": ["s_015_scene", "s_016_scene", "s_017_scene"],
    "downstream_risk": "若继续重复，将遮蔽主线并降低线程推进效率。",
    "suggested_fix_type": "thread_cleanup",
    "suggested_fix_note": "需要重新整理当前段落中 fg_002 的出现频率与层级。",
    "rewrite_needed": false,
    "replanning_needed": true,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "non_blocking",
    "fix_order": 2,
    "status": "open",
    "created_at": "review_pass_scene017",
    "last_updated": "review_pass_scene017",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "它不是单 scene 冗余，而是段落级线程使用失衡。"
  }
]
```

### 3.3 issue C：`relationship_jump`

```json id="exrp10issueC"
[
  {
    "issue_id": "ri_scene017_relation_01",
    "issue_type": "relationship_jump",
    "title": "c001 与 c002 的关系线推进脱离主线压力基础",
    "summary": "在主线停滞且支线试探重复的情况下，关系线仍继续前冲，导致关系推进失去结构支撑。",
    "object_type": "PlotUnit",
    "object_id": "pu_scene_017",
    "level": "scene",
    "plotunit_ref": "pu_scene_017",
    "chapter_ref": "chapter_06",
    "scene_ref": "scene_017",
    "violated_rule": "关系线的关键推进必须与主线压力、风险交换或信息变化形成支撑，不能脱离主结构独自前冲。",
    "supporting_facts": ["f_018"],
    "contradictory_facts": [],
    "missing_elements": ["relationship_pressure_basis"],
    "evidence_note": "关系推进本身并非唯一问题，它在当前段落中与 promise_loss 和 thread duplication 共同出现。",
    "impact_scope": "segment",
    "affected_characters": ["c001", "c002"],
    "affected_threads": ["fg_002"],
    "affected_states": ["s_017_scene"],
    "downstream_risk": "若继续局部修补，只会在主线停滞的背景下继续推高关系失真。",
    "suggested_fix_type": "arc_replanning",
    "suggested_fix_note": "需要回到段落层调整主线、支线与关系线的权重排序。",
    "rewrite_needed": true,
    "replanning_needed": true,
    "memory_update_needed": true,
    "severity": "medium",
    "urgency": "soon",
    "blocking_status": "non_blocking",
    "fix_order": 3,
    "status": "open",
    "created_at": "review_pass_scene017",
    "last_updated": "review_pass_scene017",
    "resolved_by": "",
    "resolution_note": "",
    "notes": "单看像局部问题，但放进当前 issue 组合里，它是结构偏移的第三个信号。"
  }
]
```

---

## 4. 为什么这里不该继续 Rewrite

表面上看，第三个 issue 似乎还能改 scene。

但如果把三个 issue 放在一起看，会发现：

- `promise_loss` 指向主线推进停滞
- `duplication_of_threads` 指向支线占位重复
- `relationship_jump` 指向关系线脱离主结构前冲

它们共同说明的是：

**当前段落的重心排序已经错了。**

此时如果还继续 `Rewrite`：

- 修关系跳变，主线停滞还在
- 清一处重复线程，段落重心仍没被重排
- 插一句主线提示，也无法真正修复当前段落的资源分配

所以这不是 point fix，也不是 chain fix，而是 segment / arc 级失衡。

---

## 5. 正确审查结论

推荐结论应是：

- 本轮：失败（结构性）
- 分流：升级为 `Replan`
- 当前 formal issue 保留
- 不进入局部 `Rewrite`

推荐路由：

```text
Review
  -> 读取多个 formal issue
  -> 识别它们共同指向同一结构弱点
  -> 判定为 structural failure
  -> route to Replan
```

---

## 6. 为什么这里不是“issue 多所以升级”

这里不是简单的“数量达到 3 条就自动 Replan”。

真正的升级理由是：

- 多条 issue 有共同结构指向
- 当前问题已经跨越单 scene
- 局部修补不能恢复主线 / 支线 / 关系线的权重平衡

如果只是三个互不相关的小问题：

- 一个时间小错
- 一个局部冗余
- 一个风格漂移

那仍不应自动 `Replan`。

---

## 7. 这个样例在验证什么

这份样例主要验证 4 件事：

### 7.1 `Replan` 的触发不是情绪化升级

它必须由多个 formal issue 的共同结构指向支持。

### 7.2 `Rewrite` 和 `Replan` 的边界是“修法是否仍局部有效”

如果局部修法已经不能修回主重心，就该承认需要重排。

### 7.3 单个局部 issue 放进 issue 组合后，意义会改变

`relationship_jump` 单独看可能是 `Rewrite`；
和主线停滞、线程重复一起看，就变成结构偏移信号。

### 7.4 审查必须给出明确动作，而不是只堆问题

如果审查能看见这三个问题，却不给出 `Replan`，那 workflow 仍然不闭环。

---

## 8. 当前结论

如果这份样例成立，可以认为系统已经具备三层分流样例：

- reminder only -> `Continue`
- reminder + local issue -> `Rewrite`
- multiple formal issues with shared structural weakness -> `Replan`

---

## 9. 一句话总结

`10_structural_replan_routing.md` 的任务，是证明 `Replan` 不是“问题很多时的夸张反应”，而是“多个 formal issue 已共同指向结构失衡”时的必要路由。
