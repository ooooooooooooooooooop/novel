# State V2 Integration Callgraph — BEFORE（b366390 工作树实测）

日期：2026-09-12。来源：源码调用方扫描，非设计文档推断。

## 模块 × 调用方分层

| 模块 | 关键接口 | production caller | research-only caller | no caller |
|---|---|---|---|---|
| `object_state/statemodel.py` | `StateModel` / `ThreadState` / `CompressionLevel` / `Provenance` | — | `state_selection_probe` | — |
| `workflow_action/candidate_pool.py` | `build_candidate_pool(sm, work_preference, reader_knowledge)` → `CandidatePool`（无触发线程→`excluded_alive`，ARCHIVED 跳过） | — | `state_selection_probe` | — |
| `workflow_action/narrative_selector.py` | `select_candidates(pool, sm, work_preferences, max_selected)` → `SelectionResult`（selected/background/dormant/rejected）；`suppress_overreach(sel)`（只删，命中 6 类模式→background） | — | `state_selection_probe` | — |
| `workflow_action/context_firewall.py` | `build_chapter_packet(selection, canon_required, scene_character_knowledge, necessary_relations, behavior_constraints, allowed_reveals, work_organization, chapter)` → `ChapterPacket.render()` | — | `state_selection_probe` | — |
| `workflow_action/state_maintainer.py` | `update_from_plotunit(sm, plotunit, new_state, chapter)` 确定性增量；`build_maintenance_prompt`/`apply_maintenance_response` LLM 质性层（本轮不用） | — | — | **无调用方** |
| `workflow_action/state_pivot.py` | `suspend_thread` / `reenter_thread` / `archive_thread` / `merge_threads` | — | — | **无调用方** |
| `workflow_action/state_validation.py` | `strategy_horizon_score` / `offscreen_survival_check` / `world_background_check` / `build_survival_probe` | — | — | **无调用方**（`chapter_composition` 引用其一） |
| `workflow_action/chapter_composition.py` | `build_chapter_composition(sm,…)` / `build_composition_from_selection` | — | — | **无调用方** |
| `object_state/human_eval.py` `BlindedChapterPacket` | 人评盲化包 | `novel_cli.py`（`novel blind-*` 人评入口） | — | — |

## 生产续写链实际形态（`extend_short_form.py`）

```text
committed_orchestration_state / Rebuild 产物 / excerpt
  → ContinueUnit.build_prompt（packet_context 槽位存在但生产调用未传）
  → staged prompt/response（模型自报 new_state，无独立状态维护环节）
  → review → prose → commit → build_committed_orchestration_transition
```

- State V2 全链在生产中**零接入**：`packet_context` 是现成注入槽位但没人用。
- "状态更新" = 模型在 continue 响应里输出 `new_state` 被解析提交；没有线程池/压缩/触发判定的确定性维护。
- `multi_proposals` 分支另走 `load_orchestration_context` 进 proposal prompt（不在单候选主路径）。

## 含义

"State V2 vs legacy" 不是"有状态 vs 无状态"：legacy 已有 committed orchestration ledger 回灌。接入的是**选择性线程状态闭环**（选→写→确定性更新→验证→提交→下章再选）。
