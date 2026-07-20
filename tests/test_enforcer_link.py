"""Tests for enforcer-liveness mesh gating (daemon.enforcer_link, review R6)."""

import json
from datetime import UTC, datetime, timedelta

from daemon import enforcer_link, paths


def _write_state(monkeypatch, tmp_path, *, updated_at, boot_id="test-boot"):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    monkeypatch.setattr(enforcer_link, "_current_boot_id", lambda: boot_id)
    paths.enforcer_state_path().write_text(
        json.dumps({"written_at": updated_at, "boot_id": boot_id})
    )


def test_enforcer_alive_when_fresh(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    _write_state(monkeypatch, tmp_path, updated_at=now.isoformat())
    assert enforcer_link.enforcer_alive(now) is True


def test_enforcer_dead_when_stale(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    old = (now - timedelta(seconds=enforcer_link.ENFORCER_STALE_SECONDS + 60)).isoformat()
    _write_state(monkeypatch, tmp_path, updated_at=old)
    assert enforcer_link.enforcer_alive(now) is False


def test_enforcer_dead_on_cross_boot_snapshot(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    # Snapshot claims a different boot_id than the current boot → treat as dead.
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    monkeypatch.setattr(enforcer_link, "_current_boot_id", lambda: "boot-NOW")
    paths.enforcer_state_path().write_text(
        json.dumps({"written_at": now.isoformat(), "boot_id": "boot-PREVIOUS"})
    )
    assert enforcer_link.enforcer_alive(now) is False


def test_enforcer_dead_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    monkeypatch.setattr(enforcer_link, "_current_boot_id", lambda: "b")
    assert enforcer_link.enforcer_alive() is False


def test_mesh_off_when_toggles_off(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert enforcer_link.should_run_watchdog_mesh(False, True) is False
    assert enforcer_link.should_run_watchdog_mesh(True, False) is False


def test_mesh_on_in_user_layout(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert enforcer_link.should_run_watchdog_mesh(True, True) is True


def test_mesh_is_fallback_in_root_layout(monkeypatch, tmp_path):
    now = datetime.now(UTC)
    # Enforcer alive → mesh stays OFF (enforcer supersedes it).
    _write_state(monkeypatch, tmp_path, updated_at=now.isoformat())
    assert enforcer_link.should_run_watchdog_mesh(True, True) is False


def test_mesh_spawns_when_enforcer_down_in_root_layout(monkeypatch, tmp_path):
    # No enforcer snapshot → enforcer looks down → mesh runs as fallback (no regression).
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    monkeypatch.setattr(enforcer_link, "_current_boot_id", lambda: "b")
    assert enforcer_link.should_run_watchdog_mesh(True, True) is True
