"""Tests for tier-1 allowlist mutation planning (daemon.grants.tier1)."""

from datetime import UTC, datetime, timedelta

from daemon.grants import tier1
from tests.conftest import make_block

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


class TestNormalizeUrlPattern:
    def test_strips_scheme_case_and_trailing_slash(self):
        assert tier1.normalize_url_pattern("https://Reddit.com/") == "reddit.com"

    def test_keeps_path(self):
        assert tier1.normalize_url_pattern("https://youtube.com/shorts/") == "youtube.com/shorts"

    def test_bare_domain_untouched(self):
        assert tier1.normalize_url_pattern("reddit.com") == "reddit.com"


class TestMatchingActiveBlocks:
    def test_matches_by_block_pattern(self):
        social = make_block(id=1, websites_blocked="reddit.com\ntwitter.com")
        news = make_block(id=2, websites_blocked="news.ycombinator.com")
        assert tier1.matching_active_blocks("reddit.com", [social, news]) == [social]

    def test_subdomain_matches(self):
        block = make_block(websites_blocked="reddit.com")
        assert tier1.matching_active_blocks("old.reddit.com", [block]) == [block]

    def test_disabled_block_skipped(self):
        block = make_block(websites_blocked="reddit.com", enabled=False)
        assert tier1.matching_active_blocks("reddit.com", [block]) == []


class TestPlanAllowlistGrant:
    def test_intersection_semantics_every_matching_block_mutated(self):
        # Two overlapping blocks both block reddit — the grant must hit BOTH,
        # or intersection semantics make it a no-op.
        focus = make_block(id=1, name="focus", websites_blocked="reddit.com\nyoutube.com")
        social = make_block(id=2, name="social", websites_blocked="*.reddit.com\nreddit.com")
        other = make_block(id=3, name="other", websites_blocked="twitter.com")
        plan = tier1.plan_allowlist_grant("https://reddit.com", [focus, social, other], 30, NOW)
        assert {m.block_id for m in plan.mutations} == {1, 2}
        for mutation in plan.mutations:
            assert "reddit.com" in mutation.new_websites_allowed.splitlines()

    def test_preserves_existing_allow_entries(self):
        block = make_block(websites_blocked="reddit.com", websites_allowed="reddit.com/r/programming")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 30, NOW)
        lines = plan.mutations[0].new_websites_allowed.splitlines()
        assert lines == ["reddit.com/r/programming", "reddit.com"]

    def test_already_allowed_block_skipped(self):
        block = make_block(websites_blocked="reddit.com", websites_allowed="reddit.com")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 30, NOW)
        assert plan.is_empty

    def test_no_matching_block_gives_empty_plan(self):
        block = make_block(websites_blocked="twitter.com")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 30, NOW)
        assert plan.is_empty

    def test_expiry_time(self):
        block = make_block(websites_blocked="reddit.com")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 45, NOW)
        assert plan.expires_at == NOW + timedelta(minutes=45)

    def test_minutes_clamped(self):
        block = make_block(websites_blocked="reddit.com")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 10_000, NOW)
        assert plan.expires_at <= NOW + timedelta(minutes=tier1.MAX_GRANT_MINUTES)
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 0, NOW)
        assert plan.expires_at == NOW + timedelta(minutes=1)

    def test_url_normalized_into_pattern(self):
        block = make_block(websites_blocked="reddit.com")
        plan = tier1.plan_allowlist_grant("HTTPS://Reddit.com/", [block], 30, NOW)
        assert plan.pattern == "reddit.com"


class TestPlanAllowlistExpiry:
    def test_removes_only_granted_pattern(self):
        block = make_block(id=1, websites_allowed="reddit.com/r/programming\nreddit.com")
        mutations = tier1.plan_allowlist_expiry("reddit.com", [block])
        assert len(mutations) == 1
        assert mutations[0].new_websites_allowed == "reddit.com/r/programming"

    def test_blocks_without_pattern_untouched(self):
        block = make_block(websites_allowed="twitter.com")
        assert tier1.plan_allowlist_expiry("reddit.com", [block]) == ()

    def test_scans_disabled_blocks_too(self):
        # A block whose schedule ended must still shed the temporary entry.
        block = make_block(websites_allowed="reddit.com", enabled=False)
        assert len(tier1.plan_allowlist_expiry("reddit.com", [block])) == 1

    def test_grant_then_expiry_roundtrip(self):
        block = make_block(id=1, websites_blocked="reddit.com", websites_allowed="docs.reddit.com")
        plan = tier1.plan_allowlist_grant("reddit.com", [block], 30, NOW)
        mutated = make_block(
            id=1,
            websites_blocked="reddit.com",
            websites_allowed=plan.mutations[0].new_websites_allowed,
        )
        expiry = tier1.plan_allowlist_expiry(plan.pattern, [mutated])
        assert expiry[0].new_websites_allowed == "docs.reddit.com"
