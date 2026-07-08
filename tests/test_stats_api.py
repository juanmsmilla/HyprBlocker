"""Tests for the /api/stats/details endpoint logic."""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from daemon.api.routes.status import get_stats_details
from daemon.database import Base, BlockEvent


def run_with_events(events):
    """Run get_stats_details against an in-memory DB seeded with events.

    Args:
        events: List of (blocked_target, event_type, days_ago) tuples

    Returns:
        StatsDetailsResponse
    """

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        now = datetime.now()
        async with factory() as session:
            for target, event_type, days_ago in events:
                session.add(
                    BlockEvent(
                        blocked_target=target,
                        event_type=event_type,
                        timestamp=now - timedelta(days=days_ago),
                    )
                )
            await session.commit()

        async with factory() as session:
            result = await get_stats_details(session)

        await engine.dispose()
        return result

    return asyncio.run(_run())


def test_empty_database():
    result = run_with_events([])
    assert len(result.timeline) == 14
    assert all(point.count == 0 for point in result.timeline)
    assert result.top_targets == []
    assert result.recent_events == []


def test_timeline_covers_14_days_and_counts_events():
    result = run_with_events(
        [
            ("youtube.com", "website_blocked", 0),
            ("youtube.com", "website_blocked", 0),
            ("steam", "app_closed", 3),
            ("youtube.com", "website_blocked", 13),
            ("youtube.com", "website_blocked", 15),  # outside the 14-day window
        ]
    )
    assert len(result.timeline) == 14
    assert result.timeline[-1].date == datetime.now().strftime("%Y-%m-%d")
    assert result.timeline[-1].count == 2
    assert sum(point.count for point in result.timeline) == 4


def test_top_targets_sorted_and_limited_to_30_days():
    result = run_with_events(
        [
            ("steam", "app_closed", 1),
            ("steam", "app_closed", 2),
            ("youtube.com", "website_blocked", 0),
            ("youtube.com", "website_blocked", 40),  # outside the 30-day window
        ]
    )
    assert [(t.target, t.count) for t in result.top_targets] == [
        ("steam", 2),
        ("youtube.com", 1),
    ]


def test_recent_events_newest_first():
    result = run_with_events(
        [
            ("old.com", "website_blocked", 5),
            ("new.com", "website_blocked", 0),
        ]
    )
    assert [e.blocked_target for e in result.recent_events] == ["new.com", "old.com"]
    assert result.recent_events[0].event_type == "website_blocked"
