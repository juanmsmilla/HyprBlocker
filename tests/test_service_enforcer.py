"""Tamper-repair tests for daemon.service_enforcer.

These guard the repair behaviors that are most likely to silently rot: shadow-unit
deletion, user-manifest deletion, canonical-unit verification, and system-manifest
repair. Privileged subprocess calls (systemctl) are monkeypatched out; we assert the
filesystem effects the pure repair logic produces.
"""

import json

import pytest

from daemon import service_enforcer as se
from daemon import system_assets as sa


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    # Never actually shell out to systemctl/visudo in tests.
    monkeypatch.setattr(se.subprocess, "run", lambda *a, **k: None)


def _root_layout(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "root")


def test_shadow_units_noop_in_user_layout(monkeypatch):
    monkeypatch.setenv("HYPRBLOCKER_LAYOUT", "user")
    assert se.delete_shadow_units() == 0
    assert se.delete_shadow_manifests() == 0


def test_delete_shadow_unit_file(monkeypatch, tmp_path):
    _root_layout(monkeypatch)
    shadow = tmp_path / "hyprblocker.service"
    shadow.write_text("[Service]\nExecStart=/bin/true\n")
    monkeypatch.setattr(se, "_SHADOW_UNIT", shadow)
    monkeypatch.setattr(se, "_SHADOW_UNIT_DROPIN", tmp_path / "hyprblocker.service.d")
    removed = se.delete_shadow_units()
    assert removed == 1
    assert not shadow.exists()


def test_delete_shadow_dropin_dir(monkeypatch, tmp_path):
    _root_layout(monkeypatch)
    dropin = tmp_path / "hyprblocker.service.d"
    dropin.mkdir()
    (dropin / "override.conf").write_text("[Service]\nExecStart=\n")
    monkeypatch.setattr(se, "_SHADOW_UNIT", tmp_path / "absent.service")
    monkeypatch.setattr(se, "_SHADOW_UNIT_DROPIN", dropin)
    removed = se.delete_shadow_units()
    assert removed == 1
    assert not dropin.exists()


def test_delete_shadow_manifests(monkeypatch, tmp_path):
    _root_layout(monkeypatch)
    m1 = tmp_path / "a.json"
    m2 = tmp_path / "b.json"
    m1.write_text("{}")
    m2.write_text("{}")
    monkeypatch.setattr(se, "_USER_MANIFEST_PATHS", [m1, m2, tmp_path / "absent.json"])
    assert se.delete_shadow_manifests() == 2
    assert not m1.exists() and not m2.exists()


def test_service_unit_intact_true_when_canonical(monkeypatch, tmp_path):
    unit = tmp_path / "hyprblocker.service"
    unit.write_text(sa.user_unit())
    monkeypatch.setattr(se, "_SYSTEM_USER_UNIT", unit)
    assert se.service_unit_intact() is True


def test_service_unit_intact_false_when_tampered(monkeypatch, tmp_path):
    unit = tmp_path / "hyprblocker.service"
    unit.write_text(sa.user_unit().replace("daemon.main", "this.is.evil"))
    monkeypatch.setattr(se, "_SYSTEM_USER_UNIT", unit)
    assert se.service_unit_intact() is False


def test_service_unit_intact_false_when_symlink(monkeypatch, tmp_path):
    real = tmp_path / "real"
    real.write_text(sa.user_unit())
    link = tmp_path / "hyprblocker.service"
    link.symlink_to(real)
    monkeypatch.setattr(se, "_SYSTEM_USER_UNIT", link)
    assert se.service_unit_intact() is False


def test_ensure_service_intact_rewrites_tampered(monkeypatch, tmp_path):
    unit = tmp_path / "hyprblocker.service"
    unit.write_text("ExecStart=/bin/true\n")
    monkeypatch.setattr(se, "_SYSTEM_USER_UNIT", unit)
    assert se.ensure_service_intact() is True
    assert unit.read_text() == sa.user_unit()


def test_repair_native_manifests_writes_missing(monkeypatch, tmp_path):
    chrome_dir = tmp_path / "chrome"
    ff_dir = tmp_path / "ff"
    monkeypatch.setattr(sa, "CHROME_MANIFEST_DIRS", [str(chrome_dir)])
    monkeypatch.setattr(sa, "FIREFOX_MANIFEST_DIRS", [str(ff_dir)])
    written = se.repair_native_manifests()
    assert written == 2
    got = json.loads((chrome_dir / sa.MANIFEST_FILENAME).read_text())
    assert got["allowed_origins"] == [f"chrome-extension://{sa.EXTENSION_ID}/"]


def test_repair_native_manifests_idempotent(monkeypatch, tmp_path):
    chrome_dir = tmp_path / "chrome"
    ff_dir = tmp_path / "ff"
    monkeypatch.setattr(sa, "CHROME_MANIFEST_DIRS", [str(chrome_dir)])
    monkeypatch.setattr(sa, "FIREFOX_MANIFEST_DIRS", [str(ff_dir)])
    se.repair_native_manifests()
    # Second run should rewrite nothing (content already canonical).
    assert se.repair_native_manifests() == 0
