"""Make a consistent copy of santa.db while the bot keeps running.

    python -m santa.backup [destination]     default: SANTA_DATA_DIR/backup/santa.db

Uses SQLite's online backup API, so it's safe mid-write. The copy is written next to the destination first and
then swapped in, so a half-finished backup never replaces a good one. Prints only sizes, never any contents
(the database holds the secret draw).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from . import runtime


def backup(dest: Path | str, source: Path | str | None = None) -> Path:
    source = Path(source or runtime.DB_PATH)
    dest = Path(dest)
    if not source.exists():
        raise FileNotFoundError(f"no database at {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)

    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)  # never creates an empty DB
    try:
        out = sqlite3.connect(tmp)
        try:
            src.backup(out)
            ok = out.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            out.close()
    finally:
        src.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"backup failed its integrity check: {ok}")
    os.replace(tmp, dest)
    return dest


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: python -m santa.backup [destination]", file=sys.stderr)
        return 2
    dest = Path(argv[0]) if argv else runtime.BACKUP_PATH
    try:
        done = backup(dest)
    except (OSError, sqlite3.Error, RuntimeError) as e:
        print(f"backup FAILED: {e}", file=sys.stderr)
        return 1
    print(f"backup ok: {runtime.DB_PATH} -> {done} ({done.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
