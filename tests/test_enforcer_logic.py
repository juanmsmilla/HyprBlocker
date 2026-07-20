"""Tests for the enforcer's pure decision logic (enforcer.logic).

Covers the R7 fail-closed kill matrix and the tighten-now/loosen-later
asymmetry for lock and enforcement-policy change requests.
"""

from datetime import UTC, datetime, timedelta

from daemon.enforcement_policy import EnforcementPolicy
from enforcer import logic
from enforcer.logic import (
    ChangeAction,
    GraceWindows,
    HeartbeatObservation,
    classify_lock_change,
    classify_policy_change,
    classify_request,
    kill_decision,
    should_kill_browsers,
)

BOOT = "aaaa-bbbb"
GRACE = GraceWindows(boot_grace_seconds=300.0, login_grace_seconds=120.0)


def _decide(**overrides):
    """kill_decision with a baseline that would kill (stale heartbeat, session
    up, enforcement on, all grace windows expired) — tests override one axis."""
    args = dict(
        now_monotonic=10_000.0,
        boot_id=BOOT,
        last_heartbeat=HeartbeatObservation(monotonic=5_000.0, boot_id=BOOT),
        session_present=True,
        session_started_monotonic=1_000.0,
        intended_enforcement_on=True,
        grace=GRACE,
        stale_after_seconds=90.0,
    )
    args.update(overrides)
    return kill_decision(**args)


# ---------------------------------------------------------------------------
# R7 kill matrix
# ---------------------------------------------------------------------------

def test_stale_heartbeat_with_session_and_enforcement_kills():
    d = _decide()
    assert d.kill is True
    assert "stale" in d.reason


def test_fresh_heartbeat_does_not_kill():
    d = _decide(last_heartbeat=HeartbeatObservation(monotonic=9_950.0, boot_id=BOOT))
    assert d.kill is False


def test_enforcement_intentionally_off_never_kills():
    d = _decide(intended_enforcement_on=False)
    assert d.kill is False
    assert "intentionally off" in d.reason


def test_no_session_never_kills():
    assert _decide(session_present=False).kill is False


def test_post_boot_grace_suppresses_kill():
    # monotonic counts from boot: 100s after boot is inside the 300s window.
    d = _decide(now_monotonic=100.0, session_started_monotonic=None)
    assert d.kill is False
    assert "post-boot" in d.reason


def test_post_login_grace_suppresses_kill():
    d = _decide(session_started_monotonic=9_950.0)  # session appeared 50s ago
    assert d.kill is False
    assert "post-login" in d.reason


def test_never_seen_heartbeat_kills_after_grace():
    d = _decide(last_heartbeat=None)
    assert d.kill is True
    assert "no verified heartbeat" in d.reason


def test_cross_boot_heartbeat_counts_as_stale():
    d = _decide(last_heartbeat=HeartbeatObservation(monotonic=9_999.0, boot_id="other"))
    assert d.kill is True
    assert "different boot" in d.reason


def test_negative_delta_counts_as_stale():
    # A heartbeat claiming a monotonic time in the enforcer's future is bogus.
    d = _decide(last_heartbeat=HeartbeatObservation(monotonic=99_999.0, boot_id=BOOT))
    assert d.kill is True


def test_boolean_wrapper_matches_decision():
    assert (
        should_kill_browsers(10_000.0, BOOT, None, True, True, GRACE)
        is True
    )
    assert (
        should_kill_browsers(10_000.0, BOOT, None, False, True, GRACE)
        is False
    )


# ---------------------------------------------------------------------------
# Lock asymmetry
# ---------------------------------------------------------------------------

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def test_extending_lock_applies_now():
    assert (
        classify_lock_change(NOW + timedelta(days=10), NOW + timedelta(days=30))
        is ChangeAction.APPLY_NOW
    )


def test_creating_lock_from_unlocked_applies_now():
    assert classify_lock_change(None, NOW + timedelta(days=1)) is ChangeAction.APPLY_NOW


def test_shortening_lock_is_delayed():
    assert (
        classify_lock_change(NOW + timedelta(days=30), NOW + timedelta(days=1))
        is ChangeAction.DELAY
    )


def test_clearing_lock_is_delayed():
    assert classify_lock_change(NOW + timedelta(days=30), None) is ChangeAction.DELAY


def test_clearing_nothing_is_a_noop_apply():
    assert classify_lock_change(None, None) is ChangeAction.APPLY_NOW


def test_identical_expiry_applies_now():
    until = NOW + timedelta(days=5)
    assert classify_lock_change(until, until) is ChangeAction.APPLY_NOW


def test_naive_and_aware_datetimes_compare_without_crashing():
    naive = datetime(2026, 12, 1)  # treated as UTC
    aware = datetime(2026, 8, 1, tzinfo=UTC)
    assert classify_lock_change(aware, naive) is ChangeAction.APPLY_NOW


# ---------------------------------------------------------------------------
# Policy asymmetry
# ---------------------------------------------------------------------------

def _policy(**overrides):
    return EnforcementPolicy(**{**EnforcementPolicy().__dict__, **overrides})


def test_enabling_toggle_applies_now():
    cur = _policy(shutdown_prevention_enabled=False)
    req = _policy(shutdown_prevention_enabled=True)
    assert classify_policy_change(cur, req) is ChangeAction.APPLY_NOW


def test_disabling_toggle_is_delayed():
    cur = _policy(browser_enforcement_enabled=True)
    req = _policy(browser_enforcement_enabled=False)
    assert classify_policy_change(cur, req) is ChangeAction.DELAY


def test_adding_browser_applies_now():
    cur = _policy(browsers=["firefox"])
    req = _policy(browsers=["firefox", "ladybird"])
    assert classify_policy_change(cur, req) is ChangeAction.APPLY_NOW


def test_removing_browser_is_delayed():
    cur = _policy(browsers=["firefox", "chromium"])
    req = _policy(browsers=["firefox"])
    assert classify_policy_change(cur, req) is ChangeAction.DELAY


def test_faster_heartbeat_applies_now_slower_is_delayed():
    cur = _policy(heartbeat_interval_seconds=30)
    assert (
        classify_policy_change(cur, _policy(heartbeat_interval_seconds=10))
        is ChangeAction.APPLY_NOW
    )
    assert (
        classify_policy_change(cur, _policy(heartbeat_interval_seconds=60))
        is ChangeAction.DELAY
    )


def test_mixed_request_with_any_loosening_field_is_delayed():
    # Tightens one toggle but sneaks in a kill-list removal → whole thing delays.
    cur = _policy(browsers=["firefox", "chromium"], watchdog_enabled=False)
    req = _policy(browsers=["firefox"], watchdog_enabled=True)
    assert classify_policy_change(cur, req) is ChangeAction.DELAY


def test_more_watchdogs_applies_now_fewer_is_delayed():
    cur = _policy(watchdog_count=3)
    assert classify_policy_change(cur, _policy(watchdog_count=5)) is ChangeAction.APPLY_NOW
    assert classify_policy_change(cur, _policy(watchdog_count=1)) is ChangeAction.DELAY


# ---------------------------------------------------------------------------
# Raw request classification
# ---------------------------------------------------------------------------

def test_classify_request_lock_shapes():
    cur = NOW + timedelta(days=30)
    tighten = {"type": "lock", "locked_until": (NOW + timedelta(days=60)).isoformat()}
    loosen = {"type": "lock", "locked_until": None}
    assert classify_request(tighten, cur, _policy()).action is ChangeAction.APPLY_NOW
    assert classify_request(loosen, cur, _policy()).action is ChangeAction.DELAY


def test_classify_request_policy_shape():
    req = {"type": "policy", "policy": {"browser_enforcement_enabled": False}}
    verdict = classify_request(req, None, _policy(browser_enforcement_enabled=True))
    assert verdict.action is ChangeAction.DELAY
    assert "browser_enforcement_enabled" in verdict.loosened_fields


def test_classify_request_malformed_sets_error():
    assert classify_request({"type": "lock", "locked_until": "not-a-date"}, None, _policy()).error
    assert classify_request({"type": "policy"}, None, _policy()).error
    assert classify_request({"type": "frobnicate"}, None, _policy()).error


def test_default_loosen_delay_is_within_spec_band():
    assert 24.0 <= logic.DEFAULT_LOOSEN_DELAY_HOURS <= 48.0
