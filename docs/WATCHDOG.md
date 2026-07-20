# Watchdog System

The watchdog system is HyprBlocker's answer to the most obvious bypass: killing the daemon. It spawns a small mesh of independent processes that monitor the daemon *and each other*, so that no single `kill` command disables enforcement.

## Design Goals

1. **No single point of failure** — killing any one process (daemon or watchdog) results in it being restarted by a survivor.
2. **Friction, not invincibility** — this is a self-control tool. The goal is to make an impulsive bypass take long enough that you reconsider, not to be unbeatable by a determined administrator.
3. **Clean opt-in/opt-out** — watchdogs only run when explicitly enabled, and shut down cleanly when disabled through the API (respecting the settings lock).

## How It Works

```
                     spawns N watchdogs
   Daemon ──────────────────────────────────┐
     ▲                                      ▼
     │  systemctl --user restart   ┌─── Watchdog 1 ◄──┐
     │◄────────────────────────────┤                  │  PID checks
     │  (if daemon HTTP check      ├─── Watchdog 2 ◄──┤  every 10s,
     │   fails)                    │                  │  respawn dead
     │                             └─── Watchdog 3 ◄──┘  siblings
     │      HTTP health check every 5s
     └──────────────────────────────────────┘
```

- On startup (when enabled), the daemon spawns **N watchdog processes** (configurable 2–5, default 3) via `watchdog_runner.py`.
- Each watchdog:
  - Polls the daemon's HTTP API every **5 seconds**. If the daemon is unreachable, the watchdog restarts it with `systemctl --user restart hyprblocker`.
  - Checks its **sibling watchdogs' PIDs every 10 seconds**. If a sibling has died, it respawns a replacement.
- Watchdogs run with **obfuscated process names** (e.g. `kworker-7`) so they blend in with normal system processes, raising the effort needed to find and kill all of them at once.

## Shared State

Watchdogs coordinate through a state file at `~/.config/hyprblocker/watchdog_state.json`:

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

The `shutdown_requested` flag is how a *legitimate* shutdown works: when watchdogs are disabled through the API, the daemon sets this flag first, so the watchdogs exit instead of resurrecting everything.

## Coupling with Shutdown Prevention

Watchdogs require **shutdown prevention** to be enabled:

- Shutdown prevention makes the daemon ignore `SIGTERM` while blocks are locked.
- Without it, watchdogs would be pointless — the daemon could simply be stopped via systemd.
- Disabling shutdown prevention automatically disables the watchdogs.
- When a **settings lock** is active, neither toggle can be changed, so the protection can't be removed until the lock expires (verified against NTP time, not the local clock).

## Relevant Code

| File | Role |
| --- | --- |
| `daemon/watchdog.py` | Watchdog manager: spawning, state file, shutdown coordination |
| `daemon/watchdog_runner.py` | Entry point for each standalone watchdog process |
| `daemon/api/routes/settings.py` | `/api/settings/watchdog` — enable/disable, count |
| `daemon/main.py` | Spawns watchdogs on daemon startup when enabled |

## Relationship to the root enforcer (root layout)

Once the root-owned migration is installed (see
[`documentation/ROOT_MIGRATION_DESIGN.md`](../documentation/ROOT_MIGRATION_DESIGN.md)),
the `hyprblocker-enforcer` **system** service — `Restart=always`, only stoppable with
sudo — supersedes this user-space mesh. It does the kill-resistance job properly instead
of relying on obfuscation.

The mesh is **not** deleted, though: it stays as a *fallback*. `daemon/enforcer_link.py`
gates the mesh on *observed enforcer liveness* (a fresh `secure/enforcer_state.json`
snapshot for the current boot), not merely on the layout. So if the root enforcer fails to
start after the first reboot, the daemon still spawns the mesh and protection never
silently regresses. Under the pre-migration **user layout**, the mesh behaves exactly as
documented above.

## Known Bypasses

Documented deliberately — see the Limitations section in the [README](../README.md):

- `pkill -9 python` kills daemon and watchdogs together (they're all Python processes).
  *(Closed under the root layout: the enforcer runs as root and re-kills browsers /
  restarts the daemon; stopping it needs sudo.)*
- `systemctl --user disable hyprblocker` prevents restart after the next reboot.
  *(Closed under the root layout: the unit is root-owned in `/etc/systemd/user`, and the
  daemon + enforcer delete user-dir shadow units.)*
- Booting into a recovery environment sidesteps everything. *(Remains — the physical
  backstop, acceptable by design.)*

These are acceptable within the threat model: each requires a deliberate, multi-step action
rather than a single impulsive click.
