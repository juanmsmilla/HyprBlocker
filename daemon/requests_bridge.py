"""User daemon → root enforcer request drop.

Under the root layout the security-critical state (the settings lock in
``secure/lock.json``, the enforcement policy) is root-owned and the user daemon
cannot write it. Instead the daemon drops a JSON *request* into
``requests/settings/`` and the enforcer applies it with asymmetric semantics
(tightening immediately, loosening after a delay). This module is the thin,
pure-ish writer for those requests.

The ``requests/`` directory is ``root:hyprblocker 1775`` (sticky) so the user can
drop files but cannot tamper with others' entries. In the user layout there is no
enforcer, so callers keep writing config directly and never use this bridge.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from daemon import paths

logger = logging.getLogger(__name__)


def settings_requests_dir() -> Path:
    return paths.requests_dir() / "settings"


def build_lock_request(locked_until: str | None) -> dict:
    """A request to set/extend/clear the settings lock.

    ``locked_until`` is an ISO8601 string to lock until, or ``None`` to request an
    unlock (which the enforcer treats as loosening → delayed).
    """
    return {
        "type": "lock",
        "locked_until": locked_until,
        "requested_at": datetime.now(UTC).isoformat(),
        "id": uuid.uuid4().hex,
    }


def drop_request(payload: dict) -> Path:
    """Write a request JSON file for the enforcer to consume. Returns its path."""
    d = settings_requests_dir()
    paths.ensure_dir(d)
    target = d / f"{payload.get('id', uuid.uuid4().hex)}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)
    logger.info("Dropped %s request for enforcer at %s", payload.get("type"), target)
    return target
