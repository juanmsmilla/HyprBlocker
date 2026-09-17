import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus } from 'lucide-react';
import { useStatus } from '../context/StatusContext';
import { useToast } from '../context/ToastContext';
import { Button } from '../components/ui/Button';
import { BlocksTable } from '../components/blocks/BlocksTable';
import { BlockModal } from '../components/blocks/BlockModal';
import { LockModal } from '../components/blocks/LockModal';
import { AddRulesModal } from '../components/blocks/AddRulesModal';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { PageLoading } from '../components/ui/PageLoading';
import { api } from '../lib/api';
import { formatRuleCount } from '../lib/blocks';
import type { Block, PendingUnblock } from '../types';

export function Blocks() {
  const { blocks, loading, refreshBlocks } = useStatus();
  const { showToast } = useToast();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingBlock, setEditingBlock] = useState<Block | null>(null);
  const [isLockModalOpen, setIsLockModalOpen] = useState(false);
  const [lockingBlock, setLockingBlock] = useState<Block | null>(null);
  const [isAddRulesModalOpen, setIsAddRulesModalOpen] = useState(false);
  const [addRulesBlock, setAddRulesBlock] = useState<Block | null>(null);
  const [deletingBlock, setDeletingBlock] = useState<Block | null>(null);
  const [pendingUnblocks, setPendingUnblocks] = useState<PendingUnblock[]>([]);

  const loadPending = useCallback(async () => {
    try {
      const pending = await api.getPendingUnblocks();
      setPendingUnblocks(pending);
    } catch (error) {
      console.error('Failed to load pending unblocks:', error);
    }
  }, []);

  useEffect(() => {
    loadPending();
    const id = window.setInterval(loadPending, 5000);
    return () => window.clearInterval(id);
  }, [loadPending]);

  const pendingByBlockId = useMemo(() => {
    const map = new Map<number, PendingUnblock>();
    for (const p of pendingUnblocks) {
      if (p.kind === 'settings' || !p.block_id) continue;
      map.set(p.block_id, p);
    }
    return map;
  }, [pendingUnblocks]);

  const handleAddBlock = () => {
    setEditingBlock(null);
    setIsModalOpen(true);
  };

  const handleEditBlock = async (block: Block) => {
    try {
      const lockStatus = await api.getBlockLockStatus(block.id);
      if (lockStatus.locked) {
        setAddRulesBlock(block);
        setIsAddRulesModalOpen(true);
        return;
      }
      setEditingBlock(block);
      setIsModalOpen(true);
    } catch (error) {
      console.error('Failed to check lock status:', error);
      setEditingBlock(block);
      setIsModalOpen(true);
    }
  };

  const handleToggleBlock = async (block: Block) => {
    try {
      const lockStatus = await api.getBlockLockStatus(block.id);
      if (lockStatus.locked) {
        showToast('This block is currently locked', 'warning');
        return;
      }

      const result = await api.updateBlock(block.id, { enabled: !block.enabled });
      if (result.success) {
        if ((result as { pending?: boolean }).pending) {
          showToast(
            (result as { message?: string }).message || 'Change queued — use Cancel delay in Actions',
            'success',
          );
          await loadPending();
        }
        await refreshBlocks();
      } else {
        showToast(result.error || 'Failed to update block', 'error');
      }
    } catch (error) {
      console.error('Failed to toggle block:', error);
      showToast('Failed to update block', 'error');
    }
  };

  const handleDeleteBlock = async (block: Block) => {
    try {
      const lockStatus = await api.getBlockLockStatus(block.id);
      if (lockStatus.locked) {
        showToast('This block is currently locked', 'warning');
        return;
      }
      setDeletingBlock(block);
    } catch (error) {
      console.error('Failed to check lock status:', error);
      showToast('Failed to check lock status', 'error');
    }
  };

  const confirmDeleteBlock = async () => {
    if (!deletingBlock) return;
    try {
      const result = await api.deleteBlock(deletingBlock.id);
      if (result.success) {
        if ((result as { pending?: boolean }).pending) {
          showToast(
            (result as { message?: string }).message || 'Delete queued — use Cancel delay in Actions',
            'success',
          );
          await loadPending();
        } else {
          showToast('Block deleted', 'success');
        }
        await refreshBlocks();
      } else {
        showToast(result.error || 'Failed to delete block', 'error');
      }
    } catch (error) {
      console.error('Failed to delete block:', error);
      showToast('Failed to delete block', 'error');
    } finally {
      setDeletingBlock(null);
    }
  };

  const handleCancelDelay = async (pending: PendingUnblock) => {
    try {
      const result = await api.cancelPendingUnblock(pending.id);
      if (result.success) {
        showToast('Delay canceled', 'success');
        await loadPending();
        await refreshBlocks();
      } else {
        showToast(result.error || 'Failed to cancel delay', 'error');
      }
    } catch (error) {
      console.error('Failed to cancel pending:', error);
      showToast('Failed to cancel delay', 'error');
    }
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setEditingBlock(null);
  };

  const handleLockBlock = (block: Block) => {
    setLockingBlock(block);
    setIsLockModalOpen(true);
  };

  const handleCloseLockModal = () => {
    setIsLockModalOpen(false);
    setLockingBlock(null);
  };

  const handleCloseAddRulesModal = () => {
    setIsAddRulesModalOpen(false);
    setAddRulesBlock(null);
  };

  if (loading) return <PageLoading />;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Blocks</h2>
        <Button onClick={handleAddBlock}>
          <Plus size={18} />
          Add Block
        </Button>
      </div>

      <p className="text-text-secondary mb-5">
        Blocks group rules together and define when they're active and when configuration is locked.
      </p>

      <BlocksTable
        blocks={blocks}
        pendingByBlockId={pendingByBlockId}
        onEdit={handleEditBlock}
        onToggle={handleToggleBlock}
        onDelete={handleDeleteBlock}
        onLock={handleLockBlock}
        onCancelDelay={handleCancelDelay}
        onAdd={handleAddBlock}
      />

      <ConfirmDialog
        isOpen={deletingBlock !== null}
        title="Delete Block"
        message={
          deletingBlock ? (
            <p>
              Delete <strong className="text-text">{deletingBlock.name}</strong> and its{' '}
              {formatRuleCount(deletingBlock)}? This cannot be undone.
            </p>
          ) : null
        }
        confirmLabel="Delete"
        onConfirm={confirmDeleteBlock}
        onCancel={() => setDeletingBlock(null)}
      />

      <BlockModal
        isOpen={isModalOpen}
        onClose={handleCloseModal}
        editBlock={editingBlock}
      />

      <LockModal
        isOpen={isLockModalOpen}
        onClose={handleCloseLockModal}
        block={lockingBlock}
      />

      <AddRulesModal
        isOpen={isAddRulesModalOpen}
        onClose={handleCloseAddRulesModal}
        block={addRulesBlock}
      />
    </div>
  );
}
