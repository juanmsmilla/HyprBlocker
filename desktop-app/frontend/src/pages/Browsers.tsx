import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Plus, Clock, AlertTriangle } from 'lucide-react';
import { useStatus } from '../context/StatusContext';
import { useToast } from '../context/ToastContext';
import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { PageLoading } from '../components/ui/PageLoading';
import { api, capitalizeFirst, formatTime, getBrowserIcon } from '../lib/api';
import type { GracePeriodStatus } from '../types';

export function Browsers() {
  const { browsers, loading, refreshBrowsers } = useStatus();
  const { showToast } = useToast();
  const [gracePeriod, setGracePeriod] = useState<GracePeriodStatus | null>(null);

  const refreshGracePeriod = useCallback(async () => {
    try {
      const status = await api.getGracePeriodStatus();
      setGracePeriod(status);
    } catch (error) {
      console.error('Failed to get grace period status:', error);
    }
  }, []);

  // The daemon owns the grace period, so the countdown survives navigating
  // away and reflects grace periods started elsewhere (e.g. the tray app).
  useEffect(() => {
    const load = async () => {
      await refreshGracePeriod();
    };
    load();
    const interval = setInterval(load, gracePeriod?.active ? 1000 : 5000);
    return () => clearInterval(interval);
  }, [refreshGracePeriod, gracePeriod?.active]);

  const handleRefresh = async () => {
    await refreshBrowsers();
    await refreshGracePeriod();
  };

  const startGracePeriod = async () => {
    try {
      const result = await api.startExtensionGracePeriod();
      if (result.success) {
        showToast('Grace period started - you have 30 seconds to add the extension', 'success');
        await refreshGracePeriod();
      } else {
        showToast(result.error || 'Failed to start grace period', 'error');
      }
    } catch (error) {
      console.error('Failed to start grace period:', error);
      showToast('Failed to start grace period', 'error');
    }
  };

  if (loading) return <PageLoading />;

  const nonCompliantCount = browsers.filter((b) => !b.incognito_enabled).length;
  const allCompliant = browsers.length > 0 && browsers.every((b) => b.compliant);

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Browser Status</h2>
        <div className="flex gap-3">
          <Button onClick={startGracePeriod}>
            <Plus size={18} />
            Add Extension
          </Button>
          <Button variant="secondary" onClick={handleRefresh}>
            <RefreshCw size={18} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Grace Period Banner */}
      {gracePeriod?.active && (
        <div className="bg-warning/20 border border-warning rounded-lg px-4 py-3 mb-4 flex items-center gap-2">
          <Clock size={18} className="text-warning" />
          <span className="flex-1 text-text">Grace period active - browser enforcement paused</span>
          <span className="font-bold text-warning">{gracePeriod.remaining_seconds}s</span>
        </div>
      )}

      {/* Incognito Permission Warning */}
      {nonCompliantCount > 0 && (
        <div className="bg-danger/20 border border-danger rounded-lg px-4 py-3 mb-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={18} className="text-danger" />
            <span className="font-bold text-danger">Incognito Permission Required</span>
          </div>
          <p className="text-text-secondary mb-2">
            {nonCompliantCount} browser(s) are NON-COMPLIANT because they don't have incognito
            permission
          </p>
          <p className="text-text-secondary text-sm">
            To fix: Open chrome://extensions/, find "Website Blocker", and enable "Allow in
            Incognito"
          </p>
        </div>
      )}

      {/* Browser Grid */}
      <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-5 mb-6">
        {browsers.length === 0 ? (
          <p className="text-center text-text-secondary py-8 col-span-full">
            No browsers detected. Start a browser with the extension installed.
          </p>
        ) : (
          browsers.map((browser) => (
            <Card key={browser.pid}>
              <div className="flex items-center gap-3 mb-4">
                <span className="text-2xl">{getBrowserIcon(browser.browser)}</span>
                <h4 className="flex-1 font-medium text-text">
                  {capitalizeFirst(browser.browser)}
                </h4>
                <Badge variant={browser.compliant ? 'success' : 'danger'}>
                  {browser.compliant ? 'Compliant' : 'Non-compliant'}
                </Badge>
              </div>
              <div className="text-sm text-text-secondary space-y-2">
                <p>
                  <strong className="text-text">PID:</strong> {browser.pid}
                </p>
                <p>
                  <strong className="text-text">Last Heartbeat:</strong>{' '}
                  {formatTime(browser.last_heartbeat)}
                </p>
                <p>
                  <strong className="text-text">Incognito Active:</strong>{' '}
                  {browser.incognito_active ? 'Yes' : 'No'}
                </p>
                <p>
                  <strong className="text-text">Incognito Permission:</strong>{' '}
                  <span className={browser.incognito_enabled ? 'text-accent-green' : 'text-danger'}>
                    {browser.incognito_enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </p>
              </div>
            </Card>
          ))
        )}
      </div>

      {/* Extension Info - only shown while setup is still needed */}
      {!allCompliant && (
        <Card title="Extension Setup">
          <p className="text-text-secondary mb-4">
            The browser extension is required for website blocking to work. Install it in each
            browser you use.
          </p>
          <ol className="list-decimal list-inside space-y-3 text-text">
            <li>Click "Add Extension" to start a grace period</li>
            <li>Open your browser's extension settings</li>
            <li>Enable "Developer mode"</li>
            <li>
              Load the extension from:{' '}
              <code className="bg-bg-secondary px-2 py-1 rounded text-accent-green text-sm">
                ~/.local/share/website-blocker/extension
              </code>
            </li>
            <li>Enable the extension in incognito/private mode</li>
          </ol>
        </Card>
      )}
    </div>
  );
}
