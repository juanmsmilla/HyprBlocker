"""Tests for additive SQLite column migrations."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from daemon.migrations import migrate_block_priority, migrate_websites_media_blocked


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


async def _add_priority_column():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            """
            CREATE TABLE blocks (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
        ))
        await conn.execute(text("INSERT INTO blocks (name) VALUES ('existing')"))
        async with AsyncSession(conn) as session:
            await migrate_block_priority(session)

        result = await conn.execute(text("PRAGMA table_info(blocks)"))
        columns = {row[1] for row in result}
        assert "priority" in columns

        stored = await conn.execute(text("SELECT priority FROM blocks WHERE name = 'existing'"))
        assert stored.fetchone()[0] == "low"

        async with AsyncSession(conn) as session:
            await migrate_block_priority(session)
        stored = await conn.execute(text("SELECT priority FROM blocks WHERE name = 'existing'"))
        assert stored.fetchone()[0] == "low"
    await engine.dispose()


async def _priority_skips_missing_table():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        async with AsyncSession(conn) as session:
            await migrate_block_priority(session)
    await engine.dispose()


def test_migrate_block_priority_defaults_existing_rows_to_low():
    asyncio.run(_add_priority_column())


def test_migrate_block_priority_skips_missing_table():
    asyncio.run(_priority_skips_missing_table())
