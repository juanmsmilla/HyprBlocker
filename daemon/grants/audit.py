"""Append-only grant audit log.

Every grant request, every stage decision (denylist, ratelimit, judge), and
the full judge transcript land here as one JSON object per line (JSONL) at
``paths.grants_log_path()`` — ``secure/grants.log`` under the root layout,
root-writable but WORLD-READABLE by design: the accountability story depends
on the log being inspectable by anyone.

The judge is shown a summary of prior entries ("claimed 'work research' 4×
this week") so skeptical policy presets can reason about patterns.

Pure parsing/summarizing helpers are separated from the two thin I/O wrappers
(:func:`append_entry`, :func:`read_entries`) so tests never need the real log.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from daemon import paths
from daemon.grants.models import GrantRequest, Verdict

logger = logging.getLogger(__name__)

# World-readable: audit transparency is a feature, and the log must never
# contain secrets (the judge is verdict-only I/O; keys never enter prompts).
_LOG_MODE = 0o644

_REASON_PREVIEW_CHARS = 80


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def parse_entries(text: str) -> list[dict[str, Any]]:
    """Parse JSONL audit text, skipping malformed/non-object lines."""
    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed audit line: %.80s", line)
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


def summarize_history(
    entries: Iterable[dict[str, Any]],
    now: datetime | None = None,
    window: timedelta = timedelta(days=7),
    limit: int = 20,
) -> str:
    """Render recent decision entries as plain lines for the judge prompt.

    The result is DATA injected into a delimited history block — one line per
    decision, newest last, reasons truncated. Returns "" when nothing recent.
    """
    now = now or datetime.now(UTC)
    cutoff = now - window
    lines: list[str] = []
    for entry in entries:
        if entry.get("kind") != "decision":
            continue
        raw_ts = entry.get("ts")
        try:
            ts = datetime.fromisoformat(raw_ts) if isinstance(raw_ts, str) else None
        except ValueError:
            ts = None
        if ts is not None:
            ts_utc = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
            if ts_utc < cutoff:
                continue
        reason = str(entry.get("reason", ""))[:_REASON_PREVIEW_CHARS]
        lines.append(
            f"{raw_ts or '?'} tier={entry.get('tier', '?')} "
            f"target={entry.get('target', '?')!r} reason={reason!r} "
            f"-> {entry.get('decision', '?')} ({entry.get('stage', '?')})"
        )
    return "\n".join(lines[-limit:])


# --------------------------------------------------------------------------
# I/O wrappers
# --------------------------------------------------------------------------

def append_entry(entry: dict[str, Any], path: Path | None = None) -> None:
    """Append one entry to the audit log (adds ``ts`` if absent).

    Append-only by construction: the file is opened with ``O_APPEND`` and is
    never truncated or rewritten here. Created world-readable.
    """
    path = path or paths.grants_log_path()
    paths.ensure_dir(path.parent)
    entry = dict(entry)
    entry.setdefault("ts", datetime.now(UTC).isoformat())
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, _LOG_MODE)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        # Audit is transparency, not enforcement — an unwritable log must not
        # take down the grant pipeline (it 500'd every request when this path
        # briefly pointed into root-owned secure/).
        logger.error("Cannot append grant audit entry to %s: %s", path, e)


def read_entries(path: Path | None = None) -> list[dict[str, Any]]:
    """Read all audit entries; a missing/unreadable log reads as empty."""
    path = path or paths.grants_log_path()
    try:
        return parse_entries(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def record_request(request: GrantRequest, path: Path | None = None) -> None:
    """Log a request the moment it arrives — before any stage can drop it."""
    append_entry(
        {
            "kind": "request",
            "ts": request.created_at.isoformat(),
            "request_id": request.id,
            "tier": int(request.tier),
            "target": request.target,
            "reason": request.reason,
            "minutes": request.minutes,
            "argv": list(request.argv) if request.argv else None,
        },
        path,
    )


def record_decision(
    request: GrantRequest,
    verdict: Verdict,
    stage: str,
    transcript: list[dict[str, str]] | None = None,
    path: Path | None = None,
) -> None:
    """Log the final decision for a request, including the judge transcript.

    ``stage`` names which layer decided: ``denylist`` / ``ratelimit`` /
    ``judge`` / ``error``.
    """
    append_entry(
        {
            "kind": "decision",
            "request_id": request.id,
            "tier": int(request.tier),
            "target": request.target,
            "reason": request.reason,
            "stage": stage,
            "decision": verdict.decision,
            "scope": verdict.scope,
            "granted_minutes": verdict.minutes,
            "verdict_reason": verdict.reason,
            "transcript": transcript or [],
        },
        path,
    )
