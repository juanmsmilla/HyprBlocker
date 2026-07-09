# HyprBlocker — Notes for Claude

Architecture, commands, and APIs are discoverable from the code, README, and docs/ — explore as needed. Below is only what can't be found by reading the code.

## The daemon on this machine is live (critical)

This repo is the working copy of the blocker actively enforcing on this machine: the `hyprblocker.service` systemd user unit runs `python -m daemon.main` from this repo's `.venv`, and the watchdog processes run from it too. Never stop, restart, or kill the daemon or its watchdogs — it is designed to resist that, and settings may be time-locked. Don't run `python -m daemon.main` locally either; the live daemon holds port 8765. Daemon code changes only take effect at the next reboot: edit and run tests freely, but don't try to apply changes to the running daemon.

## Non-obvious invariants

- The `"key"` field in `extension/manifest.json` pins a stable extension ID that native messaging depends on. Never remove or change it — if it breaks, the daemon kills every browser even with the extension installed. See "Native Messaging and Extension IDs" in `docs/TECHNICAL_CONCEPTS.md`.

## Developer preferences

- Early development, single user — don't worry about backwards compatibility.
