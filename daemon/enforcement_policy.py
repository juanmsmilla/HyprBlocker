"""Root-owned enforcement policy — the settings the enforcement loop and the
root enforcer actually consume.

Adversarial review finding R3: leaving enforcement-critical fields (the browser
kill-list, the browser_enforcement / shutdown_prevention / watchdog toggles, the
heartbeat interval) in the user-writable ``config.json`` makes the settings lock
decorative under the root layout — a user could set ``browser_enforcement_enabled
= false`` or ``browsers = []`` by editing the file directly, no API and no sudo
required, and enforcement silently stops at the next reboot.

So in the **root** layout these fields live in the root-owned
``secure/enforcement.json``, writable only by the enforcer (changed via the
asymmetric ``requests/`` path). In the **user** layout there is no privilege
boundary, so this transparently falls back to ``config.json`` and behavior is
unchanged from before the migration.

This module is read-only from the user daemon's perspective; the enforcer owns
writes to the root-owned file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from daemon import paths

logger = logging.getLogger(__name__)


DEFAULT_BROWSERS = [
    "firefox",
    "firefox-esr",
    "chromium",
    "google-chrome",
    "brave-browser",
    "microsoft-edge",
    "opera",
    "vivaldi-stable",
]


@dataclass
class EnforcementPolicy:
    """The authoritative, enforcement-critical subset of settings."""

    browsers: list[str] = field(default_factory=lambda: list(DEFAULT_BROWSERS))
    browser_enforcement_enabled: bool = True
    shutdown_prevention_enabled: bool = False
    watchdog_enabled: bool = False
    watchdog_count: int = 3
    heartbeat_interval_seconds: int = 30

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _from_config() -> EnforcementPolicy:
    """Build a policy from config.json (user layout / fallback)."""
    from daemon.config import get_config

    cfg = get_config()
    return EnforcementPolicy(
        browsers=list(cfg.browsers),
        browser_enforcement_enabled=cfg.security.browser_enforcement_enabled,
        shutdown_prevention_enabled=cfg.security.shutdown_prevention_enabled,
        watchdog_enabled=cfg.security.watchdog_enabled,
        watchdog_count=cfg.security.watchdog_count,
        heartbeat_interval_seconds=cfg.monitoring.heartbeat_timeout_seconds,
    )


def _enforcement_path():
    return paths.secure_dir() / "enforcement.json"


def load_policy() -> EnforcementPolicy:
    """Return the active enforcement policy.

    Root layout: read the root-owned ``secure/enforcement.json`` (falling back to
    config-derived defaults only if it is missing — e.g. before the enforcer's
    first write). User layout: derive from config.json exactly as before.
    """
    if paths.layout() != "root":
        return _from_config()

    path = _enforcement_path()
    try:
        if path.exists():
            data = json.loads(path.read_text())
            known = EnforcementPolicy().__dict__.keys()
            return EnforcementPolicy(**{k: v for k, v in data.items() if k in known})
    except (OSError, json.JSONDecodeError, TypeError) as e:
        logger.error("Failed to read %s: %s — using config fallback", path, e)
    return _from_config()


def write_policy(policy: EnforcementPolicy) -> None:
    """Persist the enforcement policy (root/enforcer only). Atomic write.

    In the user layout this is a no-op sink to a plain file under state_dir so
    tests and dev tooling can round-trip without a privilege boundary.
    """
    path = _enforcement_path()
    paths.ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(policy.to_json())
    tmp.replace(path)
