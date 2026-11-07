"""Running under Krasnodar/Docker: data-dir override, container health check, and the backup hook."""
import importlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import healthcheck
from santa import backup, runtime

ROOT = Path(__file__).resolve().parent.parent


def paths_with_env(env_extra: dict) -> dict:
    """Import santa.runtime/config in a fresh interpreter with these env vars and report the paths."""
    code = ("import json; from santa import runtime, config, letter; print(json.dumps({"
            "'data': str(runtime.DATA_DIR), 'db': str(config.DB_PATH), 'logs': str(runtime.LOG_DIR), "
            "'heartbeat': str(runtime.HEARTBEAT), 'backup': str(runtime.BACKUP_PATH), "
            "'letter': str(letter.BASE_IMAGE)}))")
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("SANTA_")}
    env.update({"GUILD_ID": "1", "ORGANIZER_ID": "2"}, **env_extra)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return {k: Path(v) for k, v in json.loads(out.stdout).items()}


def test_default_paths_are_the_repo_folder():
    p = paths_with_env({})
    assert p["data"] == ROOT
    assert p["db"] == ROOT / "santa.db"
    assert p["logs"] == ROOT / "logs"
    assert p["heartbeat"] == ROOT / "logs" / "heartbeat.json"
    assert p["letter"] == ROOT / "assets" / "santa-letter.png"


def test_data_and_assets_dirs_from_env(tmp_path):
    p = paths_with_env({"SANTA_DATA_DIR": str(tmp_path / "data"), "SANTA_ASSETS_DIR": str(tmp_path / "data" / "assets")})
    data = tmp_path / "data"
    assert p["data"] == data
    assert p["db"] == data / "santa.db"
    assert p["logs"] == data / "logs"
    assert p["heartbeat"] == data / "logs" / "heartbeat.json"
    assert p["backup"] == data / "backup" / "santa.db"
    assert p["letter"] == data / "assets" / "santa-letter.png"


def test_lock_and_heartbeat_follow_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SANTA_DATA_DIR", str(tmp_path))
    try:
        importlib.reload(runtime)
        lock = runtime.acquire_lock("bot.lock")
        assert lock is not None and (tmp_path / "logs" / "bot.lock").exists()
        assert runtime.is_locked("bot.lock")
        lock.close()
        runtime.write_heartbeat(connected=True)
        assert json.loads((tmp_path / "logs" / "heartbeat.json").read_text())["connected"] is True
    finally:
        monkeypatch.delenv("SANTA_DATA_DIR")
        importlib.reload(runtime)


def write_hb(tmp_path, monkeypatch, age_s=0, **info):
    hb = tmp_path / "heartbeat.json"
    monkeypatch.setattr(runtime, "HEARTBEAT", hb)
    info["time"] = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat(timespec="seconds")
    hb.write_text(json.dumps(info), encoding="utf-8")


def test_container_health(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime, "HEARTBEAT", tmp_path / "missing.json")
    assert healthcheck.container_check() == 1  # no heartbeat yet

    write_hb(tmp_path, monkeypatch, age_s=5, connected=True, ref="abc123")
    assert healthcheck.container_check() == 0
    assert "version=abc123" in capsys.readouterr().out

    write_hb(tmp_path, monkeypatch, age_s=5, connected=False, starting=True)  # left by bot.py at startup
    assert healthcheck.container_check() == 1
    assert "starting up" in capsys.readouterr().out

    write_hb(tmp_path, monkeypatch, age_s=5, connected=False)  # gateway dropped
    assert healthcheck.container_check() == 1

    write_hb(tmp_path, monkeypatch, age_s=healthcheck.CONTAINER_MAX_AGE + 30, connected=True)  # stuck
    assert healthcheck.container_check() == 1
    assert "stale" in capsys.readouterr().out


def make_db(path: Path, rows: int = 50) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO t (v) VALUES (?)", [(f"row {i}",) for i in range(rows)])
    con.commit()
    con.close()


def test_backup_copies_while_db_is_open(tmp_path):
    src = tmp_path / "santa.db"
    make_db(src)
    live = sqlite3.connect(src)  # the bot keeps its connection open
    live.execute("INSERT INTO t (v) VALUES ('uncommitted')")  # ...possibly mid-transaction
    dest = backup.backup(tmp_path / "backup" / "santa.db", source=src)
    live.rollback()
    live.close()
    con = sqlite3.connect(dest)
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    con.close()
    assert not (tmp_path / "backup" / "santa.db.tmp").exists()


def test_backup_replaces_old_copy_and_never_creates_db(tmp_path):
    src = tmp_path / "santa.db"
    with pytest.raises(FileNotFoundError):
        backup.backup(tmp_path / "out.db", source=src)
    assert not src.exists()  # a missing DB stays missing

    make_db(src, rows=3)
    out = tmp_path / "out.db"
    out.write_bytes(b"old junk")
    backup.backup(out, source=src)
    con = sqlite3.connect(out)
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    con.close()


def test_backup_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runtime, "DB_PATH", tmp_path / "santa.db")
    assert backup.main([str(tmp_path / "b.db")]) == 1  # no database yet
    make_db(tmp_path / "santa.db", rows=1)
    assert backup.main([str(tmp_path / "b.db")]) == 0
    out = capsys.readouterr().out
    assert "backup ok" in out and "row" not in out  # sizes only, never contents
