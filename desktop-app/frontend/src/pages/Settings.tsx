import { useState, useEffect, useCallback } from "react";
import { useStatus } from "../context/StatusContext";
import { useToast } from "../context/ToastContext";
import { Card } from "../components/ui/Card";
import { Checkbox, Select, Input, Textarea } from "../components/ui/FormElements";
import { Button } from "../components/ui/Button";
import { api } from "../lib/api";
import type {
  BrowserEnforcementStatus,
  SafeSearchStatus,
  ShutdownPreventionStatus,
  WatchdogStatus,
  SettingsLockStatus,
  JudgePolicyStatus,
  UnblockDelayStatus,
  UnblockDelayLog,
  PendingUnblock,
} from "../types";

type DurationUnit = 'minute' | 'hour' | 'day' | 'month';

export function Settings() {
  const { status } = useStatus();
  const { showToast } = useToast();
  const [browserEnforcementStatus, setBrowserEnforcementStatus] = useState<BrowserEnforcementStatus | null>(
    null,
  );
  const [safeSearchStatus, setSafeSearchStatus] = useState<SafeSearchStatus | null>(
    null,
  );
  const [shutdownPreventionStatus, setShutdownPreventionStatus] = useState<ShutdownPreventionStatus | null>(
    null,
  );
  const [watchdogStatus, setWatchdogStatus] = useState<WatchdogStatus | null>(
    null,
  );
  const [settingsLock, setSettingsLock] = useState<SettingsLockStatus | null>(
    null,
  );
  const [judgePolicy, setJudgePolicy] = useState<JudgePolicyStatus | null>(
    null,
  );
  const [unblockDelayStatus, setUnblockDelayStatus] = useState<UnblockDelayStatus | null>(null);
  const [pendingUnblocks, setPendingUnblocks] = useState<PendingUnblock[]>([]);
  const [delayMinutesDraft, setDelayMinutesDraft] = useState(10);
  const [delayLog, setDelayLog] = useState<UnblockDelayLog | null>(null);

  // null = untouched (mirror the loaded policy); a string = user has edits.
  const [policyDraft, setPolicyDraft] = useState<string | null>(null);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [lockDurationValue, setLockDurationValue] = useState(1);
  const [lockDurationUnit, setLockDurationUnit] = useState<DurationUnit>('hour');
  const [extendDurationValue, setExtendDurationValue] = useState(1);
  const [extendDurationUnit, setExtendDurationUnit] = useState<DurationUnit>('hour');

  const loadBrowserEnforcementStatus = useCallback(async () => {
    try {
      const status = await api.getBrowserEnforcementStatus();
      setBrowserEnforcementStatus(status);
    } catch (error) {
      console.error("Failed to load browser enforcement status:", error);
      showToast("Failed to load settings", "error");
    }
  }, [showToast]);

  const handleBrowserEnforcementToggle = async (enabled: boolean) => {
    setUpdating(true);
    try {
      const result = await api.updateBrowserEnforcement(enabled);

      if (result.success) {
        showToast(
          enabled
            ? "Browser enforcement enabled"
            : "Browser enforcement disabled",
          "success",
        );
        await loadBrowserEnforcementStatus();
      } else if (result.settingsLocked) {
        showToast(
          "Settings are locked — protections cannot be disabled",
          "warning",
        );
        await loadBrowserEnforcementStatus();
      } else {
        showToast(result.error || "Failed to update setting", "error");
        await loadBrowserEnforcementStatus();
      }
    } catch (error) {
      console.error("Failed to update browser enforcement:", error);
      showToast("Failed to update setting", "error");
      await loadBrowserEnforcementStatus();
    } finally {
      setUpdating(false);
    }
  };

  const loadSafeSearchStatus = useCallback(async () => {
    try {
      const status = await api.getSafeSearchStatus();
      setSafeSearchStatus(status);
    } catch (error) {
      console.error("Failed to load safe search status:", error);
      showToast("Failed to load settings", "error");
    }
  }, [showToast]);

  const handleSafeSearchToggle = async (enabled: boolean) => {
    setUpdating(true);
    try {
      const result = await api.updateSafeSearch(enabled);

      if (result.success) {
        showToast(
          enabled
            ? "Safe search enforcement enabled"
            : "Safe search enforcement disabled",
          "success",
        );
        await loadSafeSearchStatus();
      } else if (result.settingsLocked) {
        showToast(
          "Settings are locked — protections cannot be disabled",
          "warning",
        );
        await loadSafeSearchStatus();
      } else {
        showToast(result.error || "Failed to update setting", "error");
        await loadSafeSearchStatus();
      }
    } catch (error) {
      console.error("Failed to update safe search:", error);
      showToast("Failed to update setting", "error");
      await loadSafeSearchStatus();
    } finally {
      setUpdating(false);
    }
  };


  const loadUnblockDelayStatus = useCallback(async () => {
    const stepErrors: string[] = [];
    try {
      const status = await api.getUnblockDelayStatus();
      setUnblockDelayStatus(status);
      setDelayMinutesDraft(status.minutes ?? 10);
      if (status.error) {
        stepErrors.push(`status: ${status.error}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error("[unblock-delay] status load failed:", error);
      stepErrors.push(`status: ${msg}`);
    }
    try {
      const pending = await api.getPendingUnblocks();
      setPendingUnblocks(pending);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error("[unblock-delay] pending load failed:", error);
      stepErrors.push(`pending: ${msg}`);
    }
    try {
      const log = await api.getUnblockDelayLog(80);
      setDelayLog(log);
      if (log && (log as { error?: string }).error) {
        stepErrors.push(`log: ${(log as { error?: string }).error}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      console.error("[unblock-delay] log load failed:", error);
      stepErrors.push(`log: ${msg}`);
    }
    if (stepErrors.length > 0) {
      console.error("[unblock-delay] load errors:", stepErrors);
      showToast(`Failed to load delay settings (${stepErrors.join("; ")})`, "error");
    }
  }, [showToast]);

  const handleUnblockDelayToggle = async (enabled: boolean) => {
    setUpdating(true);
    try {
      const result = await api.updateUnblockDelay(enabled, undefined);
      if (result.success) {
        if (result.pending) {
          showToast(result.message || "Delay-settings change queued — cancel from list below", "success");
        } else {
          showToast(
            enabled
              ? `Unblock delay enabled (${result.minutes ?? delayMinutesDraft} min)`
              : "Unblock delay disabled",
            "success",
          );
        }
        await loadUnblockDelayStatus();
      } else {
        showToast(result.error || "Failed to update delay setting", "error");
        await loadUnblockDelayStatus();
      }
    } catch (error) {
      console.error("Failed to update unblock delay:", error);
      showToast("Failed to update delay setting", "error");
      await loadUnblockDelayStatus();
    } finally {
      setUpdating(false);
    }
  };

  const handleUnblockDelayMinutesSave = async () => {
    const minutes = Number(delayMinutesDraft);
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      showToast("Minutes must be between 1 and 1440", "warning");
      return;
    }
    setUpdating(true);
    try {
      const result = await api.updateUnblockDelay(undefined, minutes);
      if (result.success) {
        if (result.pending) {
          showToast(result.message || "Shorter delay queued — cancel from list below", "success");
        } else {
          showToast(`Delay set to ${minutes} minutes`, "success");
        }
        await loadUnblockDelayStatus();
      } else {
        showToast(result.error || "Failed to update minutes", "error");
      }
    } catch (error) {
      console.error("Failed to update delay minutes:", error);
      showToast("Failed to update minutes", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleCancelPending = async (pendingId: string) => {
    setUpdating(true);
    try {
      const result = await api.cancelPendingUnblock(pendingId);
      if (result.success) {
        showToast("Pending unblock canceled — timer reset if you try again", "success");
        await loadUnblockDelayStatus();
      } else {
        showToast(result.error || "Failed to cancel", "error");
      }
    } catch (error) {
      console.error("Failed to cancel pending:", error);
      showToast("Failed to cancel", "error");
    } finally {
      setUpdating(false);
    }
  };

  const loadShutdownPreventionStatus = useCallback(async () => {
    try {
      const status = await api.getShutdownPreventionStatus();
      setShutdownPreventionStatus(status);
    } catch (error) {
      console.error("Failed to load shutdown prevention status:", error);
    }
  }, []);

  const handleShutdownPreventionToggle = async (enabled: boolean) => {
    setUpdating(true);
    try {
      const result = await api.updateShutdownPrevention(enabled);

      if (result.success) {
        showToast(
          enabled
            ? "Shutdown prevention enabled"
            : "Shutdown prevention disabled",
          "success",
        );
        await loadShutdownPreventionStatus();
        // Also reload watchdog status since disabling shutdown prevention disables watchdogs
        if (!enabled) {
          await loadWatchdogStatus();
        }
      } else if (result.settingsLocked) {
        showToast("Settings are locked — protections cannot be disabled", "warning");
      } else {
        showToast(result.error || "Failed to update setting", "error");
      }
    } catch (error) {
      console.error("Failed to update shutdown prevention:", error);
      showToast("Failed to update setting", "error");
    } finally {
      setUpdating(false);
    }
  };

  const loadWatchdogStatus = useCallback(async () => {
    try {
      const status = await api.getWatchdogStatus();
      setWatchdogStatus(status);
    } catch (error) {
      console.error("Failed to load watchdog status:", error);
    }
  }, []);

  const loadSettingsLock = useCallback(async () => {
    try {
      const lock = await api.getSettingsLock();
      setSettingsLock(lock);
    } catch (error) {
      console.error("Failed to load settings lock:", error);
    }
  }, []);

  const loadJudgePolicy = useCallback(async () => {
    try {
      const policy = await api.getJudgePolicy();
      setJudgePolicy(policy);
    } catch (error) {
      console.error("Failed to load judge policy:", error);
    }
  }, []);

  // Load all settings on mount
  useEffect(() => {
    loadBrowserEnforcementStatus();
    loadSafeSearchStatus();
    loadUnblockDelayStatus();
    loadShutdownPreventionStatus();
    loadWatchdogStatus();
    loadSettingsLock();
    loadJudgePolicy();
  }, [
    loadBrowserEnforcementStatus,
    loadSafeSearchStatus,
    loadUnblockDelayStatus,
    loadShutdownPreventionStatus,
    loadWatchdogStatus,
    loadSettingsLock,
    loadJudgePolicy,
  ]);

  const handleSaveJudgePolicy = async () => {
    const text = policyDraft ?? judgePolicy?.text ?? "";
    setSavingPolicy(true);
    try {
      const result = await api.setJudgePolicy(text);
      if (result.success) {
        if (result.pending) {
          showToast(
            "Loosening change scheduled — it applies after the safety delay",
            "warning",
          );
        } else {
          showToast("Judge policy saved", "success");
        }
        await loadJudgePolicy();
      } else if (result.settingsLocked) {
        showToast(
          "Settings are locked — only switching to a stricter preset is allowed",
          "warning",
        );
      } else {
        showToast(result.error || "Failed to update judge policy", "error");
      }
    } catch (error) {
      console.error("Failed to update judge policy:", error);
      showToast("Failed to update judge policy", "error");
    } finally {
      setSavingPolicy(false);
    }
  };

  const handleWatchdogToggle = async (enabled: boolean) => {
    setUpdating(true);
    try {
      const result = await api.updateWatchdog(enabled);

      if (result.success) {
        showToast(
          enabled
            ? "Watchdog protection enabled"
            : "Watchdog protection disabled",
          "success",
        );
        await loadWatchdogStatus();
      } else if (result.settingsLocked) {
        showToast("Settings are locked — protections cannot be disabled", "warning");
      } else {
        showToast(result.error || "Failed to update watchdog", "error");
      }
    } catch (error) {
      console.error("Failed to update watchdog:", error);
      showToast("Failed to update watchdog", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleWatchdogCountChange = async (count: number) => {
    setUpdating(true);
    try {
      const result = await api.updateWatchdog(undefined, count);

      if (result.success) {
        showToast(`Watchdog count set to ${count}`, "success");
        await loadWatchdogStatus();
      } else if (result.settingsLocked) {
        showToast("Settings are locked — protections cannot be disabled", "warning");
      } else {
        showToast(result.error || "Failed to update watchdog count", "error");
      }
    } catch (error) {
      console.error("Failed to update watchdog count:", error);
      showToast("Failed to update watchdog count", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleLockSettings = async () => {
    setUpdating(true);
    try {
      // Calculate lock_until based on duration value and unit
      const now = new Date();
      let milliseconds = 0;

      switch (lockDurationUnit) {
        case 'minute':
          milliseconds = lockDurationValue * 60 * 1000;
          break;
        case 'hour':
          milliseconds = lockDurationValue * 60 * 60 * 1000;
          break;
        case 'day':
          milliseconds = lockDurationValue * 24 * 60 * 60 * 1000;
          break;
        case 'month':
          milliseconds = lockDurationValue * 30 * 24 * 60 * 60 * 1000;
          break;
      }

      const lockUntil = new Date(now.getTime() + milliseconds);
      const result = await api.lockSettings(lockUntil.toISOString());

      if (result.success) {
        showToast("Settings locked", "success");
        await loadSettingsLock();
      } else {
        showToast(result.error || "Failed to lock settings", "error");
      }
    } catch (error) {
      console.error("Failed to lock settings:", error);
      showToast("Failed to lock settings", "error");
    } finally {
      setUpdating(false);
    }
  };

  const handleExtendSettingsLock = async () => {
    setUpdating(true);
    try {
      // Calculate new lock_until based on current time + extension duration
      const now = new Date();
      let milliseconds = 0;

      switch (extendDurationUnit) {
        case 'minute':
          milliseconds = extendDurationValue * 60 * 1000;
          break;
        case 'hour':
          milliseconds = extendDurationValue * 60 * 60 * 1000;
          break;
        case 'day':
          milliseconds = extendDurationValue * 24 * 60 * 60 * 1000;
          break;
        case 'month':
          milliseconds = extendDurationValue * 30 * 24 * 60 * 60 * 1000;
          break;
      }

      const newLockUntil = new Date(now.getTime() + milliseconds);
      const result = await api.lockSettings(newLockUntil.toISOString());

      if (result.success) {
        showToast("Settings lock extended", "success");
        await loadSettingsLock();
      } else {
        showToast(result.error || "Failed to extend lock", "error");
      }
    } catch (error) {
      console.error("Failed to extend settings lock:", error);
      showToast("Failed to extend settings lock", "error");
    } finally {
      setUpdating(false);
    }
  };

  const formatRemainingTime = (seconds: number | null): string => {
    if (seconds === null || seconds <= 0) return "";
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
      return `${hours}h ${minutes}m remaining`;
    }
    return `${minutes}m remaining`;
  };

  const isSettingsLocked = settingsLock?.locked ?? false;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Settings</h2>
      </div>

      <div className="grid grid-cols-2 gap-5">
        <Card title="Daemon">
          <div className="flex justify-between py-3 border-b border-border">
            <span className="text-text-secondary">Status:</span>
            <span className="font-medium text-text">
              {status?.running ? "Running" : "Not Running"}
            </span>
          </div>
          <div className="flex justify-between py-3">
            <span className="text-text-secondary">Port:</span>
            <span className="font-medium text-text">8765</span>
          </div>
        </Card>

        <Card title="Browser Enforcement">
          <div className="py-3">
            <Checkbox
              label="Enable browser enforcement"
              checked={browserEnforcementStatus?.enabled ?? true}
              onChange={(e) => handleBrowserEnforcementToggle(e.target.checked)}
              disabled={updating || (isSettingsLocked && (browserEnforcementStatus?.enabled ?? true))}
            />
            <p className="text-xs text-text-secondary mt-2">
              When enabled, browsers without the extension installed will be closed.
              Disable this if you don't want browser enforcement.
            </p>
            {isSettingsLocked && (
              <p className="text-xs text-yellow-500 mt-2">
                Settings are locked — protections can be enabled but not disabled.
              </p>
            )}
          </div>
        </Card>

        <Card title="Safe Search Enforcement">
          <div className="py-3">
            <Checkbox
              label="Enforce safe search on search engines"
              checked={safeSearchStatus?.enabled ?? false}
              onChange={(e) => handleSafeSearchToggle(e.target.checked)}
              disabled={updating || (isSettingsLocked && (safeSearchStatus?.enabled ?? false))}
            />
            <p className="text-xs text-text-secondary mt-2">
              Forces Google, Bing, and DuckDuckGo to use strict safe search mode.
              Search parameters are automatically added when visiting these search engines.
            </p>
            {isSettingsLocked && (
              <p className="text-xs text-yellow-500 mt-2">
                Settings are locked — protections can be enabled but not disabled.
              </p>
            )}
          </div>
        </Card>


        <Card title="Unblock Delay (prototype)">
          <div className="py-3">
            <Checkbox
              label="Delay deletes and loosening changes"
              checked={unblockDelayStatus?.enabled ?? false}
              onChange={(e) => handleUnblockDelayToggle(e.target.checked)}
              disabled={updating}
            />
            <p className="text-xs text-text-secondary mt-2 mb-4">
              When enabled, deleting a block or weakening its rules waits N minutes
              before applying. Cancel anytime during the wait to abort — requesting
              again restarts the full timer.
            </p>

            <label className="block text-sm text-text-secondary mb-2">
              Delay (minutes)
            </label>
            <div className="flex gap-2 items-center">
              <Input
                type="number"
                min={1}
                max={1440}
                value={String(delayMinutesDraft)}
                onChange={(e) => setDelayMinutesDraft(Number(e.target.value))}
                disabled={updating || !(unblockDelayStatus?.enabled)}
                className="w-28"
              />
              <Button
                size="small"
                onClick={handleUnblockDelayMinutesSave}
                disabled={updating || !(unblockDelayStatus?.enabled)}
              >
                Save
              </Button>
            </div>

            {pendingUnblocks.length > 0 && (
              <div className="mt-4 space-y-2">
                <p className="text-sm font-medium text-text">Pending changes</p>
                {pendingUnblocks.map((p) => (
                  <div
                    key={p.id}
                    className="flex justify-between items-center gap-3 text-sm border border-border rounded px-3 py-2"
                  >
                    <div>
                      <span className="text-text">{p.kind}</span>{" "}
                      <span className="text-text-secondary">{p.block_name}</span>
                      <div className="text-xs text-text-secondary">
                        applies in {Math.ceil(p.remaining_seconds / 60)} min
                        {" "}({p.remaining_seconds}s)
                      </div>
                    </div>
                    <Button
                      size="small"
                      variant="danger"
                      onClick={() => handleCancelPending(p.id)}
                      disabled={updating}
                    >
                      Cancel
                    </Button>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-5">
              <div className="flex justify-between items-center mb-2">
                <p className="text-sm font-medium text-text">Delay log</p>
                <Button
                  size="small"
                  onClick={() => loadUnblockDelayStatus()}
                  disabled={updating}
                >
                  Refresh
                </Button>
              </div>
              <p className="text-xs text-text-secondary mb-2">
                File: {delayLog?.path ?? "~/.config/hyprblocker/unblock_delay.log"}
              </p>
              <pre className="text-xs text-text-secondary bg-bg-secondary border border-border rounded p-3 max-h-48 overflow-auto whitespace-pre-wrap">
                {(delayLog?.lines?.length ? delayLog.lines : ["(no events yet)"]).join("\n")}
              </pre>
            </div>
          </div>
        </Card>

        <Card title="About">
          <div className="flex justify-between py-3 border-b border-border">
            <span className="text-text-secondary">Version:</span>
            <span className="font-medium text-text">1.0.0</span>
          </div>
          <div className="flex justify-between py-3">
            <span className="text-text-secondary">Config:</span>
            <span className="font-medium text-text">
              ~/.config/hyprblocker/
            </span>
          </div>
        </Card>

        <Card title="Protection">
          <div className="py-3">
            <Checkbox
              label="Shutdown Prevention"
              checked={shutdownPreventionStatus?.enabled ?? false}
              onChange={(e) => handleShutdownPreventionToggle(e.target.checked)}
              disabled={updating || (isSettingsLocked && (shutdownPreventionStatus?.enabled ?? false))}
            />
            <p className="text-xs text-text-secondary mt-2 mb-4">
              Prevents the daemon from being stopped via SIGTERM signals.
            </p>

            <Checkbox
              label="Watchdog Protection"
              checked={watchdogStatus?.enabled ?? false}
              onChange={(e) => handleWatchdogToggle(e.target.checked)}
              disabled={updating || (isSettingsLocked && (watchdogStatus?.enabled ?? false)) || !(shutdownPreventionStatus?.enabled)}
            />
            <p className="text-xs text-text-secondary mt-2">
              Spawns monitor processes that restart the daemon if killed.
              {!(shutdownPreventionStatus?.enabled) && (
                <span className="text-text-secondary block mt-1">
                  (Requires Shutdown Prevention to be enabled)
                </span>
              )}
            </p>

            {shutdownPreventionStatus?.enabled && watchdogStatus?.enabled && (
              <div className="mt-4">
                <label className="block text-sm text-text-secondary mb-2">
                  Number of watchdogs
                </label>
                <Select
                  value={String(watchdogStatus?.count ?? 3)}
                  onChange={(e) =>
                    handleWatchdogCountChange(Number(e.target.value))
                  }
                  disabled={updating}
                >
                  {[2, 3, 4, 5].map((n) => (
                    <option
                      key={n}
                      value={String(n)}
                      disabled={isSettingsLocked && n < (watchdogStatus?.count ?? 3)}
                    >
                      {n}
                    </option>
                  ))}
                </Select>

                {watchdogStatus?.activeWatchdogs &&
                  watchdogStatus.activeWatchdogs.length > 0 && (
                    <div className="mt-3 text-xs text-text-secondary">
                      <p className="font-medium">Active watchdogs:</p>
                      <ul className="mt-1 space-y-1">
                        {watchdogStatus.activeWatchdogs.map((wd) => (
                          <li key={wd.pid}>
                            PID {wd.pid} ({wd.name}) -{" "}
                            {Math.floor(wd.uptime_seconds / 60)}m uptime
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
              </div>
            )}

            {isSettingsLocked && (
              <p className="text-xs text-yellow-500 mt-2">
                Settings are locked — protections can be enabled but not disabled.
              </p>
            )}
          </div>
        </Card>

        <Card title="Grant Judge Policy">
          <div className="py-3">
            <p className="text-sm text-text-secondary mb-3">
              The policy the AI judge follows when deciding access-grant
              requests. Pick a preset or write your own; switching to a
              stricter preset applies immediately, anything else counts as
              loosening and applies after a safety delay.
            </p>
            <p className="text-sm mb-3">
              Active:{" "}
              <span className="font-medium">
                {judgePolicy?.preset
                  ? `${judgePolicy.preset} preset`
                  : "custom policy"}
              </span>
            </p>
            {judgePolicy?.pendingText != null && (
              <p className="text-xs text-yellow-500 mb-3">
                A loosening edit is scheduled
                {judgePolicy.pendingEffectiveAt
                  ? ` — applies ${new Date(judgePolicy.pendingEffectiveAt).toLocaleString()}`
                  : ""}
                .
              </p>
            )}
            <div className="flex gap-2 mb-3">
              {Object.entries(judgePolicy?.presets ?? {}).map(([name, text]) => (
                <Button
                  key={name}
                  variant="secondary"
                  disabled={savingPolicy}
                  onClick={() => setPolicyDraft(text)}
                >
                  {name.charAt(0).toUpperCase() + name.slice(1)}
                </Button>
              ))}
            </div>
            <Textarea
              rows={12}
              className="font-mono text-xs"
              value={policyDraft ?? judgePolicy?.text ?? ""}
              maxLength={judgePolicy?.maxChars || undefined}
              onChange={(e) => setPolicyDraft(e.target.value)}
              disabled={savingPolicy}
            />
            <div className="flex items-center gap-3 mt-3">
              <Button
                onClick={handleSaveJudgePolicy}
                disabled={
                  savingPolicy ||
                  policyDraft === null ||
                  policyDraft === judgePolicy?.text
                }
                variant="primary"
              >
                {savingPolicy ? "Saving…" : "Save Policy"}
              </Button>
              {policyDraft !== null && policyDraft !== judgePolicy?.text && (
                <Button
                  variant="secondary"
                  disabled={savingPolicy}
                  onClick={() => setPolicyDraft(null)}
                >
                  Discard
                </Button>
              )}
            </div>
            {judgePolicy?.devMode ? (
              <p className="text-xs text-text-secondary mt-2">
                Dev mode — policy edits apply immediately, even while settings
                are locked.
              </p>
            ) : (
              isSettingsLocked && (
                <p className="text-xs text-yellow-500 mt-2">
                  Settings are locked — only switching to a stricter preset
                  will be accepted.
                </p>
              )
            )}
          </div>
        </Card>

        <Card title="Settings Lock">
          <div className="py-3">
            {isSettingsLocked ? (
              <div>
                <div className="flex items-center gap-2 text-yellow-500 mb-2">
                  <span className="text-lg">🔒</span>
                  <span className="font-medium">Settings are locked</span>
                </div>
                <p className="text-sm text-text-secondary">
                  {formatRemainingTime(settingsLock?.remainingSeconds ?? null)}
                </p>
                {settingsLock?.lockUntil && (
                  <p className="text-xs text-text-secondary mt-1">
                    Until: {new Date(settingsLock.lockUntil).toLocaleString()}
                  </p>
                )}
                <div className="mt-4 pt-4 border-t border-border">
                  <p className="text-sm text-text-secondary mb-3">
                    Extend the lock duration:
                  </p>
                  <div className="flex gap-2 items-center">
                    <Input
                      type="number"
                      min={1}
                      value={extendDurationValue}
                      onChange={(e) => setExtendDurationValue(parseInt(e.target.value) || 1)}
                      disabled={updating}
                      className="w-20"
                    />
                    <Select
                      value={extendDurationUnit}
                      onChange={(e) => setExtendDurationUnit(e.target.value as DurationUnit)}
                      disabled={updating}
                    >
                      <option value="minute">Minutes</option>
                      <option value="hour">Hours</option>
                      <option value="day">Days</option>
                      <option value="month">Months</option>
                    </Select>
                    <Button
                      onClick={handleExtendSettingsLock}
                      disabled={updating}
                      variant="secondary"
                    >
                      Extend Lock
                    </Button>
                  </div>
                  <p className="text-xs text-text-secondary mt-2">
                    You can extend the lock, but cannot shorten or remove it.
                  </p>
                </div>
              </div>
            ) : (
              <div>
                <p className="text-sm text-text-secondary mb-3">
                  Lock settings to prevent changes for a specified duration.
                  Uses NTP time verification to prevent clock manipulation.
                </p>
                <div className="flex gap-2 items-center">
                  <Input
                    type="number"
                    min={1}
                    value={lockDurationValue}
                    onChange={(e) => setLockDurationValue(parseInt(e.target.value) || 1)}
                    disabled={updating}
                    className="w-20"
                  />
                  <Select
                    value={lockDurationUnit}
                    onChange={(e) => setLockDurationUnit(e.target.value as DurationUnit)}
                    disabled={updating}
                  >
                    <option value="minute">Minutes</option>
                    <option value="hour">Hours</option>
                    <option value="day">Days</option>
                    <option value="month">Months</option>
                  </Select>
                  <Button
                    onClick={handleLockSettings}
                    disabled={updating}
                    variant="primary"
                  >
                    Lock Settings
                  </Button>
                </div>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
