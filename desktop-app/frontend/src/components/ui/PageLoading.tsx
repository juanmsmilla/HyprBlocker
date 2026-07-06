import { Loader2 } from 'lucide-react';

export function PageLoading() {
  return (
    <div className="flex items-center justify-center gap-3 py-20 text-text-secondary">
      <Loader2 size={20} className="animate-spin" />
      <span>Loading…</span>
    </div>
  );
}
