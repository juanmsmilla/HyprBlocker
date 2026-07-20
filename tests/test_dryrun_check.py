"""Unit tests for the pure helpers in ``tools.dryrun_check``.

Only the pure logic is covered (JSON/ID validation, editable-venv detection,
unit validation, stat evaluation) — the privileged wrappers (visudo,
systemd-analyze, real /var/lib stats) run only on an installed system and are
exercised by ``install-root.sh --check`` itself.
"""

from __future__ import annotations

import json

from daemon import system_assets
from tools.dryrun_check import (
    WARN,
    StatExpectation,
    _check_unit,
    evaluate_stat,
    find_editable_pth,
    is_env_verify_failure,
    validate_lock_json,
    validate_manifest,
    validate_user_unit,
)

# ---------------------------------------------------------------------------
# find_editable_pth
# ---------------------------------------------------------------------------


def test_env_verify_failure_classifier():
    assert is_env_verify_failure("Failed to initialize manager: No such device or address")
    assert is_env_verify_failure("Failed to lookup RuntimeDirectory path: ...")
    assert is_env_verify_failure("Failed to connect to bus: No such file or directory")
    # A real unit-syntax error is NOT an environment failure.
    assert not is_env_verify_failure("hyprblocker.service: Unknown key name 'Foobar'")
    assert not is_env_verify_failure("Failed to parse Restart= setting")


def test_user_unit_env_failure_is_warning_not_failure(tmp_path):
    # When systemd-analyze can't host a user manager (the sudo-as-root case), the
    # user-unit verify must degrade to a warning, never a reboot-blocking FAIL.
    unit = tmp_path / "hyprblocker.service"
    unit.write_text(system_assets.user_unit())

    def fake_run(argv):
        return 1, "Failed to initialize manager: No such device or address"

    problems = _check_unit(
        unit, system_assets.user_unit(), fake_run, user_scope=True, user=None
    )
    assert len(problems) == 1
    assert problems[0].startswith(WARN)


def test_user_unit_real_parse_error_is_failure(tmp_path):
    unit = tmp_path / "hyprblocker.service"
    unit.write_text(system_assets.user_unit())

    def fake_run(argv):
        return 1, "hyprblocker.service: Unknown key name 'Bogus' in section 'Service'"

    problems = _check_unit(
        unit, system_assets.user_unit(), fake_run, user_scope=True, user=None
    )
    assert len(problems) == 1
    assert not problems[0].startswith(WARN)
    assert "verify failed" in problems[0]


def test_user_unit_verify_success_no_problems(tmp_path):
    unit = tmp_path / "hyprblocker.service"
    unit.write_text(system_assets.user_unit())
    problems = _check_unit(
        unit, system_assets.user_unit(), lambda argv: (0, ""), user_scope=True, user=None
    )
    assert problems == []


def _make_site_packages(tmp_path, names):
    site = tmp_path / ".venv" / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    for name in names:
        (site / name).write_text("/somewhere\n")
    return tmp_path / ".venv"


def test_editable_pth_detected_both_spellings(tmp_path):
    venv = _make_site_packages(
        tmp_path,
        ["__editable__.hyprblocker-0.1.0.pth", "_editable_impl.pth", "normal.pth"],
    )
    hits = [p.name for p in find_editable_pth(venv)]
    assert hits == ["__editable__.hyprblocker-0.1.0.pth", "_editable_impl.pth"]


def test_editable_pth_clean_venv(tmp_path):
    venv = _make_site_packages(tmp_path, ["distutils-precedence.pth"])
    assert find_editable_pth(venv) == []


def test_editable_pth_missing_venv(tmp_path):
    assert find_editable_pth(tmp_path / "nonexistent") == []


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------


def test_canonical_chrome_manifest_is_valid():
    assert validate_manifest(system_assets.chrome_manifest(), "chrome") == []


def test_canonical_firefox_manifest_is_valid():
    assert validate_manifest(system_assets.firefox_manifest(), "firefox") == []


def test_manifest_invalid_json():
    problems = validate_manifest("{not json", "chrome")
    assert len(problems) == 1
    assert "invalid JSON" in problems[0]


def test_manifest_not_an_object():
    assert validate_manifest("[1, 2]", "chrome") == ["manifest is not a JSON object"]


def test_manifest_wrong_extension_id():
    text = system_assets.chrome_manifest().replace(system_assets.EXTENSION_ID, "x" * 32)
    problems = validate_manifest(text, "chrome")
    assert any("extension ID" in p for p in problems)


def test_manifest_wrong_firefox_id():
    text = system_assets.firefox_manifest().replace(
        system_assets.FIREFOX_EXTENSION_ID, "evil@example.com"
    )
    problems = validate_manifest(text, "firefox")
    assert any("Firefox ID" in p for p in problems)


def test_manifest_wrong_host_path():
    data = json.loads(system_assets.chrome_manifest())
    data["path"] = "/home/someone/host.py"
    problems = validate_manifest(json.dumps(data), "chrome")
    assert any("path" in p for p in problems)


def test_manifest_wrong_name_and_type():
    data = json.loads(system_assets.chrome_manifest())
    data["name"] = "com.evil.host"
    data["type"] = "tcp"
    problems = validate_manifest(json.dumps(data), "chrome")
    assert any("host name" in p for p in problems)
    assert any("type" in p for p in problems)


# ---------------------------------------------------------------------------
# validate_lock_json
# ---------------------------------------------------------------------------


def test_lock_json_valid_iso_datetime():
    assert validate_lock_json('{"locked_until": "2026-09-03T00:00:00"}') == []


def test_lock_json_null_is_valid():
    assert validate_lock_json('{"locked_until": null}') == []


def test_lock_json_missing_key():
    assert validate_lock_json('{"other": 1}') == ["missing 'locked_until' key"]


def test_lock_json_unparseable_datetime():
    problems = validate_lock_json('{"locked_until": "next tuesday"}')
    assert any("unparseable" in p for p in problems)


def test_lock_json_invalid_json():
    problems = validate_lock_json("not json")
    assert any("invalid JSON" in p for p in problems)


def test_lock_json_not_an_object():
    assert validate_lock_json('"2026-09-03"') == ["lock file is not a JSON object"]


# ---------------------------------------------------------------------------
# validate_user_unit
# ---------------------------------------------------------------------------


def test_canonical_user_unit_passes():
    canonical = system_assets.user_unit()
    assert validate_user_unit(canonical, canonical) == []


def test_user_unit_tampered_execstart():
    canonical = system_assets.user_unit()
    tampered = canonical.replace("-m daemon.main", "-m evil.main")
    problems = validate_user_unit(tampered, canonical)
    assert any("ExecStart" in p for p in problems)
    assert any("canonical" in p for p in problems)


def test_user_unit_missing_root_layout_env():
    canonical = system_assets.user_unit()
    tampered = canonical.replace("Environment=HYPRBLOCKER_LAYOUT=root\n", "")
    problems = validate_user_unit(tampered, canonical)
    assert any("HYPRBLOCKER_LAYOUT" in p for p in problems)


def test_user_unit_whitespace_drift_is_flagged():
    canonical = system_assets.user_unit()
    problems = validate_user_unit(canonical + "\n# extra\n", canonical)
    assert problems == ["content differs from canonical daemon.system_assets user_unit()"]


# ---------------------------------------------------------------------------
# evaluate_stat
# ---------------------------------------------------------------------------


def _exp(tmp_path, **overrides):
    defaults = dict(
        path=tmp_path / "x", kind="file", mode=0o664, owner="tyler", group="hyprblocker"
    )
    defaults.update(overrides)
    return StatExpectation(**defaults)


def test_evaluate_stat_all_matching(tmp_path):
    exp = _exp(tmp_path)
    assert evaluate_stat(exp, is_dir=False, mode=0o664, owner="tyler", group="hyprblocker") == []


def test_evaluate_stat_reports_each_mismatch(tmp_path):
    exp = _exp(tmp_path, kind="dir", mode=0o755, owner="root", group="root")
    problems = evaluate_stat(exp, is_dir=False, mode=0o777, owner="tyler", group="users")
    assert len(problems) == 4
    assert any("directory" in p for p in problems)
    assert any("0777" in p and "0755" in p for p in problems)
    assert any("owner" in p for p in problems)
    assert any("group" in p for p in problems)


def test_evaluate_stat_file_expected_but_dir(tmp_path):
    exp = _exp(tmp_path)
    problems = evaluate_stat(exp, is_dir=True, mode=0o664, owner="tyler", group="hyprblocker")
    assert problems == ["expected a regular file"]
