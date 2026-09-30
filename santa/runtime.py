"""Keeping the bot alive: log files, a single-instance lock, and a heartbeat for health checks."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
HEARTBEAT = LOG_DIR / "heartbeat.json"

# exit code bot.py uses when another copy is already running
EXIT_ALREADY_RUNNING = 3


def file_handler(name: str) -> logging.Handler:
    LOG_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOG_DIR / name, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", "%Y-%m-%d %H:%M:%S", "{"))
    return handler


def has_console() -> bool:
    return sys.stderr is not None and hasattr(sys.stderr, "write")


class _DropVoiceWarnings(logging.Filter):
    def filter(self, record):  # the bot doesn't do voice; these warnings are noise
        return "voice will NOT be supported" not in record.getMessage()


def quiet_voice_warnings() -> None:
    logging.getLogger("discord.client").addFilter(_DropVoiceWarnings())


def acquire_lock(name: str):
    """Hold an exclusive lock on logs/<name> for as long as the returned file stays open.
    Returns None if another process already holds it."""
    LOG_DIR.mkdir(exist_ok=True)
    f = open(LOG_DIR / name, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def is_locked(name: str) -> bool:
    f = acquire_lock(name)
    if f is None:
        return True
    f.close()
    return False


def write_heartbeat(**info) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    info["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    tmp.replace(HEARTBEAT)


def read_heartbeat() -> dict | None:
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
