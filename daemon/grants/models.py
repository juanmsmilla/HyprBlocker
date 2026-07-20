"""Shared dataclasses for the AI-brokered scoped-grant system.

Pure data — no I/O, no network, no privilege. Every other ``daemon.grants``
module builds on these types.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum

# Hard ceiling on how long any single grant may last, regardless of what the
# requester asked for or what the judge answered.
MAX_GRANT_MINUTES = 240


class GrantTier(IntEnum):
    """The three grant tiers from the root-migration design.

    Tier 2 (routine updates) is deterministic — a sudoers drop-in shipped by
    ``install-root.sh`` — so it never produces a :class:`GrantRequest`; the
    value exists so audit entries can reference it.
    """

    BLOCK_EXCEPTION = 1  # user daemon, no root: time-limited allowlist entry
    ROUTINE_UPDATE = 2  # deterministic sudoers rule, no AI involved
    ROOT_COMMAND = 3  # enforcer-executed constrained-grammar command


@dataclass(frozen=True)
class GrantRequest:
    """A single grant request as submitted by the user.

    ``target`` is the URL/app for tier 1, or a human-readable rendering of the
    command for tier 3 (the exact argv rides in ``argv``). ``reason`` is
    free-form requester text and is treated strictly as *data* everywhere —
    it never becomes instructions to the judge.
    """

    id: str
    tier: GrantTier
    target: str
    reason: str
    minutes: int
    created_at: datetime
    argv: tuple[str, ...] | None = None

    @classmethod
    def new(
        cls,
        tier: GrantTier,
        target: str,
        reason: str,
        minutes: int,
        argv: tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> GrantRequest:
        return cls(
            id=uuid.uuid4().hex,
            tier=tier,
            target=target,
            reason=reason,
            minutes=minutes,
            created_at=now or datetime.now(UTC),
            argv=argv,
        )


@dataclass(frozen=True)
class Verdict:
    """The judge's decision, validated against the strict verdict schema.

    ``decision`` is exactly ``"allow"`` or ``"deny"`` — anything else never
    survives :func:`daemon.grants.judge.parse_verdict`.
    """

    decision: str
    scope: str
    minutes: int
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @classmethod
    def deny(cls, reason: str) -> Verdict:
        """Canonical deny verdict — the fail-closed default everywhere."""
        return cls(decision="deny", scope="", minutes=0, reason=reason)


@dataclass(frozen=True)
class Grant:
    """An approved, time-limited grant (request + allow verdict + expiry)."""

    request: GrantRequest
    verdict: Verdict
    granted_at: datetime
    expires_at: datetime = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.expires_at is None:
            minutes = min(self.verdict.minutes, MAX_GRANT_MINUTES)
            object.__setattr__(
                self, "expires_at", self.granted_at + timedelta(minutes=minutes)
            )

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at
