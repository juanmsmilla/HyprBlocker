import { useState, useEffect } from 'react';
import { Globe, Monitor, AlertTriangle } from 'lucide-react';
import { useStatus } from '../context/StatusContext';
import { Card } from '../components/ui/Card';
import { PageLoading } from '../components/ui/PageLoading';
import { api, formatDate } from '../lib/api';
import type { StatsDetails, StatsTimelinePoint } from '../types';

const EVENT_TYPE_LABELS: Record<string, string> = {
  website_blocked: 'Website blocked',
  app_closed: 'App closed',
  browser_killed: 'Browser killed',
};

function EventIcon({ type }: { type: string }) {
  if (type === 'website_blocked') return <Globe size={16} className="text-info" />;
  if (type === 'app_closed') return <Monitor size={16} className="text-warning" />;
  return <AlertTriangle size={16} className="text-danger" />;
}

// Parse "YYYY-MM-DD" as a local date (new Date(str) would treat it as UTC)
function parseDay(date: string): Date {
  const [year, month, day] = date.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function TimelineChart({ timeline }: { timeline: StatsTimelinePoint[] }) {
  const max = Math.max(...timeline.map((p) => p.count), 0);

  if (max === 0) {
    return (
      <p className="text-center text-text-secondary py-10">
        No blocking activity in the last 14 days.
      </p>
    );
  }

  return (
    <div className="flex items-end gap-[2px] h-44 border-b border-border pb-px">
      {timeline.map((point) => {
        const day = parseDay(point.date);
        const heightPct = max > 0 ? (point.count / max) * 100 : 0;
        return (
          <div
            key={point.date}
            className="group relative flex-1 flex flex-col justify-end h-full"
          >
            {/* Direct label on the peak day only; others show on hover */}
            <span
              className={`text-center text-xs mb-1 ${
                point.count === max
                  ? 'text-text'
                  : 'text-text-secondary opacity-0 group-hover:opacity-100'
              }`}
            >
              {point.count > 0 ? point.count : ''}
            </span>
            <div
              className="rounded-t-[4px] bg-chart group-hover:brightness-125 transition-[filter] min-h-[2px]"
              style={{
                height: `${heightPct}%`,
                backgroundColor: point.count === 0 ? 'var(--color-bg-hover)' : undefined,
              }}
            />
            <div className="absolute -bottom-6 inset-x-0 text-center text-xs text-text-muted">
              {day.getDate() === 1 || point === timeline[0]
                ? day.toLocaleDateString([], { month: 'short', day: 'numeric' })
                : day.getDate()}
            </div>
            {/* Hover tooltip */}
            <div className="hidden group-hover:block absolute -top-7 left-1/2 -translate-x-1/2 bg-bg-elevated border border-border rounded px-2 py-1 text-xs text-text whitespace-nowrap z-10 shadow-md">
              {day.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
              : {point.count} blocked
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatTile({ value, label }: { value: number; label: string }) {
  return (
    <div className="bg-bg-card border border-border p-6 rounded-lg text-center shadow-md">
      <span className="block text-5xl font-bold mb-2 text-text-bright">{value}</span>
      <span className="text-sm text-text-secondary">{label}</span>
    </div>
  );
}

export function Statistics() {
  const { stats, loading } = useStatus();
  const [details, setDetails] = useState<StatsDetails | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await api.getStatsDetails();
        if (!cancelled) setDetails(data);
      } catch (error) {
        console.error('Failed to load stats details:', error);
      }
    };

    load();
    const interval = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (loading || !details) return <PageLoading />;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-semibold text-text">Statistics</h2>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-3 gap-5 mb-6">
        <StatTile value={stats?.total_blocks_today ?? 0} label="Blocks Today" />
        <StatTile value={stats?.total_blocks_week ?? 0} label="Blocks This Week" />
        <StatTile value={stats?.total_blocks_month ?? 0} label="Blocks This Month" />
      </div>

      {/* Timeline */}
      <Card title="Blocked Events — Last 14 Days" className="mb-6">
        <div className="pb-6">
          <TimelineChart timeline={details.timeline} />
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-5">
        {/* Top targets */}
        <Card title="Most Blocked — Last 30 Days">
          {details.top_targets.length === 0 ? (
            <p className="text-center text-text-secondary py-6">Nothing blocked yet.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {details.top_targets.map((item) => {
                const maxCount = details.top_targets[0].count;
                return (
                  <div key={item.target}>
                    <div className="flex justify-between items-baseline mb-1">
                      <span className="text-sm text-text truncate mr-3">{item.target}</span>
                      <span className="text-sm text-text-secondary shrink-0">{item.count}</span>
                    </div>
                    <div className="h-1.5 bg-bg-secondary rounded-full overflow-hidden">
                      <div
                        className="h-full bg-chart rounded-full"
                        style={{ width: `${(item.count / maxCount) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* Recent events */}
        <Card title="Recent Activity">
          {details.recent_events.length === 0 ? (
            <p className="text-center text-text-secondary py-6">No events recorded yet.</p>
          ) : (
            <div className="flex flex-col gap-2 max-h-80 overflow-y-auto">
              {details.recent_events.map((event, index) => (
                <div
                  key={`${event.timestamp}-${index}`}
                  className="flex items-center gap-3 p-2.5 bg-bg-secondary rounded-lg"
                >
                  <EventIcon type={event.event_type} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-text truncate">{event.blocked_target}</div>
                    <div className="text-xs text-text-secondary">
                      {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
                    </div>
                  </div>
                  <span className="text-xs text-text-secondary shrink-0">
                    {formatDate(event.timestamp)}
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
