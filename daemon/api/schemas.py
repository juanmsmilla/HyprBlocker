"""Pydantic models for the website blocker API."""


from pydantic import BaseModel


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
    apps_blocked: str | None = None


class BlockStrictUpdate(BaseModel):
    """Update a block with stricter rules only (allowed even when locked).

    These operations make the block more restrictive:
    - Adding items to blocked lists
    - Removing items from allowed lists
    """
    websites_blocked_add: str | None = None      # Newline-separated items to ADD to blocked
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
    apps_blocked: str | None
    enabled: bool
    created_at: str

    class Config:
        from_attributes = True


class StatusResponse(BaseModel):
    running: bool
    active_rules: int
    active_blocks: int
    browsers_detected: int
    browsers_compliant: int


class StatsResponse(BaseModel):
    total_blocks_today: int
    total_blocks_week: int
    total_blocks_month: int
    websites_blocked_today: int
    apps_closed_today: int
    browsers_killed_today: int


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
