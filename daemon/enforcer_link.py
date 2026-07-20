"""User-daemon view of the root enforcer's liveness.

Adversarial review finding R6: gating the watchdog mesh on *layout alone* means
that if the root enforcer fails to start at the first reboot (an unverifiable
privileged code path), the user daemon runs under the root layout with the mesh
inert — leaving the machine with *less* protection than before, silently. So the
daemon must gate mesh fallback on *observed enforcer liveness*, not layout.

The enforcer refreshes ``secure/enforcer_state.json`` every tick with a fresh
timestamp and the current boot_id. This module reads that file and decides
whether the enforcer looks alive. If it is stale/absent, the user daemon spawns
the watchdog mesh as a fallback and surfaces ``enforcer_down`` in ``/api/status``.

Contract for the JSON written by ``enforcer/main.py`` (``_write_state``):
    {"written_at": "<iso8601 UTC>", "boot_id": "<contents of /proc/.../boot_id>", ...}
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from daemon import paths

logger = logging.getLogger(__name__)

# How long the enforcer snapshot may go unrefreshed before we consider it dead.
ENFORCER_STALE_SECONDS = 120


def _current_boot_id() -> str | None:
    try:
        return open("/proc/sys/kernel/random/boot_id").read().strip()
    except OSError:
        return None


def read_enforcer_state() -> dict | None:
    path = paths.enforcer_state_path()
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read enforcer state %s: %s", path, e)
        return None


def enforcer_alive(now: datetime | None = None) -> bool:
    """True iff the enforcer refreshed its snapshot recently and for this boot.

    A snapshot from a previous boot (boot_id mismatch) is treated as dead — it
    cannot vouch for the current session and prevents cross-boot replay from
    masking a dead enforcer.
    """
    state = read_enforcer_state()
    if not state:
        return False

    boot_id = _current_boot_id()
    if boot_id is not None and state.get("boot_id") not in (None, boot_id):
        logger.warning("Enforcer snapshot is from a previous boot — treating as down")
        return False

    raw = state.get("written_at")
    if not raw:
        return False
    try:
        updated = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)

    now = now or datetime.now(UTC)
    age = (now - updated).total_seconds()
    return 0 <= age <= ENFORCER_STALE_SECONDS


def should_run_watchdog_mesh(shutdown_prevention: bool, watchdog_enabled: bool) -> bool:
    """Decide whether the user daemon should spawn the watchdog mesh.

    - User layout: original behavior — run the mesh whenever both toggles are on.
    - Root layout: the mesh is a *fallback*. Run it only when the enforcer looks
      down (so we never leave a gap), and stay out of the way when it's healthy.
    """
    if not (shutdown_prevention and watchdog_enabled):
        return False
    if paths.layout() != "root":
        return True
    return not enforcer_alive()
