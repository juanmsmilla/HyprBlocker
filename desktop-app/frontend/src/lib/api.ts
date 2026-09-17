import type {
  DaemonStatus,
  Block,
  BlockInput,
  BlockStrictUpdateInput,
  AddBlockResponse,
  ApiResponse,
  LockStatusResponse,
  Stats,
  StatsDetails,
  BrowserStatus,
  GracePeriodResponse,
  GracePeriodStatus,
  BrowserEnforcementStatus,
  BrowserEnforcementUpdateResponse,
  SafeSearchStatus,
  SafeSearchUpdateResponse,
  UnblockDelayStatus,
  UnblockDelayUpdateResponse,
  UnblockDelayLog,
  PendingUnblock,
  ShutdownPreventionStatus,
  ShutdownPreventionUpdateResponse,
  WatchdogStatus,
  WatchdogUpdateResponse,
  SettingsLockStatus,
  SettingsLockResponse,
  JudgePolicyStatus,
  JudgePolicyUpdateResponse,
  GrantDecision,
  GrantsList,
  BreakglassStatus,
} from '../types';

// Wait for pywebview to be ready
const waitForPywebview = (): Promise<void> => {
  return new Promise((resolve) => {
    if (window.pywebview?.api) {
      resolve();
    } else {
      window.addEventListener('pywebviewready', () => resolve(), { once: true });
    }
  });
};

// API wrapper with type safety
export const api = {
  async getStatus(): Promise<DaemonStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_status();
  },

  async getBlocks(): Promise<Block[]> {
    await waitForPywebview();
    return window.pywebview.api.get_blocks();
  },

  async addBlock(data: BlockInput): Promise<AddBlockResponse> {
    await waitForPywebview();
    return window.pywebview.api.add_block(data);
  },

  async updateBlock(blockId: number, updates: Partial<BlockInput>): Promise<ApiResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_block(blockId, updates);
  },

  async updateBlockStrict(blockId: number, updates: BlockStrictUpdateInput): Promise<ApiResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_block_strict(blockId, updates);
  },

  async deleteBlock(blockId: number): Promise<ApiResponse> {
    await waitForPywebview();
    return window.pywebview.api.delete_block(blockId);
  },

  async getBlockLockStatus(blockId: number): Promise<LockStatusResponse> {
    await waitForPywebview();
    return window.pywebview.api.get_block_lock_status(blockId);
  },

  async extendBlockLock(blockId: number, lockUntil: string): Promise<ApiResponse> {
    await waitForPywebview();
    return window.pywebview.api.extend_block_lock(blockId, lockUntil);
  },

  async getStats(): Promise<Stats> {
    await waitForPywebview();
    return window.pywebview.api.get_stats();
  },

  async getStatsDetails(): Promise<StatsDetails> {
    await waitForPywebview();
    return window.pywebview.api.get_stats_details();
  },

  async getBrowsers(): Promise<BrowserStatus[]> {
    await waitForPywebview();
    return window.pywebview.api.get_browsers();
  },

  async isDaemonRunning(): Promise<boolean> {
    await waitForPywebview();
    return window.pywebview.api.is_daemon_running();
  },

  async startExtensionGracePeriod(): Promise<GracePeriodResponse> {
    await waitForPywebview();
    return window.pywebview.api.start_extension_grace_period();
  },

  async getGracePeriodStatus(): Promise<GracePeriodStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_grace_period_status();
  },

  async getBrowserEnforcementStatus(): Promise<BrowserEnforcementStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_browser_enforcement_status();
  },

  async updateBrowserEnforcement(enabled: boolean): Promise<BrowserEnforcementUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_browser_enforcement(enabled);
  },

  async getSafeSearchStatus(): Promise<SafeSearchStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_safe_search_status();
  },

  async updateSafeSearch(enabled: boolean): Promise<SafeSearchUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_safe_search(enabled);
  },

  async getUnblockDelayStatus(): Promise<UnblockDelayStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_unblock_delay_status();
  },

  async updateUnblockDelay(enabled?: boolean, minutes?: number): Promise<UnblockDelayUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_unblock_delay(enabled, minutes);
  },

  async getUnblockDelayLog(limit = 80): Promise<UnblockDelayLog> {
    await waitForPywebview();
    return window.pywebview.api.get_unblock_delay_log(limit);
  },

  async getPendingUnblocks(): Promise<PendingUnblock[]> {
    await waitForPywebview();
    return window.pywebview.api.get_pending_unblocks();
  },

  async cancelPendingUnblock(pendingId: string): Promise<{ success: boolean; error?: string }> {
    await waitForPywebview();
    return window.pywebview.api.cancel_pending_unblock(pendingId);
  },

  async getWatchdogStatus(): Promise<WatchdogStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_watchdog_status();
  },

  async updateWatchdog(enabled?: boolean, count?: number): Promise<WatchdogUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_watchdog(enabled, count);
  },

  async getSettingsLock(): Promise<SettingsLockStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_settings_lock();
  },

  async lockSettings(lockUntil: string): Promise<SettingsLockResponse> {
    await waitForPywebview();
    return window.pywebview.api.lock_settings(lockUntil);
  },

  async unlockSettings(): Promise<SettingsLockResponse> {
    await waitForPywebview();
    return window.pywebview.api.unlock_settings();
  },

  async getJudgePolicy(): Promise<JudgePolicyStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_judge_policy();
  },

  async setJudgePolicy(text: string): Promise<JudgePolicyUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.set_judge_policy(text);
  },

  async getShutdownPreventionStatus(): Promise<ShutdownPreventionStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_shutdown_prevention_status();
  },

  async updateShutdownPrevention(enabled: boolean): Promise<ShutdownPreventionUpdateResponse> {
    await waitForPywebview();
    return window.pywebview.api.update_shutdown_prevention(enabled);
  },

  async requestGrant(url: string, reason: string, minutes: number): Promise<GrantDecision> {
    await waitForPywebview();
    return window.pywebview.api.request_grant(url, reason, minutes);
  },

  async listGrants(): Promise<GrantsList> {
    await waitForPywebview();
    return window.pywebview.api.list_grants();
  },

  async requestBreakglass(): Promise<BreakglassStatus> {
    await waitForPywebview();
    return window.pywebview.api.request_breakglass();
  },

  async getBreakglass(): Promise<BreakglassStatus> {
    await waitForPywebview();
    return window.pywebview.api.get_breakglass();
  },
};

// Helper to parse JSON array from string (for days_of_week fields)
export function parseDaysOfWeek(value: string | null): number[] {
  if (!value) return [];
  if (typeof value === 'object') return value as unknown as number[];
  try {
    return JSON.parse(value);
  } catch {
    return [];
  }
}

// Helper to format days for display
export function formatDays(days: number[]): string {
  const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  if (days.length === 7) return 'Every day';
  if (days.length === 5 && !days.includes(5) && !days.includes(6)) return 'Weekdays';
  if (days.length === 2 && days.includes(5) && days.includes(6)) return 'Weekends';
  return days.map((d) => dayNames[d]).join(', ');
}

// Helper to format date
export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  try {
    const date = new Date(dateStr);
    return (
      date.toLocaleDateString() +
      ' ' +
      date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    );
  } catch {
    return dateStr;
  }
}

// Helper to format time
export function formatTime(dateStr: string | null): string {
  if (!dateStr) return '-';
  try {
    const date = new Date(dateStr);
    return date.toLocaleTimeString();
  } catch {
    return dateStr;
  }
}

// Helper to capitalize first letter
export function capitalizeFirst(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// Browser icon mapping (shared by Dashboard and Browsers pages)
const BROWSER_ICONS: Record<string, string> = {
  firefox: '🦊',
  chrome: '🌐',
  chromium: '🌐',
  brave: '🦁',
  edge: '🌊',
  opera: '🎭',
  vivaldi: '🎨',
};

export function getBrowserIcon(browser: string): string {
  return BROWSER_ICONS[browser.toLowerCase()] || '🌐';
}
