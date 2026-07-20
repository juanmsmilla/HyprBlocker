"""Tests for the read-time grant overlay + store (daemon.grants.store, review M6)."""

from datetime import UTC, datetime, timedelta

from daemon.grants import store


def _blocks():
    return [
        {"id": 1, "name": "focus", "blocked": ["youtube.com", "reddit.com"], "allowed": []},
        {"id": 2, "name": "news", "blocked": ["reddit.com"], "allowed": ["reddit.com/r/python"]},
        {"id": 3, "name": "unrelated", "blocked": ["twitter.com"], "allowed": []},
    ]


def _grant(url, minutes=30, now=None):
    now = now or datetime.now(UTC)
    return store.make_active_grant(
        grant_id="g1",
        url=url,
        scope=url,
        reason="work",
        granted_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )


def test_overlay_adds_pattern_to_every_matching_block():
    now = datetime.now(UTC)
    grant = _grant("https://reddit.com", now=now)
    out = store.overlay_blocks(_blocks(), [grant], now)
    # reddit.com is blocked by blocks 1 and 2 → pattern added to both (intersection).
    assert "reddit.com" in out[0]["allowed"]
    assert "reddit.com" in out[1]["allowed"]
    # block 3 doesn't block reddit → untouched.
    assert out[2]["allowed"] == []
    # pre-existing allow entry preserved.
    assert "reddit.com/r/python" in out[1]["allowed"]


def test_overlay_skips_locked_blocks():
    now = datetime.now(UTC)
    grant = _grant("https://reddit.com", now=now)
    out = store.overlay_blocks(_blocks(), [grant], now, locked_block_ids={1})
    # block 1 is locked → grant must NOT loosen it.
    assert "reddit.com" not in out[0]["allowed"]
    # block 2 is not locked → still overlaid.
    assert "reddit.com" in out[1]["allowed"]


def test_expired_grant_is_not_overlaid():
    now = datetime.now(UTC)
    grant = _grant("https://reddit.com", minutes=30, now=now - timedelta(hours=2))
    out = store.overlay_blocks(_blocks(), [grant], now)
    assert out[0]["allowed"] == []
    assert out[1]["allowed"] == ["reddit.com/r/python"]


def test_overlay_does_not_mutate_input():
    now = datetime.now(UTC)
    blocks = _blocks()
    store.overlay_blocks(blocks, [_grant("https://reddit.com", now=now)], now)
    assert blocks[0]["allowed"] == []  # original untouched


def test_no_grants_returns_input_unchanged():
    now = datetime.now(UTC)
    blocks = _blocks()
    assert store.overlay_blocks(blocks, [], now) is blocks


def test_active_grants_filters_expired():
    now = datetime.now(UTC)
    live = _grant("https://a.com", minutes=30, now=now)
    dead = _grant("https://b.com", minutes=30, now=now - timedelta(hours=2))
    assert store.active_grants([live, dead], now) == [live]


def test_store_roundtrip_and_prune(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / "grants_active.json"
    live = _grant("https://a.com", minutes=30, now=now)
    store.save([live], path)
    assert len(store.load(path)) == 1
    # add an already-expired grant, then prune.
    dead = _grant("https://b.com", minutes=30, now=now - timedelta(hours=2))
    store.save([live, dead], path)
    removed = store.prune_expired(now, path)
    assert removed == 1
    assert [g.url for g in store.load(path)] == ["https://a.com"]


def test_parse_grants_skips_malformed():
    grants = store.parse_grants([{"bogus": 1}, "notadict", None])
    assert grants == []


def test_load_missing_file_is_empty(tmp_path):
    assert store.load(tmp_path / "absent.json") == []
