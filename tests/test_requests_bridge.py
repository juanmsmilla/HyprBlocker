"""Tests for the user daemon → enforcer request drop (daemon.requests_bridge)."""

import json

from daemon import paths, requests_bridge


def test_build_lock_request_set():
    req = requests_bridge.build_lock_request("2026-09-03T00:00:00+00:00")
    assert req["type"] == "lock"
    assert req["locked_until"] == "2026-09-03T00:00:00+00:00"
    assert "id" in req and "requested_at" in req


def test_build_lock_request_clear():
    req = requests_bridge.build_lock_request(None)
    assert req["type"] == "lock"
    assert req["locked_until"] is None


def test_drop_request_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path))
    payload = requests_bridge.build_lock_request("2026-09-03T00:00:00+00:00")
    path = requests_bridge.drop_request(payload)
    assert path.exists()
    assert path.parent == paths.requests_dir() / "settings"
    on_disk = json.loads(path.read_text())
    assert on_disk["locked_until"] == "2026-09-03T00:00:00+00:00"


def test_drop_request_atomic_no_tmp_left(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path))
    requests_bridge.drop_request(requests_bridge.build_lock_request(None))
    leftovers = list((paths.requests_dir() / "settings").glob("*.tmp"))
    assert leftovers == []
