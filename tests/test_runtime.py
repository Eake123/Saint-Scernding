from santa import runtime


def test_single_instance_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "LOG_DIR", tmp_path)
    first = runtime.acquire_lock("x.lock")
    assert first is not None
    assert runtime.acquire_lock("x.lock") is None
    assert runtime.is_locked("x.lock")
    first.close()
    assert not runtime.is_locked("x.lock")


def test_heartbeat_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "LOG_DIR", tmp_path)
    monkeypatch.setattr(runtime, "HEARTBEAT", tmp_path / "heartbeat.json")
    assert runtime.read_heartbeat() is None
    runtime.write_heartbeat(connected=True, phase="signup")
    hb = runtime.read_heartbeat()
    assert hb["connected"] is True and hb["phase"] == "signup" and "time" in hb
