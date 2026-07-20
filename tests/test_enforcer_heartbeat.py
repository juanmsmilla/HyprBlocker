"""Tests for the heartbeat attestation helpers (enforcer.heartbeat).

Everything verified here is pure given its inputs. The final test pins the
design's honest caveat (R4): a determined same-UID forger CAN pass attestation
— which is exactly why the primary defense is the enforcer's own independent
/proc browser scan (R8), not this handshake.
"""

import json

from enforcer import heartbeat
from enforcer.heartbeat import (
    AttestationVerdict,
    EchoResponse,
    PidInfo,
    parse_echo,
    pid_info_from_status,
    verify_attestation,
)

BOOT = "0f2a-boot"
NONCE = "cafe" * 8
VENV = "/opt/hyprblocker/.venv"


def _echo(**overrides):
    payload = dict(nonce=NONCE, boot_id=BOOT, pid=4242, monotonic=1_000.0)
    payload.update(overrides)
    return EchoResponse(**payload)


def _pid_info(**overrides):
    info = dict(
        exe_realpath=f"{VENV}/bin/python3.14",
        state="S",
        tracer_pid=0,
    )
    info.update(overrides)
    return PidInfo(**info)


def _verify(**overrides) -> AttestationVerdict:
    args = dict(
        issued_nonce=NONCE,
        echo=_echo(),
        current_boot_id=BOOT,
        now_monotonic=1_030.0,
        pid_info=_pid_info(),
        max_age_seconds=90.0,
    )
    args.update(overrides)
    return verify_attestation(**args)


def test_valid_attestation_passes():
    verdict = _verify()
    assert verdict.ok is True


def test_no_echo_fails():
    assert _verify(echo=None).ok is False


def test_no_outstanding_challenge_fails():
    assert _verify(issued_nonce=None).ok is False


def test_nonce_mismatch_fails():
    verdict = _verify(echo=_echo(nonce="beef" * 8))
    assert verdict.ok is False
    assert "nonce" in verdict.reason


def test_cross_boot_echo_rejected():
    verdict = _verify(echo=_echo(boot_id="previous-boot"))
    assert verdict.ok is False
    assert "boot_id" in verdict.reason


def test_negative_monotonic_delta_rejected():
    # Echo stamped "in the future" relative to the enforcer's clock: bogus.
    verdict = _verify(echo=_echo(monotonic=2_000.0), now_monotonic=1_000.0)
    assert verdict.ok is False
    assert "negative" in verdict.reason


def test_stale_echo_rejected():
    verdict = _verify(echo=_echo(monotonic=100.0), now_monotonic=1_000.0)
    assert verdict.ok is False
    assert "stale" in verdict.reason


def test_vanished_attesting_pid_rejected():
    assert _verify(pid_info=None).ok is False


def test_exe_outside_root_venv_rejected():
    # A copy of the interpreter in a user-writable dir must not attest.
    verdict = _verify(pid_info=_pid_info(exe_realpath="/home/u/.venv/bin/python"))
    assert verdict.ok is False
    assert _verify(pid_info=_pid_info(exe_realpath=None)).ok is False


def test_exe_prefix_match_is_path_aware():
    # "/opt/hyprblocker/.venv-evil/..." must not pass a startswith check.
    verdict = _verify(
        pid_info=_pid_info(exe_realpath="/opt/hyprblocker/.venv-evil/bin/python")
    )
    assert verdict.ok is False


def test_symlinked_venv_interpreter_accepted():
    # uv venvs symlink bin/python to the base interpreter; the kernel resolves
    # the symlink at exec, so /proc/<pid>/exe reports e.g. /usr/bin/python3.14.
    # The resolved target (passed via expected_exes) must attest.
    verdict = _verify(
        pid_info=_pid_info(exe_realpath="/usr/bin/python3.14"),
        expected_exes=frozenset({"/usr/bin/python3.14"}),
    )
    assert verdict.ok is True


def test_expected_exes_is_exact_match_only():
    # expected_exes must not open the door to arbitrary interpreters.
    verdict = _verify(
        pid_info=_pid_info(exe_realpath="/usr/bin/python3.13"),
        expected_exes=frozenset({"/usr/bin/python3.14"}),
    )
    assert verdict.ok is False


def test_resolve_expected_exes_resolves_symlinks(tmp_path):
    real = tmp_path / "usr" / "bin" / "python3.14"
    real.parent.mkdir(parents=True)
    real.write_text("")
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(real)
    (bin_dir / "python3").symlink_to(bin_dir / "python")
    assert heartbeat.resolve_expected_exes(str(tmp_path / "venv")) == frozenset({str(real)})


def test_sigstopped_attester_rejected():
    verdict = _verify(pid_info=_pid_info(state="T"))
    assert verdict.ok is False
    assert "stopped" in verdict.reason


def test_traced_attester_rejected():
    verdict = _verify(pid_info=_pid_info(tracer_pid=999))
    assert verdict.ok is False
    assert "traced" in verdict.reason
    # Unknown TracerPid (unparseable status) also fails closed.
    assert _verify(pid_info=_pid_info(tracer_pid=None)).ok is False


def test_documented_limitation_same_uid_forger_passes():
    """R4 honesty test: attestation is friction, not proof.

    A same-UID attacker can read the world-readable challenge and craft a
    perfect echo while running (or naming) a process whose exe resolves under
    the root venv. This test PINS that limitation so nobody later mistakes the
    handshake for a security boundary: the verdict below is OK by design, and
    the real defense is the enforcer's independent /proc browser scan + kill
    (R8), which a forged heartbeat cannot switch off.
    """
    forged = _verify(
        echo=_echo(pid=6666),
        pid_info=_pid_info(exe_realpath=f"{VENV}/bin/python3.14"),
    )
    assert forged.ok is True  # documented residual weakness, not a regression


# ---------------------------------------------------------------------------
# Parsers and file helpers
# ---------------------------------------------------------------------------

def test_parse_echo_roundtrip():
    text = json.dumps({"nonce": NONCE, "boot_id": BOOT, "pid": 7, "monotonic": 1.5})
    echo = parse_echo(text)
    assert echo == EchoResponse(nonce=NONCE, boot_id=BOOT, pid=7, monotonic=1.5)


def test_parse_echo_malformed_returns_none():
    assert parse_echo("not json") is None
    assert parse_echo(json.dumps({"nonce": NONCE})) is None
    assert parse_echo(json.dumps({"nonce": NONCE, "boot_id": BOOT, "pid": "x", "monotonic": 0})) is None


def test_pid_info_from_status_parses_state_and_tracer():
    status = "Name:\tpython\nState:\tT (stopped)\nUid:\t1000\t1000\t1000\t1000\nTracerPid:\t55\n"
    info = pid_info_from_status(status, "/opt/hyprblocker/.venv/bin/python")
    assert info.state == "T"
    assert info.tracer_pid == 55


def test_pid_info_from_status_tolerates_garbage():
    info = pid_info_from_status("", None)
    assert info.state is None
    assert info.tracer_pid is None


def test_challenge_write_read_roundtrip(tmp_path, monkeypatch):
    # conftest already redirects HYPRBLOCKER_* into tmp; exercise the file I/O.
    heartbeat.write_challenge("abc123", BOOT)
    assert heartbeat.read_challenge() == "abc123"


def test_write_and_read_echo_roundtrip(monkeypatch):
    monkeypatch.setattr(heartbeat, "read_boot_id", lambda path=None: BOOT)
    assert heartbeat.write_echo("abc123", pid=77) is True
    echo = heartbeat.read_echo()
    assert echo is not None
    assert (echo.nonce, echo.boot_id, echo.pid) == ("abc123", BOOT, 77)
    assert echo.monotonic > 0


def test_read_echo_missing_file_returns_none():
    assert heartbeat.read_echo() is None
