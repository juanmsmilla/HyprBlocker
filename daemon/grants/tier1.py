"""Tier-1 grants: time-limited blocker rule exceptions. NO root involved.

Pure planning logic only — this module takes the currently-active blocks and
returns a *mutation plan*; it never touches the database. The integrator
(``daemon/api/routes/grants.py``) applies the plan through the existing block
CRUD/session machinery and schedules the expiry.

INTERSECTION SEMANTICS (critical): ``SiteBlocker.is_site_blocked`` allows a
URL only when it appears in the ``allowed[]`` of EVERY active block that would
block it. A grant therefore must add the allow pattern to every matching
block — adding it to just one changes nothing.

Expiry is the mirror image: remove exactly the granted pattern line from every
block it was added to, leaving pre-existing allow entries untouched.

Pattern-matching reuses :class:`daemon.blocker.SiteBlocker` so grants and
enforcement can never disagree about what "matches" means.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from daemon.blocker import SiteBlocker, parse_rules_from_text
from daemon.grants.models import MAX_GRANT_MINUTES


def normalize_url_pattern(url: str) -> str:
    """Canonicalize a granted URL into an allowlist pattern.

    Strips scheme and trailing slash, lowercases — mirroring what
    ``SiteBlocker.url_matches_pattern`` does to both sides before comparing.
    """
    url = url.strip()
    if "://" in url:
        url = url.split("://", 1)[1]
    url = url.strip().lower()
    return url.rstrip("/")


@dataclass(frozen=True)
class BlockMutation:
    """One block's new ``websites_allowed`` text (add or remove already applied)."""

    block_id: int
    block_name: str
    new_websites_allowed: str


@dataclass(frozen=True)
class AllowlistPlan:
    """Everything the integrator needs to apply + later expire a tier-1 grant."""

    url: str
    pattern: str
    expires_at: datetime
    mutations: tuple[BlockMutation, ...]

    @property
    def is_empty(self) -> bool:
        return not self.mutations


def matching_active_blocks(url: str, blocks: Iterable[Any]) -> list[Any]:
    """Blocks whose ``websites_blocked`` patterns match ``url``.

    ``blocks`` must already be the ACTIVE set (the caller asks the scheduler);
    disabled blocks are skipped defensively anyway.
    """
    matcher = SiteBlocker.url_matches_pattern
    result = []
    for block in blocks:
        if not getattr(block, "enabled", True):
            continue
        for pattern in parse_rules_from_text(block.websites_blocked):
            if matcher(url, pattern):
                result.append(block)
                break
    return result


def _append_pattern(allowed_text: str | None, pattern: str) -> str:
    existing = parse_rules_from_text(allowed_text)
    return "\n".join([*existing, pattern])


def _remove_pattern(allowed_text: str | None, pattern: str) -> str:
    kept = [rule for rule in parse_rules_from_text(allowed_text) if rule.lower() != pattern.lower()]
    return "\n".join(kept)


def plan_allowlist_grant(
    url: str,
    active_blocks: Iterable[Any],
    minutes: int,
    now: datetime,
) -> AllowlistPlan:
    """Compute the mutation adding ``url`` to the allowlist of EVERY matching block.

    Blocks that already allow the exact pattern are skipped (idempotent). An
    empty plan means no active block blocks this URL — nothing to grant.
    """
    minutes = max(1, min(minutes, MAX_GRANT_MINUTES))
    pattern = normalize_url_pattern(url)
    mutations = []
    for block in matching_active_blocks(pattern, active_blocks):
        existing = [rule.lower() for rule in parse_rules_from_text(block.websites_allowed)]
        if pattern in existing:
            continue
        mutations.append(
            BlockMutation(
                block_id=block.id,
                block_name=block.name,
                new_websites_allowed=_append_pattern(block.websites_allowed, pattern),
            )
        )
    return AllowlistPlan(
        url=url,
        pattern=pattern,
        expires_at=now + timedelta(minutes=minutes),
        mutations=tuple(mutations),
    )


def plan_allowlist_expiry(pattern: str, blocks: Iterable[Any]) -> tuple[BlockMutation, ...]:
    """Compute the mutations removing an expired granted pattern.

    Scans ALL provided blocks (not just active ones — a block whose schedule
    ended must still shed the temporary entry) and removes exactly the granted
    pattern line, preserving every other allow rule.
    """
    mutations = []
    normalized = normalize_url_pattern(pattern)
    for block in blocks:
        existing = [rule.lower() for rule in parse_rules_from_text(block.websites_allowed)]
        if normalized not in existing:
            continue
        mutations.append(
            BlockMutation(
                block_id=block.id,
                block_name=block.name,
                new_websites_allowed=_remove_pattern(block.websites_allowed, normalized),
            )
        )
    return tuple(mutations)
