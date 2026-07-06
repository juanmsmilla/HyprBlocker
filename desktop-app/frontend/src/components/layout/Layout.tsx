import { type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { ToastContainer } from '../ui/Toast';
import { useStatus } from '../../context/StatusContext';

function DaemonDownBanner() {
  const { status, loading } = useStatus();

  if (loading || status?.running) return null;

  return (
    <div className="bg-danger/20 border border-danger rounded-lg px-4 py-3 mb-6 flex items-center gap-3">
      <AlertTriangle size={20} className="text-danger shrink-0" />
      <div>
        <p className="font-bold text-danger">Daemon not running — nothing is being blocked</p>
        <p className="text-sm text-text-secondary">
          Start it with{' '}
          <code className="bg-bg-secondary px-1.5 py-0.5 rounded text-accent-green">
            systemctl --user start website-blocker
          </code>{' '}
          and it will reconnect automatically.
        </p>
      </div>
    </div>
  );
}

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <div style={{ paddingLeft: '240px' }}>
        <main className="min-h-screen">
          <div className="max-w-[1400px] mx-auto px-8 py-6">
            <DaemonDownBanner />
            {children}
          </div>
        </main>
      </div>
      <ToastContainer />
    </div>
  );
}
