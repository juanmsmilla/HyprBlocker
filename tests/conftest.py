"""Shared pytest fixtures.

The most important thing here is the autouse ``_isolate_state`` fixture: it
points every ``HYPRBLOCKER_*`` path override at a throwaway temp directory and
forces the ``user`` layout, so no test can read or write the real daemon state
(``~/.config/hyprblocker`` or ``/var/lib/hyprblocker``) even if a code path
accidentally calls ``get_config`` / ``get_database_path``. Combined with the
existing ``:memory:`` SQLite engines and monkeypatched singletons, the suite
stays fully isolated from the live daemon on this machine.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Redirect all daemon state to a temp dir for the duration of each test."""
    state = tmp_path / "state"
    secure = state / "secure"
    logs = state / "logs"
    for d in (state, secure, logs):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(state))
    monkeypatch.setenv("HYPRBLOCKER_CONFIG_DIR", str(state))
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(secure))
    monkeypatch.setenv("HYPRBLOCKER_LOG_DIR", str(logs))
    monkeypatch.setenv("HYPRBLOCKER_CODE_ROOT", str(tmp_path / "code"))
    yield


def make_block(**overrides):
    """Build a lightweight stand-in for a Block ORM row.

    Pure-logic tests (blocker, scheduler, lock manager) only touch attributes,
    never the database, so a ``SimpleNamespace`` with sensible defaults is enough.
    Override any field via keyword.
    """
    defaults = dict(
        id=1,
        name="test",
        block_mode="always",
        block_days_of_week=None,
        block_start_time=None,
        block_end_time=None,
        lock_mode="none",
        lock_days_of_week=None,
        lock_start_time=None,
        lock_end_time=None,
        lock_until=None,
        websites_blocked=None,
        websites_allowed=None,
        websites_media_blocked=None,
        apps_blocked=None,
        apps_allowed=None,
        enabled=True,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class StubTimeVerifier:
    """A TimeVerifier stand-in returning a fixed, controllable time."""

    def __init__(self, now=None, valid=True):
        from datetime import datetime

        self._now = now or datetime.now()
        self._valid = valid
        self._ntp_time = self._now

    def get_verified_time(self):
        return self._now

    def get_ntp_time(self):
        return self._ntp_time if self._valid else None

    def is_system_time_valid(self):
        return self._valid

    def verify_at_lock_transitions(self):
        return self._valid

    def set_now(self, now):
        self._now = now
