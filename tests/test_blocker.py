"""Tests for core blocking logic: URL/app pattern matching and rule parsing."""

import pytest
from blocker import AppBlocker, SiteBlocker, parse_rules_from_text


class TestParseRulesFromText:
    def test_none_returns_empty_list(self):
        assert parse_rules_from_text(None) == []

    def test_empty_string_returns_empty_list(self):
        assert parse_rules_from_text("") == []

    def test_single_rule(self):
        assert parse_rules_from_text("reddit.com") == ["reddit.com"]

    def test_multiple_rules(self):
        text = "reddit.com\nyoutube.com\ntwitter.com"
        assert parse_rules_from_text(text) == ["reddit.com", "youtube.com", "twitter.com"]

    def test_strips_whitespace_and_skips_blank_lines(self):
        text = "  reddit.com  \n\n   \nyoutube.com\n"
        assert parse_rules_from_text(text) == ["reddit.com", "youtube.com"]


class TestUrlMatchesPattern:
    """Tests for SiteBlocker.url_matches_pattern.

    Documented behavior:
    - reddit.com          -> matches reddit.com, subdomains, and all paths
    - youtube.com/shorts  -> matches only that path (and subpaths)
    - *.reddit.com        -> matches all subdomains
    """

    # --- Domain-only patterns ---

    @pytest.mark.parametrize(
        "url",
        [
            "reddit.com",
            "reddit.com/",
            "reddit.com/r/programming",
            "www.reddit.com",
            "old.reddit.com",
            "old.reddit.com/r/linux",
            "https://reddit.com",
            "https://www.reddit.com/r/all",
            "REDDIT.COM",
        ],
    )
    def test_domain_pattern_matches(self, url):
        assert SiteBlocker.url_matches_pattern(url, "reddit.com")

    @pytest.mark.parametrize(
        "url",
        [
            "notreddit.com",
            "reddit.com.evil.com",
            "example.com/reddit.com",
            "example.com",
        ],
    )
    def test_domain_pattern_rejects(self, url):
        assert not SiteBlocker.url_matches_pattern(url, "reddit.com")

    # --- Path-specific patterns ---

    @pytest.mark.parametrize(
        "url",
        [
            "youtube.com/shorts",
            "youtube.com/shorts/abc123",
            "https://youtube.com/shorts",
        ],
    )
    def test_path_pattern_matches(self, url):
        assert SiteBlocker.url_matches_pattern(url, "youtube.com/shorts")

    @pytest.mark.parametrize(
        "url",
        [
            "youtube.com",
            "youtube.com/watch?v=abc",
            "youtube.com/feed",
        ],
    )
    def test_path_pattern_rejects_other_paths(self, url):
        assert not SiteBlocker.url_matches_pattern(url, "youtube.com/shorts")

    # --- Wildcard subdomain patterns ---

    @pytest.mark.parametrize(
        "url",
        [
            "old.reddit.com",
            "www.reddit.com",
            "a.b.reddit.com",
            "reddit.com",  # wildcard also matches the bare domain
        ],
    )
    def test_wildcard_pattern_matches(self, url):
        assert SiteBlocker.url_matches_pattern(url, "*.reddit.com")

    @pytest.mark.parametrize(
        "url",
        [
            "notreddit.com",
            "reddit.com.evil.com",
        ],
    )
    def test_wildcard_pattern_rejects(self, url):
        assert not SiteBlocker.url_matches_pattern(url, "*.reddit.com")

    # --- Normalization ---

    def test_protocol_stripped_from_pattern(self):
        assert SiteBlocker.url_matches_pattern("reddit.com", "https://reddit.com")

    def test_case_insensitive(self):
        assert SiteBlocker.url_matches_pattern("WWW.Reddit.COM", "reddit.com")

    def test_whitespace_stripped(self):
        assert SiteBlocker.url_matches_pattern("  reddit.com  ", " reddit.com ")


class TestShouldBlockUrl:
    def setup_method(self):
        self.blocker = SiteBlocker()

    def test_blocked_pattern_blocks(self):
        assert self.blocker.should_block_url("reddit.com", ["reddit.com"], [])

    def test_unlisted_url_not_blocked(self):
        assert not self.blocker.should_block_url("example.com", ["reddit.com"], [])

    def test_allow_list_takes_precedence(self):
        assert not self.blocker.should_block_url(
            "reddit.com/r/programming",
            blocked=["reddit.com"],
            allowed=["reddit.com/r/programming"],
        )

    def test_allow_list_only_exempts_matching_paths(self):
        assert self.blocker.should_block_url(
            "reddit.com/r/funny",
            blocked=["reddit.com"],
            allowed=["reddit.com/r/programming"],
        )

    def test_empty_lists_block_nothing(self):
        assert not self.blocker.should_block_url("reddit.com", [], [])


class TestAppMatchesPattern:
    @pytest.mark.parametrize(
        ("app_class", "pattern"),
        [
            ("steam", "steam"),  # exact
            ("Steam", "steam"),  # case-insensitive
            ("steam_app_123456", "steam"),  # partial
            ("discord", "*disc*"),  # glob
            ("org.telegram.desktop", "telegram"),  # partial within reverse-DNS class
        ],
    )
    def test_matches(self, app_class, pattern):
        assert AppBlocker.matches_pattern(app_class, pattern)

    @pytest.mark.parametrize(
        ("app_class", "pattern"),
        [
            ("firefox", "steam"),
            ("stea", "steam"),  # substring of pattern is not a match
        ],
    )
    def test_rejects(self, app_class, pattern):
        assert not AppBlocker.matches_pattern(app_class, pattern)


class TestShouldBlockApp:
    def setup_method(self):
        self.blocker = AppBlocker()

    def test_blocked_app(self):
        assert self.blocker.should_block_app("steam", ["steam"], [])

    def test_allow_list_takes_precedence(self):
        assert not self.blocker.should_block_app("steam", ["steam"], ["steam"])

    def test_unlisted_app_not_blocked(self):
        assert not self.blocker.should_block_app("firefox", ["steam"], [])
