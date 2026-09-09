# novel 的跨对话接续

2026-09-09 用户明确指出：AGENTS.md 本身不能保证遵循，同类错误应跨项目处理。

结束检查统一放在本机 Codex 用户目录的 `hooks.json` 与 `hooks/continuity.py`，适用于各项目；本仓库不再配置另一组 hooks，避免重复拦截。说明及本地行为检查位于用户目录 `hooks/CONTINUITY.md` 和 `hooks/check_continuity.py`。

本项目只保留以下接续数据：

1. 根 `AGENTS.md`：项目约束与恢复入口。
2. `docs/00_project/55_evidence_first_novel_design.md` §0：当前目标、有效授权、完成条件。
3. `.workspace_local/task_control/CURRENT_TASK.md`：私有产物和实际断点。
4. `.workspace_local/task_control/IMPLEMENTATION_RESULT.md`：本次部署的发现、信任和验证状态，不能视为其他环境的状态。

按用户级 hook 指定的当前 session/turn 文件登记，示例见 `task_state.example.json`；不同项目和会话不共用执行开关。任务状态不是生产资格，资格仍只读 `current_state.json`。

新会话及压缩恢复读取接续数据；已有会话主动重读。其他机器或 worktree 需同步其适用文件，私有材料不入 Git。规则文件、平台发现、信任定义和真实触发分别核实。

复用 [AGENTS.md 指令发现](https://learn.chatgpt.com/docs/agent-configuration/agents-md) 和 [Codex Hooks](https://learn.chatgpt.com/docs/hooks)。关键遗漏：程序无法独立证明模型对目标的理解及完成证据真实；因此检查器不允许把配置存在或状态自报当作可靠性证明。
