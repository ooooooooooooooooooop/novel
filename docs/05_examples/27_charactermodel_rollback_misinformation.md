# 示例：CharacterModel Rollback Misinformation 压测

## 文档目的

本文档提供一个 rollback-heavy repeated recovery 样例，用于验证：

- 当 `self_image` 与 `arc_stage` 已出现真实更新时，旧的 `misinformation` 是否会被系统过早清空
- repeated `Continue / Review / Rebuild` 之后，`CharacterModel` 是否还能同时保留“已推进的成长结构”和“尚未完全退出的旧误判”
- rollback 之后，系统会不会误把“成长已推进”读成“旧误判已完全失效”

它验证的不是：

- `misinformation` 是否永远不该被删除

它验证的是：

- 旧误判的衰减、动摇、残留，与 `self_image` / `arc_stage` 的推进不是同一件事

本文档主要对应：

- `02_data_models/09_field_rules.md`
- `07_decisions/04_schema_granularity_decisions.md`
- `07_decisions/10_ownership_matrix_decisions.md`
- `04_workflows/01_rebuild_workflow.md`

---

## 1. 测试定位

`26_charactermodel_cross_field_recovery.md` 已经压过：

- 多字段一起变化时，不应把长期结构、当前工作面和 supporting evidence 混在一起

但还缺另一种更隐蔽的失败：

- `self_image` 与 `arc_stage` 的确已经有 first-pass 合法推进
- 系统因此误以为旧误判也应该同步“毕业”

如果这层不压，系统最容易出现三种坏结果：

1. 旧误判被过早删除，角色像是一下子“彻底想通了”
2. `self_image` 更新被误读成误判层已经归零
3. `Rebuild` 后角色表现得比实际成长进度更稳定、更干净

---

## 2. 测试前提

沿用当前 mock case，并假设 `c001` 的相关字段如下：

```json
{
  "character_id": "c001",
  "misinformation": [
    "只要自己继续单独承担，就还能控制秘密外泄"
  ],
  "self_image": "不值得被长期信任，只适合一个人活下去",
  "arc_stage": "未觉醒"
}
```

在随后的若干轮推进中，系统已经观察到：

- `c001` 多次允许 `c002` 参与关键判断
- 这样做带来过真实代价
- `c001` 也开始怀疑“自己不能只靠一个人扛下去”

但与此同时，旧误判并没有完全消失：

- 一旦局势恶化，`c001` 仍会本能地回到“先把所有风险揽到自己身上”

这里最关键的是：

- 成长方向确实已出现稳定偏移
- 旧误判却仍有残留支配力

---

## 3. Loop 1：第一次合法推进

### 3.1 可成立的新变化

在 repeated `Continue` 后，系统可以合法更新：

- `self_image`
  - 从 `不值得被长期信任，只适合一个人活下去`
  - 调整为 `仍难完全信任他人，但已不再把独自承担视为唯一方式`
- `arc_stage`
  - 从 `未觉醒`
  - 推进到 `开始怀疑只能独活的旧信念`

### 3.2 此时最容易犯的错

系统会很自然地想把旧误判一并删掉，理由通常是：

- “既然都开始共同承担了，那这条误判应该已经失效”

### 3.3 为什么这一步还不能删

因为这里成立的是：

- 新的成长方向已经出现

而不是：

- 旧误判已经失去行为影响力

成长推进和误判消退可以同向发生，但不要求同轮完成。

---

## 4. Loop 2：rollback 压力测试

### 4.1 新推进

在一次失败后的高压场景里，`c001` 又出现了明显回摆：

- 主动切断与 `c002` 的共享链路
- 再次试图一个人承担后果
- 并说出近似旧信念的话：
  - “只要我一个人扛住，事情就还不会彻底失控”

### 4.2 这里的正确裁定

这不表示：

- `self_image` 必须立刻回退到旧版本
- `arc_stage` 必须完全归零

但它强烈说明：

- 旧 `misinformation` 仍然活跃
- 至少还不能从角色模型里被完全清空

### 4.3 为什么这一步特别关键

如果系统在 Loop 1 就把旧误判删掉，那么 Loop 2 会被迫误读成：

- 一次新的偶发异常

而不是：

- 成长推进中的真实回摆

这会让角色显得：

- 不是复杂
- 而是写法反复

---

## 5. 第一次 `Rebuild` 后的正确恢复

当 bounded package 不足并进入 `Rebuild` 时，正确恢复应至少做到：

### 5.1 仍保留在 `CharacterModel` 的

- 更新后的 `self_image`
- 更新后的 `arc_stage`
- 尚未完全退出的旧 `misinformation`

### 5.2 不应错误恢复成的两种极端

#### 极端 A：误判层被清空

错误恢复：

```json
{
  "misinformation": [],
  "self_image": "已承认共同承担并非软弱",
  "arc_stage": "开始怀疑只能独活的旧信念"
}
```

这会把角色恢复得过度干净。

#### 极端 B：成长层被一键回滚

错误恢复：

```json
{
  "misinformation": [
    "只要自己继续单独承担，就还能控制秘密外泄"
  ],
  "self_image": "不值得被长期信任，只适合一个人活下去",
  "arc_stage": "未觉醒"
}
```

这会把已经成立的成长偏移也抹掉。

### 5.3 正确恢复应更接近什么

正确恢复更接近：

```json
{
  "misinformation": [
    "仍本能地相信只要自己单独承担，就更容易控制秘密外泄"
  ],
  "self_image": "仍难完全信任他人，但已不再把独自承担视为唯一方式",
  "arc_stage": "开始怀疑只能独活的旧信念"
}
```

重点不是文字一定这样写，而是三层要同时成立：

- 成长已推进
- 旧误判未清零
- rollback 仍可被后续继续验证

---

## 6. Loop 3：第二次推进后的正确处理

### 6.1 新推进

在恢复后的若干轮里，`c001` 再次：

- 主动共享风险判断
- 在失败后没有完全退回旧模式
- 并开始承认“自己单独承担并不能真正减少外泄风险”

### 6.2 这时的正确裁定

此时可以出现以下变化：

- `misinformation` 从主导误判降为残留误判
- `self_image` 进一步稳定
- `arc_stage` 继续向下一阶段推进

### 6.3 但这仍不等于

- 旧误判必须在第一时间被删空

更合理的是：

- 先改写误判的强度或支配力
- 再在更充分的长链证据下考虑彻底移除

---

## 7. 最小裁定表

| 候选情况 | 正确去向 | keep / drop | 核心理由 |
|---|---|---|---|
| `self_image` 出现跨多轮、带代价的稳定偏移 | `CharacterModel.self_image` | keep | 已形成长期新自我定义 |
| `arc_stage` 进入 first-pass 推进 | `CharacterModel.arc_stage` | keep | 已形成阶段性变化 |
| 旧“独自承担即可控制局势”的信念仍在 rollback 中复燃 | `CharacterModel.misinformation` | keep | 误判仍有行为支配力 |
| 因成长推进就自动把旧误判清空 | 不允许 | drop too early | 把成长推进误读成误判消失 |
| 因 rollback 出现就把 `self_image` / `arc_stage` 全部一键回滚 | 不允许 | rollback too much | 抹掉已成立成长偏移 |

---

## 8. 这份样例验证了什么

这份样例主要验证五件事：

1. `misinformation` 的衰减速度不应和 `self_image`、`arc_stage` 的推进速度被强行绑死
2. 合法成长推进后，旧误判仍可能继续残留并影响行为
3. repeated `Rebuild` 必须能同时保住“已推进的成长结构”和“尚未清空的旧误判”
4. rollback 不是成长失败，而是判断误判层是否仍活跃的重要证据
5. 角色模型真正稳定时，允许同时存在“比以前更成熟”和“还没完全摆脱旧误判”这两件事

---

## 9. 一句话总结

`CharacterModel` 的成熟推进不应自动清空旧误判；真正稳定的长链恢复，必须允许 `self_image`、`arc_stage` 与 `misinformation` 在一段时间内不同步收敛。
