"""Keeps the bot running: starts bot.py and restarts it if it ever stops.

install_autostart.ps1 sets Windows up to launch this (hidden, with pythonw) when you log in.
Logs: logs/supervisor.log (starts/restarts) and logs/santa.log (the bot itself).
"""
import logging
import os
import subprocess
import sys
import time

from santa import runtime

log = logging.getLogger("supervisor")


def main():
    logging.basicConfig(level=logging.INFO, handlers=[runtime.file_handler("supervisor.log")])
    lock = runtime.acquire_lock("supervisor.lock")
    if lock is None:
        log.info("Another supervisor is already running; exiting.")
        return

    python = sys.executable  # the venv's pythonw/python that launched us
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backoff = 5
    log.info("Supervisor started (pid %s)", os.getpid())
    while True:
        started = time.monotonic()
        log.info("Starting bot")
        with open(runtime.LOG_DIR / "bot-console.log", "a", encoding="utf-8") as console:
            code = subprocess.call([python, str(runtime.ROOT / "bot.py")], cwd=runtime.ROOT,
                                   stdout=console, stderr=console, creationflags=flags)
        ran = time.monotonic() - started
        if code == runtime.EXIT_ALREADY_RUNNING:
            log.info("Bot is already running outside the supervisor (e.g. start.bat); checking again in 60s")
            time.sleep(60)
            continue
        # quick crash loops back off up to 5 minutes; a long healthy run resets it
        backoff = 5 if ran > 300 else min(backoff * 2, 300)
        log.warning("Bot stopped (exit code %s) after %.0fs; restarting in %ss", code, ran, backoff)
        time.sleep(backoff)


if __name__ == "__main__":
    main()
