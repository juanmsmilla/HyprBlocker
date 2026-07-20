"""The single source of truth for the global settings lock.

Before the root migration this state was read three different ways — the
``settings_lock_until`` field on the config dataclass, a private re-reader in
``daemon.watchdog`` with its own hardcoded NTP server list, and implicitly via
``daemon.time_verifier``. That duplication was the most dangerous path landmine
in the migration (a root process resolving ``Path.home()`` to ``/root`` would
silently read a nonexistent config and report *unlocked*). This module collapses
all of it into one reader that is layout-aware:

- ``user`` layout: the lock lives in ``config.json`` under
  ``security.settings_lock_until`` (unchanged from before — this is what keeps
  the live 2026-09-03 lock on this machine intact across a reboot).
- ``root`` layout: the lock lives in the root-owned ``secure/lock.json`` written
  only by the enforcer, so the user daemon can read but never shorten it.

``is_settings_locked`` fails **closed** (reports locked) when a lock exists but
NTP cannot be reached — you must not be able to unlock by pulling the network.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from daemon import paths

logger = logging.getLogger(__name__)

# Root-tier NTP servers. In the root layout the lock's time source of truth must
# NOT come from the user-writable config.json (a user could point ntp_servers at
# a fake local server answering with a post-expiry date and "unlock" the machine).
# The root tier therefore uses this hardcoded list and ignores config entirely.
_ROOT_NTP_SERVERS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")


def read_lock_until() -> datetime | None:
    """Return the current settings-lock expiry, or ``None`` if unlocked.

    Layout-aware: reads ``config.json`` in the user layout and the root-owned
    ``secure/lock.json`` in the root layout. Any read/parse error is treated as
    "no lock recorded" (``None``); callers that need fail-closed semantics use
    :func:`is_settings_locked`, which layers NTP handling on top.
    """
    if paths.layout() == "root":
        return _read_root_lock()
    return _read_user_lock()


def _read_user_lock() -> datetime | None:
    config_file = paths.config_path()
    try:
        if not config_file.exists():
            return None
        with open(config_file) as f:
            data = json.load(f)
        raw = data.get("security", {}).get("settings_lock_until")
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to read settings lock from %s: %s", config_file, e)
        return None
    return _parse(raw)


def _read_root_lock() -> datetime | None:
    lock_file = paths.lock_path()
    try:
        if not lock_file.exists():
            return None
        with open(lock_file) as f:
            data = json.load(f)
        raw = data.get("locked_until")
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to read root lock from %s: %s", lock_file, e)
        return None
    return _parse(raw)


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        logger.error("Unparseable settings_lock_until value: %r", raw)
        return None


def _root_lock_is_corrupt() -> bool:
    """True if the root ``lock.json`` exists but cannot be trusted.

    A legitimately *unlocked* record (``{"locked_until": null}``) is not corrupt.
    A missing file is not corrupt (there is simply no lock). But a file that is
    present yet unparseable, missing its key, or carrying an unparseable
    timestamp must NOT be read as "unlocked" — that would let a user unlock by
    scribbling on the record. Callers fail closed on corruption.
    """
    p = paths.lock_path()
    try:
        if not p.exists():
            return False
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict) or "locked_until" not in data:
        return True
    raw = data["locked_until"]
    if raw is None:
        return False  # explicit, legitimate unlock
    return _parse(raw) is None  # present but unparseable ⇒ corrupt


def is_settings_locked(verify_ntp: bool = True) -> bool:
    """Return whether the settings lock is currently active.

    Fail-closed: if a lock is recorded but NTP is unreachable, returns ``True``
    (locked) rather than trusting a possibly-rolled-back system clock; and in the
    root layout a corrupt ``lock.json`` also fails closed (locked). When no lock
    is recorded, returns ``False`` immediately without any network call.
    """
    lock_until = read_lock_until()
    if lock_until is None:
        # A corrupt root-owned lock record must never read as unlocked.
        if paths.layout() == "root" and _root_lock_is_corrupt():
            logger.warning("Root lock.json is corrupt — failing closed (locked)")
            return True
        return False

    if lock_until.tzinfo is None:
        lock_until = lock_until.replace(tzinfo=UTC)

    if not verify_ntp:
        return datetime.now(UTC) < lock_until

    ntp_time = _ntp_now()
    if ntp_time is None:
        logger.warning("NTP unreachable while a settings lock exists — failing closed (locked)")
        return True
    return ntp_time < lock_until


def _ntp_now() -> datetime | None:
    """Best NTP time.

    In the root layout, query the hardcoded root-owned server list directly so the
    authoritative lock never trusts user-writable config. In the user layout, defer
    to the shared TimeVerifier (config-driven, one NTP implementation, not three).
    """
    if paths.layout() == "root":
        return _root_ntp_now()
    try:
        from daemon.time_verifier import get_time_verifier

        return get_time_verifier().get_ntp_time()
    except Exception as e:  # pragma: no cover - defensive; ntplib/import edge cases
        logger.error("NTP query failed: %s", e)
        return None


def _root_ntp_now() -> datetime | None:
    try:
        import ntplib
    except ImportError:  # pragma: no cover - ntplib is a hard dep
        logger.error("ntplib unavailable in root tier")
        return None
    client = ntplib.NTPClient()
    for server in _ROOT_NTP_SERVERS:
        try:
            resp = client.request(server, timeout=5)
            return datetime.fromtimestamp(resp.tx_time, tz=UTC)
        except Exception:
            continue
    logger.warning("All root-tier NTP servers failed")
    return None
