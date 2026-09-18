"""API tests for block CRUD, per-block lock enforcement, and stricter-rules endpoints.

Runs the real FastAPI app against an in-memory SQLite database. NTP time
verification is stubbed out so no network traffic happens in tests.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import daemon.time_verifier as time_verifier_module
from daemon.api import app, set_session_factory
from daemon.api.routes.blocks import _is_loosening_update
from daemon.api.schemas import BlockUpdate
from daemon.database import Base, Block
from daemon.lock_manager import init_lock_manager
from tests.conftest import make_block


class StubTimeVerifier:
    """Trusts the system clock; never touches the network."""

    def __init__(self, valid=True):
        self.valid = valid

    def get_verified_time(self):
        return datetime.now()

    def is_system_time_valid(self):
        return self.valid

    def verify_at_lock_transitions(self):
        return self.valid


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(time_verifier_module, "_verifier", StubTimeVerifier())

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_all_blocks():
        async with factory() as session:
            result = await session.execute(select(Block))
            return list(result.scalars().all())

    init_lock_manager(get_all_blocks, factory)
    set_session_factory(factory)

    @asynccontextmanager
    async def test_lifespan(app):
        # Create tables inside the TestClient's event loop so the aiosqlite
        # connection (and the in-memory database it holds) stays on one loop.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    previous_lifespan = app.router.lifespan_context
    app.router.lifespan_context = test_lifespan
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.router.lifespan_context = previous_lifespan


def block_payload(**overrides):
    payload = {
        "name": "Focus",
        "block_mode": "always",
        "websites_blocked": "youtube.com\nreddit.com",
        "websites_allowed": "reddit.com/r/programming",
        "websites_media_blocked": "twitch.tv",
        "apps_blocked": "steam",
    }
    payload.update(overrides)
    return payload


def create_block(client, **overrides):
    response = client.post("/api/blocks", json=block_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()


def iso_in(hours):
    return (datetime.now() + timedelta(hours=hours)).replace(microsecond=0).isoformat()


class TestBlockCrud:
    def test_create_returns_block_with_defaults(self, client):
        block = create_block(client)
        assert block["id"] == 1
        assert block["name"] == "Focus"
        assert block["block_mode"] == "always"
        assert block["lock_mode"] == "none"
        assert block["enabled"] is True
        assert block["websites_media_blocked"] == "twitch.tv"

    def test_create_media_only_block(self, client):
        block = create_block(
            client,
            websites_blocked="",
            websites_media_blocked="youtube.com",
        )
        assert block["websites_blocked"] == ""
        assert block["websites_media_blocked"] == "youtube.com"

    def test_create_rejects_invalid_block_mode(self, client):
        response = client.post("/api/blocks", json=block_payload(block_mode="sometimes"))
        assert response.status_code == 400

    def test_create_rejects_invalid_lock_mode(self, client):
        response = client.post("/api/blocks", json=block_payload(lock_mode="forever"))
        assert response.status_code == 400

    def test_create_rejects_malformed_lock_until(self, client):
        response = client.post(
            "/api/blocks",
            json=block_payload(lock_mode="locked_until", lock_until="not-a-date"),
        )
        assert response.status_code == 400

    def test_list_returns_created_blocks(self, client):
        create_block(client, name="One")
        create_block(client, name="Two")
        response = client.get("/api/blocks")
        assert response.status_code == 200
        assert [b["name"] for b in response.json()] == ["One", "Two"]

    def test_update_changes_fields(self, client):
        block = create_block(client)
        response = client.put(
            f"/api/blocks/{block['id']}",
            json={"name": "Renamed", "websites_blocked": "news.ycombinator.com"},
        )
        assert response.status_code == 200
        updated = response.json()
        assert updated["name"] == "Renamed"
        assert updated["websites_blocked"] == "news.ycombinator.com"

    def test_update_media_blocked_list(self, client):
        block = create_block(client)
        response = client.put(
            f"/api/blocks/{block['id']}",
            json={"websites_media_blocked": "youtube.com\nreddit.com"},
        )
        assert response.status_code == 200
        assert set(response.json()["websites_media_blocked"].split("\n")) == {
            "youtube.com",
            "reddit.com",
        }

    def test_update_missing_block_returns_404(self, client):
        response = client.put("/api/blocks/999", json={"name": "Ghost"})
        assert response.status_code == 404

    def test_delete_removes_block(self, client):
        block = create_block(client)
        response = client.delete(f"/api/blocks/{block['id']}")
        assert response.status_code == 200
        assert client.get("/api/blocks").json() == []


class TestLockEnforcement:
    def test_locked_block_rejects_update(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.put(f"/api/blocks/{block['id']}", json={"name": "Sneaky rename"})
        assert response.status_code == 403

    def test_locked_block_rejects_delete(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.delete(f"/api/blocks/{block['id']}")
        assert response.status_code == 403

    def test_expired_lock_allows_update(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(-2))
        response = client.put(f"/api/blocks/{block['id']}", json={"name": "Renamed"})
        assert response.status_code == 200

    def test_disabled_block_is_not_locked(self, client):
        block = create_block(
            client, enabled=False, lock_mode="locked_until", lock_until=iso_in(2)
        )
        response = client.put(f"/api/blocks/{block['id']}", json={"name": "Renamed"})
        assert response.status_code == 200

    def test_lock_status_endpoint(self, client):
        locked = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        unlocked = create_block(client, name="Open")
        assert client.get(f"/api/blocks/{locked['id']}/lock-status").json() == {"locked": True}
        assert client.get(f"/api/blocks/{unlocked['id']}/lock-status").json() == {"locked": False}


class TestStrictUpdates:
    """/api/blocks/{id}/strict may only make a block MORE restrictive."""

    def test_strict_update_works_while_locked(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"websites_blocked_add": "twitter.com"},
        )
        assert response.status_code == 200
        blocked = response.json()["websites_blocked"].split("\n")
        assert set(blocked) == {"youtube.com", "reddit.com", "twitter.com"}

    def test_strict_update_merges_instead_of_replacing(self, client):
        block = create_block(client)
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"websites_blocked_add": "twitter.com\nyoutube.com"},
        )
        blocked = set(response.json()["websites_blocked"].split("\n"))
        # Existing entries survive; duplicates are not repeated
        assert blocked == {"youtube.com", "reddit.com", "twitter.com"}

    def test_strict_update_removes_from_allow_list(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"websites_allowed_remove": "reddit.com/r/programming"},
        )
        assert response.status_code == 200
        assert response.json()["websites_allowed"] is None

    def test_strict_update_ignores_loosening_fields(self, client):
        """Attempts to replace the block list wholesale are ignored by the schema."""
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"websites_blocked": "", "websites_allowed": "everything.com"},
        )
        assert response.status_code == 200
        result = response.json()
        assert set(result["websites_blocked"].split("\n")) == {"youtube.com", "reddit.com"}
        assert result["websites_allowed"] == "reddit.com/r/programming"

    def test_strict_update_adds_apps(self, client):
        block = create_block(client)
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"apps_blocked_add": "lutris"},
        )
        assert set(response.json()["apps_blocked"].split("\n")) == {"steam", "lutris"}

    def test_strict_update_adds_media_blocked(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.patch(
            f"/api/blocks/{block['id']}/strict",
            json={"websites_media_blocked_add": "youtube.com"},
        )
        assert response.status_code == 200
        media = response.json()["websites_media_blocked"].split("\n")
        assert set(media) == {"twitch.tv", "youtube.com"}


class TestExtendLock:
    def test_extend_lock_pushes_expiry_later(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        response = client.patch(
            f"/api/blocks/{block['id']}/extend-lock", json={"lock_until": iso_in(5)}
        )
        assert response.status_code == 200
        assert response.json()["lock_until"] == iso_in(5)

    def test_extend_lock_cannot_shorten(self, client):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(5))
        response = client.patch(
            f"/api/blocks/{block['id']}/extend-lock", json={"lock_until": iso_in(2)}
        )
        assert response.status_code == 400

    def test_extend_lock_requires_existing_lock(self, client):
        block = create_block(client)
        response = client.patch(
            f"/api/blocks/{block['id']}/extend-lock", json={"lock_until": iso_in(5)}
        )
        assert response.status_code == 400

    def test_extend_lock_rejected_when_time_manipulated(self, client, monkeypatch):
        block = create_block(client, lock_mode="locked_until", lock_until=iso_in(2))
        monkeypatch.setattr(
            time_verifier_module, "_verifier", StubTimeVerifier(valid=False)
        )
        response = client.patch(
            f"/api/blocks/{block['id']}/extend-lock", json={"lock_until": iso_in(5)}
        )
        assert response.status_code == 403


class TestMediaListLoosening:
    def test_shrinking_media_list_is_loosening(self):
        db = make_block(websites_media_blocked="youtube.com\nreddit.com")
        update = BlockUpdate(websites_media_blocked="youtube.com")
        assert _is_loosening_update(db, update)

    def test_growing_media_list_is_not_loosening(self):
        db = make_block(websites_media_blocked="youtube.com")
        update = BlockUpdate(websites_media_blocked="youtube.com\nreddit.com")
        assert not _is_loosening_update(db, update)
