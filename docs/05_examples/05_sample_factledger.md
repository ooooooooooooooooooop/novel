# 示例：FactLedger

## 文档目的
本文件提供一组 `FactLedger` 样例，用于验证：

- `FactLedger Schema` 是否足以记录“已经成立、会约束后文”的叙事实
- 系统能否区分已确认事实、角色误解、读者误导与作者计划
- 事实账本是否能稳定支撑连续性维护、信息权限判断、时间合法性检查、角色知情边界检查与世界合法性检查

本文件对应：

- `01_concepts/06_factledger.md`
- `02_data_models/06_factledger_schema.md`
- `03_rules/04_timeline_rules.md`
- `03_rules/05_information_release_rules.md`

---

## 1. 示例定位

这组样例继续沿用当前 mock project 的统一案例：

- 作品：`残雪归宗`
- 世界：`北衡界`
- 主角：`c001 / 沈青`
- 当前关键单元：`pu_scene_014 / 雨夜夺令`
- 当前关键状态：令牌已被夺到手，`c002` 已半确认异常，巡查压力已被激活，主线仍停留在“半暴露、未揭晓”阶段

这份文件不追求“事实很多”，而追求：

- 事实粒度正确
- 可见性正确
- 时间顺序正确
- 状态更新正确
- 能直接参与后续审查

---

## 2. 使用场景

这组样例主要用于验证以下问题：

### 2.1 什么东西应该进账本

系统能不能分清：

- 哪些内容是硬事实
- 哪些内容只是猜测
- 哪些内容只是情绪解读
- 哪些内容只是误导

### 2.2 账本能不能支持审查

系统能不能利用这些条目判断：

- 有没有事实冲突
- 有没有知情越界
- 有没有时间顺序错误
- 有没有把已经公开的内容当成未公开

### 2.3 账本能不能支持续写

系统能不能从这些条目出发知道：

- 谁现在知道什么
- 哪个资源现在归谁
- 哪条风险已经被激活
- 哪些状态已经不能回退

---

## 3. 示例策略

这份样例不列全书所有事实，而是只选当前阶段最关键、最有约束力的一组事实。

当前优先覆盖四类：

1. 世界硬规则
2. 资源归属
3. 知情状态
4. 风险与制度后果启动

这四类事实已经足以支撑当前 `PlotUnit` 审查、下一步续写、信息释放检查与承诺线程推进。

---

## 4. 示例 JSON

```json id="exfl05json"
[
  {
    "fact_id": "f_001",
    "fact_type": "world_rule",
    "category": "recovery_limit",
    "statement": "灵根受损不可自然恢复。",
    "involved_entities": ["北衡界", "修行体系"],
    "scope": "global",
    "established_in": "worldmodel_init",
    "source_plotunit": "",
    "source_event": "system_rule_definition",
    "evidence_type": "system_rule",
    "confidence": "confirmed",
    "established_time": "project_init",
    "effective_from": "project_init",
    "effective_until": "",
    "chronological_order": 1,
    "visibility": "public",
    "known_by": ["all_relevant_characters", "reader"],
    "unknown_to": [],
    "misinformation_link": "",
    "status": "active",
    "mutable": false,
    "revision_rule": "",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "世界硬规则；用于限制恢复类剧情处理。"
  },
  {
    "fact_id": "f_002",
    "fact_type": "world_rule",
    "category": "forbidden_action",
    "statement": "禁术使用会留下可追踪痕迹。",
    "involved_entities": ["北衡界", "禁术体系", "王城监察司"],
    "scope": "global",
    "established_in": "worldmodel_init",
    "source_plotunit": "",
    "source_event": "system_rule_definition",
    "evidence_type": "system_rule",
    "confidence": "confirmed",
    "established_time": "project_init",
    "effective_from": "project_init",
    "effective_until": "",
    "chronological_order": 2,
    "visibility": "public",
    "known_by": ["all_relevant_characters", "reader"],
    "unknown_to": [],
    "misinformation_link": "",
    "status": "active",
    "mutable": false,
    "revision_rule": "",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "是后续追踪、暴露、制度反扑的重要基础规则。"
  },
  {
    "fact_id": "f_010",
    "fact_type": "event",
    "category": "expulsion_status",
    "statement": "c001 曾被天衡宗逐出外门体系。",
    "involved_entities": ["c001", "天衡宗"],
    "scope": "character_specific",
    "established_in": "chapter_01",
    "source_plotunit": "",
    "source_event": "被逐背景已明示",
    "evidence_type": "public_record",
    "confidence": "confirmed",
    "established_time": "故事前史",
    "effective_from": "故事开始前",
    "effective_until": "",
    "chronological_order": 10,
    "visibility": "public",
    "known_by": ["c001", "天衡宗相关角色", "reader"],
    "unknown_to": [],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若后续正式恢复宗门身份，则更新 status 与说明。",
    "review_priority": "high",
    "contradiction_risk": "high",
    "notes": "这是回宗主线、身份压力与旧案线的重要前提事实。"
  },
  {
    "fact_id": "f_011",
    "fact_type": "knowledge",
    "category": "hidden_case_irregularity",
    "statement": "c002 已确认 c001 被逐一事的程序存在异常。",
    "involved_entities": ["c001", "c002", "天衡宗"],
    "scope": "character_specific",
    "established_in": "pre_scene_014_context",
    "source_plotunit": "",
    "source_event": "旧记录与宗门流程比对",
    "evidence_type": "documented_history",
    "confidence": "confirmed",
    "established_time": "scene_014 前",
    "effective_from": "scene_014 前",
    "effective_until": "",
    "chronological_order": 11,
    "visibility": "character_specific",
    "known_by": ["c002"],
    "unknown_to": ["c001", "c003"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若 c002 向他人明确说明，则更新 known_by。",
    "review_priority": "high",
    "contradiction_risk": "medium",
    "notes": "这是 c002 持续观察与迟迟不完全放手的关键依据。"
  },
  {
    "fact_id": "f_012",
    "fact_type": "resource",
    "category": "trial_token_existence",
    "statement": "黑水泽试炼令牌在 scene_014 前已流出正常分配链。",
    "involved_entities": ["黑水泽试炼令牌", "天衡宗"],
    "scope": "local",
    "established_in": "scene_014_input_state",
    "source_plotunit": "",
    "source_event": "令牌提前流出",
    "evidence_type": "direct_observation",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_start",
    "effective_until": "",
    "chronological_order": 12,
    "visibility": "restricted",
    "known_by": ["c001", "c002", "c003"],
    "unknown_to": ["大多数宗门成员"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若令牌被上交、夺回或销毁，则更新状态与归属相关条目。",
    "review_priority": "high",
    "contradiction_risk": "high",
    "notes": "这不是单纯物品事实，而是资格系统异常的证据。"
  },
  {
    "fact_id": "f_013",
    "fact_type": "knowledge",
    "category": "stance_uncertainty",
    "statement": "scene_014 开始时，c001 无法确认 c002 会在当前局势中站在哪一边。",
    "involved_entities": ["c001", "c002"],
    "scope": "character_specific",
    "established_in": "s_014_scene",
    "source_plotunit": "",
    "source_event": "当前输入状态确认",
    "evidence_type": "direct_observation",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_start",
    "effective_until": "scene_014_end",
    "chronological_order": 13,
    "visibility": "character_specific",
    "known_by": ["c001"],
    "unknown_to": ["c003"],
    "misinformation_link": "",
    "status": "inactive",
    "mutable": true,
    "revision_rule": "进入 scene_014 结尾后，此条判断被更复杂的半知情关系取代。",
    "review_priority": "medium",
    "contradiction_risk": "medium",
    "notes": "这类条目说明账本不只记大设定，也记关键知情状态。"
  },
  {
    "fact_id": "f_014",
    "fact_type": "resource",
    "category": "item_ownership",
    "statement": "scene_014 结束后，黑水泽试炼令牌当前归 c001 所有。",
    "involved_entities": ["c001", "黑水泽试炼令牌"],
    "scope": "character_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "雨夜夺令",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 14,
    "visibility": "restricted",
    "known_by": ["c001", "c002", "c003"],
    "unknown_to": ["王城监察司", "大多数宗门成员"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "令牌被夺走、上交、追踪锁定或销毁时更新。",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "直接决定后续撤离、试炼资格与追踪压力。"
  },
  {
    "fact_id": "f_015",
    "fact_type": "knowledge",
    "category": "exposure_status",
    "statement": "scene_014 结束后，c002 已确认 c001 身上存在异常力量痕迹。",
    "involved_entities": ["c001", "c002"],
    "scope": "character_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "异常反应暴露",
    "evidence_type": "direct_observation",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 15,
    "visibility": "character_specific",
    "known_by": ["c002"],
    "unknown_to": ["c003", "王城监察司"],
    "misinformation_link": "m_001",
    "status": "active",
    "mutable": true,
    "revision_rule": "若 c002 外泄、试探或利用该信息，则更新 known_by 与 visibility。",
    "review_priority": "critical",
    "contradiction_risk": "high",
    "notes": "这是当前关系线与保密承诺线的核心事实之一。"
  },
  {
    "fact_id": "f_016",
    "fact_type": "status_change",
    "category": "physical_cost",
    "statement": "scene_014 中，c001 为夺令强行动用高负荷能力，导致旧伤加重。",
    "involved_entities": ["c001"],
    "scope": "character_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "高压夺令",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 16,
    "visibility": "restricted",
    "known_by": ["c001"],
    "unknown_to": ["c003", "王城监察司"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若后续疗伤、强撑或进一步恶化，则更新状态。",
    "review_priority": "high",
    "contradiction_risk": "high",
    "notes": "这条事实主要服务于 missing_cost 检查。"
  },
  {
    "fact_id": "f_017",
    "fact_type": "event",
    "category": "trace_activation",
    "statement": "scene_014 中的异常灵压波动提高了巡查队重新锁定该区域的概率。",
    "involved_entities": ["巡查队", "黑水泽外围", "c001"],
    "scope": "local",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "灵压外泄",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 17,
    "visibility": "reader_only",
    "known_by": ["reader", "system"],
    "unknown_to": ["c001", "c002", "c003"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若巡查队正式接近、锁定或偏离，则更新为更具体状态。",
    "review_priority": "high",
    "contradiction_risk": "medium",
    "notes": "这是典型的“读者/系统已知，但角色未完全知道”的后果型事实。"
  },
  {
    "fact_id": "f_018",
    "fact_type": "relation",
    "category": "trust_shift",
    "statement": "scene_014 结束后，c001 与 c002 的关系从单纯试探转为带有保密压力的高风险半合作边缘。",
    "involved_entities": ["c001", "c002"],
    "scope": "relationship_specific",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "夺令后关系重组",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 18,
    "visibility": "restricted",
    "known_by": ["c001", "c002", "reader"],
    "unknown_to": ["c003"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若后续明确合作、背叛或保密失败，则更新关系状态。",
    "review_priority": "high",
    "contradiction_risk": "medium",
    "notes": "这类关系事实不能只停在 CharacterModel，也需要进入账本以约束后文。"
  },
  {
    "fact_id": "f_019",
    "fact_type": "event",
    "category": "goal_transition",
    "statement": "scene_014 结束后，局势主目标从争夺令牌转为带令撤离并控制秘密扩散范围。",
    "involved_entities": ["c001", "c002", "c003", "黑水泽试炼令牌"],
    "scope": "local",
    "established_in": "pu_scene_014",
    "source_plotunit": "pu_scene_014",
    "source_event": "局势升级",
    "evidence_type": "verified_action",
    "confidence": "confirmed",
    "established_time": "试炼开始前夜",
    "effective_from": "scene_014_end",
    "effective_until": "",
    "chronological_order": 19,
    "visibility": "reader_only",
    "known_by": ["reader", "system"],
    "unknown_to": ["无完整共同知情者"],
    "misinformation_link": "",
    "status": "active",
    "mutable": true,
    "revision_rule": "若下一单元主目标再次变化，则更新。",
    "review_priority": "medium",
    "contradiction_risk": "medium",
    "notes": "这是局势层事实，用来约束下一 NarrativeState 与续写方向。"
  }
]
```

---

## 5. 样例解读

### 5.1 为什么这份账本先从世界规则开始

样例开头先放了两条世界硬规则：

- `灵根受损不可自然恢复`
- `禁术使用会留下可追踪痕迹`

这是故意的，因为 `FactLedger` 不是只能记“剧情事件”，它也应该承接那些会在正文里反复被调用的世界硬事实。

这样做的价值是：

- 审查时不用重新回世界设定全文里找
- 可以直接判断为什么旧伤不能随便恢复
- 可以直接判断为什么异常使用后必须有追踪后果

也就是说，账本是运行时可直接调用的硬记忆层。

### 5.2 为什么 `f_010` 很关键

`f_010` 这条“`c001` 曾被天衡宗逐出外门体系”看起来简单，但约束力很强。

它至少限定了：

1. 主角现在没有宗门庇护
2. 回宗是需要重新争取的目标，不是默认状态
3. 她和宗门之间已经存在制度性伤痕
4. 后续任何“她自由进出宗门核心区”的剧情都要被审查

这说明账本里的事实不必花哨，但必须有约束力。

### 5.3 为什么 `f_011` 是好用的知情事实

`f_011` 写的是“`c002` 已确认 `c001` 被逐一事的程序存在异常”，而不是“`c002` 已知道所有真相”。

这个粒度很重要，因为它刚好能支撑：

- 为什么 `c002` 不会把沈青简单当成危险人物
- 为什么他会持续观察而不是立刻切断联系
- 为什么他会对宗门内部流程抱有怀疑

账本要记的是“已确认到哪一步”，而不是抢先写到最终答案。

### 5.4 为什么 `f_012` 和 `f_014` 要分开

这两条很容易被混写，但这里故意拆开：

- `f_012`：令牌在 `scene_014` 前已经异常流出分配链
- `f_014`：`scene_014` 后令牌归 `c001` 所有

前者是前态异常，后者是后态归属变化。分开后，系统才能分清：

- 哪部分是本单元开始前已经存在的异常条件
- 哪部分是本单元真正造成的新结果

### 5.5 为什么 `f_013` 这种短生命周期事实也值得记

`f_013` 写的是：`scene_014` 开始时，`c001` 无法确认 `c002` 会站在哪一边。

这种事实生命周期短，但仍然值得记，因为它直接约束当前场景中的关键决策。如果不记，后续很容易把 `c001` 的选择误写成：

- 她早就知道 `c002` 会帮她
- 她早就确定 `c002` 不可信

这两种都会把 `scene_014` 的决策逻辑写歪。

### 5.6 为什么 `f_015` 是当前阶段最核心的事实之一

`f_015` 这条“`c002` 已确认 `c001` 身上存在异常力量痕迹”几乎是当前所有后续工作的中心之一。

它会直接影响：

- `CharacterModel.relations`
- `ForeshadowGraph` 中的保密线
- `NarrativeState` 的主冲突
- 续写时 `c002` 的立场选择
- 信息释放规则的后续合法性

而且它写得很克制，不是“已知道残魂真相”，而只是“已确认存在异常力量痕迹”，说明账本粒度拿得住。

### 5.7 为什么 `misinformation_link` 只在部分条目上用

例如 `f_015` 带有 `"misinformation_link": "m_001"`，这是一个好习惯，因为它明确说明：

- 事实层和误导层是分开的
- 但二者可以互相指向

这样系统既能知道真实事实是什么，也能知道当前可能被什么误导覆盖着。它很适合后续的信息释放审查、假线索管理和误解解除后的状态更新。

### 5.8 为什么 `f_016` 和 `f_017` 很重要

这两条条目主要服务于：

- `missing_cost`
- `missing_consequence`

`f_016` 记录的是 `c001` 旧伤加重。如果后续两三个单元里主角像没事人一样，这条就会直接成为审查依据。

`f_017` 记录的是灵压波动提高了巡查队重新锁定该区域的概率。它尤其有价值，因为它属于“读者 / 系统已知，但角色尚未完全知道”的后果型事实，很适合制造紧张感，同时不让角色全知。

### 5.9 为什么 `f_018` 是关系事实，而不只放在 CharacterModel

`f_018` 写的是 `c001` 与 `c002` 的关系已经转为带保密压力的高风险半合作边缘。

很多系统只会把关系变化写在 `CharacterModel.relations` 里，但这个样例特意也把它放进账本，是因为这已经不只是角色感觉，而是会直接约束后文的关系状态。

如果后文把两人写成像什么都没发生一样继续普通试探，就会和这条事实冲突。

### 5.10 为什么 `f_019` 是局势事实

`f_019` 记录的是：局势主目标从争夺令牌转为带令撤离并控制秘密扩散范围。

它不是某个角色单独知道的一句话，而是系统对局势硬转折的确定性记录。这类条目非常适合：

- 约束下一 `NarrativeState`
- 约束 `Continue Workflow`
- 防止下一单元又退回去重复“抢令牌”阶段

也就是说，账本不只是人物事实和物品事实，也可以记录局势层已经成立的硬转折。

---

## 6. 这些事实如何支撑后续系统

### 6.1 对 NarrativeState 的支撑

这份账本可以直接支撑当前状态里的这些判断：

- 谁知道什么
- 当前风险是不是已经迫近
- 当前目标是不是已经切换
- 当前关系张力是不是已经升级

如果没有这些条目，`NarrativeState` 很容易变成“靠印象写”。

### 6.2 对 Review Workflow 的支撑

审查时，这组事实能直接抓出很多问题。

例如：

- 如果后文写 `c002` 完全不知道异常，就会撞 `f_015`
- 如果后文写 `c001` 旧伤像没存在过，就会撞 `f_016`
- 如果下一场主目标还是单纯抢令牌，就会撞 `f_019`

账本的价值就在这里：它把“以前写过什么”从模糊记忆变成了可检索硬约束。

### 6.3 对 Continue Workflow 的支撑

续写工作流拿到这份账本后，会更容易知道：

- 现在最该兑现的是哪种后果
- 哪个角色知道什么
- 哪条风险已经启动
- 下一步该从“撤离”“封口”还是“保密立场”推进

这能明显减少“写着写着忘了上一场真正改变了什么”的问题。

### 6.4 对 ForeshadowGraph 的支撑

账本不会替代承诺图，但会给承诺图提供很硬的推进节点。

例如：

- `f_015` 支撑 `c002` 是否保密
- `f_017` 支撑“异常痕迹会引来追踪”这类风险承诺
- `f_011` 支撑“旧案程序异常”这条主线继续收紧

简单说，`ForeshadowGraph` 负责答应什么，`FactLedger` 负责记录现在已经到了哪一步。

---

## 7. 最小验证清单

用这组样例时，至少验证下面这些问题：

1. 系统能不能区分“已确认事实”和“角色误解”？
2. 系统能不能根据这些条目判断谁知道什么？
3. 系统能不能根据这些条目抓出时间顺序错误？
4. 系统能不能根据这些条目抓出后果缺失？
5. 系统能不能据此约束下一步续写方向？

如果这 5 个问题都能回答，说明这组样例是可用的。

---

## 8. 样例结论

这组 `sample_factledger` 的核心价值，不在于“事实很多”，而在于它已经能提供：

- 世界硬规则的运行记忆
- 当前关键资源的归属记忆
- 当前关键知情状态的权限记忆
- 当前关键后果的激活记忆
- 当前关键关系与局势转折的约束记忆

这就足以支撑后面的：

- `sample_review`
- `mock_project_case`

---

## 9. 一句话总结

这组 `sample_factledger` 的作用，是给 mock project 提供一层不是摘要、不是评论，而是能真正约束后续剧情、知情权限、时间顺序和后果兑现的硬事实样例。
