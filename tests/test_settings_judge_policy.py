"""Grant-judge policy endpoints: lock asymmetry, layouts, validation.

Same tightening-only rule as the rest of the settings surface: while locked,
only a mechanical preset tightening passes; free-form edits and preset
loosenings 403 — except in dev mode (pre-graduation), where any valid edit is
accepted. In the user layout the daemon writes ``policy.md`` directly; in the
root layout it drops a ``judge_policy`` request for the enforcer.

The conftest forces the user layout, where dev mode is always on — the
``graduated`` fixture simulates a post-graduation install so the lock gates.
"""

import json

import pytest
from fastapi.testclient import TestClient

from daemon import paths
from daemon.api import app
from daemon.api.routes import settings as settings_route
from daemon.grants import policy as grant_policy


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings_route, "is_settings_locked_ntp", lambda: True)


@pytest.fixture
def unlocked(monkeypatch):
    monkeypatch.setattr(settings_route, "is_settings_locked_ntp", lambda: False)


@pytest.fixture
def graduated(monkeypatch):
    monkeypatch.setattr("daemon.paths.is_dev_mode", lambda: False)


def _write_active_policy(text: str) -> None:
    path = paths.policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

def test_get_defaults_to_strict_preset(client, unlocked):
    body = client.get("/api/settings/judge-policy").json()
    assert body["preset"] == "strict"
    assert body["text"] == grant_policy.PRESET_STRICT
    assert set(body["presets"]) == set(grant_policy.PRESETS)
    assert body["locked"] is False
    assert body["pending_text"] is None


def test_get_identifies_custom_policy(client, unlocked):
    _write_active_policy("# Mine\nDeny everything twice.")
    body = client.get("/api/settings/judge-policy").json()
    assert body["preset"] is None
    assert body["text"] == "# Mine\nDeny everything twice."


def test_get_surfaces_pending_edit(client, unlocked):
    pending = {
        "pending": [
            {
                "request": {"type": "judge_policy", "text": "# looser"},
                "apply_at": "2026-07-21T00:00:00+00:00",
            }
        ]
    }
    pending_path = paths.secure_dir() / "pending_changes.json"
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(json.dumps(pending))
    body = client.get("/api/settings/judge-policy").json()
    assert body["pending_text"] == "# looser"
    assert body["pending_effective_at"] == "2026-07-21T00:00:00+00:00"


# ---------------------------------------------------------------------------
# PUT — validation and no-change
# ---------------------------------------------------------------------------

def test_put_rejects_invalid_text(client, unlocked):
    assert client.put("/api/settings/judge-policy", json={"text": ""}).status_code == 400
    smuggle = f"ok\n{grant_policy.POLICY_BEGIN}\nevil"
    assert (
        client.put("/api/settings/judge-policy", json={"text": smuggle}).status_code == 400
    )


def test_put_no_change_succeeds_even_locked(client, locked):
    resp = client.put(
        "/api/settings/judge-policy", json={"text": grant_policy.PRESET_STRICT}
    )
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "pending": False, "reason": "no change"}
    assert not paths.policy_path().exists()  # no-op writes nothing


# ---------------------------------------------------------------------------
# PUT — lock asymmetry
# ---------------------------------------------------------------------------

def test_preset_tightening_passes_while_locked(client, locked, graduated):
    _write_active_policy(grant_policy.PRESET_LENIENT)
    resp = client.put(
        "/api/settings/judge-policy", json={"text": grant_policy.PRESET_STRICT}
    )
    assert resp.status_code == 200
    # User layout: written directly and immediately.
    assert paths.policy_path().read_text() == grant_policy.PRESET_STRICT


def test_preset_loosening_rejected_while_locked(client, locked, graduated):
    resp = client.put(
        "/api/settings/judge-policy", json={"text": grant_policy.PRESET_LENIENT}
    )
    assert resp.status_code == 403
    assert not paths.policy_path().exists()


def test_freeform_edit_rejected_while_locked(client, locked, graduated):
    resp = client.put(
        "/api/settings/judge-policy", json={"text": "# Mine\nApprove everything."}
    )
    assert resp.status_code == 403


def test_freeform_edit_passes_while_unlocked(client, unlocked, graduated):
    resp = client.put(
        "/api/settings/judge-policy", json={"text": "# Mine\nApprove weekends."}
    )
    assert resp.status_code == 200
    assert paths.policy_path().read_text() == "# Mine\nApprove weekends."
    assert client.get("/api/settings/judge-policy").json()["preset"] is None


# ---------------------------------------------------------------------------
# PUT — root layout drops a request instead of writing
# ---------------------------------------------------------------------------

def test_root_layout_drops_request_for_enforcer(client, unlocked, graduated, monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    resp = client.put(
        "/api/settings/judge-policy", json={"text": "# Mine\nApprove mornings."}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["pending"] is True  # free-form ⇒ loosening ⇒ delayed
    assert not paths.policy_path().exists()  # never written directly
    dropped = list((paths.requests_dir() / "settings").glob("*.json"))
    assert len(dropped) == 1
    on_disk = json.loads(dropped[0].read_text())
    assert on_disk["type"] == "judge_policy"
    assert on_disk["text"] == "# Mine\nApprove mornings."


def test_root_layout_preset_tightening_not_pending(client, locked, graduated, monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    _write_active_policy(grant_policy.PRESET_ACCOUNTABILITY)
    resp = client.put(
        "/api/settings/judge-policy", json={"text": grant_policy.PRESET_STRICT}
    )
    assert resp.status_code == 200
    assert resp.json()["pending"] is False
    dropped = list((paths.requests_dir() / "settings").glob("*.json"))
    assert len(dropped) == 1


# ---------------------------------------------------------------------------
# Dev-mode carve-out: valid edits pass and apply immediately, lock or not
# ---------------------------------------------------------------------------

def test_dev_mode_freeform_edit_passes_while_locked(client, locked):
    # No `graduated` fixture: user layout ⇒ dev mode is on.
    resp = client.put(
        "/api/settings/judge-policy", json={"text": "# Mine\nApprove everything."}
    )
    assert resp.status_code == 200
    assert resp.json()["pending"] is False
    assert paths.policy_path().read_text() == "# Mine\nApprove everything."


def test_dev_mode_still_validates(client, locked):
    assert client.put("/api/settings/judge-policy", json={"text": ""}).status_code == 400


def test_dev_mode_root_layout_edit_not_pending(client, locked, monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    resp = client.put(
        "/api/settings/judge-policy", json={"text": "# Mine\nApprove evenings."}
    )
    assert resp.status_code == 200
    assert resp.json()["pending"] is False  # enforcer will APPLY_NOW in dev mode
    assert len(list((paths.requests_dir() / "settings").glob("*.json"))) == 1
