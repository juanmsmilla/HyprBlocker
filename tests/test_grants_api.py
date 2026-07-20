"""End-to-end grant API tests: request → judge (stubbed) → store → blocked-sites overlay.

Runs the real FastAPI app against in-memory SQLite. The judge client is stubbed,
so no network traffic occurs. Exercises the tier-1 flow and the M6 read-time
overlay, plus the fail-closed paths (denylist, judge unavailable).
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import daemon.time_verifier as time_verifier_module
from daemon.api import app, set_session_factory
from daemon.api.routes import grants as grants_route
from daemon.database import Base, Block
from daemon.lock_manager import init_lock_manager
from daemon.scheduler import init_scheduler


class _StubTimeVerifier:
    def get_verified_time(self):
        return datetime.now()

    def is_system_time_valid(self):
        return True

    def verify_at_lock_transitions(self):
        return True


class _StubJudge:
    """Returns a canned verdict JSON regardless of input."""

    def __init__(self, verdict: dict):
        self._verdict = verdict

    def chat(self, messages):
        return json.dumps(self._verdict)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(time_verifier_module, "_verifier", _StubTimeVerifier())
    # Point grant store + audit log at the isolated tmp state (conftest sets env,
    # but be explicit for the grants files).
    monkeypatch.setenv("HYPRBLOCKER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRBLOCKER_SECURE_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRBLOCKER_CONFIG_DIR", str(tmp_path))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_all_blocks():
        async with factory() as session:
            result = await session.execute(select(Block))
            return list(result.scalars().all())

    init_lock_manager(get_all_blocks, factory)
    init_scheduler(factory)
    set_session_factory(factory)

    @asynccontextmanager
    async def test_lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    previous = app.router.lifespan_context
    app.router.lifespan_context = test_lifespan
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.router.lifespan_context = previous


def _make_block(client, **overrides):
    payload = {
        "name": "Focus",
        "block_mode": "always",
        "websites_blocked": "youtube.com\nreddit.com",
        "websites_allowed": "",
    }
    payload.update(overrides)
    r = client.post("/api/blocks", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_allow_grant_flows_into_blocked_sites_overlay(client, monkeypatch):
    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge({"decision": "allow", "scope": "reddit.com", "minutes": 30, "reason": "work research"}),
    )
    _make_block(client)

    r = client.post("/api/grants/request", json={"url": "https://reddit.com", "reason": "work research", "minutes": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] == "allow"
    assert body["stage"] == "judge"
    assert body["expires_at"]

    # The grant overlays onto blocked-sites: reddit.com now in the block's allowed[].
    sites = client.get("/api/blocked-sites").json()
    focus = next(b for b in sites["blocks"] if b["name"] == "Focus")
    assert "reddit.com" in focus["allowed"]

    # And it shows up in the grants listing (enforced target == the judge scope).
    listed = client.get("/api/grants").json()
    assert len(listed["active"]) == 1
    assert listed["active"][0]["url"] == "reddit.com"


def test_judge_narrowing_is_enforced_not_the_whole_domain(client, monkeypatch):
    # Judge narrows a domain request to a single path — the overlay must grant
    # only the narrow path, never the whole domain (review finding).
    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge(
            {"decision": "allow", "scope": "reddit.com/r/python", "minutes": 30, "reason": "one subreddit"}
        ),
    )
    _make_block(client)
    client.post("/api/grants/request", json={"url": "reddit.com", "reason": "one subreddit", "minutes": 30})

    sites = client.get("/api/blocked-sites").json()
    focus = next(b for b in sites["blocks"] if b["name"] == "Focus")
    # The narrow path is granted; the bare domain is NOT.
    assert "reddit.com/r/python" in focus["allowed"]
    assert "reddit.com" not in focus["allowed"]


def test_judge_cannot_widen_beyond_request(client, monkeypatch):
    # A judge scope broader than the request is ignored; the request target wins.
    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge(
            {"decision": "allow", "scope": "reddit.com", "minutes": 30, "reason": "x"}
        ),
    )
    _make_block(client, websites_blocked="reddit.com")
    client.post(
        "/api/grants/request",
        json={"url": "reddit.com/r/python", "reason": "x", "minutes": 30},
    )
    listed = client.get("/api/grants").json()
    # Enforced target stays the (narrower) requested path, not the broad scope.
    assert listed["active"][0]["url"] == "reddit.com/r/python"


def test_deny_grant_does_not_create_overlay(client, monkeypatch):
    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge({"decision": "deny", "scope": "", "minutes": 0, "reason": "vague reason"}),
    )
    _make_block(client)
    r = client.post("/api/grants/request", json={"url": "https://reddit.com", "reason": "idk", "minutes": 30})
    assert r.json()["decision"] == "deny"
    sites = client.get("/api/blocked-sites").json()
    focus = next(b for b in sites["blocks"] if b["name"] == "Focus")
    assert "reddit.com" not in focus["allowed"]


def test_denylist_blocks_before_judge(client, monkeypatch):
    # Judge should never be consulted — set a client that would allow, prove it's not used.
    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge({"decision": "allow", "scope": "x", "minutes": 30, "reason": "x"}),
    )
    r = client.post(
        "/api/grants/request",
        json={"url": "https://example.com", "reason": "please disable enforcement for the daemon", "minutes": 30},
    )
    body = r.json()
    assert body["decision"] == "deny"
    assert body["stage"] == "denylist"


def test_judge_unavailable_denies_fail_closed(client, monkeypatch):
    monkeypatch.setattr(grants_route, "_judge_client", lambda: None)
    _make_block(client)
    r = client.post("/api/grants/request", json={"url": "https://reddit.com", "reason": "work", "minutes": 30})
    body = r.json()
    assert body["decision"] == "deny"


def test_grant_does_not_loosen_locked_block(client, monkeypatch):
    from datetime import timedelta

    monkeypatch.setattr(
        grants_route,
        "_judge_client",
        lambda: _StubJudge({"decision": "allow", "scope": "reddit.com", "minutes": 30, "reason": "work"}),
    )
    lock_until = (datetime.now() + timedelta(days=1)).isoformat()
    _make_block(client, lock_mode="locked_until", lock_until=lock_until)

    client.post("/api/grants/request", json={"url": "https://reddit.com", "reason": "work", "minutes": 30})
    sites = client.get("/api/blocked-sites").json()
    focus = next(b for b in sites["blocks"] if b["name"] == "Focus")
    # Locked block must not be loosened by the grant.
    assert "reddit.com" not in focus["allowed"]


def test_status_exposes_migration_fields(client):
    r = client.get("/api/status").json()
    assert r["layout"] == "user"
    assert r["enforcement_tier"] == "user"
    assert "dev_mode" in r
    assert "active_grants" in r


def test_breakglass_request_and_status(client):
    assert client.get("/api/grants/breakglass").json()["state"] == "idle"
    posted = client.post("/api/grants/breakglass").json()
    assert posted["state"] == "requested"
    assert client.get("/api/grants/breakglass").json()["state"] == "requested"
