"""One-time migration of the legacy config directory after the rename.

The project was renamed from ``website-blocker`` to ``hyprblocker``. The
rename shipped while a pre-rename daemon was still running (by design it
cannot be stopped mid-session), so the config directory move happens here,
at daemon startup, once the old daemon can no longer be writing to it —
in practice, on the first start after a reboot.

This must run before anything reads or creates config/log files in the new
location (``load_config()`` creates a default config.json if none exists,
which would make the directory look already-migrated).
"""

import json
import shutil
import socket
import sys
from pathlib import Path

LEGACY_CONFIG_DIR = Path.home() / ".config" / "website-blocker"
CONFIG_DIR = Path.home() / ".config" / "hyprblocker"

# Files whose presence marks a directory as a real (non-empty) install
_MARKER_FILES = ("config.json", "blocker.db")


def _note(message: str) -> None:
    # Logging is not configured yet when this runs (the log file lives in the
    # directory being migrated), so write to stderr for the journal.
    print(f"legacy-migration: {message}", file=sys.stderr)


def _legacy_daemon_port(legacy_dir: Path) -> int:
    """Read the daemon port from the legacy config, defaulting to 8765."""
    try:
        with open(legacy_dir / "config.json") as f:
            return int(json.load(f).get("daemon", {}).get("port", 8765))
    except (OSError, ValueError, json.JSONDecodeError):
        return 8765


def _port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def migrate_legacy_config_dir(
    legacy_dir: Path = LEGACY_CONFIG_DIR,
    new_dir: Path = CONFIG_DIR,
    port_in_use=_port_in_use,
) -> str:
    """Move the legacy config directory to its new location, once.

    Returns "migrated", "deferred", or "none". Never moves files while a
    pre-rename daemon is still alive on the daemon port (it would be
    writing to the legacy directory), and never overwrites files already
    present in the new location.

    Callers MUST treat "deferred" as fatal for this process: continuing
    would create a default config in the new location, which would make
    the migration skip forever and silently drop all existing blocks,
    settings, and locks.
    """
    if not any((legacy_dir / marker).exists() for marker in _MARKER_FILES):
        return "none"  # fresh install or already migrated

    if any((new_dir / marker).exists() for marker in _MARKER_FILES):
        _note(f"{new_dir} already populated; leaving {legacy_dir} untouched")
        return "none"

    if port_in_use(_legacy_daemon_port(legacy_dir)):
        # A pre-rename daemon still owns the legacy directory. The caller
        # exits; systemd restarts it and the migration runs once the old
        # daemon is gone (in practice, after the next reboot).
        _note("pre-rename daemon still running; deferring migration")
        return "deferred"

    if not new_dir.exists():
        legacy_dir.rename(new_dir)
        _note(f"moved {legacy_dir} -> {new_dir}")
        return "migrated"

    # New directory exists but holds no real data (e.g. stray logs from a
    # transition-period watchdog): merge without overwriting.
    for entry in legacy_dir.iterdir():
        target = new_dir / entry.name
        if target.exists():
            continue
        shutil.move(str(entry), str(target))
    try:
        legacy_dir.rmdir()
    except OSError:
        _note(f"left non-empty {legacy_dir} behind (safe to delete)")
    _note(f"merged {legacy_dir} into existing {new_dir}")
    return "migrated"
