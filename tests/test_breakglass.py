"""Tests for the standalone break-glass runner (enforcer.breakglass_runner).

The runner is deliberately dumb: a pure delay decision plus a tiny file state
machine. Tests drive ``run_once`` with explicit ``now`` values (never sleeping)
against the conftest-isolated tmp state dirs.
"""

import json
import os

from daemon import paths
from enforcer import breakglass_runner as bg

HOUR = 3600.0
T0 = 1_800_000_000.0  # arbitrary epoch base


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------

def test_default_delay_is_within_spec_band():
    assert 24.0 <= bg.DEFAULT_DELAY_HOURS <= 48.0
    assert bg.DEFAULT_DELAY_HOURS == 36.0


def test_clamp_delay_hours():
    assert bg.clamp_delay_hours(36.0) == 36.0
    assert bg.clamp_delay_hours(1.0) == 24.0  # too short → floor
    assert bg.clamp_delay_hours(1000.0) == 48.0  # too long → ceiling


def test_should_release_boundaries():
    assert bg.should_release(T0, T0 + 36 * HOUR - 1, 36.0) is False
    assert bg.should_release(T0, T0 + 36 * HOUR, 36.0) is True
    assert bg.should_release(T0, T0 + 37 * HOUR, 36.0) is True


def test_should_release_clamps_tiny_delay():
    # A corrupt/hostile delay of 0h must still wait the 24h floor.
    assert bg.should_release(T0, T0 + 1 * HOUR, 0.0) is False
    assert bg.should_release(T0, T0 + 24 * HOUR, 0.0) is True


def test_should_release_future_request_never_releases():
    assert bg.should_release(T0 + 999 * HOUR, T0, 36.0) is False


def test_should_release_is_deterministic():
    args = (T0, T0 + 40 * HOUR, 36.0)
    assert bg.should_release(*args) is bg.should_release(*args) is True


# ---------------------------------------------------------------------------
# run_once state machine (files under the conftest-isolated tmp dirs)
# ---------------------------------------------------------------------------

def _touch_trigger():
    trigger = bg.trigger_path()
    trigger.parent.mkdir(parents=True, exist_ok=True)
    trigger.write_text("")
    return trigger


def test_idle_without_trigger():
    assert bg.run_once(now=T0) == "idle"
    assert not paths.breakglass_path().exists()


def test_trigger_recorded_then_pending_then_released():
    _touch_trigger()
    assert bg.run_once(now=T0) == "recorded"

    state = json.loads(paths.breakglass_path().read_text())
    assert state["requested_at"] == T0
    assert state["released"] is False

    assert bg.run_once(now=T0 + 1 * HOUR) == "pending"
    assert bg.run_once(now=T0 + 36 * HOUR - 1) == "pending"
    assert bg.run_once(now=T0 + 36 * HOUR) == "released"

    state = json.loads(paths.breakglass_path().read_text())
    assert state["released"] is True
    # Released ⇒ lock cleared and trigger consumed.
    lock = json.loads(paths.lock_path().read_text())
    assert lock["locked_until"] is None
    assert not bg.trigger_path().exists()

    assert bg.run_once(now=T0 + 40 * HOUR) == "already-released"


def test_noncancelable_after_recording():
    """Once recorded in root-owned breakglass.json, deleting the trigger file
    does NOT cancel the release — a wedged/hostile apparatus cannot trap the
    user by racing the trigger away (R5)."""
    trigger = _touch_trigger()
    assert bg.run_once(now=T0) == "recorded"
    trigger.unlink()
    assert bg.run_once(now=T0 + 1) == "pending"
    assert bg.run_once(now=T0 + 36 * HOUR) == "released"


def test_backdated_trigger_mtime_does_not_shorten_delay():
    """The trigger's mtime is user-settable, so the runner must time the delay
    from first observation (now), never from the mtime."""
    trigger = _touch_trigger()
    ancient = T0 - 1000 * HOUR
    os.utime(trigger, (ancient, ancient))
    assert bg.run_once(now=T0) == "recorded"
    # If mtime had been trusted, this would already release:
    assert bg.run_once(now=T0 + 1 * HOUR) == "pending"


def test_release_exposes_existing_credential():
    credential = paths.root_credential_path()
    credential.parent.mkdir(parents=True, exist_ok=True)
    credential.write_text("s3cret")
    credential.chmod(0o600)

    _touch_trigger()
    bg.run_once(now=T0)
    assert bg.run_once(now=T0 + 48 * HOUR) == "released"
    assert credential.stat().st_mode & 0o777 == 0o644


def test_release_without_credential_still_clears_lock():
    # Dev mode: no credential file exists; the lock must still be cleared.
    _touch_trigger()
    bg.run_once(now=T0)
    assert bg.run_once(now=T0 + 48 * HOUR) == "released"
    assert json.loads(paths.lock_path().read_text())["locked_until"] is None


def test_corrupt_state_file_is_treated_as_fresh():
    paths.breakglass_path().parent.mkdir(parents=True, exist_ok=True)
    paths.breakglass_path().write_text("{ not json")
    assert bg.run_once(now=T0) == "idle"


def test_runner_imports_nothing_from_the_enforcer_package():
    """R5: the break-glass runner must survive an enforcer bug, so it may not
    import enforcer.logic / heartbeat / proc_scan / main (stdlib + daemon.paths
    only). Inspect its actual module dependencies."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(bg))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {m for m in imported if m.startswith("enforcer")}
    assert not forbidden, f"breakglass_runner must not import {forbidden}"
    daemon_imports = {m for m in imported if m.startswith("daemon")}
    assert daemon_imports <= {"daemon", "daemon.paths"}, daemon_imports
