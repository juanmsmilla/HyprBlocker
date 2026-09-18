"""Core blocking logic for the website blocker daemon."""

import fnmatch
import logging

from daemon.scheduler import get_scheduler

logger = logging.getLogger(__name__)

# Browser internals + loopback: never apply catch-all `*`, and never block
# these URLs so the daemon / extension / chrome:// pages keep working.
PROTECTED_SCHEMES = frozenset(
    {
        "chrome",
        "chrome-extension",
        "about",
        "edge",
        "brave",
        "opera",
        "vivaldi",
        "moz-extension",
        "devtools",
        "view-source",
    }
)
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def parse_rules_from_text(text: str | None) -> list[str]:
    """Parse newline-separated rules from text field."""
    if not text:
        return []
    return [line.strip() for line in text.split('\n') if line.strip()]


def _normalize_website_pattern(pattern: str) -> str:
    """Strip http(s) scheme and trailing slash; lowercase. Leaves `*` intact."""
    pattern = (pattern or "").lower().strip()
    if pattern.startswith("https://"):
        pattern = pattern[8:]
    elif pattern.startswith("http://"):
        pattern = pattern[7:]
    return pattern.rstrip("/")


def is_catch_all_pattern(pattern: str) -> bool:
    """Literal `*` (optionally with an http(s) scheme) is the catch-all."""
    return _normalize_website_pattern(pattern) == "*"


def _hostname_only(host_port: str) -> str:
    host = (host_port or "").lower()
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[1:end]
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def hostname_is_loopback(hostname: str) -> bool:
    host = (hostname or "").lower()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    return host in LOOPBACK_HOSTS


def is_protected_url(url: str) -> bool:
    """True for browser internals and loopback (incl. daemon :8765).

    Fail open: these must stay reachable. Unparseable / empty URLs are
    treated as protected.
    """
    raw = (url or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    if lower.startswith("about:"):
        return True

    rest = raw
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if scheme.lower() in PROTECTED_SCHEMES:
            return True
    elif ":" in raw.split("/", 1)[0] and lower.split(":", 1)[0] in PROTECTED_SCHEMES:
        return True

    host = _hostname_only(rest.split("/")[0].split("?")[0].split("#")[0])
    return hostname_is_loopback(host)


def _catch_all_matches(url: str) -> bool:
    """`*` matches every http(s) page except internals and loopback."""
    raw = (url or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if lower.startswith("about:"):
        return False

    rest = raw
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if scheme.lower() not in ("http", "https"):
            return False
    elif ":" in raw.split("/", 1)[0]:
        maybe_scheme = lower.split(":", 1)[0]
        if maybe_scheme in PROTECTED_SCHEMES:
            return False

    host = _hostname_only(rest.split("/")[0].split("?")[0].split("#")[0])
    if not host or hostname_is_loopback(host):
        return False
    return True


class SiteBlocker:
    """Handles website blocking logic and pattern matching."""

    @staticmethod
    def url_matches_pattern(url: str, pattern: str) -> bool:
        """Check if URL matches blocking pattern.

        Supports:
        - Catch-all: * matches every http(s) site (not internals / loopback)
        - Domain matching: reddit.com matches www.reddit.com and reddit.com/anything
        - Path-specific: youtube.com/shorts only matches that specific path
        - Wildcard subdomains: *.reddit.com matches all subdomains

        Args:
            url: The URL to check (can include path)
            pattern: The blocking pattern

        Returns:
            bool: True if URL matches the pattern
        """
        if is_catch_all_pattern(pattern):
            return _catch_all_matches(url)

        # Remove protocol if present
        url = url.split('://')[-1] if '://' in url else url
        pattern = pattern.split('://')[-1] if '://' in pattern else pattern

        url = url.lower().strip()
        pattern = pattern.lower().strip()

        # Handle wildcard subdomains
        if pattern.startswith('*.'):
            base_domain = pattern[2:]
            url_domain = url.split('/')[0]
            return url_domain == base_domain or url_domain.endswith('.' + base_domain)

        # Check if pattern includes path
        if '/' in pattern:
            # Path-specific matching with subdomain support. Mirrors
            # matchesPatternWithPath in extension/matcher.js: the domain part
            # matches subdomains, and the path must match at a boundary (the
            # whole path, or a subpath starting with '/' or a query with '?')
            # so that "youtube.com/shorts" does not match "youtube.com/shortsfilm".
            if pattern.endswith('/'):
                pattern = pattern[:-1]
            if url.endswith('/'):
                url = url[:-1]

            pattern_domain, _, pattern_rest = pattern.partition('/')
            pattern_path = '/' + pattern_rest

            url_domain, _, url_rest = url.partition('/')
            url_path = '/' + url_rest

            domains_match = (
                url_domain == pattern_domain or url_domain.endswith('.' + pattern_domain)
            )
            paths_match = (
                url_path == pattern_path
                or url_path.startswith(pattern_path + '/')
                or url_path.startswith(pattern_path + '?')
            )
            return domains_match and paths_match
        else:
            # Domain-only pattern - match domain, subdomains, and all subpaths
            url_domain = url.split('/')[0]
            return (
                url_domain == pattern
                or url_domain.endswith('.' + pattern)
                or url.startswith(pattern + '/')
            )

    def should_block_url(self, url: str, blocked: list[str], allowed: list[str]) -> bool:
        """Check if URL should be blocked.

        Allow list takes precedence over block list. Browser internals and
        loopback fail open (never blocked) so the daemon stays reachable.

        Args:
            url: The URL to check
            blocked: List of blocked patterns
            allowed: List of allowed patterns

        Returns:
            bool: True if URL should be blocked
        """
        if is_protected_url(url):
            return False

        # Check if explicitly allowed
        for allow_pattern in allowed:
            if self.url_matches_pattern(url, allow_pattern):
                logger.debug(f"URL {url} explicitly allowed by pattern {allow_pattern}")
                return False  # Allowed, don't block

        # Check if blocked
        for block_pattern in blocked:
            if self.url_matches_pattern(url, block_pattern):
                logger.debug(f"URL {url} blocked by pattern {block_pattern}")
                return True  # Blocked

        return False  # Not in any list, don't block

    async def is_site_blocked(self, url: str) -> bool:
        """Check if a site is blocked using intersection-based allow logic.

        A URL is allowed only if:
        1. No active blocks would block it, OR
        2. It appears in the allow list of EVERY block that would block it

        Args:
            url: The URL to check (hostname or full URL)

        Returns:
            bool: True if blocked, False otherwise
        """
        if is_protected_url(url):
            return False

        scheduler = get_scheduler()
        if scheduler is None:
            return False

        active_blocks = await scheduler.get_active_blocks()

        # Find all blocks that would block this URL (ignoring allow lists)
        blocking_blocks = []

        for block in active_blocks:
            blocked_patterns = parse_rules_from_text(block.websites_blocked)

            # Check if this block's block patterns match the URL
            for pattern in blocked_patterns:
                if self.url_matches_pattern(url, pattern):
                    blocking_blocks.append(block)
                    break  # This block would block it, move to next block

        # If no blocks would block this URL, it's allowed
        if not blocking_blocks:
            logger.debug(f"URL {url} not blocked by any block")
            return False

        # Check if URL is in the allow list of EVERY blocking block
        for block in blocking_blocks:
            allowed_patterns = parse_rules_from_text(block.websites_allowed)

            # Check if this block's allow list contains the URL
            url_allowed_by_this_block = False
            for pattern in allowed_patterns:
                if self.url_matches_pattern(url, pattern):
                    url_allowed_by_this_block = True
                    break

            # If this blocking block doesn't allow the URL, it's blocked
            if not url_allowed_by_this_block:
                logger.debug(f"URL {url} blocked by block {block.id} ({block.name}) - not in allow list")
                return True

        # URL is in the allow list of ALL blocking blocks
        logger.debug(f"URL {url} allowed by all {len(blocking_blocks)} blocking blocks")
        return False

    async def get_blocked_sites(self) -> list[str]:
        """Get list of all currently blocked site patterns.

        Returns:
            List of blocked site patterns
        """
        scheduler = get_scheduler()
        if scheduler is None:
            return []

        active_blocks = await scheduler.get_active_blocks()
        all_blocked = []

        for block in active_blocks:
            all_blocked.extend(parse_rules_from_text(block.websites_blocked))

        return all_blocked


class AppBlocker:
    """Handles application blocking logic and pattern matching."""

    @staticmethod
    def matches_pattern(app_class: str, pattern: str) -> bool:
        """Check if an application class matches a blocking pattern.

        Args:
            app_class: The application window class
            pattern: The blocking pattern

        Returns:
            bool: True if the app matches the pattern
        """
        app_class = app_class.lower().strip()
        pattern = pattern.lower().strip()

        # Exact match
        if app_class == pattern:
            return True

        # Partial match
        if pattern in app_class:
            return True

        # Glob pattern matching
        if "*" in pattern or "?" in pattern:
            return fnmatch.fnmatch(app_class, pattern)

        return False

    def should_block_app(self, app_class: str, blocked: list[str], allowed: list[str]) -> bool:
        """Check if app should be blocked.

        Allow list takes precedence over block list.

        Args:
            app_class: The application window class
            blocked: List of blocked patterns
            allowed: List of allowed patterns

        Returns:
            bool: True if app should be blocked
        """
        # Check if explicitly allowed
        for allow_pattern in allowed:
            if self.matches_pattern(app_class, allow_pattern):
                logger.debug(f"App {app_class} explicitly allowed by pattern {allow_pattern}")
                return False  # Allowed, don't block

        # Check if blocked
        for block_pattern in blocked:
            if self.matches_pattern(app_class, block_pattern):
                logger.debug(f"App {app_class} blocked by pattern {block_pattern}")
                return True  # Blocked

        return False  # Not in any list, don't block

    async def is_app_blocked(self, app_class: str) -> bool:
        """Check if an application is blocked.

        An app is blocked if ANY active block has it in apps_blocked.

        Args:
            app_class: The application window class

        Returns:
            bool: True if blocked, False otherwise
        """
        scheduler = get_scheduler()
        if scheduler is None:
            return False

        active_blocks = await scheduler.get_active_blocks()

        for block in active_blocks:
            blocked_patterns = parse_rules_from_text(block.apps_blocked)

            for pattern in blocked_patterns:
                if self.matches_pattern(app_class, pattern):
                    logger.debug(f"App {app_class} blocked by block {block.id} ({block.name})")
                    return True

        logger.debug(f"App {app_class} not blocked by any block")
        return False

    async def get_blocked_apps(self) -> list[str]:
        """Get list of all currently blocked application patterns.

        Returns:
            List of blocked app patterns
        """
        scheduler = get_scheduler()
        if scheduler is None:
            return []

        active_blocks = await scheduler.get_active_blocks()
        all_blocked = []

        for block in active_blocks:
            all_blocked.extend(parse_rules_from_text(block.apps_blocked))

        return all_blocked


# Global blocker instances
_site_blocker: SiteBlocker | None = None
_app_blocker: AppBlocker | None = None


def get_site_blocker() -> SiteBlocker:
    """Get the global site blocker instance."""
    global _site_blocker
    if _site_blocker is None:
        _site_blocker = SiteBlocker()
    return _site_blocker


def get_app_blocker() -> AppBlocker:
    """Get the global app blocker instance."""
    global _app_blocker
    if _app_blocker is None:
        _app_blocker = AppBlocker()
    return _app_blocker
