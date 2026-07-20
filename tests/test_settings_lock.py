"""Tests for the consolidated settings-lock reader (daemon.settings_lock)."""

import json
from datetime import UTC, datetime, timedelta

from daemon import paths, settings_lock


def _write_user_config(lock_until):
    cfg = paths.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"security": {"settings_lock_until": lock_until}}))


def _write_root_lock(lock_until):
    lock = paths.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"locked_until": lock_until}))


def test_no_lock_returns_none(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert settings_lock.read_lock_until() is None
    assert settings_lock.is_settings_locked() is False


def test_user_layout_reads_config(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    _write_user_config(future)
    got = settings_lock.read_lock_until()
    assert got is not None


def test_root_layout_reads_secure_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "secure"))
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    _write_root_lock(future)
    got = settings_lock.read_lock_until()
    assert got is not None


def test_fails_closed_when_ntp_down_and_locked(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    _write_user_config(future)
    # NTP returns None (network down) → must report locked.
    monkeypatch.setattr(settings_lock, "_ntp_now", lambda: None)
    assert settings_lock.is_settings_locked(verify_ntp=True) is True


def test_no_network_call_when_unlocked(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")

    def boom():
        raise AssertionError("NTP must not be queried when no lock is recorded")

    monkeypatch.setattr(settings_lock, "_ntp_now", boom)
    assert settings_lock.is_settings_locked(verify_ntp=True) is False


def test_ntp_verified_expiry(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _write_user_config(past)
    # NTP time is "now"; lock is in the past → unlocked.
    monkeypatch.setattr(settings_lock, "_ntp_now", lambda: datetime.now(UTC))
    assert settings_lock.is_settings_locked(verify_ntp=True) is False


def test_ntp_still_before_expiry(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    _write_user_config(future)
    monkeypatch.setattr(settings_lock, "_ntp_now", lambda: datetime.now(UTC))
    assert settings_lock.is_settings_locked(verify_ntp=True) is True


def test_corrupt_config_is_treated_as_unlocked(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    cfg = paths.config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{ not json")
    assert settings_lock.read_lock_until() is None


def test_root_corrupt_lock_fails_closed(monkeypatch, tmp_path):
    # Review: a corrupt root lock.json must NOT read as unlocked.
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "secure"))
    lock = paths.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("{ corrupt not json")
    assert settings_lock.is_settings_locked(verify_ntp=False) is True


def test_root_missing_key_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "secure"))
    lock = paths.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"something_else": 1}))
    assert settings_lock.is_settings_locked(verify_ntp=False) is True


def test_root_explicit_unlock_is_not_corrupt(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "secure"))
    lock = paths.lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"locked_until": None}))
    assert settings_lock.is_settings_locked(verify_ntp=False) is False


def test_root_no_lock_file_is_unlocked(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "secure"))
    (tmp_path / "secure").mkdir(parents=True, exist_ok=True)
    assert settings_lock.is_settings_locked(verify_ntp=False) is False


def test_verify_ntp_false_uses_system_clock(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    _write_user_config(future)
    assert settings_lock.is_settings_locked(verify_ntp=False) is True
