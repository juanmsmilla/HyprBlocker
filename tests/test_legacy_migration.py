"""Tests for the one-time website-blocker → hyprblocker config dir migration."""

import json

from daemon.legacy_migration import migrate_legacy_config_dir

PORT_FREE = lambda port: False  # noqa: E731 - no old daemon running
PORT_BUSY = lambda port: True  # noqa: E731 - old daemon still alive


def make_legacy(tmp_path, port=None):
    legacy = tmp_path / "website-blocker"
    legacy.mkdir()
    config = {"daemon": {"port": port}} if port else {}
    (legacy / "config.json").write_text(json.dumps(config))
    (legacy / "blocker.db").write_text("db-bytes")
    (legacy / "daemon.log").write_text("old log")
    return legacy


def test_fresh_install_is_noop(tmp_path):
    legacy = tmp_path / "website-blocker"
    new = tmp_path / "hyprblocker"
    assert migrate_legacy_config_dir(legacy, new, PORT_FREE) == "none"
    assert not new.exists()


def test_moves_whole_directory(tmp_path):
    legacy = make_legacy(tmp_path)
    new = tmp_path / "hyprblocker"
    assert migrate_legacy_config_dir(legacy, new, PORT_FREE) == "migrated"
    assert not legacy.exists()
    assert (new / "blocker.db").read_text() == "db-bytes"
    assert (new / "daemon.log").read_text() == "old log"


def test_skips_when_new_dir_already_populated(tmp_path):
    legacy = make_legacy(tmp_path)
    new = tmp_path / "hyprblocker"
    new.mkdir()
    (new / "config.json").write_text("{}")
    assert migrate_legacy_config_dir(legacy, new, PORT_FREE) == "none"
    assert (legacy / "blocker.db").exists()  # untouched


def test_merges_into_partially_created_new_dir(tmp_path):
    """Stray files (e.g. a transition-period watchdog log) must survive."""
    legacy = make_legacy(tmp_path)
    new = tmp_path / "hyprblocker"
    new.mkdir()
    (new / "daemon.log").write_text("new log")  # collision: keep existing
    assert migrate_legacy_config_dir(legacy, new, PORT_FREE) == "migrated"
    assert (new / "blocker.db").read_text() == "db-bytes"
    assert (new / "daemon.log").read_text() == "new log"
    # the colliding legacy log stays behind rather than being destroyed
    assert (legacy / "daemon.log").read_text() == "old log"


def test_defers_while_old_daemon_is_running(tmp_path):
    legacy = make_legacy(tmp_path)
    new = tmp_path / "hyprblocker"
    assert migrate_legacy_config_dir(legacy, new, PORT_BUSY) == "deferred"
    assert (legacy / "blocker.db").exists()
    assert not new.exists()


def test_reads_daemon_port_from_legacy_config(tmp_path):
    legacy = make_legacy(tmp_path, port=9999)
    new = tmp_path / "hyprblocker"
    seen_ports = []

    def record_port(port):
        seen_ports.append(port)
        return False

    migrate_legacy_config_dir(legacy, new, record_port)
    assert seen_ports == [9999]
