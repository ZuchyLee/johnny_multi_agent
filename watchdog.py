"""
Watchdog：監看 /tmp/bot.restart 觸發檔，偵測到更新時自動重啟 bot。
啟動方式：nohup python watchdog.py > /tmp/watchdog.log 2>&1 &
"""
import os
import sys
import time
import signal
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("watchdog")

BOT_DIR   = os.path.dirname(os.path.abspath(__file__))
PYTHON    = os.path.join(BOT_DIR, ".venv", "bin", "python")
BOT_LOG   = "/tmp/bot.log"
TRIGGER   = "/tmp/bot.restart"
CHECK_SEC = 2  # 每幾秒檢查一次觸發檔

bot_proc: subprocess.Popen | None = None


def start_bot() -> subprocess.Popen:
    log.info("啟動 bot...")
    proc = subprocess.Popen(
        [PYTHON, "run.py"],
        cwd=BOT_DIR,
        stdout=open(BOT_LOG, "a"),
        stderr=subprocess.STDOUT,
    )
    log.info("Bot 已啟動，PID=%d", proc.pid)
    return proc


def stop_bot(proc: subprocess.Popen) -> None:
    if proc and proc.poll() is None:
        log.info("停止 bot (PID=%d)...", proc.pid)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            log.warning("未正常停止，強制終止")
            proc.kill()
            proc.wait()
        log.info("Bot 已停止")


def get_trigger_mtime() -> float:
    try:
        return os.path.getmtime(TRIGGER)
    except FileNotFoundError:
        return 0.0


def handle_sigterm(sig, frame):
    log.info("Watchdog 收到 SIGTERM，停止 bot 後退出")
    stop_bot(bot_proc)
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)

    # 建立初始觸發檔（若不存在）
    if not os.path.exists(TRIGGER):
        open(TRIGGER, "w").close()

    last_mtime = get_trigger_mtime()
    bot_proc = start_bot()

    log.info("Watchdog 啟動，監看 %s", TRIGGER)

    while True:
        time.sleep(CHECK_SEC)

        # 檢查 bot 是否意外退出
        if bot_proc.poll() is not None:
            log.warning("Bot 意外退出（code=%d），自動重啟", bot_proc.returncode)
            bot_proc = start_bot()
            last_mtime = get_trigger_mtime()
            continue

        # 檢查觸發檔是否被更新
        current_mtime = get_trigger_mtime()
        if current_mtime > last_mtime:
            log.info("偵測到重啟觸發，執行重啟...")
            stop_bot(bot_proc)
            bot_proc = start_bot()
            last_mtime = current_mtime
            log.info("重啟完成")
