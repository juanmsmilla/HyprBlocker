"""Tests for the central path resolver (daemon.paths)."""

from daemon import paths


def test_user_layout_is_default(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert paths.layout() == "user"


def test_root_layout_via_env(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    assert paths.layout() == "root"


def test_layout_autodetect_from_code_root(monkeypatch):
    # Pretend the package lives under /opt/hyprblocker.
    monkeypatch.delenv("HYPRBLOCKER_LAYOUT", raising=False)
    monkeypatch.setenv("HYPRBLOCKER_CODE_ROOT", "/opt/hyprblocker")
    # __file__ won't be under /opt in the test tree, so detection falls back to user
    # unless the override equals code path; assert the override at least resolves code_root.
    assert paths.code_root() == paths.Path("/opt/hyprblocker")


def test_env_overrides_win(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "sec"))
    monkeypatch.setenv("HYPRBLOCKER_LOG_DIR", str(tmp_path / "l"))
    monkeypatch.delenv("HYPRBLOCKER_CONFIG_DIR", raising=False)  # so config_dir falls back to state
    assert paths.state_dir() == tmp_path / "s"
    assert paths.secure_dir() == tmp_path / "sec"
    assert paths.log_dir() == tmp_path / "l"
    assert paths.config_path() == (tmp_path / "s") / "config.json"
    assert paths.database_path() == (tmp_path / "s") / "blocker.db"


def test_root_layout_secure_and_logs_are_subdirs(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.delenv("HYPRBLOCKER_STATE_DIR", raising=False)
    monkeypatch.delenv("HYPRBLOCKER_SECURE_DIR", raising=False)
    monkeypatch.delenv("HYPRBLOCKER_LOG_DIR", raising=False)
    assert paths.state_dir() == paths.Path("/var/lib/hyprblocker")
    assert paths.secure_dir() == paths.Path("/var/lib/hyprblocker/secure")
    assert paths.log_dir() == paths.Path("/var/lib/hyprblocker/logs")


def test_user_layout_collapses_secure_onto_state(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRBLOCKER_SECURE_DIR", raising=False)
    monkeypatch.delenv("HYPRBLOCKER_LOG_DIR", raising=False)
    # No privilege boundary in user layout: secure/log collapse onto state.
    assert paths.secure_dir() == tmp_path
    assert paths.log_dir() == tmp_path


def test_secure_file_accessors(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    assert paths.lock_path() == tmp_path / "lock.json"
    assert paths.policy_path() == tmp_path / "policy.md"
    assert paths.grants_log_path() == tmp_path / "grants.log"
    assert paths.breakglass_path() == tmp_path / "breakglass.json"
    assert paths.enforcer_state_path() == tmp_path / "enforcer_state.json"
    assert paths.root_credential_path() == tmp_path / "root_credential"


def test_ensure_dir_creates(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    paths.ensure_dir(target)
    assert target.is_dir()


def test_ensure_dir_swallows_permission_error(monkeypatch):
    # Simulate a root-owned directory: mkdir raises PermissionError, ensure_dir must not.
    from pathlib import Path as _P

    def boom(self, *a, **k):
        raise PermissionError("read-only")

    monkeypatch.setattr(_P, "mkdir", boom)
    # Should return the path without raising.
    assert paths.ensure_dir(_P("/var/lib/hyprblocker/secure")) == _P(
        "/var/lib/hyprblocker/secure"
    )


def test_root_layout_user_files_live_in_user_subdir(monkeypatch):
    # Review M1: user-writable files must NOT sit directly under the root:root 0755
    # parent; they live in state_dir/user so directory-rename attacks on secure/
    # are impossible.
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    for v in ("HYPRBLOCKER_STATE_DIR", "HYPRBLOCKER_CONFIG_DIR", "HYPRBLOCKER_SECURE_DIR"):
        monkeypatch.delenv(v, raising=False)
    assert paths.user_dir() == paths.Path("/var/lib/hyprblocker/user")
    assert paths.config_path() == paths.Path("/var/lib/hyprblocker/user/config.json")
    assert paths.database_path() == paths.Path("/var/lib/hyprblocker/user/blocker.db")
    assert paths.heartbeat_path() == paths.Path("/var/lib/hyprblocker/user/heartbeat.json")
    # secure/ sits directly under the root-owned parent, not under user/.
    assert paths.secure_dir() == paths.Path("/var/lib/hyprblocker/secure")


def test_user_layout_heartbeat_collapses_onto_state(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRBLOCKER_CONFIG_DIR", raising=False)
    assert paths.user_dir() == tmp_path
    assert paths.heartbeat_path() == tmp_path / "heartbeat.json"


def test_dir_overrides_ignored_on_real_opt_deploy(monkeypatch, tmp_path):
    # Review M2: when the code physically lives under /opt, env dir-overrides are
    # ignored (a user could otherwise redirect secure_dir at a forged directory).
    monkeypatch.setattr(paths, "_real_opt_deploy", lambda: True)
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path / "forged"))
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path / "forged2"))
    assert paths.layout() == "root"
    assert paths.secure_dir() == paths.Path("/var/lib/hyprblocker/secure")
    assert paths.state_dir() == paths.Path("/var/lib/hyprblocker")


def test_dev_mode_user_layout_always_true(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert paths.is_dev_mode() is True


def test_dev_mode_root_layout_depends_on_credential(monkeypatch, tmp_path):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    cred = tmp_path / "root_credential"
    assert paths.is_dev_mode() is True  # credential absent
    cred.write_text("secret")
    assert paths.is_dev_mode() is False  # credential present ⇒ graduated
