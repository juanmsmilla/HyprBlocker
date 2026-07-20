"""Settings-lock semantics on the settings routes: tightening-only.

While a lock is active, enabling a protection (or raising the watchdog count)
must pass; disabling (or lowering) must 403. Regression for the first-deploy
finding where the daemon booted with default (weakest) settings and the lock
then blocked re-enabling every protection until its 2026 expiry.
"""

import pytest
from fastapi.testclient import TestClient

import daemon.config as config_module
from daemon.api import app
from daemon.api.routes import settings as settings_route


class _StubWatchdogManager:
    """Never touches real processes."""

    def __init__(self, *args, **kwargs):
        pass

    def spawn_watchdogs(self):
        pass

    def signal_shutdown(self):
        pass

    def get_active_watchdogs(self):
        return []


@pytest.fixture
def client(monkeypatch):
    # Fresh config per test (conftest already isolates the config file path).
    monkeypatch.setattr(config_module, "_config", None)
    monkeypatch.setattr(settings_route, "ensure_service_enabled", lambda: None)
    monkeypatch.setattr(settings_route, "WatchdogManager", _StubWatchdogManager)
    return TestClient(app)


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings_route, "is_settings_locked_ntp", lambda: True)


@pytest.fixture
def unlocked(monkeypatch):
    monkeypatch.setattr(settings_route, "is_settings_locked_ntp", lambda: False)


def test_enable_safe_search_passes_while_locked(client, locked):
    resp = client.put("/api/settings/safe-search", json={"enabled": True})
    assert resp.status_code == 200
    assert client.get("/api/settings/safe-search").json()["enabled"] is True


def test_disable_safe_search_rejected_while_locked(client, locked):
    resp = client.put("/api/settings/safe-search", json={"enabled": False})
    assert resp.status_code == 403


def test_enable_browser_enforcement_passes_while_locked(client, locked):
    resp = client.put("/api/settings/browser-enforcement", json={"enabled": True})
    assert resp.status_code == 200


def test_disable_browser_enforcement_rejected_while_locked(client, locked):
    resp = client.put("/api/settings/browser-enforcement", json={"enabled": False})
    assert resp.status_code == 403


def test_enable_shutdown_prevention_passes_while_locked(client, locked):
    resp = client.put("/api/settings/shutdown-prevention", json={"enabled": True})
    assert resp.status_code == 200


def test_disable_shutdown_prevention_rejected_while_locked(client, locked):
    resp = client.put("/api/settings/shutdown-prevention", json={"enabled": False})
    assert resp.status_code == 403


def test_enable_watchdogs_passes_while_locked(client, locked):
    config = config_module.get_config()
    config.security.shutdown_prevention_enabled = True
    resp = client.put("/api/settings/watchdog", json={"enabled": True})
    assert resp.status_code == 200


def test_disable_watchdogs_rejected_while_locked(client, locked):
    config = config_module.get_config()
    config.security.shutdown_prevention_enabled = True
    config.security.watchdog_enabled = True
    resp = client.put("/api/settings/watchdog", json={"enabled": False})
    assert resp.status_code == 403


def test_raise_watchdog_count_passes_while_locked(client, locked):
    config = config_module.get_config()
    config.security.shutdown_prevention_enabled = True
    config.security.watchdog_enabled = True
    config.security.watchdog_count = 3
    resp = client.put("/api/settings/watchdog", json={"count": 5})
    assert resp.status_code == 200
    assert config_module.get_config().security.watchdog_count == 5


def test_lower_watchdog_count_rejected_while_locked(client, locked):
    config = config_module.get_config()
    config.security.shutdown_prevention_enabled = True
    config.security.watchdog_enabled = True
    config.security.watchdog_count = 3
    resp = client.put("/api/settings/watchdog", json={"count": 2})
    assert resp.status_code == 403


def test_disabling_works_when_unlocked(client, unlocked):
    resp = client.put("/api/settings/safe-search", json={"enabled": False})
    assert resp.status_code == 200
    resp = client.put("/api/settings/browser-enforcement", json={"enabled": False})
    assert resp.status_code == 200
