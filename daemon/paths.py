"""Central filesystem layout — the single source of truth for every path the
daemon, enforcer, installers, and tests touch.

Two layouts exist:

- ``user``  — the legacy per-user install. All state lives under
  ``~/.config/hyprblocker`` exactly as it did before the root migration, so a
  reboot from the working copy *before* ``install-root.sh`` behaves identically
  to the old system (same files, same watchdog mesh, same settings lock).

- ``root``  — the two-tier root-owned install. Immutable code + venv under
  ``/opt/hyprblocker``; mutable state under ``/var/lib/hyprblocker``; a
  root-owned ``secure/`` subtree the user daemon can read but not write.

The layout is auto-detected from where this module lives (under
``/opt/hyprblocker`` ⇒ ``root``) and can be forced with ``HYPRBLOCKER_LAYOUT``.
Individual directories are overridable with ``HYPRBLOCKER_STATE_DIR`` /
``_CONFIG_DIR`` / ``_LOG_DIR`` / ``_SECURE_DIR`` / ``_CODE_ROOT`` — tests point
these at a tmp dir so nothing ever touches real state.

Every accessor returns a :class:`pathlib.Path`. Directory creation is
best-effort: in ``user`` layout the dirs are created on demand (matching the old
``os.makedirs`` side effects); in ``root`` layout the installer owns directory
creation, so a missing/read-only directory never raises here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Installed code location for the root layout. Detection compares the real path
# of this file against this prefix.
_ROOT_CODE_PREFIX = Path("/opt/hyprblocker")

# Legacy per-user state directory (unchanged from before the migration).
_USER_STATE_DIR = Path.home() / ".config" / "hyprblocker"

# Root-layout fixed directories.
_ROOT_STATE_DIR = Path("/var/lib/hyprblocker")


def _real_opt_deploy() -> bool:
    """True iff this module physically lives under ``/opt/hyprblocker``.

    That is the one situation an unprivileged user cannot fake (the code tree is
    root-owned), so it is the signal we trust to lock down environment overrides.
    """
    try:
        here = Path(__file__).resolve()
        return here == _ROOT_CODE_PREFIX or _ROOT_CODE_PREFIX in here.parents
    except OSError:
        return False


def _allow_dir_overrides() -> bool:
    """Whether ``HYPRBLOCKER_*`` directory overrides are honored.

    Review finding M2: on a real ``/opt`` deploy the environment is attacker-
    controlled (``python -I`` does *not* strip ``HYPRBLOCKER_SECURE_DIR`` et al.,
    and the systemd unit's ``UnsetEnvironment`` is the belt; this is the braces),
    so a user could redirect ``secure_dir()`` at a forged directory. When the code
    lives under ``/opt`` we therefore ignore all dir overrides. In a dev/test
    checkout the code is not under ``/opt``, so overrides work normally.
    """
    return not _real_opt_deploy()


def _env_path(name: str) -> Path | None:
    if not _allow_dir_overrides():
        return None
    value = os.environ.get(name)
    return Path(value) if value else None


def layout() -> str:
    """Return the active layout: ``"user"`` or ``"root"``.

    A real ``/opt`` deploy is always ``root``. Otherwise ``HYPRBLOCKER_LAYOUT``
    selects the layout (used by tests and by the systemd unit's ``Environment=``);
    the default is ``user``.
    """
    if _real_opt_deploy():
        return "root"
    override = os.environ.get("HYPRBLOCKER_LAYOUT")
    if override in ("user", "root"):
        return override
    return "user"


def code_root() -> Path:
    """Directory containing the daemon package (``/opt/hyprblocker`` or repo root)."""
    override = _env_path("HYPRBLOCKER_CODE_ROOT")
    if override:
        return override
    if layout() == "root":
        return _ROOT_CODE_PREFIX
    # Repo root == parent of the daemon package directory.
    return Path(__file__).resolve().parent.parent


def state_dir() -> Path:
    """Top-level state directory.

    Review finding M1: in the ``root`` layout this is ``root:root 0755`` — it is
    NOT group-writable, because directory write permission allows *renaming* any
    entry, which would let a user swap out ``secure/`` wholesale and forge the
    lock/policy/credential with zero sudo. User-writable content therefore lives
    in the ``user/`` subdirectory, not as files directly under this parent.
    """
    override = _env_path("HYPRBLOCKER_STATE_DIR")
    if override:
        return override
    return _ROOT_STATE_DIR if layout() == "root" else _USER_STATE_DIR


def user_dir() -> Path:
    """User-writable state (config.json, blocker.db, heartbeat.json).

    ``root`` layout: ``state_dir/user`` (``user:hyprblocker 0775`` — its own
    writable directory so temp-write+rename works for config/DB saves). ``user``
    layout: collapses onto ``state_dir`` (no privilege boundary), unchanged from
    before the migration.
    """
    override = _env_path("HYPRBLOCKER_STATE_DIR")
    if override:
        return override
    return state_dir() / "user" if layout() == "root" else state_dir()


def config_dir() -> Path:
    """Directory holding ``config.json``. Same as :func:`user_dir` unless overridden."""
    return _env_path("HYPRBLOCKER_CONFIG_DIR") or user_dir()


def secure_dir() -> Path:
    """Root-owned security state (lock, policy, grants log, credential, enforcer state).

    In ``root`` layout this is ``state_dir/secure`` — ``root:root 0755`` sitting
    directly under the ``0755`` parent, so a user can read but neither write it nor
    rename it. In ``user`` layout there is no privilege boundary, so it collapses
    onto ``state_dir`` — preserving the pre-migration reality.
    """
    override = _env_path("HYPRBLOCKER_SECURE_DIR")
    if override:
        return override
    return state_dir() / "secure" if layout() == "root" else state_dir()


def log_dir() -> Path:
    """Directory for daemon/watchdog/enforcer log files (user-writable)."""
    override = _env_path("HYPRBLOCKER_LOG_DIR")
    if override:
        return override
    return state_dir() / "logs" if layout() == "root" else state_dir()


def requests_dir() -> Path:
    """Drop directory where the user daemon hands change requests to the enforcer.

    ``root:hyprblocker 1775`` — the sticky bit means a non-owner cannot rename or
    delete another's entries (the user can drop requests but not tamper with the
    directory structure the enforcer consumes).
    """
    return state_dir() / "requests"


def config_path() -> Path:
    return config_dir() / "config.json"


def database_path() -> Path:
    return user_dir() / "blocker.db"


def heartbeat_path() -> Path:
    """User-written liveness attestation the enforcer reads (review finding M4).

    Lives in the user-writable ``user/`` subdir (NOT ``secure/``, which is
    root-write-only). The enforcer validates its *content* (challenge echo,
    boot_id, /proc PID checks), never trusting its location.
    """
    return user_dir() / "heartbeat.json"


def watchdog_state_path() -> Path:
    return state_dir() / "watchdog_state.json"


def lock_path() -> Path:
    """Authoritative settings-lock record (root layout). See :mod:`daemon.settings_lock`."""
    return secure_dir() / "lock.json"


def policy_path() -> Path:
    """User-authored judge policy document (layer 2 of the grant judge prompt)."""
    return secure_dir() / "policy.md"


def grants_log_path() -> Path:
    """Append-only grant audit log (world-readable)."""
    return secure_dir() / "grants.log"


def grants_active_path() -> Path:
    """Active tier-1 grant store, overlaid onto blocks at read time (review M6).

    Root layout: ``secure/grants_active.json`` — root-owned and world-readable so
    the enforcer is the authoritative writer and a forged grant cannot loosen a
    locked block. User/dev layout: collapses onto ``secure_dir`` (== state_dir),
    written by the user daemon (matching the "tier 1 needs no root" intent)."""
    return secure_dir() / "grants_active.json"


def breakglass_path() -> Path:
    """Break-glass time-delay release state."""
    return secure_dir() / "breakglass.json"


def enforcer_state_path() -> Path:
    """Authoritative enforcer snapshot (lock, heartbeat attestation, repair status)."""
    return secure_dir() / "enforcer_state.json"


def root_credential_path() -> Path:
    """The root credential file (present only after graduation; absent ⇒ dev mode)."""
    return secure_dir() / "root_credential"


def ensure_dir(path: Path, create: bool = True) -> Path:
    """Best-effort directory creation.

    Creates ``path`` when ``create`` is true, but never raises if the directory
    is owned by root and we are the unprivileged user (the installer is
    responsible for root-owned directories). Callers that must have the
    directory should check existence themselves.
    """
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Root-owned directory in the root layout; installer created it.
            logger.debug("No permission to create %s (expected under root layout)", path)
        except OSError as e:
            logger.warning("Could not create %s: %s", path, e)
    return path


def is_dev_mode() -> bool:
    """True while root enforcement is intentionally weakened for development.

    Dev mode is active whenever the root credential has not yet been written
    (graduation ceremony). In ``user`` layout there is no root tier, so dev mode
    is always considered active (nothing to graduate).
    """
    if layout() != "root":
        return True
    return not root_credential_path().exists()
