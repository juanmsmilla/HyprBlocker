import { Lock, Unlock, Plus } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { parseDaysOfWeek, formatDays, formatDate } from '../../lib/api';
import { getBlockActivity, formatRuleCount } from '../../lib/blocks';
import type { Block, BlockPriority, PendingUnblock } from '../../types';

interface BlocksTableProps {
  blocks: Block[];
  pendingByBlockId: Map<number, PendingUnblock>;
  onEdit: (block: Block) => void;
  onToggle: (block: Block) => void;
  onDelete: (block: Block) => void;
  onLock: (block: Block) => void;
  onCancelDelay: (pending: PendingUnblock) => void;
  onAdd: () => void;
}

function formatPriority(priority: BlockPriority | undefined): React.ReactNode {
  if (priority === 'high') {
    return <Badge variant="warning">High</Badge>;
  }
  if (priority === 'medium') {
    return <Badge variant="info">Medium</Badge>;
  }
  return <Badge variant="default">Low</Badge>;
}

function formatBlockMode(block: Block): React.ReactNode {
  if (block.block_mode === 'always') {
    return <Badge variant="info">Always</Badge>;
  } else if (block.block_mode === 'time_range') {
    const days = parseDaysOfWeek(block.block_days_of_week);
    const daysText = days.length > 0 ? formatDays(days) : 'All days';
    return (
      <div>
        <Badge variant="info">Time Range</Badge>
        <div className="text-xs text-text-secondary mt-1">
          {daysText} {block.block_start_time || ''} - {block.block_end_time || ''}
        </div>
      </div>
    );
  } else {
    return <Badge variant="default">Disabled</Badge>;
  }
}

function isBlockLocked(block: Block): boolean {
  if (block.lock_mode !== 'locked_until' || !block.lock_until) {
    return false;
  }
  return new Date(block.lock_until) > new Date();
}

function formatLockStatus(block: Block): React.ReactNode {
  const locked = isBlockLocked(block);

  if (locked) {
    return (
      <div className="flex flex-col items-start">
        <div className="flex items-center gap-1.5 text-yellow-500">
          <Lock size={16} />
          <span className="text-sm font-medium">Locked</span>
        </div>
        <div className="text-xs text-text-secondary mt-0.5">
          Until {formatDate(block.lock_until)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 text-text-secondary">
      <Unlock size={16} />
      <span className="text-sm">Unlocked</span>
    </div>
  );
}

function formatActivityStatus(block: Block, pending?: PendingUnblock): React.ReactNode {
  if (pending) {
    const mins = Math.max(1, Math.ceil(pending.remaining_seconds / 60));
    return (
      <div>
        <Badge variant="warning">Delay pending</Badge>
        <div className="text-xs text-text-secondary mt-1">
          {pending.kind} in ~{mins} min
        </div>
      </div>
    );
  }

  const activity = getBlockActivity(block);

  if (activity.state === 'active') {
    return <Badge variant="success">Active now</Badge>;
  }
  if (activity.state === 'scheduled') {
    return (
      <div>
        <Badge variant="info">Scheduled</Badge>
        <div className="text-xs text-text-secondary mt-1">{activity.detail}</div>
      </div>
    );
  }
  return <Badge variant="default">Off</Badge>;
}

export function BlocksTable({
  blocks,
  pendingByBlockId,
  onEdit,
  onToggle,
  onDelete,
  onLock,
  onCancelDelay,
  onAdd,
}: BlocksTableProps) {
  if (blocks.length === 0) {
    return (
      <div className="text-center py-10">
        <p className="text-text-secondary mb-4">
          No blocks configured. Add a block to organize your rules.
        </p>
        <Button onClick={onAdd}>
          <Plus size={18} />
          Add Your First Block
        </Button>
      </div>
    );
  }

  return (
    <div className="bg-bg-card rounded-lg shadow-md border border-border overflow-hidden">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-bg-secondary">
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Name
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Priority
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Block Mode
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Lock
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Rules
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {blocks.map((block) => {
            const pending = pendingByBlockId.get(block.id);
            return (
              <tr key={block.id} className="border-t border-border hover:bg-bg-hover/50">
                <td className="px-4 py-3 text-text">{block.name}</td>
                <td className="px-4 py-3">{formatPriority(block.priority)}</td>
                <td className="px-4 py-3">{formatBlockMode(block)}</td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => onLock(block)}
                    className="hover:bg-bg-hover rounded p-1 transition-colors cursor-pointer"
                    title="Configure lock"
                  >
                    {formatLockStatus(block)}
                  </button>
                </td>
                <td className="px-4 py-3 text-text">{formatRuleCount(block)}</td>
                <td className="px-4 py-3">{formatActivityStatus(block, pending)}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-2">
                    {pending ? (
                      <Button size="small" variant="danger" onClick={() => onCancelDelay(pending)}>
                        Cancel delay
                      </Button>
                    ) : (
                      <>
                        <Button size="small" variant="secondary" onClick={() => onEdit(block)}>
                          Edit
                        </Button>
                        <Button size="small" variant="secondary" onClick={() => onToggle(block)}>
                          {block.enabled ? 'Disable' : 'Enable'}
                        </Button>
                        <Button size="small" variant="danger" onClick={() => onDelete(block)}>
                          Delete
                        </Button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
