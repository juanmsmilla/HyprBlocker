"""Cancelable delayed unblock / loosening queue (prototype).

When enabled, deletes, loosening updates, and *disabling/reducing the delay
itself* are queued and applied after ``unblock_delay_minutes``. Cancel drops
the pending change; a new request starts the wait again from scratch.

Human-readable events go to ``~/.config/hyprblocker/unblock_delay.log``.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from daemon import paths
from daemon.config import get_config, reload_config, save_config

logger = logging.getLogger(__name__)

PendingKind = Literal["delete", "update", "settings"]


@dataclass
class PendingUnblock:
    id: str
    kind: PendingKind
    block_id: int
    block_name: str
    payload: dict[str, Any] | None
    created_at: str
    effective_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_lock = threading.RLock()
_pending: dict[str, PendingUnblock] = {}
_loaded = False


def _store_path() -> Path:
    paths.ensure_dir(paths.config_dir())
    return paths.config_dir() / "pending_unblocks.json"


def log_path() -> Path:
    paths.ensure_dir(paths.config_dir())
    return paths.config_dir() / "unblock_delay.log"


_LOG_MAX_BYTES = 1_048_576  # 1 MiB
_LOG_BACKUP_COUNT = 3


def _rotate_event_log_if_needed(path: Path) -> None:
    """Size-rotate unblock_delay.log when it reaches 1 MiB (keep .1 .. .N)."""
    try:
        if not path.exists() or path.stat().st_size < _LOG_MAX_BYTES:
            return
    except OSError:
        return
    for i in range(_LOG_BACKUP_COUNT, 0, -1):
        src = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        dst = path.with_name(f"{path.name}.{i}")
        try:
            if dst.exists():
                dst.unlink()
            if src.exists():
                src.rename(dst)
        except OSError:
            logger.exception("Failed rotating unblock_delay.log to %s", dst.name)


def event_log(message: str, **fields: Any) -> None:
    """Append one easy-to-skim line to unblock_delay.log and the daemon logger."""
    stamp = _iso(_now())
    extra = "".join(f" {k}={v!r}" for k, v in fields.items())
    line = f"{stamp} {message}{extra}"
    try:
        path = log_path()
        _rotate_event_log_if_needed(path)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        logger.exception("Failed to write unblock_delay.log")
    logger.info("[unblock-delay] %s%s", message, extra)


def read_event_log(limit: int = 100) -> list[str]:
    path = log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    limit = max(1, min(limit, 500))
    return lines[-limit:]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    path = _store_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            items = data if isinstance(data, list) else data.get("pending", [])
            for item in items:
                p = PendingUnblock(**item)
                _pending[p.id] = p
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error("Failed to load pending unblocks: %s", e)
            event_log("load_failed", error=str(e))
    _loaded = True


def _persist() -> None:
    path = _store_path()
    payload = [p.to_dict() for p in _pending.values()]
    path.write_text(json.dumps(payload, indent=2))


def delay_settings() -> tuple[bool, int]:
    """Return (enabled, minutes)."""
    cfg = get_config().security
    enabled = bool(getattr(cfg, "unblock_delay_enabled", False))
    minutes = int(getattr(cfg, "unblock_delay_minutes", 10) or 10)
    minutes = max(1, min(minutes, 24 * 60))
    return enabled, minutes


def list_pending() -> list[dict[str, Any]]:
    with _lock:
        _ensure_loaded()
        return [p.to_dict() for p in sorted(_pending.values(), key=lambda x: x.effective_at)]


def cancel(pending_id: str) -> bool:
    with _lock:
        _ensure_loaded()
        if pending_id not in _pending:
            return False
        removed = _pending.pop(pending_id)
        _persist()
        event_log(
            "canceled",
            kind=removed.kind,
            block_id=removed.block_id,
            name=removed.block_name,
            pending_id=removed.id,
        )
        return True


def cancel_all() -> int:
    with _lock:
        _ensure_loaded()
        n = len(_pending)
        ids = list(_pending.keys())
        _pending.clear()
        _persist()
        event_log("canceled_all", count=n, pending_ids=ids)
        return n


def cancel_for_block(block_id: int) -> int:
    """Drop any pending change for this block (new request restarts the wait)."""
    with _lock:
        _ensure_loaded()
        to_drop = [pid for pid, p in _pending.items() if p.block_id == block_id and p.kind != "settings"]
        for pid in to_drop:
            del _pending[pid]
        if to_drop:
            _persist()
            event_log("restarted_block_wait", block_id=block_id, dropped=len(to_drop))
        return len(to_drop)


def cancel_settings_pending() -> int:
    with _lock:
        _ensure_loaded()
        to_drop = [pid for pid, p in _pending.items() if p.kind == "settings"]
        for pid in to_drop:
            del _pending[pid]
        if to_drop:
            _persist()
            event_log("restarted_settings_wait", dropped=len(to_drop))
        return len(to_drop)


def enqueue(
    *,
    kind: PendingKind,
    block_id: int,
    block_name: str,
    payload: dict[str, Any] | None = None,
) -> PendingUnblock:
    enabled, minutes = delay_settings()
    if not enabled:
        raise RuntimeError("unblock delay is disabled")

    with _lock:
        _ensure_loaded()
        if kind == "settings":
            cancel_settings_pending()
        else:
            cancel_for_block(block_id)
        now = _now()
        effective = now + timedelta(minutes=minutes)
        pending = PendingUnblock(
            id=str(uuid.uuid4()),
            kind=kind,
            block_id=block_id,
            block_name=block_name,
            payload=payload,
            created_at=_iso(now),
            effective_at=_iso(effective),
        )
        _pending[pending.id] = pending
        _persist()
        event_log(
            "queued",
            kind=kind,
            block_id=block_id,
            name=block_name,
            pending_id=pending.id,
            effective_at=pending.effective_at,
            delay_minutes=minutes,
            payload=payload,
        )
        return pending


def enqueue_settings_loosen(payload: dict[str, Any]) -> PendingUnblock:
    """Queue disabling delay or reducing minutes (restartable)."""
    return enqueue(
        kind="settings",
        block_id=0,
        block_name="unblock-delay settings",
        payload=payload,
    )


def _apply_settings_payload(payload: dict[str, Any]) -> None:
    config = get_config()
    if "minutes" in payload and payload["minutes"] is not None:
        config.security.unblock_delay_minutes = int(payload["minutes"])
    if "enabled" in payload and payload["enabled"] is not None:
        turning_off = config.security.unblock_delay_enabled and not payload["enabled"]
        config.security.unblock_delay_enabled = bool(payload["enabled"])
        if turning_off:
            # Drop other pending block changes — delay is off, they should not fire.
            with _lock:
                _ensure_loaded()
                keep = {pid: p for pid, p in _pending.items() if p.kind == "settings"}
                dropped = len(_pending) - len(keep)
                _pending.clear()
                _pending.update(keep)
                _persist()
            event_log("settings_disable_applied_dropped_block_pending", dropped=dropped)
    save_config(config)
    reload_config()
    event_log("settings_applied", **payload)


async def apply_due(session_factory) -> int:
    """Apply any pending changes whose effective_at has passed. Returns count."""
    from sqlalchemy import select

    from daemon.database import Block

    with _lock:
        _ensure_loaded()
        now = _now()
        due = [p for p in _pending.values() if _parse_iso(p.effective_at) <= now]

    applied = 0
    for pending in due:
        try:
            if pending.kind == "settings":
                _apply_settings_payload(pending.payload or {})
                with _lock:
                    _pending.pop(pending.id, None)
                    _persist()
                event_log("applied", kind="settings", pending_id=pending.id)
                applied += 1
                continue

            async with session_factory() as session:
                result = await session.execute(
                    select(Block).where(Block.id == pending.block_id)
                )
                db_block = result.scalar_one_or_none()
                if pending.kind == "delete":
                    if db_block is not None:
                        await session.delete(db_block)
                        await session.commit()
                        event_log("applied", kind="delete", block_id=pending.block_id, name=pending.block_name)
                    else:
                        event_log("applied_missing_block", kind="delete", block_id=pending.block_id)
                elif pending.kind == "update":
                    if db_block is None:
                        event_log("applied_missing_block", kind="update", block_id=pending.block_id)
                    else:
                        payload = pending.payload or {}
                        for key, value in payload.items():
                            if key == "lock_until" and isinstance(value, str) and value.strip():
                                setattr(db_block, key, datetime.fromisoformat(value))
                            elif hasattr(db_block, key):
                                setattr(db_block, key, value)
                        await session.commit()
                        event_log(
                            "applied",
                            kind="update",
                            block_id=pending.block_id,
                            name=pending.block_name,
                            payload=payload,
                        )
            with _lock:
                _pending.pop(pending.id, None)
                _persist()
            applied += 1
        except Exception as e:
            event_log("apply_failed", pending_id=pending.id, kind=pending.kind, error=str(e))
            logger.exception("Failed to apply pending %s", pending.id)
    return applied
