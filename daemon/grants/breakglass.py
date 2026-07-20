"""Break-glass status view + trigger drop — the USER-tier side only.

Break-glass is the deterministic, AI-free, network-free backstop: if the whole
apparatus wedges, the user can always start a non-cancelable 24-48h countdown
after which the root credential/lock is released.

Division of labor (hardening R5): the actual delayed release is performed by a
separate tiny root unit (``hyprblocker-breakglass.service``/``.timer`` — the
``enforcer/breakglass_runner``, owned by the phase-2 work) which watches for a
trigger file and owns ``secure/breakglass.json``. THIS module is deliberately
dumb: it (a) reads that root-owned state to display status, and (b) lets the
UI request a release by dropping ``requests/breakglass.trigger``. Nothing
here imports the judge, the network client, or anything from ``enforcer/``.

The trigger file's mtime — not its user-writable content — is what the root
runner trusts for the countdown start; the timestamp written inside is
informational.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from daemon import paths

logger = logging.getLogger(__name__)

TRIGGER_FILENAME = "breakglass.trigger"

# Status values, in escalation order.
IDLE = "idle"  # nothing requested
REQUESTED = "requested"  # trigger dropped; root runner has not yet acknowledged
PENDING = "pending"  # root runner acknowledged; countdown running
RELEASED = "released"  # delay elapsed; credential/lock released


def trigger_path() -> Path:
    return paths.requests_dir() / TRIGGER_FILENAME


@dataclass(frozen=True)
class BreakGlassStatus:
    """User-facing snapshot of the break-glass state machine."""

    state: str
    requested_at: datetime | None = None
    release_at: datetime | None = None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def compute_status(
    state_doc: dict | None,
    trigger_exists: bool,
    trigger_requested_at: datetime | None = None,
) -> BreakGlassStatus:
    """Pure state derivation from the root-owned doc + trigger presence.

    The root runner's ``breakglass.json`` is authoritative once it exists;
    until it appears, a dropped trigger reads as ``requested``.
    """
    if state_doc:
        requested_at = _parse_iso(state_doc.get("requested_at"))
        release_at = _parse_iso(state_doc.get("release_at"))
        if state_doc.get("released") is True:
            return BreakGlassStatus(RELEASED, requested_at, release_at)
        if release_at is not None:
            return BreakGlassStatus(PENDING, requested_at, release_at)
    if trigger_exists:
        return BreakGlassStatus(REQUESTED, trigger_requested_at, None)
    return BreakGlassStatus(IDLE)


def read_status() -> BreakGlassStatus:
    """Read the current break-glass status (root state + trigger file)."""
    state_doc: dict | None = None
    try:
        raw = paths.breakglass_path().read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            state_doc = parsed
    except OSError:
        pass
    except json.JSONDecodeError:
        logger.warning("Corrupt breakglass.json — treating as absent")

    trigger = trigger_path()
    trigger_exists = trigger.exists()
    trigger_ts: datetime | None = None
    if trigger_exists:
        try:
            trigger_ts = _parse_iso(json.loads(trigger.read_text(encoding="utf-8")).get("requested_at"))
        except (OSError, json.JSONDecodeError, AttributeError):
            trigger_ts = None
    return compute_status(state_doc, trigger_exists, trigger_ts)


def request_release() -> BreakGlassStatus:
    """Drop the trigger file to start the break-glass countdown.

    Idempotent: an existing trigger (or an already pending/released state) is
    left untouched — the countdown is non-cancelable and non-restartable from
    the user tier. Returns the resulting status.
    """
    status = read_status()
    if status.state != IDLE:
        return status

    trigger = trigger_path()
    paths.ensure_dir(trigger.parent)
    now = datetime.now(UTC)
    try:
        trigger.write_text(json.dumps({"requested_at": now.isoformat()}), encoding="utf-8")
    except OSError as e:
        logger.error("Could not drop break-glass trigger at %s: %s", trigger, e)
        return status
    return BreakGlassStatus(REQUESTED, now, None)
