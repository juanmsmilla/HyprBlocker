"""Tests for core blocking logic: URL/app pattern matching and rule parsing."""

import pytest

from daemon.blocker import (
    AppBlocker,
    SiteBlocker,
    is_catch_all_pattern,
    is_protected_url,
    parse_rules_from_text,
)


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
            "www.youtube.com/shorts",  # subdomains match on path patterns
            "youtube.com/shorts?feature=share",  # query string after the path
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
            "youtube.com/shortsfilm",  # prefix of the path segment, not a subpath
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

    def test_catch_all_matches_every_http_site(self):
        assert is_catch_all_pattern("*")
        assert is_catch_all_pattern(" * ")
        assert is_catch_all_pattern("https://*")
        assert not is_catch_all_pattern("http*")
        assert not is_catch_all_pattern("*.reddit.com")
        assert SiteBlocker.url_matches_pattern("https://example.com/foo", "*")
        assert SiteBlocker.url_matches_pattern("example.com", "*")
        assert SiteBlocker.url_matches_pattern("www.news.example.com/a", "*")

    def test_catch_all_rejects_internals_and_loopback(self):
        assert not SiteBlocker.url_matches_pattern("chrome://extensions", "*")
        assert not SiteBlocker.url_matches_pattern("chrome-extension://abc/page.html", "*")
        assert not SiteBlocker.url_matches_pattern("about:blank", "*")
        assert not SiteBlocker.url_matches_pattern("edge://settings", "*")
        assert not SiteBlocker.url_matches_pattern("http://127.0.0.1:8765/api", "*")
        assert not SiteBlocker.url_matches_pattern("http://localhost:8765/", "*")
        assert not SiteBlocker.url_matches_pattern("127.0.0.1:8765", "*")
        assert not SiteBlocker.url_matches_pattern("localhost", "*")
        assert not SiteBlocker.url_matches_pattern("example.com", "http*")

    def test_protected_url_helper(self):
        assert is_protected_url("chrome://extensions")
        assert is_protected_url("http://127.0.0.1:8765/api")
        assert is_protected_url("localhost")
        assert not is_protected_url("https://example.com/")
        assert not is_protected_url("reddit.com")


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

    def test_catch_all_blocks_every_site_except_allows(self):
        assert self.blocker.should_block_url("https://example.com/", ["*"], ["openai.com"])
        assert self.blocker.should_block_url("news.ycombinator.com", ["*"], ["openai.com"])
        assert not self.blocker.should_block_url("https://openai.com/", ["*"], ["openai.com"])
        assert not self.blocker.should_block_url("https://chat.openai.com/", ["*"], ["openai.com"])

    def test_catch_all_never_blocks_internals_or_daemon(self):
        assert not self.blocker.should_block_url("chrome://extensions", ["*"], [])
        assert not self.blocker.should_block_url("chrome-extension://abc/blocked.html", ["*"], [])
        assert not self.blocker.should_block_url("about:blank", ["*"], [])
        assert not self.blocker.should_block_url("http://127.0.0.1:8765/api", ["*"], [])
        assert not self.blocker.should_block_url("http://localhost:8765/", ["*"], [])

    def test_catch_all_with_specific_hosts_still_blocks_everything(self):
        assert self.blocker.should_block_url("https://example.com/", ["*", "reddit.com"], [])

    def test_without_catch_all_host_patterns_unchanged(self):
        assert self.blocker.should_block_url("reddit.com", ["reddit.com"], [])
        assert not self.blocker.should_block_url("example.com", ["reddit.com"], [])


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
