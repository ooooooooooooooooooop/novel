"""Devin end-of-turn check (port of ~/.codex/hooks/continuity.py).

Events: SessionStart / UserPromptSubmit / Stop.
Per-prompt task file under .workspace_local/task_control/devin_continuity/.

Stop blocks turn end when mode=execute still has authorized unfinished work,
or when intent was never registered. mode=answer/analysis/paused requires
disposition_reason. Blocked state needs blocker text and empty next_action.
Local files only; no model calls.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


def token(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def read_json(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def state_root():
    proj = os.environ.get("DEVIN_PROJECT_DIR") or os.getcwd()
    return Path(proj) / ".workspace_local" / "task_control" / "devin_continuity"


def task_path(folder, prompt_id):
    return folder / (token(prompt_id) + ".task.json")


def context(event, path):
    return {"hookSpecificOutput": {
        "hookEventName": event["hook_event_name"],
        "additionalContext": (
            "Devin 结束检查已触发。最新用户输入优先；执行中的补充问题默认不取消"
            "原任务，回答后继续；仅明确暂停、取消或要求先分析才改模式。"
            f"当前 session_id={event['session_id']}，prompt_id={event.get('prompt_id', '')}。"
            f"结束前在 {path.as_posix()} 登记本次请求；普通问答 mode=answer，"
            "分析 mode=analysis，用户暂停 mode=paused；填写 disposition_reason 说明依据。"
            "执行用 mode=execute，并填写 objective、authorization_source、"
            "completion_conditions（criterion/evidence）、remaining_actions、next_action、blocker。"
            "仍有已授权可执行工作就直接继续，禁止靠改标模式、清空事项、虚填证据"
            "或把下一步做成『要不要继续』式问句来通过。"
            "等后台进程属于 blocker（写明等什么+恢复条件），不算完成。"
        )}}


def incomplete(task):
    mode = task.get("mode")
    if mode in {"answer", "analysis", "paused"}:
        return None if has_text(task.get("disposition_reason")) else "请记录本次问答、分析或暂停的用户依据。"
    if mode != "execute":
        return "尚未登记本次请求意图；先区分执行、问答、分析或用户暂停，不自动恢复旧任务。"
    if not has_text(task.get("objective")) or not has_text(task.get("authorization_source")):
        return "执行目标或授权来源缺失；从已有对话恢复，不自行编造或重复索取已获授权。"
    conditions, remaining = task.get("completion_conditions"), task.get("remaining_actions")
    if not isinstance(conditions, list) or not conditions or not isinstance(remaining, list):
        return "执行记录缺少逐项完成条件或剩余工作列表。"
    if any(not isinstance(c, dict) or not has_text(c.get("criterion")) for c in conditions):
        return "完成条件格式不完整。"
    if any(not has_text(item) for item in remaining):
        return "剩余工作须逐项写明，不能使用空白占位。"
    if has_text(task.get("blocker")) and not task.get("next_action"):
        return None
    if remaining or task.get("next_action"):
        return "本次执行仍有未完成工作。下一步：" + str(task.get("next_action") or remaining[0])
    if any(not has_text(c.get("evidence")) for c in conditions):
        return "完成条件尚缺证据；完成必要工作并记录证据，不能只把剩余事项清空。"
    return None


def handle(event, root):
    if not isinstance(event, dict):
        raise ValueError("Expected an event object")
    name = event.get("hook_event_name")
    sid, pid = event.get("session_id"), event.get("prompt_id")
    if not sid:
        return {"systemMessage": "结束检查未生效：事件缺少 session_id。"}
    folder = root / token(sid)
    folder.mkdir(parents=True, exist_ok=True)
    request_file = folder / "request.json"
    request = read_json(request_file)
    path = task_path(folder, pid) if pid else folder / "request.json"
    result, decision = {}, "allow"

    if name == "SessionStart":
        result = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": (
            "Devin 持续执行检查已加载；先从项目交接文件恢复目标、授权和断点。"
            "最新用户意图优先。规则文件不是执行保证；最终答复前有独立的本地状态检查。"
            f"本会话状态目录：{folder.as_posix()}。"
        )}}
    elif name == "UserPromptSubmit":
        if not pid:
            return {"systemMessage": "结束检查未生效：UserPromptSubmit 缺少 prompt_id。"}
        is_continuation = (request.get("continuation_pending") is True
                           and event.get("prompt") == request.get("continuation_reason"))
        if is_continuation:
            previous = read_json(task_path(folder, request.get("prompt_id")))
            previous.update(session_id=sid, prompt_id=pid)
            write_json(path, previous)
            request.update(prompt_id=pid, continuation_pending=False)
        else:
            previous_path = task_path(folder, request.get("prompt_id")) if request.get("prompt_id") else None
            if previous_path and previous_path.exists() and previous_path == path:
                saved_previous = path.with_suffix(".before_prompt.json")
                write_json(saved_previous, read_json(previous_path))
                previous_path = saved_previous
            request = {"prompt_id": pid, "cwd": event.get("cwd")}
            write_json(path, {"session_id": sid, "prompt_id": pid,
                              "mode": "unclassified", "disposition_reason": "",
                              "previous_task_file": str(previous_path) if previous_path else None})
        write_json(request_file, request)
        result = context(event, path)
    elif name == "Stop":
        disable = root / "DISABLE"
        if event.get("stop_hook_active"):
            # 本轮已是 stop-hook 强制续行——再拦会让用户无法中止会话
            decision = "hook_continuation"
        elif disable.exists() or (folder / "DISABLE").exists():
            decision = "disabled"
        elif not pid or not request:
            decision = "unarmed"
            result = {"systemMessage": "结束检查未生效：未收到本轮 UserPromptSubmit 登记事件。"}
        elif request.get("prompt_id") != pid:
            decision = "inactive_or_superseded"
        elif request.get("blocked_once") == pid:
            # 同一 prompt 已拦过一次：用户再次停止必须放行（用户终止优先）
            decision = "user_abort"
        else:
            task = read_json(path)
            problem = ("当前任务记录缺失或不属于本次请求，请恢复正确记录。"
                       if task.get("session_id") != sid or task.get("prompt_id") != pid
                       else incomplete(task))
            if problem:
                progress = {k: task.get(k) for k in (
                    "mode", "disposition_reason", "objective", "authorization_source",
                    "completion_conditions", "remaining_actions", "next_action", "blocker")}
                digest = token(json.dumps(progress, sort_keys=True, ensure_ascii=False))
                if request.get("last_block_digest") == digest:
                    decision = "no_progress"
                    result = {"systemMessage": (
                        "结束检查发现续行后任务记录仍无变化，已停止重复补发以避免空转。"
                        "任务未被确认完成；需报告未解决问题，不能把此警告当作完成证据。")}
                else:
                    decision = "block"
                    reason = ("[Devin continuity check] " + problem
                              + f" 当前状态文件：{path.as_posix()}。"
                              + "只继续本次已授权工作；用户的分析、暂停或新范围优先。"
                              + "若用户要求停止，立即停下。")
                    request.update(last_block_digest=digest, continuation_reason=reason,
                                   continuation_pending=True, blocked_once=pid)
                    write_json(request_file, request)
                    result = {"decision": "block", "reason": reason}
    record = {"time": datetime.now(timezone.utc).isoformat(), "event": name,
              "prompt_id": pid, "decision": decision}
    with (folder / "events.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return result


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        result = handle(json.load(sys.stdin), state_root())
    except (ValueError, OSError, TypeError, KeyError, IndexError) as error:
        result = {"systemMessage": "结束检查未生效，未安排续行：" + type(error).__name__}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
