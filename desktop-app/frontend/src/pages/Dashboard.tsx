import { ShieldCheck, ShieldOff, CalendarClock, CircleOff } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { useStatus } from '../context/StatusContext';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { PageLoading } from '../components/ui/PageLoading';
import { capitalizeFirst, getBrowserIcon } from '../lib/api';
import { getBlockActivity, formatRuleCount, type BlockActivityState } from '../lib/blocks';

const ACTIVITY_ORDER: Record<BlockActivityState, number> = {
  active: 0,
  scheduled: 1,
  off: 2,
};

function ActivityBadge({ state }: { state: BlockActivityState }) {
  if (state === 'active') return <Badge variant="success">Active now</Badge>;
  if (state === 'scheduled') return <Badge variant="info">Scheduled</Badge>;
  return <Badge variant="default">Off</Badge>;
}

function ActivityIcon({ state }: { state: BlockActivityState }) {
  if (state === 'active') return <ShieldCheck size={18} className="text-success" />;
  if (state === 'scheduled') return <CalendarClock size={18} className="text-info" />;
  return <CircleOff size={18} className="text-text-muted" />;
}

export function Dashboard() {
  const { setCurrentPage } = useApp();
  const { status, stats, browsers, blocks, loading } = useStatus();

  if (loading) return <PageLoading />;

  const running = status?.running ?? false;
  const blockActivities = blocks
    .map((block) => ({ block, activity: getBlockActivity(block) }))
    .sort((a, b) => ACTIVITY_ORDER[a.activity.state] - ACTIVITY_ORDER[b.activity.state]);
  const activeCount = blockActivities.filter((b) => b.activity.state === 'active').length;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Dashboard</h2>
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* Status Card */}
        <Card title="Status">
          <div
            className={`flex items-center gap-3 text-3xl font-bold mb-2 ${
              running ? 'text-success' : 'text-danger'
            }`}
          >
            {running ? <ShieldCheck size={32} /> : <ShieldOff size={32} />}
            {running ? 'Active' : 'Daemon Not Running'}
          </div>
          <div className="text-sm text-text-secondary">
            {running
              ? `${activeCount} of ${blocks.length} blocks enforcing now | ${
                  status?.browsers_compliant ?? 0
                }/${status?.browsers_detected ?? 0} browsers compliant`
              : 'Nothing is being blocked right now'}
          </div>
        </Card>

        {/* Today's Activity Card */}
        <Card title="Today's Activity">
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center p-4 bg-bg-secondary rounded-lg">
              <span className="block text-3xl font-bold text-accent-blue">
                {stats?.websites_blocked_today ?? 0}
              </span>
              <span className="text-xs text-text-secondary uppercase tracking-wide">
                Sites Blocked
              </span>
            </div>
            <div className="text-center p-4 bg-bg-secondary rounded-lg">
              <span className="block text-3xl font-bold text-accent-blue">
                {stats?.apps_closed_today ?? 0}
              </span>
              <span className="text-xs text-text-secondary uppercase tracking-wide">
                Apps Closed
              </span>
            </div>
            <div className="text-center p-4 bg-bg-secondary rounded-lg">
              <span className="block text-3xl font-bold text-accent-blue">
                {stats?.browsers_killed_today ?? 0}
              </span>
              <span className="text-xs text-text-secondary uppercase tracking-wide">
                Browsers Killed
              </span>
            </div>
          </div>
        </Card>

        {/* Blocks Card */}
        <Card title="Blocks" className="col-span-2">
          {blocks.length === 0 ? (
            <div className="text-center py-6">
              <p className="text-text-secondary mb-3">No blocks configured yet.</p>
              <button
                onClick={() => setCurrentPage('blocks')}
                className="text-accent-blue hover:underline"
              >
                Create your first block →
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {blockActivities.map(({ block, activity }) => (
                <div
                  key={block.id}
                  className="flex items-center gap-3 p-3 bg-bg-secondary rounded-lg"
                >
                  <ActivityIcon state={activity.state} />
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-text">{block.name}</span>
                    <span className="text-xs text-text-secondary ml-2">
                      {formatRuleCount(block)}
                    </span>
                  </div>
                  <span className="text-xs text-text-secondary">{activity.detail}</span>
                  <ActivityBadge state={activity.state} />
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Browser Status Card */}
        <Card title="Browser Status" className="col-span-2">
          {browsers.length === 0 ? (
            <p className="text-center text-text-secondary py-4">No browsers detected</p>
          ) : (
            <div className="flex flex-col gap-2">
              {browsers.map((browser) => (
                <div
                  key={browser.pid}
                  className="flex items-center gap-3 p-3 bg-bg-secondary rounded-lg"
                >
                  <span className="text-xl">{getBrowserIcon(browser.browser)}</span>
                  <span className="flex-1 font-medium">{capitalizeFirst(browser.browser)}</span>
                  <span
                    className={`text-xs px-2 py-1 rounded-full text-text-bright ${
                      browser.compliant ? 'bg-success' : 'bg-danger'
                    }`}
                  >
                    {browser.compliant ? 'Active' : 'No Extension'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
