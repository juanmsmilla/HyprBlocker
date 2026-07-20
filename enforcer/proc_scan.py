"""Browser discovery via a root ``/proc`` scan — the primary kill path (R8).

The enforcer does NOT trust the user daemon's process reports (a compromised or
SIGSTOPped daemon could lie). Instead it walks ``/proc`` itself and matches the
realpath basename of ``/proc/<pid>/exe`` against the root-owned browser
kill-list, filtered to the target user's uid.

All scanning/parsing here is pure given a ``proc_root`` path, so tests exercise
it against a synthesized fake procfs tree in tmp — no root, no live processes.
The only privileged piece is :func:`kill_pids`, a thin ``os.kill`` wrapper.
"""

from __future__ import annotations

import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

# Kernel sentinel for "loginuid not set" (e.g. daemons started before login).
_LOGINUID_UNSET = 4294967295


def parse_proc_status(text: str) -> dict[str, str]:
    """Parse a ``/proc/<pid>/status`` document into a ``{field: raw_value}`` map.

    Values keep their internal tabs (e.g. ``Uid`` stays ``"1000\\t1000\\t1000\\t1000"``)
    so callers can pick the column they need. Malformed lines are skipped.
    """
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def status_real_uid(fields: dict[str, str]) -> int | None:
    """Real uid from a parsed status map (first column of ``Uid:``), or None."""
    raw = fields.get("Uid")
    if raw is None:
        return None
    try:
        return int(raw.split()[0])
    except (ValueError, IndexError):
        return None


def exe_realpath(proc_root: Path, pid: int) -> str | None:
    """Resolved target of ``/proc/<pid>/exe``, or None if unreadable/absent.

    Strips the kernel's `` (deleted)`` suffix so a browser whose binary was
    replaced mid-run (e.g. during a package update) still matches its basename.
    """
    link = proc_root / str(pid) / "exe"
    try:
        target = os.path.realpath(link, strict=False)
        if not os.path.islink(link) and not os.path.exists(link):
            return None
    except OSError:
        return None
    if target.endswith(" (deleted)"):
        target = target[: -len(" (deleted)")]
    return target


def _loginuid(proc_root: Path, pid: int) -> int | None:
    try:
        value = int((proc_root / str(pid) / "loginuid").read_text().strip())
    except (OSError, ValueError):
        return None
    return None if value == _LOGINUID_UNSET else value


def _pid_real_uid(proc_root: Path, pid: int) -> int | None:
    status_file = proc_root / str(pid) / "status"
    try:
        return status_real_uid(parse_proc_status(status_file.read_text()))
    except OSError:
        return None


def _uid_matches(proc_root: Path, pid: int, target_uid: int | None) -> bool:
    """True if the process belongs to the target user.

    Matches on the real uid from ``status`` (the normal case — browsers run as
    the user) or, failing that, on ``loginuid`` (catches uid games played by a
    process spawned from the user's login session). When ``target_uid`` is
    ``None`` the match is "any non-root process" — used as a fail-closed fallback
    when the enforcer cannot pin the login uid but a kill has already been
    decided (better to kill a browser owned by an unexpected uid than to let the
    kill silently no-op).
    """
    uid = _pid_real_uid(proc_root, pid)
    if target_uid is None:
        login = _loginuid(proc_root, pid)
        return (uid is not None and uid != 0) or (login is not None and login != 0)
    if uid == target_uid:
        return True
    return _loginuid(proc_root, pid) == target_uid


def find_session_uid(proc_root: Path, session_binaries: list[str]) -> int | None:
    """The uid of a running, non-root compositor process (R7/R8 session detection).

    This is derived from ``/proc`` — a source the user cannot delete while the
    session is live — so it is trustworthy where the file-ownership heuristic is
    not. Returns the real uid of the first matching non-root process, or ``None``
    if no such compositor is running.
    """
    wanted = set(session_binaries)
    try:
        entries = list(proc_root.iterdir())
    except OSError as e:
        logger.error("Cannot scan %s: %s", proc_root, e)
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        exe = exe_realpath(proc_root, pid)
        if exe is None or Path(exe).name not in wanted:
            continue
        uid = _pid_real_uid(proc_root, pid)
        if uid is not None and uid != 0:
            return uid
    return None


def find_browser_pids(
    proc_root: Path, browser_binaries: list[str], target_uid: int | None
) -> list[int]:
    """All pids under ``proc_root`` whose exe basename is a listed browser and
    whose uid matches ``target_uid`` (R8 primary kill selection).

    ``target_uid=None`` matches any non-root process — the fail-closed fallback
    when the login uid cannot be pinned. Pure given ``proc_root`` — pass
    ``Path("/proc")`` in production or a fake tree in tests. Entries that vanish
    mid-scan or are unreadable are skipped.
    """
    wanted = set(browser_binaries)
    matches: list[int] = []
    try:
        entries = list(proc_root.iterdir())
    except OSError as e:
        logger.error("Cannot scan %s: %s", proc_root, e)
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        exe = exe_realpath(proc_root, pid)
        if exe is None or Path(exe).name not in wanted:
            continue
        if _uid_matches(proc_root, pid, target_uid):
            matches.append(pid)
    return sorted(matches)


def kill_pids(pids: list[int], sig: signal.Signals = signal.SIGKILL) -> int:
    """Signal each pid (privileged wrapper around the pure scan). Returns the
    number successfully signalled; races with process exit are ignored."""
    killed = 0
    for pid in pids:
        try:
            os.kill(pid, sig)
            killed += 1
            logger.warning("Sent %s to pid %d", sig.name, pid)
        except ProcessLookupError:
            pass  # exited between scan and kill
        except OSError as e:
            logger.error("Failed to signal pid %d: %s", pid, e)
    return killed
