"""HyprBlocker root enforcer (phase 2 of the root migration).

Runs as root via ``hyprblocker-enforcer.service`` under the **root** layout
only. Owns the authoritative settings lock (``secure/lock.json``), watches the
user daemon's heartbeat attestation, fail-closes by killing browsers directly
via a ``/proc`` scan when the attestation goes stale, and repairs tampered
system files (systemd unit, native-messaging manifests).

Module split (pure logic vs. privilege):

- :mod:`enforcer.logic`      — all decision logic; zero I/O; fully unit-tested.
- :mod:`enforcer.proc_scan`  — /proc parsing (pure given a ``proc_root``) plus a
  thin SIGKILL wrapper.
- :mod:`enforcer.heartbeat`  — challenge/echo attestation helpers (pure verify).
- :mod:`enforcer.main`       — the privileged loop wiring it all together.
- :mod:`enforcer.breakglass_runner` — standalone, deliberately dumb time-delay
  release; imports nothing from the rest of this package (hardening R5).

This package is import-light by design: stdlib plus the path/uid-clean shared
modules from ``daemon`` (paths, settings_lock, enforcement_policy,
service_enforcer, system_assets). Importing it never performs I/O.
"""
