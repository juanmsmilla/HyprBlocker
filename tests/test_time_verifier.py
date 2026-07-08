"""Tests for NTP time verification with a fake NTP client (no network).

The security property under test: lock transitions must FAIL CLOSED. If NTP
is unreachable at a lock transition and there is no recent successful
verification, the verifier reports failure (which the daemon treats as
"keep blocking"), never success.
"""

import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import ntplib
import pytest

import daemon.time_verifier as time_verifier_module
from daemon.time_verifier import TimeVerifier


class FakeNTPClient:
    """Scripted stand-in for ntplib.NTPClient.

    `behaviors` maps server name -> either an exception to raise or an
    offset in seconds to apply to the real current time.
    """

    def __init__(self, behaviors):
        self.behaviors = behaviors
        self.requested = []

    def request(self, server, timeout=None):
        self.requested.append(server)
        behavior = self.behaviors[server]
        if isinstance(behavior, Exception):
            raise behavior
        return SimpleNamespace(tx_time=time.time() + behavior)


@pytest.fixture
def fake_config(monkeypatch):
    servers = ["ntp-a.test", "ntp-b.test"]
    config = SimpleNamespace(
        security=SimpleNamespace(ntp_servers=servers, max_time_diff_seconds=300)
    )
    monkeypatch.setattr(time_verifier_module, "get_config", lambda: config)
    return config


def make_verifier(behaviors):
    verifier = TimeVerifier()
    verifier._ntp_client = FakeNTPClient(behaviors)
    return verifier


class TestGetNtpTime:
    def test_returns_time_from_first_server(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 0, "ntp-b.test": 0})
        ntp_time = verifier.get_ntp_time()
        assert ntp_time is not None
        assert abs((ntp_time - datetime.now(UTC)).total_seconds()) < 5
        assert verifier._ntp_client.requested == ["ntp-a.test"]

    def test_falls_back_to_next_server_on_failure(self, fake_config):
        verifier = make_verifier(
            {"ntp-a.test": ntplib.NTPException("boom"), "ntp-b.test": 0}
        )
        assert verifier.get_ntp_time() is not None
        assert verifier._ntp_client.requested == ["ntp-a.test", "ntp-b.test"]

    def test_returns_none_when_all_servers_fail(self, fake_config):
        verifier = make_verifier(
            {"ntp-a.test": TimeoutError(), "ntp-b.test": OSError("network down")}
        )
        assert verifier.get_ntp_time() is None


class TestIsSystemTimeValid:
    def test_valid_when_clock_matches_ntp(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 0, "ntp-b.test": 0})
        assert verifier.is_system_time_valid() is True
        assert verifier._last_verified is not None

    def test_invalid_when_clock_differs_beyond_threshold(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 3600, "ntp-b.test": 3600})
        assert verifier.is_system_time_valid() is False

    def test_trusts_system_time_when_ntp_unreachable(self, fake_config):
        """Ordinary checks fail open (network down is not proof of cheating)."""
        verifier = make_verifier(
            {"ntp-a.test": OSError(), "ntp-b.test": OSError()}
        )
        assert verifier.is_system_time_valid() is True
        # ...but it does NOT count as a successful verification
        assert verifier._last_verified is None


class TestVerifyAtLockTransitions:
    def test_passes_when_clock_matches_ntp(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 0, "ntp-b.test": 0})
        assert verifier.verify_at_lock_transitions() is True

    def test_detects_manipulation_and_poisons_cache(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 3600, "ntp-b.test": 3600})
        assert verifier.verify_at_lock_transitions() is False
        assert verifier._cached_valid is False

    def test_fails_closed_when_ntp_down_and_no_recent_verification(self, fake_config):
        verifier = make_verifier(
            {"ntp-a.test": OSError(), "ntp-b.test": OSError()}
        )
        assert verifier.verify_at_lock_transitions() is False

    def test_uses_cached_result_when_ntp_down_but_recently_verified(self, fake_config):
        verifier = make_verifier(
            {"ntp-a.test": OSError(), "ntp-b.test": OSError()}
        )
        verifier._last_verified = datetime.now(UTC) - timedelta(seconds=60)
        verifier._cached_valid = True
        assert verifier.verify_at_lock_transitions() is True

    def test_ignores_stale_cached_verification(self, fake_config):
        verifier = make_verifier(
            {"ntp-a.test": OSError(), "ntp-b.test": OSError()}
        )
        verifier._last_verified = datetime.now(UTC) - timedelta(seconds=600)
        verifier._cached_valid = True
        assert verifier.verify_at_lock_transitions() is False


class TestGetVerifiedTime:
    def test_verifies_on_first_call_and_returns_local_time(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 0, "ntp-b.test": 0})
        result = verifier.get_verified_time()
        assert abs((result - datetime.now()).total_seconds()) < 5
        assert verifier._ntp_client.requested == ["ntp-a.test"]

    def test_skips_ntp_when_recently_verified(self, fake_config):
        verifier = make_verifier({"ntp-a.test": 0, "ntp-b.test": 0})
        verifier._last_verified = datetime.now(UTC)
        verifier.get_verified_time()
        assert verifier._ntp_client.requested == []
