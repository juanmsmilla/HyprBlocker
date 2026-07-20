"""Break-glass release — the dumb, deterministic, AI-free escape hatch (R5).

Runs as its own tiny root unit (``hyprblocker-breakglass.service`` fired by a
15-minute timer), completely independent of the enforcer so it still works while
the enforcer is crash-looping. It deliberately imports NOTHING from the rest of
the ``enforcer`` package — only the stdlib and :mod:`daemon.paths` (itself
stdlib-only). No network, no AI, no configuration surface. It never gains
features.

Protocol (file-drop, no API needed):

1. The user creates ``requests/breakglass.trigger`` (any content; ``touch`` is
   enough — the desktop app may do it for them).
2. On the next timer run the runner records the request into the root-owned
   ``secure/breakglass.json`` with ``requested_at = now``. The trigger file's
   mtime is deliberately IGNORED for timing — it is user-settable and could be
   backdated to skip the delay. Worst case the timer cadence adds 15 minutes.
3. Once recorded, the request is **non-cancelable**: deleting the trigger file
   changes nothing, and no other component can write breakglass.json. After the
   delay (default 36h, clamped to [24h, 48h]) the runner *releases*: it clears
   the settings lock (``secure/lock.json``) and makes the root credential
   world-readable (dev mode: the credential file may be absent; the lock is
   still cleared).

The delay decision is a pure function of (request time, now, delay) —
deterministic and unit-tested in ``tests/test_breakglass.py``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from daemon import paths

logger = logging.getLogger(__name__)

DEFAULT_DELAY_HOURS = 36.0
MIN_DELAY_HOURS = 24.0
MAX_DELAY_HOURS = 48.0

TRIGGER_NAME = "breakglass.trigger"


# ---------------------------------------------------------------------------
# Pure decision logic
# ---------------------------------------------------------------------------

def clamp_delay_hours(hours: float) -> float:
    """Clamp a requested delay into the allowed [24h, 48h] band."""
    return min(max(hours, MIN_DELAY_HOURS), MAX_DELAY_HOURS)


def should_release(trigger_mtime: float, now: float, delay_hours: float) -> bool:
    """Pure delay decision: has ``delay_hours`` elapsed since the request?

    ``trigger_mtime`` is the *recorded* request time (epoch seconds) — in
    production this is the root-recorded ``requested_at``, never the raw file
    mtime. A request time in the future never releases (negative elapsed).
    """
    elapsed = now - trigger_mtime
    return elapsed >= clamp_delay_hours(delay_hours) * 3600.0


# ---------------------------------------------------------------------------
# File plumbing (all paths via daemon.paths, so tests redirect into tmp)
# ---------------------------------------------------------------------------

def trigger_path() -> Path:
    return paths.requests_dir() / TRIGGER_NAME


def _load_state() -> dict:
    try:
        data = json.loads(paths.breakglass_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    target = paths.breakglass_path()
    paths.ensure_dir(target.parent)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(target)


def _release() -> None:
    """Clear the settings lock and expose the root credential. Idempotent."""
    lock = paths.lock_path()
    try:
        paths.ensure_dir(lock.parent)
        tmp = lock.with_suffix(".tmp")
        tmp.write_text(json.dumps({"locked_until": None, "released_by": "breakglass"}))
        tmp.replace(lock)
        logger.warning("Break-glass: settings lock cleared")
    except OSError as e:
        logger.error("Break-glass: failed to clear lock: %s", e)

    credential = paths.root_credential_path()
    try:
        if credential.exists():
            credential.chmod(0o644)
            logger.warning("Break-glass: root credential made world-readable")
        else:
            logger.info("Break-glass: no root credential present (dev mode)")
    except OSError as e:
        logger.error("Break-glass: failed to release credential: %s", e)

    try:
        trigger_path().unlink(missing_ok=True)
    except OSError:
        pass


def run_once(now: float | None = None) -> str:
    """One timer pass. Returns the action taken (for logs and tests):
    ``"idle"`` | ``"recorded"`` | ``"pending"`` | ``"released"`` | ``"already-released"``.
    """
    if now is None:
        now = time.time()
    state = _load_state()

    if state.get("released"):
        return "already-released"

    requested_at = state.get("requested_at")
    if requested_at is None:
        if not trigger_path().exists():
            return "idle"
        # Record NOW, not the trigger's mtime — mtime is user-settable and
        # backdating it must not shorten the delay.
        state = {
            "requested_at": now,
            "delay_hours": DEFAULT_DELAY_HOURS,
            "released": False,
        }
        _save_state(state)
        logger.warning(
            "Break-glass requested; releasing in %.0fh (non-cancelable)",
            DEFAULT_DELAY_HOURS,
        )
        return "recorded"

    delay = clamp_delay_hours(float(state.get("delay_hours", DEFAULT_DELAY_HOURS)))
    if not should_release(float(requested_at), now, delay):
        return "pending"

    _release()
    state["released"] = True
    state["released_at"] = now
    _save_state(state)
    return "released"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    if paths.layout() != "root":
        logger.error("Refusing to run: layout is %r, not 'root'.", paths.layout())
        return 2
    if os.geteuid() != 0:
        logger.error("Refusing to run: euid=%d, root required.", os.geteuid())
        return 2
    action = run_once()
    logger.info("Break-glass pass: %s", action)
    return 0


if __name__ == "__main__":
    sys.exit(main())
