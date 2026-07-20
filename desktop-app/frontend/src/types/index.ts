// Block configuration
export interface Block {
  id: number;
  name: string;
  block_mode: 'always' | 'time_range' | 'disabled';
  block_days_of_week: string | null; // JSON string of number array
  block_start_time: string | null;
  block_end_time: string | null;
  lock_mode: 'none' | 'locked_until';
  lock_until: string | null;
  enabled: boolean;
  created_at: string;
  websites_blocked: string | null;
  websites_allowed: string | null;
  apps_blocked: string | null;
}

// Block input for creating/updating
export interface BlockInput {
  name: string;
  block_mode: 'always' | 'time_range' | 'disabled';
  lock_mode: 'none' | 'locked_until';
  enabled: boolean;
  block_days_of_week?: string;
  block_start_time?: string;
  block_end_time?: string;
  lock_until?: string;
  websites_blocked?: string | null;
  websites_allowed?: string | null;
  apps_blocked?: string | null;
}

// Daemon status
export interface DaemonStatus {
  running: boolean;
  active_rules: number;
  active_blocks: number;
  browsers_detected: number;
  browsers_compliant: number;
  layout?: 'user' | 'root';
  enforcement_tier?: 'user' | 'root';
  dev_mode?: boolean;
  enforcer_down?: boolean;
  settings_locked?: boolean;
  lock_until?: string | null;
  active_grants?: number;
  error?: string;
}

// Statistics
export interface Stats {
  total_blocks_today: number;
  total_blocks_week: number;
  total_blocks_month: number;
  websites_blocked_today: number;
  apps_closed_today: number;
  browsers_killed_today: number;
}

// Detailed statistics
export interface StatsTimelinePoint {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface StatsTopTarget {
  target: string;
  count: number;
}

export interface StatsRecentEvent {
  blocked_target: string;
  event_type: string;
  timestamp: string;
}

export interface StatsDetails {
  timeline: StatsTimelinePoint[];
  top_targets: StatsTopTarget[];
  recent_events: StatsRecentEvent[];
}

// Browser status
export interface BrowserStatus {
  pid: number;
  browser: string;
  compliant: boolean;
  last_heartbeat: string;
  incognito_active: boolean;
  incognito_enabled: boolean;
}

// Grace period status
export interface GracePeriodStatus {
  active: boolean;
  expires_at: string | null;
  remaining_seconds: number;
}

// API response types
export interface ApiResponse {
  success: boolean;
  error?: string;
  locked?: boolean;
}

export interface AddBlockResponse extends ApiResponse {
  block?: {
    id: number;
    name: string;
  };
}

export interface GracePeriodResponse extends ApiResponse {
  active?: boolean;
  expires_at?: string;
  remaining_seconds?: number;
}

export interface LockStatusResponse {
  locked: boolean;
}

// Strict update input (for adding rules to locked blocks)
export interface BlockStrictUpdateInput {
  websites_blocked_add?: string;
  apps_blocked_add?: string;
  websites_allowed_remove?: string;
}

// Browser enforcement settings
export interface BrowserEnforcementStatus {
  enabled: boolean;
  source: 'config' | 'default' | 'unknown';
  error?: string;
}

export interface BrowserEnforcementUpdateResponse {
  success: boolean;
  enabled?: boolean;
  error?: string;
  settingsLocked?: boolean;
}

// Safe search enforcement settings
export interface SafeSearchStatus {
  enabled: boolean;
  source: 'config' | 'default' | 'unknown';
  error?: string;
}

export interface SafeSearchUpdateResponse {
  success: boolean;
  enabled?: boolean;
  error?: string;
  settingsLocked?: boolean;
}

// Shutdown prevention settings
export interface ShutdownPreventionStatus {
  enabled: boolean;
  source: 'config' | 'default' | 'unknown';
  error?: string;
}

export interface ShutdownPreventionUpdateResponse {
  success: boolean;
  enabled?: boolean;
  error?: string;
  settingsLocked?: boolean;
}

// Watchdog status
export interface WatchdogStatus {
  enabled: boolean;
  count: number;
  activeWatchdogs: Array<{
    pid: number;
    name: string;
    uptime_seconds: number;
  }>;
  error?: string;
}

export interface WatchdogUpdateResponse {
  success: boolean;
  enabled?: boolean;
  count?: number;
  error?: string;
  settingsLocked?: boolean;
}

// Settings lock
export interface SettingsLockStatus {
  locked: boolean;
  lockUntil: string | null;
  remainingSeconds: number | null;
}

export interface SettingsLockResponse {
  success: boolean;
  lockUntil?: string;
  error?: string;
  stillLocked?: boolean;
}

// Grants
export interface GrantDecision {
  decision: 'allow' | 'deny';
  stage: string;
  reason: string;
  granted_minutes: number;
  expires_at: string | null;
}

export interface Grant {
  id: string;
  url: string;
  scope: string;
  reason: string;
  granted_at: string;
  expires_at: string;
}

export interface GrantsList {
  active: Grant[];
  rate_limit_remaining: number;
}

export type BreakglassState = 'idle' | 'requested' | 'pending' | 'released';

export interface BreakglassStatus {
  state: BreakglassState;
  triggered_at: string | null;
  release_at: string | null;
}

// Navigation pages
export type Page = 'dashboard' | 'blocks' | 'stats' | 'browsers' | 'grants' | 'settings';

// Toast types
export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

// Declare global pywebview API
declare global {
  interface Window {
    pywebview: {
      api: {
        get_status(): Promise<DaemonStatus>;
        get_blocks(): Promise<Block[]>;
        add_block(data: BlockInput): Promise<AddBlockResponse>;
        update_block(block_id: number, updates: Partial<BlockInput>): Promise<ApiResponse>;
        update_block_strict(block_id: number, updates: BlockStrictUpdateInput): Promise<ApiResponse>;
        delete_block(block_id: number): Promise<ApiResponse>;
        get_block_lock_status(block_id: number): Promise<LockStatusResponse>;
        extend_block_lock(block_id: number, lock_until: string): Promise<ApiResponse>;
        get_stats(): Promise<Stats>;
        get_stats_details(): Promise<StatsDetails>;
        get_browsers(): Promise<BrowserStatus[]>;
        is_daemon_running(): Promise<boolean>;
        start_extension_grace_period(): Promise<GracePeriodResponse>;
        get_grace_period_status(): Promise<GracePeriodStatus>;
        get_browser_enforcement_status(): Promise<BrowserEnforcementStatus>;
        update_browser_enforcement(enabled: boolean): Promise<BrowserEnforcementUpdateResponse>;
        get_safe_search_status(): Promise<SafeSearchStatus>;
        update_safe_search(enabled: boolean): Promise<SafeSearchUpdateResponse>;
        get_shutdown_prevention_status(): Promise<ShutdownPreventionStatus>;
        update_shutdown_prevention(enabled: boolean): Promise<ShutdownPreventionUpdateResponse>;
        get_watchdog_status(): Promise<WatchdogStatus>;
        update_watchdog(enabled?: boolean, count?: number): Promise<WatchdogUpdateResponse>;
        get_settings_lock(): Promise<SettingsLockStatus>;
        lock_settings(lock_until: string): Promise<SettingsLockResponse>;
        unlock_settings(): Promise<SettingsLockResponse>;
        request_grant(url: string, reason: string, minutes: number): Promise<GrantDecision>;
        list_grants(): Promise<GrantsList>;
        request_breakglass(): Promise<BreakglassStatus>;
        get_breakglass(): Promise<BreakglassStatus>;
      };
    };
  }
}
