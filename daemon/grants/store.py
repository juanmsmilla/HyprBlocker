"""Active tier-1 grant store + read-time overlay.

Review finding M6: a granted blocker-rule exception must NOT be written into the
block rows themselves. Doing so either violates the per-block lock ratchet
(loosening a locked block in place), leaks a permanent loosening if the daemon
crashes before the expiry cleanup runs, and misses blocks created mid-grant.

Instead, active grants live in their own small store and are *overlaid onto the
blocked-sites response at read time*: each unexpired grant adds its pattern to the
``allowed[]`` of every currently-blocking, **unlocked** block. Expiry needs no
cleanup writes — an expired grant simply stops being overlaid. A grant can never
loosen a locked block, which defangs the "forge a grant for a locked block"
attack regardless of who wrote the store.

Pure overlay/parse logic is separated from the two thin I/O wrappers so the
overlay is fully unit-testable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from daemon import paths
from daemon.blocker import SiteBlocker
from daemon.grants.tier1 import normalize_url_pattern

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveGrant:
    """One approved, unexpired tier-1 exception in the store."""

    id: str
    url: str
    pattern: str
    scope: str
    reason: str
    granted_at: str  # ISO8601
    expires_at: str  # ISO8601

    def is_expired(self, now: datetime) -> bool:
        try:
            exp = datetime.fromisoformat(self.expires_at)
        except (ValueError, TypeError):
            return True  # unparseable ⇒ treat as expired (fail closed)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return now >= exp


# --------------------------------------------------------------------------
# Pure logic
# --------------------------------------------------------------------------

def parse_grants(data: Any) -> list[ActiveGrant]:
    """Parse the store's JSON payload into grants, skipping malformed entries."""
    grants: list[ActiveGrant] = []
    if not isinstance(data, list):
        return grants
    fields = ActiveGrant.__dataclass_fields__.keys()
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            grants.append(ActiveGrant(**{k: item[k] for k in fields}))
        except (KeyError, TypeError):
            logger.warning("Skipping malformed grant entry: %.80s", item)
    return grants


def active_grants(grants: Iterable[ActiveGrant], now: datetime) -> list[ActiveGrant]:
    """The subset of grants that have not yet expired."""
    return [g for g in grants if not g.is_expired(now)]


def overlay_blocks(
    blocks_data: list[dict[str, Any]],
    grants: Iterable[ActiveGrant],
    now: datetime,
    locked_block_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Return a copy of ``blocks_data`` with active grants overlaid onto allowed[].

    For each unexpired grant, its pattern is added to the ``allowed[]`` of every
    block that would block the granted URL — except blocks in ``locked_block_ids``,
    which are never loosened (the lock ratchet wins over a grant). The input is
    not mutated.
    """
    locked = locked_block_ids or set()
    live = active_grants(list(grants), now)
    if not live:
        return blocks_data

    result: list[dict[str, Any]] = []
    for block in blocks_data:
        allowed = list(block.get("allowed", []))
        if block.get("id") not in locked:
            blocked_patterns = block.get("blocked", [])
            for grant in live:
                blocks_it = any(
                    SiteBlocker.url_matches_pattern(grant.url, p) for p in blocked_patterns
                )
                if blocks_it and grant.pattern not in allowed:
                    allowed.append(grant.pattern)
        result.append({**block, "allowed": allowed})
    return result


def make_active_grant(grant_id, url, scope, reason, granted_at, expires_at) -> ActiveGrant:
    """Build an ActiveGrant, normalising the URL into an allowlist pattern."""
    return ActiveGrant(
        id=grant_id,
        url=url,
        pattern=normalize_url_pattern(url),
        scope=scope,
        reason=reason,
        granted_at=granted_at.isoformat() if hasattr(granted_at, "isoformat") else str(granted_at),
        expires_at=expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
    )


# --------------------------------------------------------------------------
# I/O wrappers
# --------------------------------------------------------------------------

def load(path: Path | None = None) -> list[ActiveGrant]:
    """Read the grant store; a missing/unreadable store reads as empty."""
    path = path or paths.grants_active_path()
    try:
        return parse_grants(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []


def save(grants: list[ActiveGrant], path: Path | None = None) -> None:
    """Persist the grant store atomically (temp-write + rename)."""
    path = path or paths.grants_active_path()
    paths.ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(g) for g in grants], indent=2), encoding="utf-8")
    tmp.replace(path)


def add_grant(grant: ActiveGrant, now: datetime, path: Path | None = None) -> list[ActiveGrant]:
    """Add a grant and drop any already-expired ones. Returns the new active set."""
    current = active_grants(load(path), now)
    current.append(grant)
    save(current, path)
    return current


def prune_expired(now: datetime, path: Path | None = None) -> int:
    """Drop expired grants from the store. Returns the number removed."""
    current = load(path)
    live = active_grants(current, now)
    removed = len(current) - len(live)
    if removed:
        save(live, path)
    return removed
