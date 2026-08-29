"""S6 canary 看门狗：监控 driver 存活与推进，driver 崩溃/卡死时自动重启。

纯监控脚本，不改 driver 逻辑。看门狗自己 Popen 启动 driver（持有 pid），
每 60s 检查一次：
- 已提交章数变化（推进判定）
- 最新 calls 文件 mtime（卡死判定：正常时每 60s 一个 calls；失败冷却 600s；
  超过 STALL_MINUTES 无 calls = A1 子进程挂起或 driver 死）
- driver 进程存活
异常时 taskkill /T 清理进程树并重启 driver。3 个 genre 依次跑完 90 章后退出。

启动：python scripts/s6_watchdog.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
DRIVER = str(REPO / "scripts" / "s6_canary_driver.py")
RUN_DIR = REPO / "runtime" / "refs" / "cpa_active"
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
STALL_MINUTES = 30  # 超过该时长无 calls 视为卡死（> 冷却 10 分钟 + 缓冲）
CHECK_INTERVAL = 60
# 子进程标志：DETACHED_PROCESS 让 driver 脱离看门狗控制台/父进程，看门狗退出
# 后 driver 继续运行（不随看门狗死）。
DETACHED = 0x00000008
PROCESS_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | DETACHED


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
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


def start_driver(genre: str) -> subprocess.Popen:
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
    dlog = open(DRIVER_LOG, "a", encoding="utf-8", buffering=1)
    proc = subprocess.Popen(
        cmd, cwd=str(REPO), env=env,
        stdout=dlog, stderr=subprocess.STDOUT,
        creationflags=PROCESS_FLAGS,
    )
    log(f"启动 driver: genre={genre} pid={proc.pid}")
    return proc


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, timeout=20,
        )
        log(f"已 kill driver 进程树 pid={proc.pid}")
    except Exception as exc:  # noqa: BLE001
        log(f"kill driver 失败: {exc}")


def supervise_genre(genre: str) -> None:
    while committed_count(genre) < CHAPTERS:
        committed = committed_count(genre)
        log(f"[{genre}] committed={committed}/{CHAPTERS} 开始监督")
        proc = start_driver(genre)
        last_commit = committed
        last_mtime = latest_call_mtime(genre)
        while True:
            time.sleep(CHECK_INTERVAL)
            try:
                cc = committed_count(genre)
                if cc >= CHAPTERS:
                    log(f"[{genre}] 完成 {cc}/{CHAPTERS}")
                    break
                mtime = latest_call_mtime(genre)
                if cc > last_commit:
                    log(f"[{genre}] 新提交 {cc}/{CHAPTERS}")
                    last_commit = cc
                if proc.poll() is not None:
                    log(f"[{genre}] driver 退出 rc={proc.returncode}，重启")
                    kill_tree(proc)
                    break
                if mtime and time.time() - mtime > STALL_MINUTES * 60:
                    stall = (time.time() - mtime) / 60
                    log(f"[{genre}] 卡死（calls 无变化 {stall:.0f} 分钟），kill+重启")
                    kill_tree(proc)
                    break
                if mtime != last_mtime:
                    last_mtime = mtime
            except Exception as exc:  # noqa: BLE001
                log(f"监督循环异常（继续）: {type(exc).__name__}: {exc}")


def main() -> int:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log("=== 看门狗启动 ===")
    try:
        for genre in GENRES:
            supervise_genre(genre)
        log("=== 看门狗完成：3 genre 90 章全部提交 ===")
    except BaseException as exc:  # 看门狗自身永不静默退出
        log(f"看门狗异常: {type(exc).__name__}: {exc}")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
