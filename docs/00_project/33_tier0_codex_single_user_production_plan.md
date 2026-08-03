# Tier 0 Codex 单用户生产就绪实施规划

**文档编号**：`docs/00_project/33_tier0_codex_single_user_production_plan.md`  
**目标层级**：Tier 0 —— local staged CLI v0，operator-in-the-loop  
**运行时**：Codex / 类似 CLI 工具，人工写入 response 文件  
**用户模型**：单一用户，本地工作区  
**不实现**：DirectAPI、provider 调用、UI、自动闭环、多用户并发  

---

## 1. 目标与范围

让当前 `novel` CLI 在 Codex 环境中成为可重复、可验证、可发布的内部生产工具。

完成此规划后，项目应达到：

- 任意单次 `novel audit / extend / compose` 都能在 Codex 循环中跑通
- 存在一份通过验证的 Tier 0 release record
- 存在一份通过验证的 canary evidence
- 测试基线被记录为 immutable checkpoint
- 已知限制被显式文档化

---

## 2. 不适用事项（本规划明确不做）

| 事项 | 原因 |
|---|---|
| DirectAPI / provider 调用 | Tier 0 要求 operator 写入 response 文件 |
| 自动 retry / fallback provider | 不允许 |
| UI / Web 界面 | 超出 Tier 0 |
| 多用户并发 | 单用户本地模型 |
| 长文自动完结 | 长期目标，当前 deferred |
| 当前工作区未提交修改的处理 | 用户指示先不管；但实施前需确认 |

---

## 3. 前置条件

1. Python >= 3.11
2. 已安装项目：`pip install -e .`
3. `novel` 命令可用：`novel --help`
4. 工作区干净或已明确当前 modified 文件不影响发布基线
5. 已选择 immutable checkpoint（git tag 或 40 字符 commit hash）

---

## 4. 实施步骤

### 步骤 1：确认测试基线

运行完整测试并记录实际通过的测试数：

```bash
python -m pytest tests/ -q --basetemp .pytest-tmp-tier0-baseline -p no:cacheprovider
```

记录输出中的 `N passed`。本轮已批准的实际基线为 `1571 passed`；后续重跑如果 `N` 不等于 1571，需更新所有文档中的基线数字，并在此规划中注明实际数字。

**决策点**：如果测试失败，停止并报告失败用例，不要继续 canary。

---

### 步骤 2：准备 Canary 工作区

1. 创建临时 canary 输入文件：

```bash
mkdir -p [本地路径]/canary_inputs
```

写入 `[本地路径]/canary_inputs/tier0_canary_input.txt`，内容为一短篇中文小说文本（约 500–2000 字），确保：
- 至少包含一个角色
- 至少包含一个事件
- 不触发 30+ 章 outline 注入（保持短篇）

示例见附录 A。

---

### 步骤 3：执行 Audit Canary

在 Codex 循环中执行以下命令序列：

```bash
cd [本地路径]
novel audit tier0-canary --input [本地路径]/canary_inputs/tier0_canary_input.txt
```

预期输出包含 `[WAITING]` 和 `rebuild_prompt.txt` 路径。

读取 `novels/tier0-canary/output/audit/rebuild_prompt.txt`，用附录 B 的 rebuild response 模板生成响应，保存到：

```bash
[本地路径]/canary_inputs/tier0_rebuild_response.json
```

然后执行：

```bash
novel respond tier0-canary --slot-id rebuild --prompt-hash <rebuild_prompt_hash> --response-file [本地路径]/canary_inputs/tier0_rebuild_response.json --json
```

其中 `<rebuild_prompt_hash>` 从上一个 `[AGENT_ACTION]` 块或 `novel pending tier0-canary --require-automation-ready --json` 中获取。

继续：

```bash
novel resume tier0-canary
```

预期输出包含 `[WAITING]` 和 `review_prompt.txt` 路径。

用附录 C 的 review response 模板生成响应，保存到：

```bash
[本地路径]/canary_inputs/tier0_review_response.json
```

执行：

```bash
novel respond tier0-canary --slot-id review --prompt-hash <review_prompt_hash> --response-file [本地路径]/canary_inputs/tier0_review_response.json --json
novel resume tier0-canary
novel gate tier0-canary --json
```

---

### 步骤 4：验证 Canary 通过标准

`novel gate tier0-canary --json` 必须返回：

```json
{
  "ok": true,
  "review_route": "pass",
  "next_workflow": "ContinueUnit",
  "blocking_pending_count": 0
}
```

`novel pending` 在两次 respond 前必须返回：

- `automation_ready=true`
- `provider_calls_implemented=false`
- `closed_loop_allowed=false`

`novel respond` 两次都必须返回：

- `provider_call_performed=false`
- `closed_loop_advanced=false`
- `materialized_action=materialize_staged_response_only`

**决策点**：任何一项不满足，停止并记录失败命令与输出，不要继续。

---

### 步骤 5：生成 Canary Evidence

```bash
novel-release-record docs/00_project/releases/tier0-canary-evidence.json \
  --expected-baseline <实际测试数> \
  --generate-canary-evidence \
  --release-id tier0-canary-YYYYMMDD \
  --canary-workspace novels/tier0-canary \
  --canary-gate-result docs/00_project/releases/tier0-canary-gate.json \
  --canary-artifact-root [本地路径]
```

其中 `YYYYMMDD` 替换为实际日期。

**要求**：
- `tier0-canary-gate.json` 必须提前保存为 `novel gate tier0-canary --json` 的原始输出
- 不要覆盖已有 evidence 文件

---

### 步骤 6：生成 Release Record

```bash
novel-release-record docs/00_project/releases/tier0-release.json \
  --expected-baseline <实际测试数> \
  --record-path docs/00_project/releases/tier0-release.json \
  --generate \
  --release-id tier0-canary-YYYYMMDD \
  --created-at-utc YYYY-MM-DDTHH:MM:SSZ \
  --release-tag-or-checkpoint <tag-or-40-char-commit> \
  --git-commit <40-char-lowercase-hex-commit> \
  --full-pytest-command "python -m pytest -q --basetemp .pytest-tmp-current-tier0-release-evidence-full -p no:cacheprovider" \
  --canary-evidence docs/00_project/releases/tier0-canary-evidence.json
```

参数说明：

- `<实际测试数>`：步骤 1 记录的通过数
- `<tag-or-40-char-commit>`：immutable checkpoint，建议使用 git tag，如 `v0.1.0-tier0`
- `<40-char-lowercase-hex-commit>`：对应的完整 commit hash
- `--created-at-utc`：UTC 时间，必须与 release-id 中的日期一致

---

### 步骤 7：验证 Release Record

运行单一组合验证命令：

```bash
novel-release-record docs/00_project/releases/tier0-release.json \
  --expected-baseline <实际测试数> \
  --record-path docs/00_project/releases/tier0-release.json \
  --require-evidence-files --evidence-root [本地路径] \
  --require-git-checkpoint --repo-root [本地路径] \
  --canary-evidence docs/00_project/releases/tier0-canary-evidence.json \
  --require-canary-artifacts --canary-artifact-root [本地路径]
```

**验收标准**：命令退出码为 0，输出无 violation。

---

### 步骤 8：更新项目文档

1. 更新 `docs/00_project/03_current_status.md`
   - 添加 Tier 0 完成记录
   - 记录 release record 路径
   - 记录 immutable checkpoint

2. 更新 `docs/00_project/30_production_readiness_checklist.md`
   - 在 "Current production tier" 处确认 `local staged CLI v0`
   - 列出 known limitations（见第 6 节）

3. 更新 `README.md`
   - 在 "Current Phase" 中声明 Tier 0 生产就绪
   - 添加 release record 链接
   - 强调 DirectAPI 未实现、闭环自动化未允许

4. 更新 `AGENTS.md`
   - 同步当前阶段状态

**决策点**：文档更新是否应单独作为一个 commit？建议是的，release record 与代码文档分开提交更清晰。

---

### 步骤 9：创建 Immutable Checkpoint

```bash
git tag -a v0.1.0-tier0 -m "Tier 0 production ready: Codex-native staged CLI"
git push origin v0.1.0-tier0
```

如果没有 remote，至少本地保留 tag。

---

## 5. 验收标准总览

| 检查项 | 通过标准 |
|---|---|
| 完整 pytest | 全部通过，数字记录一致 |
| Audit canary | `novel gate --json` 返回 `ok=true`, `review_route=pass`, `next_workflow=ContinueUnit`, `blocking_pending_count=0` |
| Canary evidence | 通过 `validate_tier0_canary_evidence_artifacts()` |
| Release record | 通过完整组合验证命令 |
| Git checkpoint | tag 指向 release record 中的 commit hash |
| 文档 | current status、checklist、README、AGENTS 已同步 |

---

## 6. 已知限制（必须在文档中声明）

`known_limitations` 必须包含：

- `DirectAPI provider calling is not implemented`
- `closed-loop automation remains disallowed`
- `Tier 0 is not a public product surface`
- `release record does not replace a release tag or immutable checkpoint`
- `response files must be materialized by the operator or Codex; no automatic model call is performed`

---

## 7. 决策点（实施到这里必须停下来问）

| 步骤 | 触发条件 | 需要决定 |
|---|---|---|
| 步骤 1 | 测试数不等于已批准基线 1571 或有失败 | 是否更新基线？是否先修复失败？ |
| 步骤 4 | canary gate 未返回 pass | 是调整 response 模板、修复代码，还是重新定义通过标准？ |
| 步骤 6 | 工作区仍有未提交修改 | 是否要在 dirty 状态下打 tag？（强烈建议不要） |
| 步骤 8 | 文档更新范围 | 是否只更新必要文档，还是同步全部相关 docs？ |

---

## 8. 回滚方案

如果 canary 或 release record 验证失败：

1. 保留失败工作区 `novels/tier0-canary/`，不要删除
2. 保留失败命令的完整 stdout/stderr
3. 回滚到步骤 1 的 clean checkpoint
4. 修改 response 模板或修复代码后重新从步骤 2 开始
5. 不要手动覆盖 `*_response.txt` 或最终产物文件

---

## 附录 A：Canary 输入文本示例

保存到 `[本地路径]/canary_inputs/tier0_canary_input.txt`：

```text
青云宗三年一度的大比前夜，林青独自站在山脚。

三个月前，她被执法长老以"盗窃宗门令牌"的罪名逐出宗门。没人相信她，除了她自己知道，那枚刻着云纹的令牌是某个人在临走前塞进她手里的。

"你若想明白真相，就回来。"那人说。

现在她回来了。山门的灯火通明，弟子们还在演练阵法。林青摸了摸怀中的令牌，冰凉的触感让她冷静下来。

她不能从正门进去。执法长老一定在等她。

后山有一条废弃的石阶，是小时候师兄带她偷偷下山时发现的。她提起衣摆，没入夜色。

第一道关卡是护山阵法。令牌在怀中微微发热，阵法的波纹像没有看见她一样分开了。

林青愣了一下。这枚令牌，比她想象的更危险。
```

---

## 附录 B：Canary Rebuild Response 模板

保存到 `[本地路径]/canary_inputs/tier0_rebuild_response.json`：

```json
{
  "workspec": {
    "genre": "仙侠",
    "subgenre": "宗门成长",
    "audience": "青年读者",
    "theme": "代价",
    "tone": "克制",
    "pacing": "前快中稳后爆",
    "length_target": 50000,
    "constraints": ["主角不无敌", "禁术使用留下痕迹"],
    "romance_weight": 0.2,
    "mystery_weight": 0.4,
    "action_weight": 0.4
  },
  "worldmodel": {
    "world_facts": ["宗门以灵根定资质", "青云宗三年一度大比"],
    "social_structure": "宗门-王城-世家三方制衡",
    "power_system": "灵根等级制",
    "resource_system": "灵石与功法",
    "geography": "东荒大陆",
    "factions": ["青云宗"],
    "time_rules": ["宗门大比三年一次"],
    "prohibitions": ["王城内禁止斗法"],
    "consequence_logic": ["禁术使用留下可追踪痕迹"]
  },
  "charactermodels": [
    {
      "character_id": "c001",
      "name": "林青",
      "identity": "被逐出宗门的少女",
      "outer_goal": "重返宗门并揭露陷害真相",
      "inner_need": "证明自己值得被信任",
      "fear": "再次被抛弃",
      "flaw": "冲动",
      "strength": "意志坚定",
      "stance": "中立",
      "knowledge_state": ["令牌在她手中"],
      "misinformation": [],
      "relations": {}
    }
  ],
  "narrativestate": {
    "state_id": "s001",
    "current_time": "宗门大比前夜",
    "current_location": "青云宗山脚",
    "active_characters": ["c001"],
    "current_situation": "主角被逐出宗门，准备潜入大比现场",
    "primary_goal": "揭露陷害真相",
    "active_conflicts": ["与宗门执法长老的冲突"],
    "emotional_temperature": "压抑",
    "public_information": ["宗门大比即将开始"],
    "hidden_information": ["令牌在主角手中"],
    "active_suspense_items": ["令牌真正的来历"],
    "current_goals": ["重返宗门"],
    "linked_open_threads": ["t001"],
    "current_facts_in_scope": ["f001"]
  },
  "factledger": {
    "entries": [
      {
        "fact_id": "f001",
        "statement": "令牌归c001所有",
        "fact_type": "object",
        "involved_entities": ["c001", "令牌"],
        "confirmed": true
      }
    ]
  },
  "foreshadowgraph": {
    "entries": [
      {
        "thread_id": "t001",
        "setup_point": "第一章末尾神秘人影",
        "content": "主角身世之谜",
        "visibility_level": "implicit",
        "expected_payoff": "大比现场揭晓",
        "current_status": "active",
        "linked_characters": ["c001"],
        "linked_facts": ["f001"],
        "linked_plotunits": []
      }
    ]
  },
  "confidence_gaps": ["令牌具体来历尚不明确", "塞令牌的人身份未确认"]
}
```

---

## 附录 C：Canary Review Response 模板

保存到 `[本地路径]/canary_inputs/tier0_review_response.json`：

```json
{
  "issues": [],
  "reminders": [],
  "route": "pass"
}
```

---

## 附录 D：预期 Canary 工作区结构

验证时 `novels/tier0-canary/` 下应包含：

```text
novels/tier0-canary/
├── input/
│   └── tier0_canary_input.txt
├── output/
│   └── audit/
│       ├── rebuild_prompt.txt
│       ├── rebuild_response.txt
│       ├── review_prompt.txt
│       ├── review_response.txt
│       ├── rebuild_package.json
│       ├── review_result.json
│       ├── audit_report.json
│       └── route_handoff.json
└── ...
```

---

## 附录 E：实施前最终检查清单

- [ ] 已确认当前目标为 Tier 0，不使用 DirectAPI
- [ ] 已记录实际 pytest 通过数
- [ ] 已准备 canary 输入文本
- [ ] 已准备 rebuild / review response 模板
- [ ] 已创建 `docs/00_project/releases/` 目录（如不存在）
- [ ] 已确认 immutable checkpoint 可用
- [ ] 已决定文档更新策略

---

## 备注

- 本规划假设当前代码与文档一致。如果实施时发现 `novel-release-record` 命令参数或输出格式与本文档不一致，应停下来更新本文档而非绕过。
- 所有日期、hash、commit、测试数均需替换为实际值，不能保留模板占位符。
