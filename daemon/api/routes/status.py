"""Status, stats, browsers, and blocked-sites API routes."""

from datetime import datetime, timedelta

from database import Block, BlockEvent
from fastapi import APIRouter, Depends
from heartbeat_tracker import get_heartbeat_tracker
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session
from ..schemas import (
    BrowserStatus,
    StatsDetailsResponse,
    StatsRecentEvent,
    StatsResponse,
    StatsTimelinePoint,
    StatsTopTarget,
    StatusResponse,
)

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=StatusResponse)
async def get_status(session: AsyncSession = Depends(get_session)):
    """Get daemon status."""
    tracker = get_heartbeat_tracker()

    # Count active blocks
    result = await session.execute(
        select(func.count(Block.id)).where(Block.enabled.is_(True))
    )
    active_blocks = result.scalar() or 0

    browser_statuses = tracker.get_all_browser_statuses()
    browsers_detected = len(browser_statuses)
    browsers_compliant = sum(1 for b in browser_statuses if b.get("compliant", False))

    return StatusResponse(
        running=True,
        active_rules=0,  # Legacy field, no longer used
        active_blocks=active_blocks,
        browsers_detected=browsers_detected,
        browsers_compliant=browsers_compliant
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get blocking statistics."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Today's stats
    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= today)
    )
    total_today = result.scalar() or 0

    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= today)
        .where(BlockEvent.event_type == 'website_blocked')
    )
    websites_today = result.scalar() or 0

    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= today)
        .where(BlockEvent.event_type == 'app_closed')
    )
    apps_today = result.scalar() or 0

    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= today)
        .where(BlockEvent.event_type == 'browser_killed')
    )
    browsers_today = result.scalar() or 0

    # Week stats
    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= week_ago)
    )
    total_week = result.scalar() or 0

    # Month stats
    result = await session.execute(
        select(func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= month_ago)
    )
    total_month = result.scalar() or 0

    return StatsResponse(
        total_blocks_today=total_today,
        total_blocks_week=total_week,
        total_blocks_month=total_month,
        websites_blocked_today=websites_today,
        apps_closed_today=apps_today,
        browsers_killed_today=browsers_today
    )


@router.get("/stats/details", response_model=StatsDetailsResponse)
async def get_stats_details(session: AsyncSession = Depends(get_session)):
    """Get detailed statistics: daily timeline, top blocked targets, recent events."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    timeline_start = today - timedelta(days=13)
    month_start = today - timedelta(days=29)

    # Events per day over the last 14 days (including empty days)
    result = await session.execute(
        select(func.date(BlockEvent.timestamp), func.count(BlockEvent.id))
        .where(BlockEvent.timestamp >= timeline_start)
        .group_by(func.date(BlockEvent.timestamp))
    )
    counts_by_day = {str(date): count for date, count in result.all()}
    timeline = []
    for i in range(14):
        day = (timeline_start + timedelta(days=i)).strftime("%Y-%m-%d")
        timeline.append(StatsTimelinePoint(date=day, count=counts_by_day.get(day, 0)))

    # Most-blocked targets over the last 30 days
    result = await session.execute(
        select(BlockEvent.blocked_target, func.count(BlockEvent.id).label("count"))
        .where(BlockEvent.timestamp >= month_start)
        .group_by(BlockEvent.blocked_target)
        .order_by(func.count(BlockEvent.id).desc())
        .limit(10)
    )
    top_targets = [
        StatsTopTarget(target=target, count=count) for target, count in result.all()
    ]

    # Most recent events
    result = await session.execute(
        select(BlockEvent).order_by(BlockEvent.timestamp.desc()).limit(15)
    )
    recent_events = [
        StatsRecentEvent(
            blocked_target=event.blocked_target,
            event_type=event.event_type,
            timestamp=event.timestamp.isoformat(),
        )
        for event in result.scalars().all()
    ]

    return StatsDetailsResponse(
        timeline=timeline,
        top_targets=top_targets,
        recent_events=recent_events,
    )


@router.get("/browsers", response_model=list[BrowserStatus])
async def get_browsers():
    """Get detected browsers and extension status."""
    tracker = get_heartbeat_tracker()
    statuses = tracker.get_all_browser_statuses()

    return [
        BrowserStatus(
            pid=s["pid"],
            browser=s["browser"],
            compliant=s["compliant"],
            last_heartbeat=s["last_heartbeat"],
            incognito_active=s["incognito_active"],
            incognito_enabled=s["incognito_enabled"]
        )
        for s in statuses
    ]


@router.get("/blocked-sites")
async def get_blocked_sites():
    """Get list of currently active blocked website patterns.

    This endpoint is used by the browser extension to get the list
    of sites to block. Returns per-block data so extension can implement
    intersection-based allow list logic.
    """
    from scheduler import get_scheduler

    from config import get_config

    scheduler = get_scheduler()
    config = get_config()

    if scheduler is None:
        return {
            "blocks": [],
            "safe_search_enabled": config.security.safe_search_enabled
        }

    active_blocks = await scheduler.get_active_blocks()

    # Return per-block data
    blocks_data = []

    for block in active_blocks:
        block_data = {
            "id": block.id,
            "name": block.name,
            "blocked": [],
            "allowed": []
        }

        # Parse blocked patterns
        if block.websites_blocked:
            block_data["blocked"] = [
                line.strip()
                for line in block.websites_blocked.split('\n')
                if line.strip()
            ]

        # Parse allowed patterns
        if block.websites_allowed:
            block_data["allowed"] = [
                line.strip()
                for line in block.websites_allowed.split('\n')
                if line.strip()
            ]

        blocks_data.append(block_data)

    return {
        "blocks": blocks_data,
        "safe_search_enabled": config.security.safe_search_enabled
    }
