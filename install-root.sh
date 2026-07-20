#!/bin/bash
# HyprBlocker root-layout installer (phase 1 of the root migration).
#
# Run:    sudo ./install-root.sh          # install / refresh (idempotent)
#         sudo ./install-root.sh --check  # deep pre-reboot validation, changes NOTHING
#
# What it does (see documentation/ROOT_INSTALL.md for the operator runbook):
#   - creates the 'hyprblocker' group and adds $SUDO_USER;
#   - syncs the repo into root-owned /opt/hyprblocker and builds a root-owned,
#     NON-editable venv there with uv;
#   - creates /var/lib/hyprblocker/{,secure,logs,requests} with the spec ownerships;
#   - renders every systemd unit / native-messaging manifest / sudoers file from
#     the single source of truth (`python -m daemon.system_assets`) — nothing is
#     hand-duplicated here;
#   - R9 cutover: COPIES (never moves) config.json / blocker.db / the live
#     settings lock into /var/lib/hyprblocker, seeds secure/lock.json and
#     secure/enforcement.json, and rewrites the existing per-user unit in place
#     to point at the /opt venv. The live daemon is NEVER touched; everything
#     lands at the next reboot.
#   - enables (never starts) the root enforcer and break-glass timer.
#
# SAFETY: this script never stops, restarts, signals, or reloads the running
# user daemon or its watchdogs. No `systemctl --user` calls, no process signals.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OPT_DIR="/opt/hyprblocker"
STATE_DIR="/var/lib/hyprblocker"
VENV_PY="$OPT_DIR/.venv/bin/python"
GROUP="hyprblocker"
SUDOERS_FILE="/etc/sudoers.d/hyprblocker-pacman"

die() { echo "install-root.sh: error: $*" >&2; exit 1; }
say() { echo "==> $*"; }

# --- preconditions ----------------------------------------------------------

[[ $EUID -eq 0 ]] || die "must run as root (use sudo)"

TARGET_USER="${SUDO_USER:-}"
[[ -n "$TARGET_USER" && "$TARGET_USER" != "root" ]] \
    || die "\$SUDO_USER is unset or root — run via 'sudo ./install-root.sh' from the login user"

USER_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -d "$USER_HOME" ]] || die "cannot resolve home directory of $TARGET_USER"

# --- --check: deep pre-reboot validation, changes nothing -------------------

if [[ "${1:-}" == "--check" ]]; then
    [[ -x "$VENV_PY" ]] \
        || die "--check requires an existing install ($VENV_PY missing) — run 'sudo ./install-root.sh' first"
    exec "$VENV_PY" -I "$OPT_DIR/tools/dryrun_check.py" --user "$TARGET_USER"
fi
[[ $# -eq 0 ]] || die "unknown argument: $1 (only --check is supported)"

command -v rsync  >/dev/null || die "rsync not found"
command -v visudo >/dev/null || die "visudo not found"

UV_BIN="$(command -v uv || true)"
[[ -n "$UV_BIN" || -x "$USER_HOME/.local/bin/uv" ]] || die "uv not found (looked in PATH and $USER_HOME/.local/bin)"
UV_BIN="${UV_BIN:-$USER_HOME/.local/bin/uv}"

# --- group ------------------------------------------------------------------

say "Group '$GROUP' + membership for $TARGET_USER"
getent group "$GROUP" >/dev/null || groupadd --system "$GROUP"
usermod -aG "$GROUP" "$TARGET_USER"

# --- directories (spec layout block) ----------------------------------------

say "Directory layout"
install -d -o root -g root       -m 0755 "$OPT_DIR"
install -d -o root -g "$GROUP"   -m 0775 "$STATE_DIR"
install -d -o root -g root       -m 0755 "$STATE_DIR/secure"
install -d -o root -g "$GROUP"   -m 0775 "$STATE_DIR/logs"
install -d -o root -g "$GROUP"   -m 0775 "$STATE_DIR/requests"
install -d -o root -g "$GROUP"   -m 0775 "$STATE_DIR/requests/settings"
install -d -o root -g "$GROUP"   -m 0775 "$STATE_DIR/requests/grants"

# --- code sync into /opt ----------------------------------------------------

say "Syncing repo -> $OPT_DIR"
# --exclude also protects the destination-side .venv and native-host from
# --delete (rsync never deletes excluded receiver files without --delete-excluded).
# .env is excluded on purpose: /opt is world-readable and the tier-1 judge key
# must never land there (R2) — the user daemon reads it from its own config dir.
rsync -a --delete \
    --exclude=.git --exclude=.venv --exclude=dist --exclude=build \
    --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
    --exclude=node_modules --exclude=.env --exclude=.claude \
    --exclude=/native-host \
    "$REPO_DIR"/ "$OPT_DIR"/
chown -R root:root "$OPT_DIR"

say "Building root-owned non-editable venv (uv sync)"
# --no-editable: the project package must be COPIED into site-packages, never
# .pth-linked back to this user-writable checkout (root would import user code).
# UV_PYTHON_INSTALL_DIR keeps any uv-managed interpreter world-readable under
# /opt instead of root's 0700 home.
(cd "$OPT_DIR" && UV_PYTHON_INSTALL_DIR="$OPT_DIR/python" \
    "$UV_BIN" sync --frozen --no-editable --no-dev)

EDITABLE_PTH="$(find "$OPT_DIR/.venv" -path '*/site-packages/*' -name '*editable*.pth' 2>/dev/null || true)"
[[ -z "$EDITABLE_PTH" ]] || die "editable install detected in the /opt venv (user-writable code on root's import path): $EDITABLE_PTH"

# World-readable code + venv: the user daemon executes this interpreter.
chmod -R u+rwX,go+rX,go-w "$OPT_DIR"

"$VENV_PY" -I -c 'import daemon.system_assets, daemon.paths' \
    || die "the /opt venv cannot import the daemon package"

# --- native host + extension -------------------------------------------------

say "Native host + extension payload"
install -d -o root -g root -m 0755 "$OPT_DIR/native-host"
install -o root -g root -m 0755 "$REPO_DIR/extension/native-host/host.py" "$OPT_DIR/native-host/host.py"
# extension/ itself arrived via rsync and was made world-readable above.
[[ -f "$OPT_DIR/extension/manifest.json" ]] || die "$OPT_DIR/extension/manifest.json missing after rsync"

# --- rendered assets (single source of truth: daemon.system_assets) ---------

render() { "$VENV_PY" -I -m daemon.system_assets "$1"; }

install_rendered() {  # <asset-name> <dest> [mode]
    local name="$1" dest="$2" mode="${3:-0644}" tmp
    tmp="$(mktemp)"
    render "$name" >"$tmp"
    install -o root -g root -m "$mode" "$tmp" "$dest"
    rm -f "$tmp"
    echo "    installed $dest (from '$name')"
}

say "Systemd units (rendered from daemon.system_assets)"
install_rendered user-unit        /etc/systemd/user/hyprblocker.service
install_rendered enforcer-unit    /etc/systemd/system/hyprblocker-enforcer.service
install_rendered breakglass-unit  /etc/systemd/system/hyprblocker-breakglass.service
install_rendered breakglass-timer /etc/systemd/system/hyprblocker-breakglass.timer

say "System-wide native-messaging manifests"
MANIFEST_FILENAME="$("$VENV_PY" -I -c 'from daemon.system_assets import MANIFEST_FILENAME as f; print(f)')"
mapfile -t CHROME_DIRS  < <("$VENV_PY" -I -c 'from daemon.system_assets import CHROME_MANIFEST_DIRS as d; print("\n".join(d))')
mapfile -t FIREFOX_DIRS < <("$VENV_PY" -I -c 'from daemon.system_assets import FIREFOX_MANIFEST_DIRS as d; print("\n".join(d))')
for dir in "${CHROME_DIRS[@]}"; do
    install -d -o root -g root -m 0755 "$dir"
    install_rendered chrome-manifest "$dir/$MANIFEST_FILENAME"
done
for dir in "${FIREFOX_DIRS[@]}"; do
    install -d -o root -g root -m 0755 "$dir"
    install_rendered firefox-manifest "$dir/$MANIFEST_FILENAME"
done

say "Sudoers drop-in (tier-2 'pacman -Syu' carve-out)"
SUDOERS_TMP="$(mktemp)"
render pacman-sudoers >"$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP" >/dev/null || die "rendered sudoers failed 'visudo -cf' — NOT installed"
install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS_FILE"
rm -f "$SUDOERS_TMP"
echo "    installed $SUDOERS_FILE (visudo-validated)"

# --- R9: COPY state (never move) --------------------------------------------

say "Copying state (R9: originals left untouched for the live daemon)"
SRC_DIR="$USER_HOME/.config/hyprblocker"
for f in config.json blocker.db blocker.db-wal blocker.db-shm; do
    if [[ -f "$SRC_DIR/$f" ]]; then
        install -o "$TARGET_USER" -g "$GROUP" -m 0664 "$SRC_DIR/$f" "$STATE_DIR/$f"
        echo "    copied $SRC_DIR/$f -> $STATE_DIR/$f"
    fi
done
[[ -f "$STATE_DIR/config.json" ]] || echo "    WARNING: no config.json found at $SRC_DIR — root tier will boot with defaults"

# Tier-1 judge key (R2): never in world-readable /opt — the user daemon reads
# it from its own state dir (user/.env). Seed it from the repo .env when present.
if [[ -f "$REPO_DIR/.env" ]]; then
    install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 0755 "$STATE_DIR/user"
    install -o "$TARGET_USER" -g "$TARGET_USER" -m 0600 "$REPO_DIR/.env" "$STATE_DIR/user/.env"
    echo "    seeded tier-1 judge key -> $STATE_DIR/user/.env (0600 $TARGET_USER)"
else
    echo "    WARNING: no .env at $REPO_DIR — tier-1 grant requests will fail-closed deny"
fi

say "Seeding secure/lock.json + secure/enforcement.json from the copied config"
HYPRBLOCKER_LAYOUT=root "$VENV_PY" -I - <<'PY'
"""Seed the root tier's authoritative files from the just-copied config.json.

- lock.json is tightening-only: an existing later lock is never shortened by a
  re-run (asymmetric semantics, same as the enforcer will apply after reboot).
- enforcement.json is seeded once; after that the enforcer owns it (a re-run of
  the installer must not clobber policy changes made via the requests/ path).
"""
import json
import os
from datetime import UTC, datetime

from daemon import paths
from daemon.enforcement_policy import DEFAULT_BROWSERS, EnforcementPolicy, write_policy

cfg: dict = {}
cfg_path = paths.state_dir() / "config.json"
if cfg_path.exists():
    cfg = json.loads(cfg_path.read_text())
sec = cfg.get("security", {})
mon = cfg.get("monitoring", {})


def parse(raw):
    try:
        dt = datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


lock_file = paths.lock_path()
new_raw = sec.get("settings_lock_until")
existing_raw = None
if lock_file.exists():
    try:
        existing_raw = json.loads(lock_file.read_text()).get("locked_until")
    except (OSError, json.JSONDecodeError):
        existing_raw = None

new_dt, old_dt = parse(new_raw), parse(existing_raw)
if lock_file.exists() and (new_dt is None or (old_dt is not None and old_dt >= new_dt)):
    print(f"    lock.json kept (existing {existing_raw!r} >= copied {new_raw!r})")
else:
    lock_file.write_text(json.dumps({"locked_until": new_raw}, indent=2) + "\n")
    os.chmod(lock_file, 0o644)
    print(f"    lock.json seeded: locked_until={new_raw!r}")

enforcement_file = paths.secure_dir() / "enforcement.json"
if enforcement_file.exists():
    print("    enforcement.json already present — left for the enforcer to own")
else:
    write_policy(
        EnforcementPolicy(
            browsers=list(cfg.get("browsers", DEFAULT_BROWSERS)),
            browser_enforcement_enabled=sec.get("browser_enforcement_enabled", True),
            shutdown_prevention_enabled=sec.get("shutdown_prevention_enabled", False),
            watchdog_enabled=sec.get("watchdog_enabled", False),
            watchdog_count=sec.get("watchdog_count", 3),
            heartbeat_interval_seconds=mon.get("heartbeat_timeout_seconds", 60),
        )
    )
    os.chmod(enforcement_file, 0o644)
    print("    enforcement.json seeded from the copied config")
PY

# --- R9: unit cutover shim (rewrite in place, never delete, never reload) ---

say "Cutover shim: rewriting the per-user unit in place"
USER_UNIT="$USER_HOME/.config/systemd/user/hyprblocker.service"
if [[ -f "$USER_UNIT" ]]; then
    UNIT_TMP="$(mktemp)"
    render user-unit >"$UNIT_TMP"
    # cat > preserves the inode and the user's ownership; systemd only re-reads
    # the file at the next daemon-reload/reboot, so the live daemon is unaffected.
    cat "$UNIT_TMP" > "$USER_UNIT"
    rm -f "$UNIT_TMP"
    echo "    rewrote $USER_UNIT -> ExecStart now targets $VENV_PY (lands at reboot)"
    echo "    NOT deleted: the daemon's first root-layout boot removes this shadow copy itself"
else
    echo "    no $USER_UNIT — the /etc/systemd/user copy will be used as-is"
fi

# --- enable (never start) the root units ------------------------------------

say "Enabling root units (enable only — nothing is started before reboot)"
systemctl daemon-reload
systemctl enable hyprblocker-enforcer.service hyprblocker-breakglass.timer

# --- summary ----------------------------------------------------------------

cat <<SUMMARY

============================================================
 HyprBlocker root-layout install complete (nothing restarted)
============================================================
 Code + venv:      $OPT_DIR  (root-owned, non-editable)
 State:            $STATE_DIR  (config/db COPIED; originals untouched)
 Authoritative:    $STATE_DIR/secure/{lock.json,enforcement.json}
 Units installed:  /etc/systemd/user/hyprblocker.service
                   /etc/systemd/system/hyprblocker-enforcer.service (enabled)
                   /etc/systemd/system/hyprblocker-breakglass.{service,timer} (timer enabled)
 Cutover shim:     $USER_UNIT (rewritten in place)
 Manifests:        system-wide native-messaging manifests (root-owned)
 Sudoers:          $SUDOERS_FILE (visudo-validated)

 The LIVE daemon was not touched. Everything above takes effect at
 the next reboot, when the user unit starts from the /opt venv under
 HYPRBLOCKER_LAYOUT=root and the root enforcer starts alongside it.

 Next steps:
   1. Validate:  sudo ./install-root.sh --check
   2. Read:      documentation/ROOT_INSTALL.md  (first-reboot risks, rollback)
   3. Reboot to activate the root layout.
============================================================
SUMMARY
