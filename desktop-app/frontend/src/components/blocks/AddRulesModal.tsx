import { useState } from 'react';
import { Modal, ModalFooter } from '../ui/Modal';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { FormGroup, FormSection, Textarea } from '../ui/FormElements';
import { useToast } from '../../context/ToastContext';
import { useStatus } from '../../context/StatusContext';
import { api, formatDays, parseDaysOfWeek } from '../../lib/api';
import { getBlockActivity } from '../../lib/blocks';
import type { Block, BlockPriority } from '../../types';

interface AddRulesModalProps {
  isOpen: boolean;
  onClose: () => void;
  block: Block | null;
}

function ruleLines(value: string | null): string[] {
  if (!value) return [];
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function priorityLabel(priority: BlockPriority | undefined): string {
  if (priority === 'high') return 'High';
  if (priority === 'medium') return 'Medium';
  return 'Low';
}

function priorityVariant(priority: BlockPriority | undefined): 'warning' | 'info' | 'default' {
  if (priority === 'high') return 'warning';
  if (priority === 'medium') return 'info';
  return 'default';
}

// Same window text as the blocks table, plus whether that window is active.
function formatSchedule(block: Block): { window: string; activity: string } {
  const activity = getBlockActivity(block);
  let activityText = 'Off';
  if (activity.state === 'active') {
    activityText = activity.detail.startsWith('Until ')
      ? `Active now, ${activity.detail.toLowerCase()}`
      : 'Active now';
  } else if (activity.state === 'scheduled') {
    activityText = 'Scheduled';
  } else if (!block.enabled) {
    activityText = 'Off (disabled)';
  } else if (block.block_mode === 'disabled') {
    activityText = 'Off (not blocking)';
  }

  if (block.block_mode === 'always') {
    return { window: 'Always', activity: activityText };
  }
  if (block.block_mode === 'time_range') {
    const days = parseDaysOfWeek(block.block_days_of_week);
    const daysText = days.length > 0 ? formatDays(days) : 'All days';
    const start = block.block_start_time || '';
    const end = block.block_end_time || '';
    const range = [start, end].filter(Boolean).join(' - ');
    return { window: range ? `${daysText} ${range}` : daysText, activity: activityText };
  }
  return { window: 'Disabled', activity: activityText };
}

function ReadOnlyRules({ value }: { value: string | null }) {
  const items = ruleLines(value);
  if (items.length === 0) {
    return <p className="text-sm text-text-secondary">(none)</p>;
  }
  return (
    <ul className="text-sm text-text space-y-0.5 break-words">
      {items.map((item, index) => (
        <li key={`${index}:${item}`}>{item}</li>
      ))}
    </ul>
  );
}

function CurrentRulesSummary({ block }: { block: Block }) {
  const schedule = formatSchedule(block);

  return (
    <FormSection
      title="Current Rules"
      hint="Read-only. These lists cannot be edited while the block is locked."
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 mb-5">
        <div>
          <dt className="text-xs text-text-secondary mb-1">Name</dt>
          <dd className="text-sm text-text break-words">{block.name}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-secondary mb-1">Priority</dt>
          <dd>
            <Badge variant={priorityVariant(block.priority)}>{priorityLabel(block.priority)}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-xs text-text-secondary mb-1">Enabled</dt>
          <dd className="text-sm text-text">{block.enabled ? 'Enabled' : 'Disabled'}</dd>
        </div>
        <div>
          <dt className="text-xs text-text-secondary mb-1">Schedule</dt>
          <dd>
            <div className="text-sm text-text">{schedule.window}</div>
            <div className="text-xs text-text-secondary mt-1">{schedule.activity}</div>
          </dd>
        </div>
      </dl>

      <FormGroup label="Websites blocked">
        <ReadOnlyRules value={block.websites_blocked} />
      </FormGroup>
      <FormGroup label="Media blocked">
        <ReadOnlyRules value={block.websites_media_blocked} />
      </FormGroup>
      <FormGroup label="Apps blocked">
        <ReadOnlyRules value={block.apps_blocked} />
      </FormGroup>
      <FormGroup label="Websites allowed" className="!mb-0">
        <ReadOnlyRules value={block.websites_allowed} />
      </FormGroup>
    </FormSection>
  );
}

export function AddRulesModal({ isOpen, onClose, block }: AddRulesModalProps) {
  const { showToast } = useToast();
  const { refreshBlocks } = useStatus();
  const [websitesBlockedAdd, setWebsitesBlockedAdd] = useState('');
  const [websitesMediaBlockedAdd, setWebsitesMediaBlockedAdd] = useState('');
  const [appsBlockedAdd, setAppsBlockedAdd] = useState('');
  const [websitesAllowedRemove, setWebsitesAllowedRemove] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!block) return;

    // Check if any fields have content
    const hasContent =
      websitesBlockedAdd.trim() ||
      websitesMediaBlockedAdd.trim() ||
      appsBlockedAdd.trim() ||
      websitesAllowedRemove.trim();

    if (!hasContent) {
      showToast('Please enter at least one rule to add or remove', 'warning');
      return;
    }

    setSubmitting(true);

    try {
      const updates: Record<string, string> = {};

      if (websitesBlockedAdd.trim()) {
        updates.websites_blocked_add = websitesBlockedAdd.trim();
      }
      if (websitesMediaBlockedAdd.trim()) {
        updates.websites_media_blocked_add = websitesMediaBlockedAdd.trim();
      }
      if (appsBlockedAdd.trim()) {
        updates.apps_blocked_add = appsBlockedAdd.trim();
      }
      if (websitesAllowedRemove.trim()) {
        updates.websites_allowed_remove = websitesAllowedRemove.trim();
      }

      const result = await api.updateBlockStrict(block.id, updates);

      if (result.success) {
        showToast('Rules updated successfully', 'success');
        await refreshBlocks();
        // Clear fields
        setWebsitesBlockedAdd('');
        setWebsitesMediaBlockedAdd('');
        setAppsBlockedAdd('');
        setWebsitesAllowedRemove('');
        onClose();
      } else {
        showToast(result.error || 'Failed to update rules', 'error');
      }
    } catch (error) {
      console.error('Failed to update rules:', error);
      showToast('Failed to update rules', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  if (!block) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`Add Rules: ${block.name}`}
      size="large"
    >
      <form onSubmit={handleSubmit}>
        <CurrentRulesSummary block={block} />

        <p className="text-sm text-text-secondary mb-4">
          This block is locked, but you can still add stricter rules.
          Adding blocked items and removing allowed items makes the block more restrictive.
        </p>

        <FormSection title="Add to Blocked Lists" hint="Enter one item per line">
          <FormGroup
            label="Websites to Block"
            hint="These will be added to the blocked websites list. * means every http(s) URL; Allowed websites are the exceptions."
          >
            <Textarea
              rows={4}
              placeholder={'*\nreddit.com\nyoutube.com/shorts'}
              value={websitesBlockedAdd}
              onChange={(e) => setWebsitesBlockedAdd(e.target.value)}
            />
          </FormGroup>

          <FormGroup
            label="Websites to media-block"
            hint="Page stays available; images/video/audio cancelled. * = every URL; use Allowed websites for exceptions."
          >
            <Textarea
              rows={3}
              placeholder={'*\nyoutube.com'}
              value={websitesMediaBlockedAdd}
              onChange={(e) => setWebsitesMediaBlockedAdd(e.target.value)}
            />
          </FormGroup>

          <FormGroup label="Apps to Block" hint="These will be added to the blocked apps list">
            <Textarea
              rows={3}
              placeholder="steam&#10;discord"
              value={appsBlockedAdd}
              onChange={(e) => setAppsBlockedAdd(e.target.value)}
            />
          </FormGroup>
        </FormSection>

        <FormSection title="Remove from Allow Lists" hint="Enter one item per line">
          <FormGroup label="Websites to Remove from Allow List" hint="These will be removed from the allowed websites">
            <Textarea
              rows={3}
              placeholder="youtube.com/educational"
              value={websitesAllowedRemove}
              onChange={(e) => setWebsitesAllowedRemove(e.target.value)}
            />
          </FormGroup>
        </FormSection>

        <ModalFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            Add Rules
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}
