"""Pydantic models for the website blocker API."""


from pydantic import BaseModel, ConfigDict


class HeartbeatRequest(BaseModel):
    pid: int
    browser: str
    incognito: bool = False
    incognito_enabled: bool = True
    extension_id: str  # Unique per browser profile
    window_count: int  # Windows visible to this extension
    timestamp: int | None = None


class HeartbeatResponse(BaseModel):
    status: str


class BlockCreate(BaseModel):
    name: str
    block_mode: str = 'always'  # 'always', 'time_range', 'disabled'
    block_days_of_week: str | None = None  # JSON array
    block_start_time: str | None = None
    block_end_time: str | None = None
    lock_mode: str = 'none'  # 'none', 'locked_until'
    lock_until: str | None = None  # ISO format datetime
    enabled: bool = True
    websites_blocked: str | None = None  # Newline-separated list
    websites_allowed: str | None = None  # Newline-separated allow list
    websites_media_blocked: str | None = None  # Images/video/audio on matching pages
    apps_blocked: str | None = None      # Newline-separated list


class BlockUpdate(BaseModel):
    name: str | None = None
    block_mode: str | None = None
    block_days_of_week: str | None = None
    block_start_time: str | None = None
    block_end_time: str | None = None
    lock_mode: str | None = None
    lock_until: str | None = None
    enabled: bool | None = None
    websites_blocked: str | None = None
    websites_allowed: str | None = None
    websites_media_blocked: str | None = None
    apps_blocked: str | None = None


class BlockStrictUpdate(BaseModel):
    """Update a block with stricter rules only (allowed even when locked).

    These operations make the block more restrictive:
    - Adding items to blocked lists
    - Removing items from allowed lists
    """
    websites_blocked_add: str | None = None      # Newline-separated items to ADD to blocked
    websites_media_blocked_add: str | None = None  # ADD to media-blocked (tightening)
    apps_blocked_add: str | None = None          # Newline-separated items to ADD to blocked
    websites_allowed_remove: str | None = None   # Newline-separated items to REMOVE from allowed


class BlockLockExtendRequest(BaseModel):
    """Request to extend lock duration for a block (allowed even when locked)."""
    lock_until: str  # ISO datetime - must be later than current lock_until


class BlockResponse(BaseModel):
    id: int
    name: str
    block_mode: str
    block_days_of_week: str | None
    block_start_time: str | None
    block_end_time: str | None
    lock_mode: str
    lock_until: str | None
    websites_blocked: str | None
    websites_allowed: str | None
    websites_media_blocked: str | None
    apps_blocked: str | None
    enabled: bool
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class StatusResponse(BaseModel):
    running: bool
    active_rules: int
    active_blocks: int
    browsers_detected: int
    browsers_compliant: int
    # Root-migration fields (see daemon.paths / daemon.enforcer_link):
    layout: str = "user"  # 'user' | 'root'
    enforcement_tier: str = "user"  # 'user' (watchdog mesh) | 'root' (enforcer)
    dev_mode: bool = True  # root enforcement intentionally weakened (pre-graduation)
    enforcer_down: bool = False  # root layout: enforcer snapshot stale/absent
    settings_locked: bool = False
    lock_until: str | None = None
    active_grants: int = 0


class GrantRequestBody(BaseModel):
    """Tier-1 blocker-rule exception request from the UI."""

    url: str
    reason: str
    minutes: int = 30


class GrantDecisionResponse(BaseModel):
    decision: str  # 'allow' | 'deny'
    stage: str  # 'denylist' | 'ratelimit' | 'judge'
    reason: str
    granted_minutes: int = 0
    expires_at: str | None = None


class ActiveGrantResponse(BaseModel):
    id: str
    url: str
    scope: str
    reason: str
    granted_at: str
    expires_at: str


class GrantsListResponse(BaseModel):
    active: list[ActiveGrantResponse]
    rate_limit_remaining: int


class BreakGlassResponse(BaseModel):
    state: str  # 'inactive' | 'pending' | 'released'
    triggered_at: str | None = None
    release_at: str | None = None


class StatsResponse(BaseModel):
    total_blocks_today: int
    total_blocks_week: int
    total_blocks_month: int
    websites_blocked_today: int
    apps_closed_today: int
    browsers_killed_today: int


class StatsTimelinePoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class StatsTopTarget(BaseModel):
    target: str
    count: int


class StatsRecentEvent(BaseModel):
    blocked_target: str
    event_type: str
    timestamp: str  # ISO datetime


class StatsDetailsResponse(BaseModel):
    timeline: list[StatsTimelinePoint]
    top_targets: list[StatsTopTarget]
    recent_events: list[StatsRecentEvent]


class BrowserStatus(BaseModel):
    pid: int
    browser: str
    compliant: bool
    last_heartbeat: str
    incognito_active: bool
    incognito_enabled: bool


class GracePeriodResponse(BaseModel):
    active: bool
    expires_at: str | None
    remaining_seconds: int | None


class BrowserEnforcementStatusResponse(BaseModel):
    enabled: bool
    source: str  # 'config' or 'default'


class BrowserEnforcementUpdateRequest(BaseModel):
    enabled: bool


class SafeSearchStatusResponse(BaseModel):
    enabled: bool
    source: str  # 'config' or 'default'


class SafeSearchUpdateRequest(BaseModel):
    enabled: bool


class ShutdownPreventionStatusResponse(BaseModel):
    enabled: bool
    source: str  # 'config' or 'default'


class ShutdownPreventionUpdateRequest(BaseModel):
    enabled: bool


class WatchdogStatusResponse(BaseModel):
    enabled: bool
    count: int
    active_watchdogs: list[dict]  # [{pid, name, uptime_seconds}]


class WatchdogUpdateRequest(BaseModel):
    enabled: bool | None = None
    count: int | None = None


class SettingsLockResponse(BaseModel):
    locked: bool
    lock_until: str | None  # ISO datetime
    remaining_seconds: int | None


class SettingsLockRequest(BaseModel):
    lock_until: str  # ISO datetime


class JudgePolicyResponse(BaseModel):
    text: str  # the active policy document (strict preset when no file exists)
    preset: str | None  # which shipped preset the active text is, else None
    presets: dict[str, str]  # {name: full text} for the UI's preset picker
    max_chars: int
    locked: bool
    dev_mode: bool  # pre-graduation: edits apply immediately, lock or not
    pending_text: str | None  # a scheduled (delayed loosening) edit, if any
    pending_effective_at: str | None  # ISO datetime the pending edit applies


class JudgePolicyUpdateRequest(BaseModel):
    text: str


class UnblockDelayStatusResponse(BaseModel):
    enabled: bool
    minutes: int
    pending_count: int = 0


class UnblockDelayUpdateRequest(BaseModel):
    enabled: bool | None = None
    minutes: int | None = None


class PendingUnblockResponse(BaseModel):
    id: str
    kind: str
    block_id: int
    block_name: str
    created_at: str
    effective_at: str
    remaining_seconds: int


class PendingUnblockQueuedResponse(BaseModel):
    status: str = "pending"
    pending_id: str
    kind: str
    block_id: int
    block_name: str
    effective_at: str
    delay_minutes: int


class UnblockDelayLogResponse(BaseModel):
    path: str
    lines: list[str]
