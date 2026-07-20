"""Tests for the /proc browser scan (enforcer.proc_scan) against a fake procfs.

The scan is pure given a ``proc_root``, so these tests synthesize a /proc tree
in tmp — no root, no live processes, no signals ever sent.
"""

from pathlib import Path

from enforcer import proc_scan
from enforcer.proc_scan import (
    exe_realpath,
    find_browser_pids,
    parse_proc_status,
    status_real_uid,
)

BROWSERS = ["firefox", "chromium", "brave-browser"]


def _status_text(uid=1000, state="S", tracer=0):
    return (
        "Name:\tfirefox\n"
        f"State:\t{state} (sleeping)\n"
        f"Uid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        f"Gid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        f"TracerPid:\t{tracer}\n"
    )


def _add_pid(
    proc: Path,
    pid: int,
    exe_target: Path | str | None = None,
    *,
    uid: int | None = 1000,
    loginuid: int | None = None,
    state: str = "S",
):
    d = proc / str(pid)
    d.mkdir()
    if exe_target is not None:
        (d / "exe").symlink_to(exe_target)
    if uid is not None:
        (d / "status").write_text(_status_text(uid=uid, state=state))
    if loginuid is not None:
        (d / "loginuid").write_text(str(loginuid))
    return d


def _make_bin(tmp_path: Path, name: str) -> Path:
    bin_dir = tmp_path / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    binary = bin_dir / name
    binary.write_text("#!ELF")
    return binary


def _proc(tmp_path: Path) -> Path:
    proc = tmp_path / "proc"
    proc.mkdir()
    return proc


def test_finds_matching_browser_for_target_uid(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, _make_bin(tmp_path, "firefox"), uid=1000)
    _add_pid(proc, 200, _make_bin(tmp_path, "chromium"), uid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == [100, 200]


def test_excludes_other_uid(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, _make_bin(tmp_path, "firefox"), uid=1001)
    assert find_browser_pids(proc, BROWSERS, 1000) == []


def test_excludes_non_browser_exe(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, _make_bin(tmp_path, "vim"), uid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == []


def test_skips_non_pid_entries_and_kernel_threads(tmp_path):
    proc = _proc(tmp_path)
    (proc / "self").mkdir()
    (proc / "cpuinfo").write_text("")
    _add_pid(proc, 2, None, uid=0)  # kthreadd-style: no exe
    _add_pid(proc, 100, _make_bin(tmp_path, "firefox"), uid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == [100]


def test_matches_via_symlink_resolution(tmp_path):
    # exe → /usr/bin/browser-wrapper → firefox: realpath basename is what counts.
    proc = _proc(tmp_path)
    real = _make_bin(tmp_path, "firefox")
    wrapper = tmp_path / "usr" / "bin" / "browser-wrapper"
    wrapper.symlink_to(real)
    _add_pid(proc, 100, wrapper, uid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == [100]


def test_deleted_binary_suffix_still_matches(tmp_path):
    # A browser whose binary was replaced mid-run: exe dangles at
    # ".../firefox (deleted)". The scan must still recognise it.
    proc = _proc(tmp_path)
    _add_pid(proc, 100, tmp_path / "usr" / "bin" / "firefox (deleted)", uid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == [100]


def test_loginuid_fallback_when_status_unreadable(tmp_path):
    # status missing (or a uid-masked process) but loginuid pins it to the user.
    proc = _proc(tmp_path)
    _add_pid(proc, 100, _make_bin(tmp_path, "firefox"), uid=None, loginuid=1000)
    assert find_browser_pids(proc, BROWSERS, 1000) == [100]


def test_unset_loginuid_sentinel_does_not_match(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, _make_bin(tmp_path, "firefox"), uid=None, loginuid=4294967295)
    assert find_browser_pids(proc, BROWSERS, 4294967295) == []


def test_missing_proc_root_returns_empty(tmp_path):
    assert find_browser_pids(tmp_path / "nope", BROWSERS, 1000) == []


# ---------------------------------------------------------------------------
# Parsers / helpers
# ---------------------------------------------------------------------------

def test_parse_proc_status_fields():
    fields = parse_proc_status(_status_text(uid=1234, state="T", tracer=42))
    assert fields["State"].startswith("T")
    assert fields["TracerPid"] == "42"
    assert status_real_uid(fields) == 1234


def test_parse_proc_status_tolerates_garbage():
    fields = parse_proc_status("no colon line\nUid:\tnot-a-number\n")
    assert status_real_uid(fields) is None
    assert status_real_uid({}) is None


def test_exe_realpath_none_when_absent(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, None, uid=1000)
    assert exe_realpath(proc, 100) is None
    assert exe_realpath(proc, 999) is None  # no such pid dir


def test_exe_realpath_strips_deleted_suffix(tmp_path):
    proc = _proc(tmp_path)
    _add_pid(proc, 100, tmp_path / "bin" / "chromium (deleted)", uid=1000)
    resolved = exe_realpath(proc, 100)
    assert resolved is not None
    assert resolved.endswith("/chromium")


def test_kill_pids_counts_and_ignores_vanished(monkeypatch):
    # Never signal anything real in tests: stub os.kill. Pid 3 "vanished"
    # (ProcessLookupError) and must be excluded from the count, not raise.
    sent = []

    def fake_kill(pid, sig):
        if pid == 3:
            raise ProcessLookupError
        sent.append((pid, sig))

    monkeypatch.setattr(proc_scan.os, "kill", fake_kill)
    assert proc_scan.kill_pids([1, 3, 5]) == 2
    assert [p for p, _ in sent] == [1, 5]
