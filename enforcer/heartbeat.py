"""Heartbeat attestation — challenge/echo helpers for the enforcer (R4).

Protocol: each tick the enforcer writes a fresh random nonce to a root-owned,
world-readable challenge file under ``secure/``. The user daemon reads it and
echoes it back — together with the current ``boot_id``
(``/proc/sys/kernel/random/boot_id``), its pid, and a CLOCK_MONOTONIC stamp —
into the group-writable ``requests/`` directory. The enforcer then verifies:

- the nonce matches the challenge it actually issued (no replay of old echoes);
- the ``boot_id`` matches the current boot (cross-boot replays rejected);
- the monotonic delta is non-negative and fresh (a stamp "from the future" or
  older than the staleness window is rejected);
- the attesting pid looks like the real daemon: its exe is the root-owned
  venv's interpreter (either under ``/opt/hyprblocker/.venv`` or the resolved
  target of its ``bin/python*`` symlinks — the kernel resolves symlinks at
  exec, so a uv-built venv reports the base interpreter as the exe), it is
  not stopped (``State != T``, i.e. not SIGSTOPped), and it is not being
  traced (``TracerPid == 0``).

HONESTY NOTE (from the adversarial review): this is friction, not invincibility.
A determined same-UID forger can read the world-readable challenge and write a
perfectly-formed echo while pointing at (or briefly exec-ing) the real venv
python — attestation cannot cryptographically bind "policy is actually being
enforced". The *primary* defense is therefore independent verification: the
enforcer does its own /proc browser scan and kills browsers itself when the
attestation goes stale (R8), so forging the heartbeat only silences the alarm,
it does not disable enforcement. ``tests/test_enforcer_heartbeat.py`` pins this
caveat with an explicit forger test.

All verification logic is pure given its inputs; the file read/write wrappers
at the bottom are the only I/O.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from daemon import paths, system_assets
from enforcer.proc_scan import exe_realpath, parse_proc_status

logger = logging.getLogger(__name__)

# The attesting daemon must run from the root-owned venv (no user-writable exe).
EXPECTED_EXE_PREFIX = f"{system_assets.CODE_ROOT}/.venv"


def resolve_expected_exes(venv_prefix: str = EXPECTED_EXE_PREFIX) -> frozenset[str]:
    """Resolved targets of the venv's ``bin/python*`` — the values
    ``/proc/<pid>/exe`` actually reports for a daemon started via the venv.

    The kernel resolves symlinks at exec time and uv-built venvs symlink
    ``bin/python`` to the base interpreter (e.g. ``/usr/bin/python3.14``), so
    the attesting exe lands *outside* the venv prefix. Trusting the resolution
    is sound: both the symlink (root-owned /opt) and its target are
    root-write-only.
    """
    exes: set[str] = set()
    for p in Path(venv_prefix).glob("bin/python*"):
        try:
            exes.add(str(p.resolve()))
        except OSError:
            continue
    return frozenset(exes)

# Default freshness window for an echo's monotonic stamp.
DEFAULT_MAX_AGE_SECONDS = 90.0

BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


@dataclass(frozen=True)
class EchoResponse:
    """The daemon's answer to a challenge, parsed from the echo file."""

    nonce: str
    boot_id: str
    pid: int
    monotonic: float


@dataclass(frozen=True)
class PidInfo:
    """What /proc says about the attesting pid at verification time."""

    exe_realpath: str | None
    state: str | None  # single-letter process state, e.g. "S", "R", "T"
    tracer_pid: int | None


@dataclass(frozen=True)
class AttestationVerdict:
    ok: bool
    reason: str


def new_challenge() -> str:
    """A fresh random nonce for the next challenge."""
    return secrets.token_hex(16)


def parse_echo(text: str) -> EchoResponse | None:
    """Parse the daemon-written echo file; None on any malformation (fail closed)."""
    try:
        data = json.loads(text)
        return EchoResponse(
            nonce=str(data["nonce"]),
            boot_id=str(data["boot_id"]).strip(),
            pid=int(data["pid"]),
            monotonic=float(data["monotonic"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def pid_info_from_status(status_text: str, exe: str | None) -> PidInfo:
    """Build a :class:`PidInfo` from a raw ``/proc/<pid>/status`` document. Pure."""
    fields = parse_proc_status(status_text)
    state_raw = fields.get("State", "")
    state = state_raw.split()[0] if state_raw.split() else None
    try:
        tracer = int(fields.get("TracerPid", "").split()[0])
    except (ValueError, IndexError):
        tracer = None
    return PidInfo(exe_realpath=exe, state=state, tracer_pid=tracer)


def verify_attestation(
    issued_nonce: str | None,
    echo: EchoResponse | None,
    current_boot_id: str,
    now_monotonic: float,
    pid_info: PidInfo | None,
    *,
    expected_exe_prefix: str = EXPECTED_EXE_PREFIX,
    expected_exes: frozenset[str] = frozenset(),
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> AttestationVerdict:
    """Pure verification of one challenge/echo round (R4). Fail closed everywhere.

    ``pid_info`` is what /proc reported for ``echo.pid`` at verification time
    (None if the pid vanished). See the module docstring for the honesty caveat:
    a passing verdict means "looks like the real daemon", not proof of it.
    """
    if issued_nonce is None:
        return AttestationVerdict(False, "no challenge outstanding")
    if echo is None:
        return AttestationVerdict(False, "no (or malformed) echo")
    if echo.nonce != issued_nonce:
        return AttestationVerdict(False, "nonce mismatch (stale or replayed echo)")
    if echo.boot_id != current_boot_id:
        return AttestationVerdict(False, "boot_id mismatch (cross-boot echo)")
    delta = now_monotonic - echo.monotonic
    if delta < 0:
        return AttestationVerdict(False, "negative monotonic delta (stamp from the future)")
    if delta > max_age_seconds:
        return AttestationVerdict(False, f"echo stale ({delta:.0f}s > {max_age_seconds:.0f}s)")
    if pid_info is None:
        return AttestationVerdict(False, "attesting pid vanished")
    exe = pid_info.exe_realpath
    under_venv = bool(exe) and exe.startswith(expected_exe_prefix.rstrip("/") + "/")
    if not exe or not (under_venv or exe in expected_exes):
        return AttestationVerdict(
            False,
            f"attesting exe {exe!r} is not the {expected_exe_prefix} interpreter",
        )
    if pid_info.state == "T":
        return AttestationVerdict(False, "attesting pid is stopped (SIGSTOP/ptrace-stop)")
    if pid_info.tracer_pid != 0:
        return AttestationVerdict(False, f"attesting pid is traced (TracerPid={pid_info.tracer_pid})")
    return AttestationVerdict(True, "attestation verified")


# ---------------------------------------------------------------------------
# I/O wrappers (thin; everything above is pure)
# ---------------------------------------------------------------------------

def challenge_path() -> Path:
    """Root-written, world-readable challenge file the daemon polls."""
    return paths.secure_dir() / "heartbeat_challenge.json"


def echo_path() -> Path:
    """Daemon-written echo file in the group-writable requests directory."""
    return paths.requests_dir() / "heartbeat_echo.json"


def read_boot_id(path: Path = BOOT_ID_PATH) -> str:
    """The kernel's boot UUID; empty string if unreadable (never matches)."""
    try:
        return path.read_text().strip()
    except OSError as e:
        logger.error("Cannot read boot_id from %s: %s", path, e)
        return ""


def write_challenge(nonce: str, boot_id: str) -> None:
    """Enforcer side: publish the current challenge (atomic, world-readable)."""
    target = challenge_path()
    paths.ensure_dir(target.parent)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"nonce": nonce, "boot_id": boot_id}))
    tmp.chmod(0o644)
    tmp.replace(target)


def read_challenge() -> str | None:
    """Daemon side: the currently published challenge nonce, or None."""
    try:
        return str(json.loads(challenge_path().read_text())["nonce"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def write_echo(nonce: str, pid: int | None = None) -> bool:
    """Daemon side: answer a challenge. Called from the user daemon's heartbeat
    loop (integration hook — see enforcer/main.py). Returns success."""
    import os

    payload = {
        "nonce": nonce,
        "boot_id": read_boot_id(),
        "pid": pid if pid is not None else os.getpid(),
        "monotonic": time.monotonic(),
    }
    target = echo_path()
    paths.ensure_dir(target.parent)
    try:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(target)
        return True
    except OSError as e:
        logger.error("Cannot write heartbeat echo %s: %s", target, e)
        return False


def read_echo() -> EchoResponse | None:
    """Enforcer side: the daemon's latest echo, or None."""
    try:
        return parse_echo(echo_path().read_text())
    except OSError:
        return None


def read_pid_info(proc_root: Path, pid: int) -> PidInfo | None:
    """Gather :class:`PidInfo` for a pid from ``proc_root`` (fake-able in tests)."""
    status_file = proc_root / str(pid) / "status"
    try:
        status_text = status_file.read_text()
    except OSError:
        return None
    return pid_info_from_status(status_text, exe_realpath(proc_root, pid))
