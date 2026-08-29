"""S6 canary 看门狗检查脚本（单次运行，由 schtasks 每 1 分钟调度）。

不常驻——每次运行检查并修复后退出：
1. driver 在跑（状态文件记录 pid + 存活）→ 检查卡死，卡死则 kill+重启
2. driver 不在跑 且 目标未完成 → 启动 driver（DETACHED，脱离本脚本生命周期）
3. 当前 genre 完成 30 章 → 切换下一 genre；90 章全绿 → 停止

启动 driver 用 DETACHED_PROCESS：本脚本退出后 driver 继续运行。
本脚本由 Windows Task Scheduler 调度，完全独立于 DSH 会话（会话结束不影响）。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
DRIVER = str(REPO / "scripts" / "s6_canary_driver.py")
RUN_DIR = REPO / "runtime" / "refs" / "cpa_active"
STATE = RUN_DIR / "watchdog_state.json"
LOG = RUN_DIR / "watchdog.log"
DRIVER_LOG = RUN_DIR / "driver_run.log"

GENRES = ["offdom", "mythic", "hist"]
NOVELS = {
    "offdom": "s6-canary-offdom",
    "mythic": "s6-canary-mythic",
    "hist": "s6-canary-hist",
}
CHAPTERS = 30
MAX_ATTEMPTS = 10
COOLDOWN = 600
STALL_MINUTES = 35  # calls 无变化超过该时长视为卡死（> 冷却 10 分钟 + 缓冲）
DETACHED = 0x00000008
PROCESS_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | DETACHED


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_state() -> dict:
    try:
        if STATE.exists():
            return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {"genre": "offdom", "driver_pid": None}


def write_state(st: dict) -> None:
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def committed_count(genre: str) -> int:
    ch_dir = REPO / "novels" / NOVELS[genre] / "chapters"
    if not ch_dir.exists():
        return 0
    return len(list(ch_dir.glob("chapter_*.txt")))


def latest_call_mtime(genre: str) -> float:
    out = REPO / "novels" / NOVELS[genre] / "output"
    if not out.exists():
        return 0.0
    times: list[float] = []
    for run in out.iterdir():
        if not run.is_dir():
            continue
        calls = run / "calls"
        if calls.exists():
            times.extend(p.stat().st_mtime for p in calls.glob("*.json"))
    return max(times) if times else 0.0


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限访问


def kill_driver(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=20,
        )
        log(f"已 kill driver 进程树 pid={pid}")
    except Exception as exc:  # noqa: BLE001
        log(f"kill driver 失败: {exc}")


def start_driver(genre: str) -> None:
    env = os.environ.copy()
    env["CPA_BASE_URL"] = "http://127.0.0.1:8317"
    env["CPA_AUTH_TOKEN"] = "123456"
    env["NOVEL_PROVIDER_MIN_INTERVAL"] = "60"
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        PY, DRIVER,
        "--genre", genre,
        "--chapters", str(CHAPTERS),
        "--max-attempts", str(MAX_ATTEMPTS),
        "--cooldown", str(COOLDOWN),
    ]
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        dlog = open(DRIVER_LOG, "a", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            cmd, cwd=str(REPO), env=env,
            stdout=dlog, stderr=subprocess.STDOUT,
            creationflags=PROCESS_FLAGS,
        )
        st = read_state()
        st["driver_pid"] = proc.pid
        write_state(st)
        log(f"启动 driver: genre={genre} pid={proc.pid}")
    except Exception as exc:  # noqa: BLE001
        log(f"启动 driver 失败: {type(exc).__name__}: {exc}")


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    st = read_state()
    genre = st.get("genre", "offdom")
    cc = committed_count(genre)

    # genre 完成 → 切换或收尾
    if cc >= CHAPTERS:
        idx = GENRES.index(genre) if genre in GENRES else 0
        if idx + 1 < len(GENRES):
            genre = GENRES[idx + 1]
            st["genre"] = genre
            st["driver_pid"] = None
            write_state(st)
            log(f"[{genre}] 前 genre 完成，切换到 {genre}")
            cc = committed_count(genre)
        else:
            log(f"全部完成：90 章（{genre} 达 {cc}）")
            return

    pid = st.get("driver_pid")
    mtime = latest_call_mtime(genre)

    if pid and pid_alive(pid):
        # driver 在跑：检查卡死
        if mtime and time.time() - mtime > STALL_MINUTES * 60:
            stall = (time.time() - mtime) / 60
            log(f"[{genre}] 卡死（calls 无变化 {stall:.0f} 分钟），kill+重启")
            kill_driver(pid)
            st["driver_pid"] = None
            write_state(st)
            start_driver(genre)
        return

    # driver 不在跑
    if cc < CHAPTERS:
        log(f"[{genre}] driver 不在运行，启动（committed={cc}/{CHAPTERS}）")
        start_driver(genre)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # noqa: BLE001
        log(f"检查脚本异常: {type(exc).__name__}: {exc}")
