import type { Block } from '../types';
import { parseDaysOfWeek, formatDays } from './api';

// Whether a block is enforcing right now, waiting for its schedule, or off.
export type BlockActivityState = 'active' | 'scheduled' | 'off';

export interface BlockActivity {
  state: BlockActivityState;
  detail: string;
}

function parseMinutes(time: string): number {
  const [hours, minutes] = time.split(':');
  return Number(hours) * 60 + Number(minutes);
}

// Mirrors BlockChecker._is_time_in_range in daemon/scheduler.py
function isInTimeRange(
  days: number[],
  startTime: string | null,
  endTime: string | null,
  now: Date,
): boolean {
  if (days.length > 0) {
    const weekday = (now.getDay() + 6) % 7; // Monday=0, matching the daemon
    if (!days.includes(weekday)) return false;
  }

  if (startTime && endTime) {
    const current = now.getHours() * 60 + now.getMinutes();
    const start = parseMinutes(startTime);
    const end = parseMinutes(endTime);
    if (start <= end) {
      return start <= current && current <= end;
    }
    // Overnight window, e.g. 22:00 - 06:00
    return current >= start || current <= end;
  }

  return true;
}

function formatWindow(block: Block): string {
  const days = parseDaysOfWeek(block.block_days_of_week);
  const daysText = days.length > 0 ? formatDays(days) : 'Every day';
  if (block.block_start_time && block.block_end_time) {
    return `${daysText}, ${block.block_start_time}–${block.block_end_time}`;
  }
  return daysText;
}

// Mirrors BlockChecker._is_block_active in daemon/scheduler.py
export function getBlockActivity(block: Block, now: Date = new Date()): BlockActivity {
  if (!block.enabled) {
    return { state: 'off', detail: 'Disabled' };
  }

  if (block.block_mode === 'disabled') {
    return { state: 'off', detail: 'Blocking turned off' };
  }

  if (block.block_mode === 'always') {
    return { state: 'active', detail: 'Always blocking' };
  }

  if (block.block_mode === 'time_range') {
    const days = parseDaysOfWeek(block.block_days_of_week);
    if (isInTimeRange(days, block.block_start_time, block.block_end_time, now)) {
      return {
        state: 'active',
        detail: block.block_end_time
          ? `Until ${block.block_end_time}`
          : formatWindow(block),
      };
    }
    return { state: 'scheduled', detail: formatWindow(block) };
  }

  return { state: 'off', detail: 'Disabled' };
}

export function countRules(block: Block): number {
  const countLines = (value: string | null) =>
    value ? value.split('\n').filter((line) => line.trim()).length : 0;
  return (
    countLines(block.websites_blocked) +
    countLines(block.websites_media_blocked) +
    countLines(block.apps_blocked)
  );
}

export function formatRuleCount(block: Block): string {
  const count = countRules(block);
  return count === 1 ? '1 rule' : `${count} rules`;
}
