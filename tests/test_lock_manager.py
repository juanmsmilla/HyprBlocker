"""Tests for per-block lock logic and expired-lock cleanup."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import daemon.time_verifier as time_verifier_module
from daemon.database import Base, Block
from daemon.lock_manager import LockManager


class StubTimeVerifier:
    """Returns the system clock without any NTP traffic."""

    def get_verified_time(self):
        return datetime.now()


@pytest.fixture(autouse=True)
def stub_time_verifier(monkeypatch):
    monkeypatch.setattr(time_verifier_module, "_verifier", StubTimeVerifier())


def make_block(**overrides):
    defaults = {
        "id": 1,
        "enabled": True,
        "lock_mode": "locked_until",
        "lock_until": datetime.now() + timedelta(hours=1),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


NOW = datetime.now()


class TestIsBlockLocked:
    def setup_method(self):
        self.manager = LockManager(get_blocks_func=None)

    def test_locked_until_future_is_locked(self):
        assert self.manager._is_block_locked(make_block(), NOW) is True

    def test_locked_until_past_is_not_locked(self):
        block = make_block(lock_until=NOW - timedelta(hours=1))
        assert self.manager._is_block_locked(block, NOW) is False

    def test_lock_mode_none_is_not_locked(self):
        block = make_block(lock_mode="none")
        assert self.manager._is_block_locked(block, NOW) is False

    def test_disabled_block_is_not_locked(self):
        block = make_block(enabled=False)
        assert self.manager._is_block_locked(block, NOW) is False

    def test_locked_until_without_datetime_is_not_locked(self):
        block = make_block(lock_until=None)
        assert self.manager._is_block_locked(block, NOW) is False


class TestIsBlockLockedById:
    def test_finds_block_by_id(self):
        blocks = [make_block(id=1, lock_mode="none"), make_block(id=2)]

        async def get_blocks():
            return blocks

        manager = LockManager(get_blocks)
        assert asyncio.run(manager.is_block_locked(1)) is False
        assert asyncio.run(manager.is_block_locked(2)) is True

    def test_unknown_id_is_not_locked(self):
        async def get_blocks():
            return []

        manager = LockManager(get_blocks)
        assert asyncio.run(manager.is_block_locked(42)) is False


class TestCheckTransitions:
    def test_expired_locks_are_reset(self):
        async def _run():
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            async with factory() as session:
                session.add(
                    Block(
                        name="expired",
                        lock_mode="locked_until",
                        lock_until=datetime.now() - timedelta(hours=1),
                    )
                )
                session.add(
                    Block(
                        name="still-locked",
                        lock_mode="locked_until",
                        lock_until=datetime.now() + timedelta(hours=1),
                    )
                )
                await session.commit()

            manager = LockManager(get_blocks_func=None, session_factory=factory)
            await manager.check_transitions()

            async with factory() as session:
                result = await session.execute(select(Block).order_by(Block.name))
                blocks = {b.name: b for b in result.scalars().all()}

            await engine.dispose()
            return blocks

        blocks = asyncio.run(_run())
        assert blocks["expired"].lock_mode == "none"
        assert blocks["expired"].lock_until is None
        assert blocks["still-locked"].lock_mode == "locked_until"
        assert blocks["still-locked"].lock_until is not None

    def test_no_session_factory_is_a_noop(self):
        manager = LockManager(get_blocks_func=None, session_factory=None)
        # Must not raise
        asyncio.run(manager.check_transitions())
