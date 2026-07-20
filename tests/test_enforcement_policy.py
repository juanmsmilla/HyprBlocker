"""Tests for daemon.enforcement_policy (root-owned enforcement settings, R3)."""

import json

from daemon import enforcement_policy as ep


def test_user_layout_reads_from_config(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    pol = ep.load_policy()
    # Defaults come from config; browsers list is non-empty.
    assert isinstance(pol.browsers, list) and pol.browsers
    assert isinstance(pol.browser_enforcement_enabled, bool)


def test_root_layout_reads_secure_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    secure = tmp_path / "secure"
    secure.mkdir()
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(secure))
    (secure / "enforcement.json").write_text(
        json.dumps(
            {
                "browsers": ["firefox"],
                "browser_enforcement_enabled": True,
                "shutdown_prevention_enabled": True,
                "watchdog_enabled": False,
                "watchdog_count": 3,
                "heartbeat_interval_seconds": 30,
            }
        )
    )
    pol = ep.load_policy()
    assert pol.browsers == ["firefox"]
    assert pol.shutdown_prevention_enabled is True


def test_root_layout_missing_file_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    secure = tmp_path / "secure"
    secure.mkdir()
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(secure))
    # No enforcement.json → falls back to config-derived defaults, does not crash.
    pol = ep.load_policy()
    assert pol.browsers


def test_root_layout_ignores_unknown_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    secure = tmp_path / "secure"
    secure.mkdir()
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(secure))
    (secure / "enforcement.json").write_text(
        json.dumps({"browsers": ["chromium"], "bogus_field": 1})
    )
    pol = ep.load_policy()
    assert pol.browsers == ["chromium"]


def test_write_then_read_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    secure = tmp_path / "secure"
    secure.mkdir()
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(secure))
    pol = ep.EnforcementPolicy(browsers=["opera"], watchdog_count=5)
    ep.write_policy(pol)
    got = ep.load_policy()
    assert got.browsers == ["opera"]
    assert got.watchdog_count == 5
