"""Settings API routes for browser enforcement, safe search, watchdog, and lock."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from daemon.config import get_config, reload_config, save_config
from daemon.service_enforcer import ensure_service_enabled
from daemon.time_verifier import get_time_verifier
from daemon.watchdog import WatchdogManager, is_settings_locked_ntp

from ..schemas import (
    BrowserEnforcementStatusResponse,
    BrowserEnforcementUpdateRequest,
    JudgePolicyResponse,
    JudgePolicyUpdateRequest,
    SafeSearchStatusResponse,
    SafeSearchUpdateRequest,
    SettingsLockRequest,
    SettingsLockResponse,
    ShutdownPreventionStatusResponse,
    ShutdownPreventionUpdateRequest,
    WatchdogStatusResponse,
    WatchdogUpdateRequest,
    UnblockDelayStatusResponse,
    UnblockDelayUpdateRequest,
    UnblockDelayLogResponse,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)


def _reject_if_locked(loosening: bool) -> None:
    """403 only when a *loosening* change is attempted under an active lock.

    The lock exists to stop future-you from weakening protections; making them
    stricter must always stay possible (tightening-only — the same asymmetry
    the root tier applies to lock requests).
    """
    if loosening and is_settings_locked_ntp():
        raise HTTPException(
            status_code=403,
            detail="Settings are locked — only tightening changes are allowed",
        )


# Browser enforcement endpoints
@router.get("/browser-enforcement", response_model=BrowserEnforcementStatusResponse)
async def get_browser_enforcement_status():
    """Get current browser enforcement status."""
    config = get_config()

    return BrowserEnforcementStatusResponse(
        enabled=config.security.browser_enforcement_enabled,
        source='config' if not config.security.browser_enforcement_enabled else 'default'
    )


@router.put("/browser-enforcement")
async def update_browser_enforcement_status(request: BrowserEnforcementUpdateRequest):
    """Update browser enforcement setting.

    While locked, only enabling (tightening) is allowed.
    """
    _reject_if_locked(loosening=not request.enabled)

    # Update config
    config = get_config()
    config.security.browser_enforcement_enabled = request.enabled
    save_config(config)

    # Reload config to apply changes immediately
    reload_config()

    if request.enabled:
        logger.info("Browser enforcement ENABLED via UI")
    else:
        logger.warning("Browser enforcement DISABLED via UI")

    return {"success": True, "enabled": request.enabled}


# Safe search endpoints
@router.get("/safe-search", response_model=SafeSearchStatusResponse)
async def get_safe_search_status():
    """Get current safe search enforcement status."""
    config = get_config()

    return SafeSearchStatusResponse(
        enabled=config.security.safe_search_enabled,
        source='config' if config.security.safe_search_enabled else 'default'
    )


@router.put("/safe-search")
async def update_safe_search_status(request: SafeSearchUpdateRequest):
    """Update safe search enforcement setting.

    While locked, only enabling (tightening) is allowed.
    """
    _reject_if_locked(loosening=not request.enabled)

    # Update config
    config = get_config()
    config.security.safe_search_enabled = request.enabled
    save_config(config)

    # Reload config to apply changes immediately
    reload_config()

    if request.enabled:
        logger.info("Safe search enforcement ENABLED via UI")
    else:
        logger.warning("Safe search enforcement DISABLED via UI")

    return {"success": True, "enabled": request.enabled}


# Shutdown prevention endpoints
@router.get("/shutdown-prevention", response_model=ShutdownPreventionStatusResponse)
async def get_shutdown_prevention_status():
    """Get current shutdown prevention status."""
    config = get_config()

    return ShutdownPreventionStatusResponse(
        enabled=config.security.shutdown_prevention_enabled,
        source='config' if config.security.shutdown_prevention_enabled else 'default'
    )


@router.put("/shutdown-prevention")
async def update_shutdown_prevention_status(request: ShutdownPreventionUpdateRequest):
    """Update shutdown prevention setting.

    While locked, only enabling (tightening) is allowed.
    If disabling, also disables and stops watchdogs.
    """
    _reject_if_locked(loosening=not request.enabled)

    config = get_config()
    config.security.shutdown_prevention_enabled = request.enabled

    # If disabling shutdown prevention, also disable watchdogs
    if not request.enabled and config.security.watchdog_enabled:
        config.security.watchdog_enabled = False
        manager = WatchdogManager(
            watchdog_count=config.security.watchdog_count,
            daemon_port=config.daemon.port
        )
        manager.signal_shutdown()
        logger.info("Watchdog processes stopped (shutdown prevention disabled)")

    save_config(config)
    reload_config()

    if request.enabled:
        # Immediately restore the enable symlink in case it was removed
        ensure_service_enabled()
        logger.info("Shutdown prevention ENABLED via UI")
    else:
        logger.warning("Shutdown prevention DISABLED via UI")

    return {"success": True, "enabled": request.enabled}


# Watchdog endpoints
@router.get("/watchdog", response_model=WatchdogStatusResponse)
async def get_watchdog_status():
    """Get current watchdog status and active processes."""
    config = get_config()
    manager = WatchdogManager(
        watchdog_count=config.security.watchdog_count,
        daemon_port=config.daemon.port
    )

    active = manager.get_active_watchdogs()

    return WatchdogStatusResponse(
        enabled=config.security.watchdog_enabled,
        count=config.security.watchdog_count,
        active_watchdogs=active
    )


@router.put("/watchdog")
async def update_watchdog_settings(request: WatchdogUpdateRequest):
    """Update watchdog settings.

    While locked, only tightening is allowed: enabling watchdogs or raising the
    count passes; disabling or lowering the count is rejected.
    Cannot enable watchdogs if shutdown prevention is disabled.
    """
    config = get_config()
    loosening = (request.enabled is not None and not request.enabled) or (
        request.count is not None and request.count < config.security.watchdog_count
    )
    _reject_if_locked(loosening)

    if request.enabled is not None:
        # Cannot enable watchdogs if shutdown prevention is disabled
        if request.enabled and not config.security.shutdown_prevention_enabled:
            raise HTTPException(
                status_code=400,
                detail="Cannot enable watchdogs when shutdown prevention is disabled"
            )

        old_enabled = config.security.watchdog_enabled
        config.security.watchdog_enabled = request.enabled

        # If enabling, spawn watchdogs
        if request.enabled and not old_enabled:
            manager = WatchdogManager(
                watchdog_count=config.security.watchdog_count,
                daemon_port=config.daemon.port
            )
            manager.spawn_watchdogs()
            logger.info("Watchdog processes spawned")

        # If disabling, signal shutdown
        elif not request.enabled and old_enabled:
            manager = WatchdogManager(
                watchdog_count=config.security.watchdog_count,
                daemon_port=config.daemon.port
            )
            manager.signal_shutdown()
            logger.info("Watchdog shutdown signaled")

    if request.count is not None:
        # Clamp to valid range
        config.security.watchdog_count = max(2, min(5, request.count))

    save_config(config)
    reload_config()

    return {
        "success": True,
        "enabled": config.security.watchdog_enabled,
        "count": config.security.watchdog_count
    }


# Grant-judge policy endpoints
def _pending_judge_policy() -> tuple[str | None, str | None]:
    """The scheduled (delayed loosening) judge-policy edit, if one is pending.

    Reads the enforcer's world-readable ``secure/pending_changes.json``. Returns
    ``(text, apply_at_iso)`` of the newest pending ``judge_policy`` entry, or
    ``(None, None)`` — including in the user layout, where the file never exists.
    """
    import json

    from daemon import paths

    try:
        data = json.loads((paths.secure_dir() / "pending_changes.json").read_text())
        entries = data.get("pending", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return None, None
    text: str | None = None
    apply_at: str | None = None
    for entry in entries:
        request = entry.get("request") if isinstance(entry, dict) else None
        if isinstance(request, dict) and request.get("type") == "judge_policy":
            text = request.get("text")
            apply_at = entry.get("apply_at")
    return text, apply_at


@router.get("/judge-policy", response_model=JudgePolicyResponse)
async def get_judge_policy():
    """Get the active grant-judge policy, available presets, and any pending edit."""
    from daemon import paths
    from daemon.grants import policy as grant_policy

    text = grant_policy.load_policy_text()
    pending_text, pending_at = _pending_judge_policy()
    return JudgePolicyResponse(
        text=text,
        preset=grant_policy.identify_preset(text),
        presets=grant_policy.PRESETS,
        max_chars=grant_policy.MAX_POLICY_CHARS,
        locked=is_settings_locked_ntp(),
        dev_mode=paths.is_dev_mode(),
        pending_text=pending_text,
        pending_effective_at=pending_at,
    )


@router.put("/judge-policy")
async def update_judge_policy(request: JudgePolicyUpdateRequest):
    """Replace the grant-judge policy document.

    Same asymmetry as every other setting: while locked, only a mechanical
    tightening (shipped preset → stricter shipped preset) is accepted; free-form
    edits and preset loosenings 403. Unlocked, any valid edit is accepted, but
    loosenings still apply only after the enforcer's delay (root layout).

    Dev-mode carve-out: pre-graduation (no root credential yet) any valid edit
    is accepted and applies immediately, lock or not — the lock and the loosening
    delay bind future-you, not development. The enforcer applies the same rule
    on its side, so the dropped request is not delayed either.

    Root layout: the file is root-owned ``secure/policy.md``, so the edit is
    dropped into ``requests/settings/`` for the enforcer (tightenings land on
    its next tick). User layout: no enforcer and no privilege boundary — the
    daemon writes the file directly and immediately.
    """
    from daemon import paths
    from daemon.grants import policy as grant_policy

    errors = grant_policy.validate_policy_text(request.text)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    current = grant_policy.load_policy_text()
    decision = grant_policy.classify_policy_edit(current, request.text)
    if decision.reason == "no change":
        return {"success": True, "pending": False, "reason": "no change"}
    dev_mode = paths.is_dev_mode()
    if not dev_mode:
        _reject_if_locked(loosening=not decision.apply_immediately)

    if paths.layout() == "root":
        from daemon import requests_bridge

        requests_bridge.drop_request(requests_bridge.build_judge_policy_request(request.text))
        logger.info("Judge policy edit dropped for enforcer (%s)", decision.reason)
        return {
            "success": True,
            "pending": not decision.apply_immediately and not dev_mode,
            "reason": decision.reason,
        }

    path = paths.policy_path()
    paths.ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(request.text, encoding="utf-8")
    tmp.replace(path)
    logger.info("Judge policy updated (%s)", decision.reason)
    return {"success": True, "pending": False, "reason": decision.reason}


# Settings lock endpoints
@router.get("/lock", response_model=SettingsLockResponse)
async def get_settings_lock():
    """Get current settings lock status.

    Reads the authoritative lock via :mod:`daemon.settings_lock` so it is correct
    in both layouts (config.json in user layout; root-owned secure/lock.json in
    root layout).
    """
    from daemon import settings_lock

    lock_until = settings_lock.read_lock_until()
    lock_until_str = lock_until.isoformat() if lock_until else None

    if not lock_until_str:
        return SettingsLockResponse(
            locked=False,
            lock_until=None,
            remaining_seconds=None
        )

    # Check if actually locked (NTP verified)
    is_locked = is_settings_locked_ntp()

    if not is_locked:
        return SettingsLockResponse(
            locked=False,
            lock_until=lock_until_str,
            remaining_seconds=0
        )

    # Calculate remaining time
    try:
        lock_until = datetime.fromisoformat(lock_until_str)
        if lock_until.tzinfo is None:
            lock_until = lock_until.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        remaining = int((lock_until - now).total_seconds())
    except Exception:
        remaining = None

    return SettingsLockResponse(
        locked=True,
        lock_until=lock_until_str,
        remaining_seconds=max(0, remaining) if remaining else None
    )


@router.post("/lock")
async def lock_settings(request: SettingsLockRequest):
    """Lock settings until a specific datetime.

    Uses NTP verification to prevent clock manipulation.
    If already locked, allows extending the lock (but not shortening).
    """
    # Parse and validate lock_until
    try:
        lock_until = datetime.fromisoformat(request.lock_until)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid datetime format. Use ISO format like '2024-12-25T14:30:00'"
        ) from None

    # Verify system time with NTP
    verifier = get_time_verifier()
    if not verifier.is_system_time_valid():
        raise HTTPException(
            status_code=403,
            detail="System time appears to be manipulated. Cannot set lock."
        )

    now = datetime.now(UTC)
    if lock_until.tzinfo is None:
        lock_until = lock_until.replace(tzinfo=UTC)

    # Root layout: the authoritative lock lives in root-owned secure/lock.json,
    # which the user daemon cannot write. Drop a request for the enforcer instead
    # (it applies tightening — extending the lock — immediately). (Review M3.)
    from daemon import paths, settings_lock

    if paths.layout() == "root":
        current_lock = settings_lock.read_lock_until()
        if current_lock is not None:
            if current_lock.tzinfo is None:
                current_lock = current_lock.replace(tzinfo=UTC)
            if lock_until <= current_lock:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot shorten lock. New time must be later than current lock expiry.",
                )
        elif lock_until <= now:
            # New lock with no active lock present: must be in the future
            # (parity with the user-layout branch below).
            raise HTTPException(status_code=400, detail="lock_until must be in the future")
        from daemon import requests_bridge

        requests_bridge.drop_request(requests_bridge.build_lock_request(lock_until.isoformat()))
        return {"success": True, "pending": True, "lock_until": lock_until.isoformat()}

    # Check if already locked
    config = get_config()
    current_lock_str = config.security.settings_lock_until

    if current_lock_str and is_settings_locked_ntp():
        # Already locked - this is an EXTENSION request
        current_lock = datetime.fromisoformat(current_lock_str)
        if current_lock.tzinfo is None:
            current_lock = current_lock.replace(tzinfo=UTC)

        if lock_until <= current_lock:
            raise HTTPException(
                status_code=400,
                detail="Cannot shorten lock. New time must be later than current lock expiry."
            )
        # Allow extension - no need to check against 'now' since current lock is active
    else:
        # New lock - must be in the future
        if lock_until <= now:
            raise HTTPException(
                status_code=400,
                detail="lock_until must be in the future"
            )

    # Save the lock
    config.security.settings_lock_until = lock_until.isoformat()
    save_config(config)
    reload_config()

    logger.info(f"Settings locked until {lock_until.isoformat()}")

    return {
        "success": True,
        "lock_until": lock_until.isoformat()
    }


@router.delete("/lock")
async def unlock_settings():
    """Unlock settings.

    Only works if the lock has expired (verified via NTP).
    """
    # Check if still locked
    if is_settings_locked_ntp():
        raise HTTPException(
            status_code=403,
            detail="Settings are still locked. Cannot unlock before expiry."
        )

    # Root layout: only the enforcer can write the authoritative lock. Since the
    # lock has already expired (checked above), drop a clear request. (Review M3.)
    from daemon import paths

    if paths.layout() == "root":
        from daemon import requests_bridge

        requests_bridge.drop_request(requests_bridge.build_lock_request(None))
        return {"success": True, "pending": True}

    # Clear the lock
    config = get_config()
    config.security.settings_lock_until = None
    save_config(config)
    reload_config()

    logger.info("Settings lock cleared")

    return {"success": True}


# Unblock delay (prototype)
@router.get("/unblock-delay", response_model=UnblockDelayStatusResponse)
async def get_unblock_delay_status():
    """Get cancelable delay-before-unblock settings."""
    from daemon import pending_unblock

    config = get_config()
    return UnblockDelayStatusResponse(
        enabled=config.security.unblock_delay_enabled,
        minutes=config.security.unblock_delay_minutes,
        pending_count=len(pending_unblock.list_pending()),
    )


@router.get("/unblock-delay/log", response_model=UnblockDelayLogResponse)
async def get_unblock_delay_log(limit: int = 100):
    """Recent human-readable delay events (also at ~/.config/hyprblocker/unblock_delay.log)."""
    from daemon import pending_unblock

    return UnblockDelayLogResponse(
        path=str(pending_unblock.log_path()),
        lines=pending_unblock.read_event_log(limit),
    )


@router.put("/unblock-delay")
async def update_unblock_delay_settings(request: UnblockDelayUpdateRequest):
    """Update delay-before-unblock toggle and minutes.

    Tightening (enable, or raise minutes) applies immediately.
    Loosening (disable, or lower minutes) is itself delayed when delay is on —
    cancelable; a new request restarts the full wait.
    """
    from fastapi import Response

    from daemon import pending_unblock
    from daemon.api.schemas import PendingUnblockQueuedResponse

    config = get_config()
    enabled_now, minutes_now = pending_unblock.delay_settings()

    if request.minutes is not None:
        if request.minutes < 1 or request.minutes > 24 * 60:
            raise HTTPException(status_code=400, detail="minutes must be between 1 and 1440")

    payload: dict = {}
    if request.enabled is not None and request.enabled != config.security.unblock_delay_enabled:
        payload["enabled"] = request.enabled
    if request.minutes is not None and request.minutes != config.security.unblock_delay_minutes:
        payload["minutes"] = request.minutes

    if not payload:
        return {
            "success": True,
            "enabled": config.security.unblock_delay_enabled,
            "minutes": config.security.unblock_delay_minutes,
            "pending_count": len(pending_unblock.list_pending()),
        }

    # Classify: loosening if disabling or reducing minutes
    loosening = False
    if "enabled" in payload and payload["enabled"] is False and enabled_now:
        loosening = True
    if "minutes" in payload and payload["minutes"] < minutes_now:
        loosening = True

    if enabled_now and loosening:
        pending = pending_unblock.enqueue_settings_loosen(payload)
        return {
            "success": True,
            "pending": True,
            "pending_id": pending.id,
            "kind": pending.kind,
            "effective_at": pending.effective_at,
            "delay_minutes": minutes_now,
            "enabled": config.security.unblock_delay_enabled,
            "minutes": config.security.unblock_delay_minutes,
            "pending_count": len(pending_unblock.list_pending()),
            "message": (
                f"Delay-settings change queued — applies in {minutes_now} min "
                "(cancel from pending list). Turning delay off is also delayed."
            ),
        }

    # Immediate tightening / changes while delay is off
    if "minutes" in payload:
        config.security.unblock_delay_minutes = int(payload["minutes"])
    if "enabled" in payload:
        config.security.unblock_delay_enabled = bool(payload["enabled"])
        if not payload["enabled"]:
            canceled = pending_unblock.cancel_all()
            pending_unblock.event_log("disabled_immediately", canceled=canceled)

    save_config(config)
    reload_config()
    pending_unblock.event_log("settings_saved_immediate", **payload)

    return {
        "success": True,
        "pending": False,
        "enabled": config.security.unblock_delay_enabled,
        "minutes": config.security.unblock_delay_minutes,
        "pending_count": len(pending_unblock.list_pending()),
    }
