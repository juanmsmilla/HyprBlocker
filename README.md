# HyprBlocker

[![CI](https://github.com/TTeuber/HyprBlocker/actions/workflows/ci.yml/badge.svg)](https://github.com/TTeuber/HyprBlocker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Platform](https://img.shields.io/badge/Platform-Linux%20%2B%20Hyprland-1793D1?logo=archlinux&logoColor=white)

A self-control website and application blocker for Linux + Hyprland, built around a **tamper-resistant daemon**. Blocks distracting sites and apps on a schedule, and is deliberately hard to switch off in a moment of weakness — watchdog processes, NTP-verified time locks, and browser enforcement all work to keep the block in place until it's supposed to end.

<!-- SCREENSHOTS: replace these placeholders with real captures (docs/screenshots/*.png)
![Dashboard](docs/screenshots/dashboard.png)
![Block configuration](docs/screenshots/block-config.png)
![Blocked page](docs/screenshots/blocked-page.png)
-->

> 🚧 **Screenshots coming soon** — Dashboard, block configuration, and the in-browser blocked page.

## Why this project is interesting

Most website blockers are trivially bypassed: kill the process, change the clock, or uninstall the extension. HyprBlocker treats "future me trying to cheat" as the adversary and defends in depth:

| Bypass attempt | Defense |
| --- | --- |
| Kill the daemon | Systemd auto-restart, plus 2–5 independent [watchdog processes](docs/WATCHDOG.md) with obfuscated names that monitor the daemon *and each other* |
| Stop the systemd service | Daemon refuses `SIGTERM` while shutdown prevention is on |
| Change the system clock to end a lock early | Lock expiry is verified against **NTP time**, not the local clock |
| Disable or remove the browser extension | Daemon tracks extension heartbeats and **closes any browser** that stops reporting (60s timeout) |
| Use incognito mode | Extension reports incognito status; enforcement requires it to be enabled |
| Spoof the extension's identity | Native messaging host verifies the real browser PID against Hyprland's window list |
| Edit settings during a block | Per-block lock mode makes configuration read-only (stricter rules can still be *added*) |

The design principle throughout: **the daemon is the source of truth and the extension is untrusted**. In-browser blocking is a convenience layer; the real enforcement is the daemon killing non-compliant browsers via Hyprland IPC. And when anything fails — network, database, NTP — the system **fails closed** (blocks) rather than open.

It's equally honest about what it *can't* stop — see [Limitations](#limitations).

## Features

- **Website blocking** — domain, subdomain, wildcard (`*.reddit.com`), and path-specific (`youtube.com/shorts`) patterns
- **Allow-list exceptions** — block all of Reddit except `reddit.com/r/programming`
- **App blocking** — closes blocked applications via Hyprland IPC (window-class matching)
- **Scheduling** — always-on or time ranges per weekday (e.g. weekdays 9–5)
- **Lock mode** — block configuration becomes read-only while active
- **Settings lock** — freeze all settings until a chosen date/time, NTP-verified
- **Watchdog system** — self-healing mesh of processes that restart the daemon if killed
- **Safe search enforcement** — forces strict safe search on Google, Bing, and DuckDuckGo
- **Statistics** — track blocked attempts over time
- **Desktop GUI** — React + TypeScript frontend in a native pywebview window
- **System tray** — status icon and quick-access menu

## Architecture

```
┌─────────────────┐         ┌──────────────────────┐         ┌─────────────────┐
│  Desktop App    │  HTTP   │   Daemon (systemd)   │ Hyprland│   Applications  │
│  (pywebview +   │◄───────►│   - FastAPI server   │  IPC    │   & Browsers    │
│   React GUI)    │         │   - Block scheduler  │────────►│                 │
│                 │         │   - Lock enforcer    │         │                 │
│  - Config UI    │         │   - NTP verifier     │         │                 │
│  - View stats   │         │   - Watchdog manager │         │                 │
└─────────────────┘         └──────────┬───────────┘         └────────▲────────┘
                                       │                              │
┌─────────────────┐         ┌──────────▼────────────┐                 │
│   Tray App      │         │  Browser Extension    │  Heartbeat      │
│   (pystray)     │         │  - Blocks websites    │─────────────────┘
│                 │         │  - Sends heartbeat    │  (every 30s;
│  - Quick access │         │  - Safe search        │   silence = browser
│  - Status icon  │         └───────────────────────┘   gets closed)
└─────────────────┘
```

1. **Daemon** (`daemon/`) — Python/FastAPI systemd service; owns the database, schedules, and all enforcement
2. **Desktop app** (`desktop-app/`) — pywebview shell around a React + TypeScript (Vite) frontend
3. **Tray app** (`tray/`) — pystray/AppIndicator status icon
4. **Browser extension** (`extension/`) — Manifest v3 WebExtension; in-browser blocking + compliance heartbeat

Deeper dives: [Watchdog system](docs/WATCHDOG.md) · [Systemd ordering & native messaging](docs/TECHNICAL_CONCEPTS.md)

## Quick Start

Requires Arch Linux (or similar) with Hyprland, [uv](https://docs.astral.sh/uv/), and a Chromium- or Firefox-based browser.

### 1. Install dependencies

```bash
# System dependencies
sudo pacman -S webkit2gtk python-gobject

# Python dependencies
cd /path/to/HyprBlocker
uv sync
```

### 2. Run the install script

```bash
./install.sh
```

This builds the desktop and tray app executables into `~/.local/bin/`, copies the daemon and extension into place, creates the systemd service, and sets up tray autostart.

### 3. Start the daemon

```bash
systemctl --user enable --now website-blocker

# Check status / logs
systemctl --user status website-blocker
journalctl --user -u website-blocker -f
```

### 4. Install the browser extension

**Chrome/Chromium:**

1. Go to `chrome://extensions/`, enable "Developer mode"
2. "Load unpacked" → select `~/.local/share/website-blocker/extension/`
3. In the extension's details, enable **"Allow in incognito"** (required — enforcement checks for it)

### 5. Launch the desktop app

```bash
website-blocker          # installed executable
# or from source:
uv run python desktop-app/main.py
```

## Usage

### Creating blocks

A *block* groups rules together and defines when they're enforced and when configuration is locked.

- **Block schedule**: always, time range (days + start/end time, overnight ranges supported), or disabled
- **Lock schedule**: none, or locked until a specific date/time
- **Rules** (one per line):

```
Blocked Websites          Allowed Websites             Blocked Applications
reddit.com                reddit.com/r/programming     steam
youtube.com/shorts        reddit.com/r/linux           discord
twitter.com
```

### Pattern matching

| Pattern | Matches |
| --- | --- |
| `reddit.com` | reddit.com, all subdomains, all paths |
| `youtube.com/shorts` | only that path and its subpaths |
| `*.reddit.com` | all subdomains |
| `old.reddit.com` | only that subdomain |
| `steam` (app) | window class containing "steam" (e.g. `steam_app_123456`) |

Allow lists always take precedence over block lists. When multiple blocks match a URL, it's only allowed if **every** matching block's allow list permits it.

### Lock mode

While a block's lock is active: the block can't be edited or deleted, the daemon refuses to stop, and only *stricter* rules can be added. The settings lock does the same for global settings, with expiry checked against NTP so changing the system clock doesn't help.

### Browser status & grace period

The "Browsers" page shows which running browsers have a live extension heartbeat. "Add Extension" starts a 30-second grace period that pauses enforcement so you can install the extension without the browser being closed.

## Configuration Files

| File | Purpose |
| --- | --- |
| `~/.config/website-blocker/config.json` | Daemon settings |
| `~/.config/website-blocker/blocker.db` | SQLite database (blocks, events, heartbeats) |
| `~/.config/website-blocker/watchdog_state.json` | Watchdog process state |
| `~/.config/website-blocker/daemon.log` | Daemon log |
| `~/.config/systemd/user/website-blocker.service` | Systemd unit |

## API

The daemon exposes a REST API on `http://127.0.0.1:8765`. Highlights:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/status` | GET | Daemon status, active blocks |
| `/api/blocks` | GET/POST | List/create blocks |
| `/api/blocks/{id}` | PUT/DELETE | Update/delete (refused while locked) |
| `/api/blocks/{id}/strict` | PATCH | Add stricter rules (allowed while locked) |
| `/api/heartbeat` | POST | Browser extension heartbeat |
| `/api/blocked-sites` | GET | Current patterns, consumed by the extension |
| `/api/settings/lock` | GET/POST/DELETE | NTP-verified settings lock |
| `/api/settings/watchdog` | GET/PUT | Watchdog enable/disable |

## Development

### Running from source

```bash
uv run python daemon/main.py        # daemon in foreground
uv run python desktop-app/main.py   # desktop app
uv run python tray/main.py          # tray app

cd desktop-app/frontend && bun dev  # frontend with hot reload
```

### Tests & linting

```bash
uv run pytest            # unit tests (pattern matching, scheduling)
uv run ruff check .      # Python lint
cd desktop-app/frontend && bun run lint && bun run build
```

CI runs all of the above on every push (see `.github/workflows/ci.yml`).

### Debugging

```bash
curl http://127.0.0.1:8765/api/status | python3 -m json.tool   # daemon alive?
curl http://127.0.0.1:8765/api/browsers                        # extension heartbeats
hyprctl clients -j | jq '.[] | {class, pid, title}'            # what Hyprland sees
journalctl --user -u website-blocker -n 50 --no-pager          # recent daemon logs
```

## Limitations

**This is designed for self-control, not parental controls.** A determined user with system access can always win:

- `pkill -9 python` kills the daemon, watchdogs, and desktop app together
- `systemctl --user disable website-blocker` prevents auto-start after reboot
- Booting into recovery mode sidesteps everything
- Editing the database directly (when no lock is active)

The threat model is *impulsive* bypass, not adversarial admin access. The watchdog mesh, obfuscated process names, and NTP-verified locks are there to make cheating take long enough that the impulse passes. For genuinely adversarial scenarios you'd want network-level blocking or a separate restricted user account.

## License

[MIT](LICENSE)

---

Built for personal use on Arch Linux + Hyprland — designed specifically for tiling window managers and strict enforcement. The goal is productivity, not suffering. 🚀
