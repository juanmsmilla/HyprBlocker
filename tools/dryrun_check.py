"""Deep pre-reboot validator for the root-layout install.

Invoked by ``install-root.sh --check`` (and runnable directly as
``/opt/hyprblocker/.venv/bin/python -I /opt/hyprblocker/tools/dryrun_check.py --user <login>``).

The installer's job ends with files on disk; nothing new actually *runs* until
the next reboot. This validator therefore verifies everything that must already
hold **before** rebooting into the root layout, and exits nonzero if any check
fails:

- the /opt venv python exists, is world-traversable, imports ``daemon``, and is
  a NON-editable install (no ``*editable*.pth`` reaching back into a
  user-writable checkout — that would put user-writable code on root's import path);
- ``systemd-analyze verify`` passes for all four installed units, and each
  unit's content matches its canonical renderer in :mod:`daemon.system_assets`;
- every system-wide native-messaging manifest is valid JSON, points at the /opt
  host, and carries the pinned extension ID;
- the ``/var/lib/hyprblocker`` layout, ownerships, and modes are correct;
- ``secure/lock.json`` / ``secure/enforcement.json`` are present and parseable;
- the sudoers drop-in passes ``visudo -cf``;
- the rewritten ``~/.config/systemd/user/hyprblocker.service`` cutover shim
  resolves (canonical content, ExecStart target executable).

Pure helpers (JSON/ID validation, editable-venv detection, unit validation)
take strings/paths and do no privileged I/O — they are unit-tested in
``tests/test_dryrun_check.py``. The privileged wrappers below call them.

Run as root: ``visudo -cf`` and some stat calls need it.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from daemon import system_assets

CODE_ROOT = Path(system_assets.CODE_ROOT)
VENV_DIR = CODE_ROOT / ".venv"
VENV_PYTHON = Path(system_assets.VENV_PYTHON)
NATIVE_HOST_PATH = Path(system_assets.NATIVE_HOST_PATH)
STATE_DIR = Path(system_assets.STATE_DIR)
GROUP = "hyprblocker"

SUDOERS_PATH = Path("/etc/sudoers.d/hyprblocker-pacman")
ETC_USER_UNIT = Path("/etc/systemd/user") / system_assets.SERVICE_NAME
ENFORCER_UNIT = Path("/etc/systemd/system") / system_assets.ENFORCER_SERVICE_NAME
BREAKGLASS_UNIT = Path("/etc/systemd/system") / system_assets.BREAKGLASS_SERVICE_NAME
BREAKGLASS_TIMER = BREAKGLASS_UNIT.with_suffix(".timer")

Runner = Callable[[Sequence[str]], tuple[int, str]]


# ---------------------------------------------------------------------------
# Pure helpers (no privileged I/O beyond the paths handed in) — unit-tested.
# ---------------------------------------------------------------------------


def find_editable_pth(venv_dir: Path) -> list[Path]:
    """Return editable-install ``.pth`` files under the venv's site-packages.

    Both spellings are caught: pip writes ``__editable__.<name>.pth``, uv/hatch
    historically ``_<name>__editable__``-style names. Any ``.pth`` whose
    filename mentions "editable" is a red flag: it splices an external (usually
    user-writable) directory onto the import path of a venv that root executes.
    """
    hits: list[Path] = []
    for site_packages in venv_dir.glob("lib*/python*/site-packages"):
        for pth in site_packages.glob("*.pth"):
            if "editable" in pth.name.lower():
                hits.append(pth)
    return sorted(hits)


def validate_manifest(text: str, browser: Literal["chrome", "firefox"]) -> list[str]:
    """Validate a rendered native-messaging manifest. Returns problem strings."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]
    if not isinstance(data, dict):
        return ["manifest is not a JSON object"]

    problems: list[str] = []
    if data.get("name") != "com.hyprblocker.host":
        problems.append(f"unexpected host name {data.get('name')!r}")
    if data.get("type") != "stdio":
        problems.append(f"unexpected type {data.get('type')!r}")
    if data.get("path") != str(NATIVE_HOST_PATH):
        problems.append(f"path {data.get('path')!r} != {str(NATIVE_HOST_PATH)!r}")

    if browser == "chrome":
        origins = data.get("allowed_origins") or []
        expected = f"chrome-extension://{system_assets.EXTENSION_ID}/"
        if expected not in origins:
            problems.append(f"pinned extension ID missing from allowed_origins {origins!r}")
    else:
        extensions = data.get("allowed_extensions") or []
        if system_assets.FIREFOX_EXTENSION_ID not in extensions:
            problems.append(f"pinned Firefox ID missing from allowed_extensions {extensions!r}")
    return problems


def validate_lock_json(text: str) -> list[str]:
    """Validate the seeded ``secure/lock.json``. Returns problem strings.

    A ``null`` ``locked_until`` is legal (no lock recorded), but the key must
    exist and any non-null value must be ISO-8601 parseable — exactly what
    ``daemon.settings_lock._read_root_lock`` will consume after reboot.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]
    if not isinstance(data, dict):
        return ["lock file is not a JSON object"]
    if "locked_until" not in data:
        return ["missing 'locked_until' key"]
    raw = data["locked_until"]
    if raw is None:
        return []
    try:
        datetime.fromisoformat(raw)
    except TypeError, ValueError:
        return [f"unparseable locked_until value {raw!r}"]
    return []


def validate_user_unit(text: str, canonical: str) -> list[str]:
    """Validate the cutover user unit against the canonical rendering.

    The runtime repair logic (``daemon.service_enforcer``) compares against the
    canonical ``system_assets.user_unit()`` content, so anything other than an
    exact match will be flagged/repaired after reboot — surface it now.
    """
    problems: list[str] = []
    exec_line = f"ExecStart={system_assets.VENV_PYTHON} -I -m daemon.main"
    if exec_line not in text:
        problems.append(f"missing canonical ExecStart line ({exec_line!r})")
    if "Environment=HYPRBLOCKER_LAYOUT=root" not in text:
        problems.append("missing Environment=HYPRBLOCKER_LAYOUT=root")
    if text != canonical:
        problems.append("content differs from canonical daemon.system_assets user_unit()")
    return problems


def world_inaccessible_components(path: Path) -> list[Path]:
    """Paths an unprivileged user cannot traverse on the way to ``path``.

    Guards against e.g. a uv-managed interpreter symlinked under ``/root``
    (mode 0700): root can run it, the user daemon cannot — a failure that would
    only surface at first boot. Checks o+x on every ancestor directory and
    o+rx on the final file, following symlinks.
    """
    bad: list[Path] = []
    real = path.resolve()
    for parent in real.parents:
        try:
            if not parent.stat().st_mode & stat.S_IXOTH:
                bad.append(parent)
        except OSError:
            bad.append(parent)
    try:
        mode = real.stat().st_mode
        if not (mode & stat.S_IXOTH and mode & stat.S_IROTH):
            bad.append(real)
    except OSError:
        bad.append(real)
    return bad


@dataclass(frozen=True)
class StatExpectation:
    """Expected kind/mode/ownership for one filesystem entry."""

    path: Path
    kind: Literal["dir", "file"]
    mode: int
    owner: str
    group: str


def evaluate_stat(
    exp: StatExpectation, *, is_dir: bool, mode: int, owner: str, group: str
) -> list[str]:
    """Pure comparison of an observed stat against an expectation."""
    problems: list[str] = []
    if exp.kind == "dir" and not is_dir:
        problems.append("expected a directory")
    if exp.kind == "file" and is_dir:
        problems.append("expected a regular file")
    if mode != exp.mode:
        problems.append(f"mode {mode:04o} != {exp.mode:04o}")
    if owner != exp.owner:
        problems.append(f"owner {owner!r} != {exp.owner!r}")
    if group != exp.group:
        problems.append(f"group {group!r} != {exp.group!r}")
    return problems


# ---------------------------------------------------------------------------
# Privileged wrappers (filesystem stat, subprocess) — thin, call pure helpers.
# ---------------------------------------------------------------------------


def _run(argv: Sequence[str]) -> tuple[int, str]:
    proc = subprocess.run(list(argv), capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _check_stat(exp: StatExpectation) -> list[str]:
    try:
        st = exp.path.stat()
    except FileNotFoundError:
        return ["missing"]
    except OSError as e:
        return [f"stat failed: {e}"]
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return evaluate_stat(
        exp,
        is_dir=stat.S_ISDIR(st.st_mode),
        mode=stat.S_IMODE(st.st_mode),
        owner=owner,
        group=group,
    )


def _check_venv(run: Runner) -> list[str]:
    if not VENV_PYTHON.is_file():
        return [f"{VENV_PYTHON} missing — did install-root.sh run uv sync?"]
    problems: list[str] = []
    if not os.access(VENV_PYTHON, os.X_OK):
        problems.append(f"{VENV_PYTHON} is not executable")
    editable = find_editable_pth(VENV_DIR)
    if editable:
        problems.append(
            "editable-install .pth files (user-writable code on root's import path): "
            + ", ".join(str(p) for p in editable)
        )
    blocked = world_inaccessible_components(VENV_PYTHON)
    if blocked:
        problems.append(
            "interpreter not world-accessible via: " + ", ".join(str(p) for p in blocked)
        )
    rc, out = run([str(VENV_PYTHON), "-I", "-c", "import daemon.system_assets, daemon.paths"])
    if rc != 0:
        problems.append(f"venv python cannot import daemon (rc={rc}): {out}")
    # The root units run `-m enforcer.main` / `-m enforcer.breakglass_runner`;
    # a venv without the enforcer package crash-loops both after reboot.
    rc, out = run([str(VENV_PYTHON), "-I", "-c", "import enforcer.main, enforcer.breakglass_runner"])
    if rc != 0:
        problems.append(f"venv python cannot import enforcer (rc={rc}): {out}")
    return problems


# Prefix marking a non-fatal warning (does not block reboot). See run_checks.record.
WARN = "WARN::"

# systemd-analyze substrings that mean "the checker's environment couldn't host a
# manager to verify against" rather than "the unit is malformed". Verifying a *user*
# unit needs a user manager; running the checker as root under sudo has none, so this
# is an environment limitation, not a unit defect.
_ENV_VERIFY_MARKERS = (
    "Failed to initialize manager",
    "Failed to lookup RuntimeDirectory",
    "No such device or address",
    "Failed to get D-Bus connection",
    "Failed to connect to bus",
    "Failed to create /run/user",
)


def is_env_verify_failure(out: str) -> bool:
    """True if systemd-analyze failed for lack of a manager context, not a unit defect."""
    return any(marker in out for marker in _ENV_VERIFY_MARKERS)


def _verify_user_unit(path: Path, user: str | None, run: Runner) -> tuple[int, str]:
    """Verify a *user* unit in the target user's session context.

    A user unit can only be meaningfully verified against a user manager. The
    checker runs as root (sudo), which has none — so re-enter the login user's
    session (they are logged into Hyprland, so ``/run/user/<uid>`` exists) and run
    ``systemd-analyze --user verify`` there. Falls back to a plain ``--user`` run
    when the uid can't be resolved.
    """
    base = ["systemd-analyze", "--user", "verify", str(path)]
    if user is None:
        return run(base)
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return run(base)
    return run(
        [
            "sudo", "-u", user, "env",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            *base,
        ]
    )


def _check_unit(
    path: Path, canonical: str, run: Runner, *, user_scope: bool, user: str | None = None
) -> list[str]:
    if not path.is_file():
        return ["missing"]
    problems: list[str] = []
    try:
        text = path.read_text()
    except OSError as e:
        return [f"unreadable: {e}"]
    if text != canonical:
        problems.append("content differs from canonical daemon.system_assets rendering")

    if user_scope:
        rc, out = _verify_user_unit(path, user, run)
    else:
        rc, out = run(["systemd-analyze", "verify", str(path)])

    if rc != 0:
        if user_scope and is_env_verify_failure(out):
            # Can't host a user manager to verify against from this context. The
            # canonical-content check above already covers unit correctness; flag
            # this as a warning, not a reboot-blocking failure.
            first = out.splitlines()[0] if out else "(no output)"
            problems.append(
                WARN
                + f"could not verify user unit from root context — environment, not a "
                f"unit defect ({first}). Verify manually as the user: "
                f"systemd-analyze --user verify {path}"
            )
        else:
            problems.append(f"systemd-analyze verify failed (rc={rc}): {out}")
    return problems


def _check_home_unit(user: str) -> list[str]:
    try:
        home = Path(pwd.getpwnam(user).pw_dir)
    except KeyError:
        return [f"user {user!r} does not exist"]
    unit = home / ".config" / "systemd" / "user" / system_assets.SERVICE_NAME
    if not unit.is_file():
        # Absence is legal in two states: no per-user unit existed at install
        # time (the /etc/systemd/user copy is used as-is), or the daemon's
        # first root-layout boot already deleted the shim as designed. Only a
        # *stale* shim (wrong ExecStart) is dangerous, and that is checked below.
        return [WARN + f"{unit} absent (normal after the first root-layout boot)"]
    try:
        text = unit.read_text()
    except OSError as e:
        return [f"unreadable: {e}"]
    problems = validate_user_unit(text, system_assets.user_unit())
    if not VENV_PYTHON.is_file() or not os.access(VENV_PYTHON, os.X_OK):
        problems.append(f"ExecStart target {VENV_PYTHON} does not resolve to an executable")
    return problems


def _check_manifests() -> list[tuple[str, list[str]]]:
    results: list[tuple[str, list[str]]] = []
    targets = [(d, "chrome") for d in system_assets.CHROME_MANIFEST_DIRS] + [
        (d, "firefox") for d in system_assets.FIREFOX_MANIFEST_DIRS
    ]
    for directory, browser in targets:
        manifest = Path(directory) / system_assets.MANIFEST_FILENAME
        if not manifest.is_file():
            results.append((str(manifest), ["missing"]))
            continue
        try:
            text = manifest.read_text()
        except OSError as e:
            results.append((str(manifest), [f"unreadable: {e}"]))
            continue
        results.append((str(manifest), validate_manifest(text, browser)))
    return results


def _check_group(user: str) -> list[str]:
    try:
        group = grp.getgrnam(GROUP)
    except KeyError:
        return [f"group {GROUP!r} does not exist"]
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        return [f"user {user!r} does not exist"]
    if user in group.gr_mem or pw.pw_gid == group.gr_gid:
        return []
    return [f"user {user!r} is not a member of group {GROUP!r}"]


def _check_sudoers(run: Runner) -> list[str]:
    problems = _check_stat(StatExpectation(SUDOERS_PATH, "file", 0o440, owner="root", group="root"))
    if "missing" in problems:
        return problems
    rc, out = run(["visudo", "-cf", str(SUDOERS_PATH)])
    if rc != 0:
        problems.append(f"visudo -cf failed (rc={rc}): {out}")
    return problems


def _check_secure_file(path: Path, validator: Callable[[str], list[str]]) -> list[str]:
    if not path.is_file():
        return ["missing"]
    try:
        text = path.read_text()
    except OSError as e:
        return [f"unreadable: {e}"]
    return validator(text)


def _validate_enforcement_json(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]
    if not isinstance(data, dict):
        return ["enforcement file is not a JSON object"]
    if not isinstance(data.get("browsers"), list):
        return ["missing/invalid 'browsers' kill-list"]
    return []


def _check_extension_key() -> list[str]:
    """The pinned ``"key"`` in extension/manifest.json must survive the rsync.

    If it is lost, the extension ID changes and the daemon kills every browser
    even with the extension installed (see docs/TECHNICAL_CONCEPTS.md).
    """
    manifest = CODE_ROOT / "extension" / "manifest.json"
    if not manifest.is_file():
        return ["missing"]
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"unreadable/invalid: {e}"]
    if not data.get("key"):
        return ["the pinned 'key' field is absent — extension ID would change"]
    return []


def _layout_expectations(user: str) -> list[StatExpectation]:
    secure = STATE_DIR / "secure"
    return [
        StatExpectation(STATE_DIR, "dir", 0o775, owner="root", group=GROUP),
        StatExpectation(secure, "dir", 0o755, owner="root", group="root"),
        StatExpectation(STATE_DIR / "logs", "dir", 0o775, owner="root", group=GROUP),
        StatExpectation(STATE_DIR / "requests", "dir", 0o775, owner="root", group=GROUP),
        StatExpectation(STATE_DIR / "config.json", "file", 0o664, owner=user, group=GROUP),
        StatExpectation(STATE_DIR / "blocker.db", "file", 0o664, owner=user, group=GROUP),
        StatExpectation(secure / "lock.json", "file", 0o644, owner="root", group="root"),
        StatExpectation(secure / "enforcement.json", "file", 0o644, owner="root", group="root"),
        StatExpectation(NATIVE_HOST_PATH, "file", 0o755, owner="root", group="root"),
    ]


def run_checks(
    user: str, *, run: Runner = _run, report: Callable[[str], None] = print
) -> list[str]:
    """Run every pre-reboot check; return the list of failure strings (empty = safe)."""
    failures: list[str] = []

    def record(label: str, problems: list[str]) -> None:
        warns = [p[len(WARN):] for p in problems if p.startswith(WARN)]
        fails = [p for p in problems if not p.startswith(WARN)]
        if fails:
            failures.extend(f"{label}: {p}" for p in fails)
            report(f"FAIL  {label}: " + "; ".join(fails))
        elif warns:
            report(f"warn  {label}: " + "; ".join(warns))
        else:
            report(f"ok    {label}")

    record("group membership", _check_group(user))
    record(f"venv ({VENV_PYTHON})", _check_venv(run))
    record("extension manifest 'key' pin", _check_extension_key())

    record(
        f"unit {ETC_USER_UNIT}",
        _check_unit(ETC_USER_UNIT, system_assets.user_unit(), run, user_scope=True, user=user),
    )
    record(
        f"unit {ENFORCER_UNIT}",
        _check_unit(ENFORCER_UNIT, system_assets.enforcer_unit(), run, user_scope=False),
    )
    record(
        f"unit {BREAKGLASS_UNIT}",
        _check_unit(BREAKGLASS_UNIT, system_assets.breakglass_unit(), run, user_scope=False),
    )
    record(
        f"unit {BREAKGLASS_TIMER}",
        _check_unit(BREAKGLASS_TIMER, system_assets.breakglass_timer(), run, user_scope=False),
    )
    record("cutover shim (~/.config user unit)", _check_home_unit(user))

    for label, problems in _check_manifests():
        record(f"manifest {label}", problems)

    for exp in _layout_expectations(user):
        record(f"layout {exp.path}", _check_stat(exp))

    record(
        "secure/lock.json content",
        _check_secure_file(STATE_DIR / "secure" / "lock.json", validate_lock_json),
    )
    record(
        "secure/enforcement.json content",
        _check_secure_file(STATE_DIR / "secure" / "enforcement.json", _validate_enforcement_json),
    )
    record(f"sudoers ({SUDOERS_PATH})", _check_sudoers(run))

    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify everything the root-layout reboot depends on (pre-reboot)."
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("SUDO_USER"),
        help="login user the install targeted (default: $SUDO_USER)",
    )
    args = parser.parse_args(argv)
    if not args.user or args.user == "root":
        print("error: pass --user <login> (or run via sudo so $SUDO_USER is set)", file=sys.stderr)
        return 2

    failures = run_checks(args.user)
    if failures:
        print(f"\n{len(failures)} problem(s) found — NOT safe to reboot:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("\nAll checks passed — safe to reboot into the root layout.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
