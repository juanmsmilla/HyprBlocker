"""Tests for additive SQLite column migrations."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from daemon.migrations import migrate_websites_media_blocked


async def _add_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE blocks (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                websites_blocked TEXT
            )
            """
        ))
        async with AsyncSession(conn) as session:
            await migrate_websites_media_blocked(session)

        result = await conn.execute(text("PRAGMA table_info(blocks)"))
        columns = {row[1] for row in result}
        assert "websites_media_blocked" in columns

        async with AsyncSession(conn) as session:
            await migrate_websites_media_blocked(session)
    await engine.dispose()


async def _skip_missing_table():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        async with AsyncSession(conn) as session:
            await migrate_websites_media_blocked(session)
    await engine.dispose()


def test_migrate_websites_media_blocked_adds_column():
    asyncio.run(_add_column())


def test_migrate_websites_media_blocked_skips_missing_table():
    asyncio.run(_skip_missing_table())
