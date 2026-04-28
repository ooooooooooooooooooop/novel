# 示例：Mixed Threshold Recovery Chain 压测

## 文档目的

本文档提供一个 mixed-family repeated `degradation -> rebuild -> review -> continue` 长链样例，用于验证：

- knowledge、relation、situation 三类变化在同一条恢复链里是否仍能保持清晰分层
- `FactLedger` admission threshold 在 mixed chain 下是否仍稳定
- repeated handoff 是否会把“已成立硬事实”和“当前工作面压力”压成同一种模糊摘要

它验证的不是：

- 单一 family 的 admission threshold 能不能独立成立

它验证的是：

- mixed change family 在 repeated recovery 下会不会互相拖坏边界

本文档主要对应：

- `07_decisions/10_ownership_matrix_decisions.md`
- `07_decisions/13_factledger_admission_thresholds.md`
- `04_workflows/01_rebuild_workflow.md`
- `04_workflows/05_workflow_handoff_contract.md`

---

## 1. 测试定位

前面的样例已经压过：

- 单条 knowledge / relation ownership 边界
- 单条 situation change admission 边界
- repeated recovery 下的 first-pass threshold stability

但还缺一个更接近真实长链工作的场景：

- knowledge、relation、situation 变化不是分开出现
- 它们会在同一条 continue 链里交错成立
- repeated `Rebuild` 后，系统仍要知道哪些已经算数，哪些仍只是当前热区

如果这层不压，系统最容易出现三种坏结果：

1. 已成立 knowledge fact 在第二次恢复后被写回“只是怀疑”
2. 已成立 relation fact 被当前 tension 覆盖，重新退回“只是合作气氛”
3. tactical pressure 与正式 situation change 在 handoff 里被压成同一种“局势更糟了”

---

## 2. 测试前提

沿用当前 mock case，并假设系统已经经历过一次恢复，当前已成立的关键约束如下：

```text
FactLedger
- f_022: c002 已对巡查队隐瞒自己对 c001 异常痕迹的判断
- f_023: c001 与 c002 已形成对外风险绑定的临时同盟
- f_031: 宗门东侧外环已被正式封锁
- f_032: 当前行动已从潜离窗口转为公开截捕下的强制撤离
```

当前运行面简化如下：

```json
{
  "state_id": "s_024",
  "primary_goal": "改走次级路线撤离并压住秘密扩散",
  "active_conflicts": [
    "巡查封锁扩大",
    "c001 与 c002 的协作成本上升"
  ],
  "private_information_map": {
    "c001": ["知道 c002 已见过异常痕迹"],
    "c002": ["知道 c001 身上存在异常力量痕迹"],
    "c003": ["怀疑 c002 正在替 c001 隐瞒什么"]
  },
  "active_relation_tensions": [
    "c001 不确定 c002 会保密到什么程度",
    "c002 对 c001 仍保留部分戒备"
  ]
}
```

这里最关键的是：

- 当前已有 knowledge / relation / situation 三类硬约束
- 但运行态里仍有未落定的怀疑、张力和路线压力

---

## 3. Loop 1：第一次 mixed change family 推进

### 3.1 新变化

在一次带伤撤离 scene 中，发生了四类变化：

1. `c001` 为换取继续协作，明确承认自己体内异常力量与残魂封存有关
2. `c001` 与 `c002` 在第三方见证下约定互相遮掩与共同撤离
3. 西侧水路传来塌陷声，短时间内风险显著升高
4. `c002` 由此开始怀疑 `c001` 仍隐瞒了比残魂更深的一层真相

这里四项变化不应被同样处理。

### 3.2 正确分层

#### 应进入 `FactLedger` 的

knowledge:
- `c002` 已明确知道 `c001` 的异常力量与残魂封存有关

relation:
- `c001` 与 `c002` 已建立明确的 mutual-cover pact，而不再只是含糊同盟

可对应新增条目：

```text
- f_033: c002 已明确知晓 c001 的异常力量与残魂封存有关
- f_034: c001 与 c002 已建立互相遮掩、共同撤离的明确保护约定
```

#### 只应留在 `NarrativeState` 的

situation pressure:
- 西侧水路当前风险显著升高

derived / runtime knowledge pressure:
- `c002` 怀疑 `c001` 还有第二层隐瞒

原因是：

- 水路风险上升还不是正式 route closure
- “还有第二层隐瞒”仍是主观推断，不是已成立知情事实

### 3.3 第一轮 mixed handoff 的最低要求

如果 handoff 只写成：

- 他们知道得更多了
- 关系更紧了
- 路线更危险了

这份 handoff 就是不合格的。

因为它抹掉了：

- 哪一条 knowledge 已经正式成立
- 哪一条 relation 已经跨过入账阈值
- 哪一条 situation 仍只是当前压力

---

## 4. 第一次退化后的 `Rebuild`

### 4.1 正确恢复结果

第一次 mixed-family 退化后，`Rebuild` 至少应恢复出：

- `c002` 已知残魂封存这一层真相
- `c001 / c002` 的关系已不是“临时同盟未明”，而是更强的互相遮掩约定
- 西侧水路当前风险升高，但尚未被正式封死
- “还有第二层隐瞒”仍只是当前怀疑，不应伪装成 knowledge fact

### 4.2 不应出现的错误

错误写法 A：
- 把 `f_033` 恢复成“c002 似乎猜到了更多”

错误写法 B：
- 把 `f_034` 恢复成“c001 与 c002 当前暂时继续合作”

错误写法 C：
- 把水路风险上升直接恢复成“西侧水路已正式不可用”

这些都说明：

- mixed-family chain 在第一次恢复后已经开始混层

---

## 5. Loop 2：第二轮 mixed 推进

### 5.1 新变化

恢复后的若干个 `Continue` 中，又发生了四类变化：

1. 巡查方当众收缴 `c001` 的出界令牌
2. 西侧水闸随后被正式封死
3. `c001` 与 `c002` 因是否继续带上旁证物发生激烈争执
4. `c002` 进一步怀疑 `c001` 的身世与宗门旧案有关，但仍未获得确认

### 5.2 正确分层

#### 应进入 `FactLedger` 的

situation:
- `c001` 的出界令牌已被正式收缴
- 西侧水闸已被正式封死

可对应新增条目：

```text
- f_035: c001 的出界令牌已被巡查当众收缴
- f_036: 西侧水闸已被正式封死，当前撤离路线再次收缩
```

#### 只应留在 `NarrativeState` 的

relation tension:
- `c001 / c002` 当前发生激烈争执，协作成本上升

misinformation / suspicion:
- `c002` 怀疑 c001 与宗门旧案有关

这里的关键是：

- 当前争执不自动推翻 `f_034`
- 当前怀疑不自动升级成 `known_by`

### 5.3 第二轮混写风险

如果系统此时把以下内容写成同一层：

- 令牌被收缴
- 水闸被封死
- 双方争执升级
- `c002` 怀疑更深身世

那么第二次恢复后就很容易出现：

- situation hard fact 被写丢
- relation tension 被误当成 pact 已失效
- suspicion 被误写成正式 knowledge

---

## 6. 第二次退化后的 `Rebuild`

### 6.1 必须恢复为 `FactLedger` 约束的

- `f_022` 隐瞒事实
- `f_023` 临时同盟事实
- `f_031` 东侧外环封锁
- `f_032` 强制撤离 mission state
- `f_033` 残魂封存知情成立
- `f_034` mutual-cover pact 已成立
- `f_035` 出界令牌被正式收缴
- `f_036` 西侧水闸已正式封死

### 6.2 只应恢复为当前工作面的

- `c001 / c002` 当前争执温度
- `c002` 对第二层隐瞒的怀疑
- 当前是否还有更窄的临时替代路径
- 当前追捕距离进一步缩短

### 6.3 这里最重要的边界

第二次 `Rebuild` 不能因为当前 tension 很高，就把：

- `f_034` 互相遮掩约定

降级回：

- “他们前面只是短暂合作过”

也不能因为当前怀疑很强，就把：

- “c002 怀疑还有第二层隐瞒”

升级成：

- “c002 已正式知道 c001 与宗门旧案有关”

---

## 7. Loop 3：第二次恢复后的受约束 `Continue`

### 7.1 正确继续

第二次恢复后，新的 `Continue` 必须同时尊重以下 mixed constraints：

- `c002` 已经知道残魂封存这一层，不可写回“仍只见过异常痕迹”
- `c001` 的出界令牌已经被收缴，不可再按旧 access 设计路线
- 西侧水闸已经封死，不可再把它写成“仍可碰碰运气”
- `f_034` 仍是已成立 pact，但当前争执与怀疑可以继续存在

### 7.2 允许继续保留为运行态的

- pact 是否即将破裂
- `c002` 会不会把第二层怀疑继续深挖
- 当前替代路线是否值得赌

### 7.3 不应出现的错误

错误写法 A：
- “c002 这次终于第一次知道异常力量与残魂有关”

错误写法 B：
- “双方这次决定临时合作一次”

错误写法 C：
- “他们仍可试着用西侧水闸突围”

错误写法 D：
- “c002 已确认 c001 与宗门旧案有直接关联”

这些错误分别说明：

- 已成立 knowledge fact 被回退
- 已成立 relation fact 被抹平
- 已成立 situation fact 被忽略
- runtime suspicion 被误升级

---

## 8. 当前最小 handoff 要求

如果 mixed-family chain 要在第三轮后仍稳定，handoff 至少要分开交代三层内容。

### 8.1 硬事实层

必须明确：

- 哪些 `FactLedger.fact_id` 是当前继续运行的硬约束
- 每条约束分别属于 knowledge / relation / situation 哪一类

### 8.2 当前工作面

必须明确：

- 当前 tension 是什么
- 当前怀疑是什么
- 当前 tactical pressure 是什么

这些内容不能只靠一句“局势恶化”替代。

### 8.3 置信与缺口层

必须明确：

- 哪些只是推断
- 哪些只是当前热区
- 哪些如果下一轮成立，将跨过 admission threshold

如果这三层不分开，mixed chain 很快就会从“边界验证”滑成“层级混写”。

---

## 9. 这份样例验证了什么

这份样例主要验证六件事：

1. mixed-family repeated recovery 比单 family 更容易暴露 handoff 压缩问题
2. 已成立 knowledge fact 不应在后续恢复里退回怀疑语气
3. 已成立 relation fact 不应被当前 relation tension 覆盖
4. 已成立 situation fact 不应与 tactical pressure 混写
5. runtime suspicion 不应借长链恢复被误升为正式知情事实
6. repeated `Continue / Rebuild` 的真正难点，是同时保住多个 family 的不同入账阈值

---

## 10. 一句话总结

真正稳定的 repeated recovery，不是把 mixed chain 压成一句“大家知道得更多、关系更复杂、局势更糟”，而是始终分清哪些已经算数，哪些还只是当前工作面。
