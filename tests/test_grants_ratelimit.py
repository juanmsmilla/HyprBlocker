"""Tests for grant rate limiting (daemon.grants.ratelimit) and the audit
parsing helpers it consumes (daemon.grants.audit — pure + tmp-file I/O)."""

import json
from datetime import UTC, datetime, timedelta

from daemon.grants import audit, ratelimit
from daemon.grants.models import GrantRequest, GrantTier, Verdict

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _request_entry(hours_ago=0.0, tier=1, kind="request"):
    return {"kind": kind, "ts": (NOW - timedelta(hours=hours_ago)).isoformat(), "tier": tier}


class TestCounting:
    def test_empty_log_is_zero(self):
        assert ratelimit.count_recent_requests([], NOW) == 0

    def test_counts_requests_in_window(self):
        entries = [_request_entry(1), _request_entry(5), _request_entry(23)]
        assert ratelimit.count_recent_requests(entries, NOW) == 3

    def test_old_entries_ignored(self):
        entries = [_request_entry(25), _request_entry(48), _request_entry(1)]
        assert ratelimit.count_recent_requests(entries, NOW) == 1

    def test_non_request_kinds_ignored(self):
        entries = [_request_entry(1, kind="decision"), _request_entry(1)]
        assert ratelimit.count_recent_requests(entries, NOW) == 1

    def test_missing_or_corrupt_ts_counts_fail_closed(self):
        entries = [{"kind": "request"}, {"kind": "request", "ts": "not-a-date"}]
        assert ratelimit.count_recent_requests(entries, NOW) == 2

    def test_tier_filter(self):
        entries = [_request_entry(1, tier=1), _request_entry(1, tier=3)]
        assert ratelimit.count_recent_requests(entries, NOW, tier=GrantTier.BLOCK_EXCEPTION) == 1
        assert ratelimit.count_recent_requests(entries, NOW, tier=GrantTier.ROOT_COMMAND) == 1

    def test_naive_timestamps_treated_as_utc(self):
        naive = (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
        assert ratelimit.count_recent_requests([{"kind": "request", "ts": naive}], NOW) == 1


class TestBudget:
    def test_under_limit_allowed(self):
        entries = [_request_entry(1)] * (ratelimit.DEFAULT_DAILY_LIMIT - 1)
        status = ratelimit.check(entries, NOW)
        assert status.allowed is True
        assert status.remaining == 1
        assert ratelimit.is_rate_limited(entries, NOW) is False

    def test_at_limit_blocked(self):
        entries = [_request_entry(1)] * ratelimit.DEFAULT_DAILY_LIMIT
        assert ratelimit.is_rate_limited(entries, NOW) is True
        assert ratelimit.check(entries, NOW).remaining == 0

    def test_custom_limit_and_window(self):
        entries = [_request_entry(30)]  # 30h old
        assert ratelimit.is_rate_limited(entries, NOW, limit=1, window=timedelta(days=2)) is True
        assert ratelimit.is_rate_limited(entries, NOW, limit=1) is False


class TestAuditParsing:
    def test_parse_skips_malformed_lines(self):
        text = '{"kind": "request", "ts": "2026-07-17T10:00:00+00:00"}\nnot json\n[1,2]\n\n'
        entries = audit.parse_entries(text)
        assert len(entries) == 1
        assert entries[0]["kind"] == "request"

    def test_append_and_read_roundtrip(self, tmp_path):
        log = tmp_path / "grants.log"
        request = GrantRequest.new(GrantTier.BLOCK_EXCEPTION, "reddit.com", "work", 30)
        audit.record_request(request, path=log)
        audit.record_decision(request, Verdict.deny("nope"), stage="judge", path=log)
        entries = audit.read_entries(log)
        assert [e["kind"] for e in entries] == ["request", "decision"]
        assert entries[1]["decision"] == "deny"
        # Append-only: a second write adds, never truncates.
        audit.record_request(request, path=log)
        assert len(audit.read_entries(log)) == 3

    def test_read_missing_log_is_empty(self, tmp_path):
        assert audit.read_entries(tmp_path / "absent.log") == []

    def test_summarize_history_lines(self):
        entries = [
            {
                "kind": "decision",
                "ts": NOW.isoformat(),
                "tier": 1,
                "target": "reddit.com",
                "reason": "work research",
                "decision": "deny",
                "stage": "judge",
            },
            {"kind": "request", "ts": NOW.isoformat()},  # non-decision ignored
        ]
        summary = audit.summarize_history(entries, now=NOW)
        assert "reddit.com" in summary
        assert "work research" in summary
        assert "deny" in summary
        assert len(summary.splitlines()) == 1

    def test_summarize_history_window(self):
        old = {
            "kind": "decision",
            "ts": (NOW - timedelta(days=30)).isoformat(),
            "target": "old.com",
            "decision": "allow",
        }
        assert audit.summarize_history([old], now=NOW) == ""

    def test_log_is_valid_jsonl(self, tmp_path):
        log = tmp_path / "grants.log"
        request = GrantRequest.new(GrantTier.ROOT_COMMAND, "pacman -S rg", "tooling", 0, argv=("pacman", "-S", "rg"))
        audit.record_request(request, path=log)
        for line in log.read_text().splitlines():
            json.loads(line)
