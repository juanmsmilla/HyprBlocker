import { useState, useEffect } from 'react';
import { Modal, ModalFooter } from '../ui/Modal';
import { Button } from '../ui/Button';
import {
  FormGroup,
  FormSection,
  FormRow,
  Input,
  Select,
  Textarea,
  Checkbox,
  DayCheckboxes,
} from '../ui/FormElements';
import { useToast } from '../../context/ToastContext';
import { useStatus } from '../../context/StatusContext';
import { api, parseDaysOfWeek } from '../../lib/api';
import type { Block, BlockInput, BlockPriority } from '../../types';

interface BlockModalProps {
  isOpen: boolean;
  onClose: () => void;
  editBlock?: Block | null;
}

const INITIAL_FORM_STATE: BlockInput = {
  name: '',
  block_mode: 'always',
  lock_mode: 'none',
  enabled: true,
  block_days_of_week: '[]',
  block_start_time: '09:00',
  block_end_time: '17:00',
  websites_blocked: '',
  websites_allowed: '',
  websites_media_blocked: '',
  apps_blocked: '',
  priority: 'low',
};

export function BlockModal({ isOpen, onClose, editBlock }: BlockModalProps) {
  const { showToast } = useToast();
  const { refreshBlocks } = useStatus();
  const [formData, setFormData] = useState<BlockInput>(INITIAL_FORM_STATE);
  const [blockDays, setBlockDays] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const isEditMode = !!editBlock;

  // Populate form when editing
  useEffect(() => {
    if (editBlock) {
      setFormData({
        name: editBlock.name,
        block_mode: editBlock.block_mode,
        lock_mode: editBlock.lock_mode,
        enabled: editBlock.enabled,
        block_start_time: editBlock.block_start_time || '09:00',
        block_end_time: editBlock.block_end_time || '17:00',
        websites_blocked: editBlock.websites_blocked || '',
        websites_allowed: editBlock.websites_allowed || '',
        websites_media_blocked: editBlock.websites_media_blocked || '',
        apps_blocked: editBlock.apps_blocked || '',
        priority: editBlock.priority === 'high' || editBlock.priority === 'medium'
          ? editBlock.priority
          : 'low',
      });
      setBlockDays(parseDaysOfWeek(editBlock.block_days_of_week));
    } else {
      setFormData(INITIAL_FORM_STATE);
      setBlockDays([]);
    }
  }, [editBlock, isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      const data: BlockInput = {
        ...formData,
        block_days_of_week: JSON.stringify(blockDays),
      };

      // Remove block time fields if block_mode is not 'time_range'
      if (formData.block_mode !== 'time_range') {
        delete data.block_start_time;
        delete data.block_end_time;
        delete data.block_days_of_week;
      }

      let result;
      if (isEditMode && editBlock) {
        result = await api.updateBlock(editBlock.id, data);
      } else {
        result = await api.addBlock(data);
      }

      if (result.success) {
        showToast(isEditMode ? 'Block updated successfully' : 'Block added successfully', 'success');
        await refreshBlocks();
        onClose();
      } else {
        showToast(result.error || 'Failed to save block', 'error');
      }
    } catch (error) {
      console.error('Failed to save block:', error);
      showToast('Failed to save block', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const updateField = <K extends keyof BlockInput>(field: K, value: BlockInput[K]) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEditMode ? 'Edit Block' : 'Add Block'}
      size="large"
    >
      <form onSubmit={handleSubmit}>
        <FormGroup label="Name">
          <Input
            type="text"
            placeholder="e.g., Work Focus"
            value={formData.name}
            onChange={(e) => updateField('name', e.target.value)}
            required
          />
        </FormGroup>

        <FormGroup
          label="Priority"
          hint="Higher priority overrides lower for sites this block lists. Same priority: every matching block must allow the site. To exempt a site from a lower block, list it in this block's blocked or media-blocked list and in Allowed websites."
        >
          <Select
            value={formData.priority}
            onChange={(e) => updateField('priority', e.target.value as BlockPriority)}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </Select>
        </FormGroup>

        {/* Block Schedule Section */}
        <FormSection title="Block Schedule" hint="When should content be blocked?">
          <FormGroup label="Block Mode">
            <Select
              value={formData.block_mode}
              onChange={(e) => updateField('block_mode', e.target.value as BlockInput['block_mode'])}
            >
              <option value="always">Always Block</option>
              <option value="time_range">Block During Time Range</option>
              <option value="disabled">Disabled (Don't Block)</option>
            </Select>
          </FormGroup>

          {formData.block_mode === 'time_range' && (
            <>
              <FormGroup label="Block Days">
                <DayCheckboxes
                  name="block-days"
                  selectedDays={blockDays}
                  onChange={setBlockDays}
                />
              </FormGroup>
              <FormRow>
                <FormGroup label="Start Time">
                  <Input
                    type="time"
                    value={formData.block_start_time}
                    onChange={(e) => updateField('block_start_time', e.target.value)}
                  />
                </FormGroup>
                <FormGroup label="End Time">
                  <Input
                    type="time"
                    value={formData.block_end_time}
                    onChange={(e) => updateField('block_end_time', e.target.value)}
                  />
                </FormGroup>
              </FormRow>
            </>
          )}
        </FormSection>

        {/* Blocked Content Section */}
        <FormSection title="Blocked Content" hint="Enter one item per line">
          <FormGroup
            label="Blocked Websites"
            hint="Host/path patterns, or * for every http(s) URL. Allowed websites are the exceptions. chrome://, extension pages, and localhost are never blocked."
          >
            <Textarea
              rows={4}
              placeholder={'*\nreddit.com\nyoutube.com/shorts'}
              value={formData.websites_blocked || ''}
              onChange={(e) => updateField('websites_blocked', e.target.value || '')}
            />
          </FormGroup>

          <FormGroup
            label="Media-blocked websites"
            hint="Page stays available; images, video, and audio are cancelled. * = every URL; use Allowed websites for exceptions (e.g. radio, tools)."
          >
            <Textarea
              rows={3}
              placeholder={'*\nyoutube.com'}
              value={formData.websites_media_blocked || ''}
              onChange={(e) => updateField('websites_media_blocked', e.target.value || '')}
            />
          </FormGroup>

          <FormGroup
            label="Allowed Websites (exceptions)"
            hint="Overrides Blocked and Media-blocked lists, including when those lists use *"
          >
            <Textarea
              rows={3}
              placeholder={'openai.com\nreddit.com/r/programming'}
              value={formData.websites_allowed || ''}
              onChange={(e) => updateField('websites_allowed', e.target.value || '')}
            />
          </FormGroup>

          <FormGroup label="Blocked Applications">
            <Textarea
              rows={4}
              placeholder="steam&#10;discord"
              value={formData.apps_blocked || ''}
              onChange={(e) => updateField('apps_blocked', e.target.value || '')}
            />
          </FormGroup>
        </FormSection>

        <Checkbox
          label="Enabled"
          checked={formData.enabled}
          onChange={(e) => updateField('enabled', e.target.checked)}
        />

        <ModalFooter>
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={submitting}>
            {isEditMode ? 'Save Changes' : 'Add Block'}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}
