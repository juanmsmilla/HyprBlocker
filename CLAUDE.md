# HyprBlocker - Technical Reference for Claude

## Architecture Overview

Four main components:

1. **Daemon** (daemon/) - FastAPI server, port 8765, systemd service
2. **Desktop App** (desktop-app/) - PyWebView GUI with React frontend
3. **Tray App** (tray/) - System tray icon using pystray with appindicator
4. **Browser Extension** (extension/) - WebExtensions API (Manifest v3)

```
Tray App + Desktop App + Browser Extension
              ↓ HTTP API (localhost:8765)
           Daemon (FastAPI)
              ↓ SQLite + Hyprland IPC
          Database + Window Manager
```

## Key Files & Modules

### Daemon (daemon/)

A proper Python package (`daemon/__init__.py`); all intra-daemon imports use `from daemon.x import y`. Run with `python -m daemon.main` (the systemd unit does this from the root `.venv`). Watchdogs are spawned as `python -m daemon.watchdog_runner`; `watchdog_runner.py` keeps a small bootstrap shim so pre-package watchdog processes that respawn siblings by file path still work.

- `main.py` - Entry point, systemd integration, signal handling, watchdog spawning
- `legacy_migration.py` - One-time `~/.config/website-blocker` → `~/.config/hyprblocker` move at startup (post-rename)
- `api/` - REST API package
  - `__init__.py` - App creation and router wiring
  - `app.py` - FastAPI app setup with CORS
  - `deps.py` - Shared dependencies (session factory, lock checks)
  - `schemas.py` - Pydantic request/response models
  - `routes/` - API route handlers
    - `heartbeat.py` - `/api/heartbeat`, `/api/grace-period`
    - `blocks.py` - `/api/blocks` CRUD
    - `status.py` - `/api/status`, `/api/stats`, `/api/browsers`, `/api/blocked-sites`
    - `settings.py` - `/api/settings/*` endpoints
- `blocker.py` - Pattern matching for websites/apps
- `scheduler.py` - Block schedule checking and activation
- `hyprland_monitor.py` - Window monitoring and app closing via Hyprland IPC
- `heartbeat_tracker.py` - Browser compliance tracking
- `lock_manager.py` - Per-block lock mode enforcement
- `time_verifier.py` - NTP time verification
- `database.py` - SQLAlchemy ORM models
- `config.py` - Configuration management
- `migrations.py` - Database migration logic
- `watchdog.py` - Watchdog manager and process logic
- `watchdog_runner.py` - Standalone watchdog process entry point

### Desktop App (desktop-app/)

- `main.py` - PyWebView window + JS bridge, starts tray if not running
- `api_client.py` - HTTP client for daemon API
- `frontend/` - React + TypeScript (Vite build)
- `desktop-app.spec` - PyInstaller spec for building executable

### Tray App (tray/)

- `main.py` - System tray app using pystray (appindicator backend)
- `tray-app.spec` - PyInstaller spec for building executable

### Icons (icons/)

- `icon-desktop-*.png` - Desktop app icons (32, 48, 64, 128, 256 px)
- `icon-tray-*.png` - Tray app icons (16, 22, 24 px)

### Browser Extension (extension/)

- `background.js` - Service worker (heartbeat, blocking)
- `matcher.js` - URL pattern matching (loaded via `importScripts`; unit-tested with bun, keep in sync with `daemon/blocker.py`)
- `matcher.test.js` - bun test suite for the matcher
- `blocked.html` - Blocked page display
- `popup/` - Extension popup UI
- `native-host/host.py` - Native messaging for PID detection

### Tests (tests/)

- `test_blocker.py` - URL/app pattern matching and rule parsing
- `test_scheduler.py` - Schedule logic (day/time parsing, active-block evaluation)
- `test_stats_api.py` - `/api/stats/details` endpoint (timeline, top targets, recent events)
- `test_blocks_api.py` - Block CRUD via FastAPI TestClient + in-memory SQLite; lock-mode 403s, `/strict` and `/extend-lock` tighten-only semantics
- `test_lock_manager.py` - Per-block lock logic and expired-lock cleanup
- `test_time_verifier.py` - NTP verification with a fake NTP client (fail-closed at lock transitions)
- `test_legacy_migration.py` - Config-dir rename migration (move/merge/defer-while-old-daemon-runs)
- No conftest hack: `pythonpath = ["."]` in root pyproject makes `import daemon` work
- Run with `uv run pytest` (pytest/pytest-cov/httpx are in the root dev dependency group)
- Extension matcher tests: `bun test extension` (`extension/matcher.test.js`, mirrors `test_blocker.py` to guard daemon/extension parity)

### Docs (docs/)

- `WATCHDOG.md` - Watchdog system deep-dive (linked from README)
- `TECHNICAL_CONCEPTS.md` - Systemd startup ordering and native messaging writeup
- `PORTFOLIO_TODO.md` - Remaining portfolio-polish work items
- `UI_IMPROVEMENTS.md` - Desktop app UI improvement backlog (what's done, what remains)

### CI & Tooling

- `.github/workflows/ci.yml` - GitHub Actions: ruff lint, pytest with coverage (Codecov upload), bun extension tests, frontend lint + build
- Ruff config lives in the root `pyproject.toml` (`uv run ruff check .`)
- **Single root `pyproject.toml`** for all Python components (daemon/desktop/tray deps + dev group); hatchling builds the `daemon` package so `python -m daemon.main` works from the root `.venv`. There are no per-component pyproject/lock files.
- `LICENSE` - MIT
- Everything is named **hyprblocker**: executables, systemd unit `hyprblocker.service`, config dir `~/.config/hyprblocker`, native-messaging host `com.hyprblocker.host`, Firefox extension ID `hyprblocker@hyprblocker.local`. `daemon/legacy_migration.py` moves a pre-rename `~/.config/website-blocker` dir into place on daemon startup (deferring, and exiting, while a pre-rename daemon still holds the port); a `website-blocker.service` shim unit forwards restarts from pre-rename watchdogs. The shim, the old `com.websiteblocker.host.json` browser manifests, and old bins are removed by running `./install.sh` after the first post-rename reboot.

## Database Schema

Location: `~/.config/hyprblocker/blocker.db`

### blocks table

```sql
id INTEGER PRIMARY KEY
name TEXT NOT NULL
enabled BOOLEAN DEFAULT true

-- Block schedule
block_mode TEXT CHECK(block_mode IN ('always', 'time_range', 'disabled'))
block_days_of_week TEXT  -- JSON array [0-6], Monday=0
block_start_time TIME
block_end_time TIME

-- Lock schedule (per-block)
lock_mode TEXT CHECK(lock_mode IN ('none', 'locked_until'))
lock_until DATETIME

-- Rules (newline-separated text)
websites_blocked TEXT
websites_allowed TEXT
apps_blocked TEXT
```

### block_events table

```sql
id INTEGER PRIMARY KEY
blocked_target TEXT
timestamp DATETIME
event_type TEXT
```

### heartbeat_logs table

```sql
id INTEGER PRIMARY KEY
browser_pid INTEGER
browser_name TEXT
incognito BOOLEAN
incognito_enabled BOOLEAN
timestamp DATETIME
```

## Key API Endpoints

| Endpoint                       | Method         | Purpose                                  |
| ------------------------------ | -------------- | ---------------------------------------- |
| `/api/status`                  | GET            | Daemon status, active blocks             |
| `/api/blocks`                  | GET/POST       | List/create blocks                       |
| `/api/blocks/{id}`             | PUT/DELETE     | Update/delete block                      |
| `/api/blocks/{id}/strict`      | PATCH          | Add stricter rules (allowed when locked) |
| `/api/blocks/{id}/lock-status` | GET            | Check if block is locked                 |
| `/api/stats`                   | GET            | Blocking statistics                      |
| `/api/stats/details`           | GET            | 14-day timeline, top targets, recent events |
| `/api/browsers`                | GET            | Browser extension status                 |
| `/api/heartbeat`               | POST           | Browser extension heartbeat              |
| `/api/grace-period`            | GET/POST       | Grace period for extension setup         |
| `/api/blocked-sites`           | GET            | Current blocked patterns (for extension) |
| `/api/settings/browser-enforcement` | GET/PUT   | Browser enforcement toggle               |
| `/api/settings/safe-search`    | GET/PUT        | Safe search enforcement toggle           |
| `/api/settings/shutdown-prevention` | GET/PUT   | Shutdown prevention toggle               |
| `/api/settings/watchdog`       | GET/PUT        | Watchdog enable/disable, count           |
| `/api/settings/lock`           | GET/POST/DELETE| Settings lock (lock-until with NTP)      |

## Data Model

### Rules Storage

- **Text-based**: Newline-separated strings in blocks table
- **Three rule types**: websites_blocked, websites_allowed, apps_blocked
- **Allow list precedence**: websites_allowed overrides websites_blocked

### Website Patterns

- Domain: `youtube.com`
- Subdomain: `www.youtube.com` (matches when blocking `youtube.com`)
- Wildcard: `*.reddit.com`
- Path-specific: `youtube.com/shorts`

### App Patterns

- Window class matching via Hyprland IPC
- Partial matching: `steam` matches `steam_app_123456`

## Monitoring Intervals

- Schedule checking: Every 10 seconds
- Window monitoring: Every 5 seconds
- Browser heartbeat timeout: 60 seconds
- Extension heartbeat send: Every 30 seconds
- Grace period: 30 seconds (for extension installation)

## Security Features

- **Per-block lock mode**: Prevents modifications to a specific block when active (stricter rules can still be added)
- **Settings lock**: Prevents all settings changes until expiry (with NTP verification)
- **Shutdown prevention**: Daemon refuses SIGTERM signals when enabled
- **NTP verification**: Prevents clock manipulation
- **Fail-safe design**: Errors result in blocking (not allowing)
- **Browser enforcement**: Force-close browsers if extension stops responding
- **Safe search enforcement**: Forces strict safe search on Google, Bing, and DuckDuckGo
- **Incognito detection**: Extension reports incognito status
- **Watchdog system**: Independent processes restart daemon if killed (requires shutdown prevention)

## Safe Search Enforcement

The safe search enforcement feature automatically modifies search engine URLs to enable strict safe search mode.

### How it works

1. Daemon stores `safe_search_enabled` boolean in config (`config.py`)
2. `/api/blocked-sites` endpoint includes `safe_search_enabled` in response
3. Extension stores setting and applies it before blocking check
4. When user navigates to a search engine, extension checks and modifies URL if needed

### Search Engine Parameters

| Engine | Detection | Parameter | Value |
|--------|-----------|-----------|-------|
| Google | `google.*` + `/search` path | `safe` | `active` |
| Bing | `bing.com` + `/search` path | `adlt` | `strict` |
| DuckDuckGo | `duckduckgo.com` (any path) | `kp` | `1` |

### Implementation (extension/background.js)

```javascript
function enforceSafeSearch(url) {
    const urlObj = new URL(url);

    // Check if parameter already set
    if (urlObj.searchParams.get('safe') === 'active') return { redirect: false };

    // Add parameter and redirect
    urlObj.searchParams.set('safe', 'active');
    return { redirect: true, newUrl: urlObj.toString() };
}
```

### Integration with blocking

Safe search enforcement runs **before** blocking logic in `handleNavigationBlock()`:
1. Check if safe search is enabled
2. If enabled, enforce safe search parameters
3. If redirect needed, stop processing (don't check for blocks)
4. Otherwise, continue with normal blocking logic

This ensures search engines are accessible but with safe search enforced.

## Watchdog System

The watchdog system provides daemon resilience by spawning independent processes that monitor the daemon and each other.

### How it works

1. Watchdog requires **both** shutdown prevention AND watchdog to be enabled
2. When enabled, daemon spawns N watchdog processes (configurable 2-5, default 3)
3. Each watchdog monitors:
   - Daemon health (HTTP check every 5 seconds)
   - Sibling watchdog processes (PID check every 10 seconds)
4. If daemon dies → watchdog restarts via `systemctl --user restart hyprblocker`
5. If sibling dies → remaining watchdogs respawn it
6. Watchdogs use obfuscated process names for resilience

### State File

Location: `~/.config/hyprblocker/watchdog_state.json`

```json
{
  "enabled": true,
  "watchdog_count": 3,
  "watchdogs": [
    {"pid": 12345, "name": "kworker-7", "started": "...", "last_heartbeat": "..."}
  ],
  "daemon_pid": 12340,
  "shutdown_requested": false
}
```

### Shutdown Prevention Integration

- Watchdog toggle is disabled in UI if shutdown prevention is off
- Disabling shutdown prevention automatically disables watchdog
- When settings are locked, both toggles cannot be changed
- This pairing ensures watchdogs only run when daemon shutdown protection is needed

## Data Flow

1. **Configuration**: Desktop App → POST /api/blocks → SQLite
2. **Schedule checking**: Daemon polls every 10s, activates blocks
3. **Browser monitoring**: Extension → POST /api/heartbeat every 30s
4. **Blocking enforcement**:
   - Extension enforces safe search (if enabled) via URL parameter injection
   - Extension blocks in-browser via webNavigation API
   - Daemon closes non-compliant browsers via Hyprland IPC
5. **App blocking**: Daemon → Hyprland IPC → Close windows

## Native Messaging

- **Purpose**: Get real browser PID (not extension process PID)
- **Protocol**: Stdin/stdout JSON messages
- **Host location**: `~/.config/chromium/NativeMessagingHosts/com.hyprblocker.host.json`
- **Host script**: `extension/native-host/host.py`
- **Permissions**: nativeMessaging in manifest.json

### Extension ID and Key (CRITICAL)

The extension manifest (`extension/manifest.json`) includes a **"key"** field:
```json
{
  "key": "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA6e2iRfjdXt..."
}
```

**Why this exists:**
- Chrome generates random extension IDs for unpacked extensions
- Native messaging requires the exact extension ID in `allowed_origins` (NO wildcards supported)
- The "key" field gives a **stable, deterministic extension ID**: `djngojgikpdalhbiimclpdcfehcphcim`
- This ID is derived from the SHA256 hash of the public key
- **DO NOT REMOVE THIS KEY** - native messaging will fail and browsers will be killed

The native messaging manifest must use this exact ID:
```json
{
  "allowed_origins": ["chrome-extension://djngojgikpdalhbiimclpdcfehcphcim/"]
}
```

**What happens if this breaks:**
- Extension can't connect to native host
- Extension falls back to hash-based PID (10 digits)
- Daemon sees different PID than Hyprland reports
- All browsers get killed even with extension installed

## Configuration Files

- Config: `~/.config/hyprblocker/config.json`
- Database: `~/.config/hyprblocker/blocker.db`
- Watchdog state: `~/.config/hyprblocker/watchdog_state.json`
- Daemon log: `~/.config/hyprblocker/daemon.log`
- Watchdog log: `~/.config/hyprblocker/watchdog.log`
- Systemd: `~/.config/systemd/user/hyprblocker.service`
- Native messaging: `~/.config/chromium/NativeMessagingHosts/com.hyprblocker.host.json`
- Tray autostart: `~/.config/autostart/hyprblocker-tray.desktop`

## Installation & Executables

- Executables: `~/.local/bin/hyprblocker`, `~/.local/bin/hyprblocker-tray`
- Icons: `~/.local/share/hyprblocker/icons/`
- Build with: `./install.sh --build`
- Tray app starts automatically on login via autostart entry
- Desktop app starts tray app if not running (production mode only)

### Systemd Service Dependencies (IMPORTANT)

The daemon service (`~/.config/systemd/user/hyprblocker.service`) has specific dependencies:

```ini
[Unit]
After=wayland-session@hyprland.desktop.target
BindsTo=wayland-session@hyprland.desktop.target

[Install]
WantedBy=wayland-session@hyprland.desktop.target
```

**Why these dependencies are critical:**
- Daemon uses `hyprctl clients -j` to list browser windows
- `hyprctl` only works after Hyprland is fully initialized
- Starting too early (e.g., with `network.target`) causes `hyprctl` to fail
- Failed `hyprctl` → empty window list → daemon can't detect browsers
- `BindsTo=` ensures daemon stops when Hyprland session ends

**What happens if this is wrong:**
- Daemon starts before Hyprland is ready
- All `hyprctl` calls return errors
- Daemon thinks no browsers are running
- Browser enforcement completely broken until manual daemon restart

### Config Fields (config.json security section)

```json
{
  "security": {
    "browser_enforcement_enabled": true,
    "safe_search_enabled": false,
    "shutdown_prevention_enabled": false,
    "watchdog_enabled": false,
    "watchdog_count": 3,
    "settings_lock_until": null
  }
}
```

## Design Principles

- **Daemon is source of truth**: All enforcement server-side
- **Extension is untrusted**: Browsers killed if extension stops
- **Fail-safe**: When in doubt, block (not allow)
- **Self-control focused**: Not designed as parental controls

## Notes from Developer

- This app is in early development, don't worry about backwards compatibility
- If there are any changes to the structure of this app like adding/removing files or changing the database model, please update CLAUDE.md with those changes
