"""Grant-request rate limiting — a few requests per day, counted from the audit log.

Pure logic: callers read entries via :mod:`daemon.grants.audit` and pass them
in. Nothing here touches the filesystem, so tests cover it with plain dicts.

Fail-closed detail: entries with unparseable timestamps still COUNT toward the
limit — a corrupted audit line must never widen the budget.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from daemon.grants.models import GrantTier

DEFAULT_DAILY_LIMIT = 3
DEFAULT_WINDOW = timedelta(days=1)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("ts")
    if not isinstance(raw, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def count_recent_requests(
    entries: Iterable[dict[str, Any]],
    now: datetime,
    window: timedelta = DEFAULT_WINDOW,
    tier: GrantTier | None = None,
) -> int:
    """Count ``kind == "request"`` audit entries inside the rolling window.

    Entries with a missing/corrupt timestamp count (fail closed). ``tier``
    narrows the count to one tier; ``None`` counts all tiers together.
    """
    now = _as_utc(now)
    cutoff = now - window
    count = 0
    for entry in entries:
        if entry.get("kind") != "request":
            continue
        if tier is not None and entry.get("tier") != int(tier):
            continue
        ts = _entry_timestamp(entry)
        if ts is None or cutoff <= ts <= now:
            count += 1
    return count


@dataclass(frozen=True)
class RateLimitStatus:
    """Snapshot of the budget at a moment in time."""

    used: int
    limit: int
    window: timedelta

    @property
    def allowed(self) -> bool:
        return self.used < self.limit

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def check(
    entries: Iterable[dict[str, Any]],
    now: datetime,
    *,
    limit: int = DEFAULT_DAILY_LIMIT,
    window: timedelta = DEFAULT_WINDOW,
    tier: GrantTier | None = None,
) -> RateLimitStatus:
    """Return the current budget status for a would-be NEW request."""
    used = count_recent_requests(entries, now, window=window, tier=tier)
    return RateLimitStatus(used=used, limit=limit, window=window)


def is_rate_limited(
    entries: Iterable[dict[str, Any]],
    now: datetime,
    *,
    limit: int = DEFAULT_DAILY_LIMIT,
    window: timedelta = DEFAULT_WINDOW,
    tier: GrantTier | None = None,
) -> bool:
    """True when a new request must be rejected for exceeding the budget."""
    return not check(entries, now, limit=limit, window=window, tier=tier).allowed
