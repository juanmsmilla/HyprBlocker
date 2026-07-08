/**
 * HyprBlocker - URL pattern matching.
 *
 * Loaded by the service worker via importScripts() and by the bun test
 * suite via require(). This logic mirrors SiteBlocker.url_matches_pattern
 * in daemon/blocker.py — if you change matching behavior here, change it
 * there too (extension/matcher.test.js guards against drift).
 */

/**
 * Check if hostname matches a blocking pattern
 */
function matchesPattern(hostname, pattern) {
    hostname = hostname.toLowerCase();
    pattern = pattern.toLowerCase();

    // Remove protocol if present
    if (pattern.startsWith('http://')) {
        pattern = pattern.substring(7);
    } else if (pattern.startsWith('https://')) {
        pattern = pattern.substring(8);
    }

    // Remove trailing slash and path
    pattern = pattern.split('/')[0];

    // Exact match
    if (hostname === pattern) {
        return true;
    }

    // Wildcard subdomain (*.example.com)
    if (pattern.startsWith('*.')) {
        const domain = pattern.substring(2);
        return hostname === domain || hostname.endsWith('.' + domain);
    }

    // Subdomain match (example.com matches www.example.com)
    if (hostname.endsWith('.' + pattern)) {
        return true;
    }

    return false;
}

/**
 * Check if URL (with path) matches a pattern
 * Supports:
 * - Domain matching: reddit.com matches www.reddit.com and reddit.com/anything
 * - Path-specific: youtube.com/shorts only matches that specific path
 * - Wildcard subdomains: *.reddit.com matches all subdomains
 */
function matchesPatternWithPath(urlPath, pattern) {
    urlPath = urlPath.toLowerCase();
    pattern = pattern.toLowerCase();

    // Remove protocol if present
    if (pattern.startsWith('http://')) {
        pattern = pattern.substring(7);
    } else if (pattern.startsWith('https://')) {
        pattern = pattern.substring(8);
    }

    // Remove trailing slash from pattern
    if (pattern.endsWith('/')) {
        pattern = pattern.slice(0, -1);
    }

    // Remove trailing slash from urlPath
    if (urlPath.endsWith('/')) {
        urlPath = urlPath.slice(0, -1);
    }

    // Handle wildcard subdomains (*.example.com)
    if (pattern.startsWith('*.')) {
        const domain = pattern.substring(2);
        const hostname = urlPath.split('/')[0];
        return hostname === domain || hostname.endsWith('.' + domain);
    }

    // Check if pattern includes path
    if (pattern.includes('/')) {
        // Path-specific matching with subdomain support
        // Split pattern into domain and path parts
        const patternParts = pattern.split('/');
        const patternDomain = patternParts[0];
        const patternPath = '/' + patternParts.slice(1).join('/');

        // Split URL into domain and path parts
        const urlParts = urlPath.split('/');
        const urlDomain = urlParts[0];
        const urlPathPart = '/' + urlParts.slice(1).join('/');

        // Check if domains match (with subdomain support like "www.twitch.tv" matches "twitch.tv")
        const domainsMatch = urlDomain === patternDomain ||
                            urlDomain.endsWith('.' + patternDomain);

        // Check if paths match (exact match or subpath)
        const pathsMatch = urlPathPart === patternPath ||
                          urlPathPart.startsWith(patternPath + '/') ||
                          urlPathPart.startsWith(patternPath + '?');

        return domainsMatch && pathsMatch;
    } else {
        // Domain-only pattern - match domain and all paths
        const hostname = urlPath.split('/')[0];
        const patternParts = pattern.split('/');
        const patternHostname = patternParts[0];

        // Exact hostname match or subdomain match
        return hostname === patternHostname ||
               hostname.endsWith('.' + patternHostname) ||
               urlPath.startsWith(patternHostname + '/');
    }
}

// Export for the bun test suite; the service worker gets these as globals
// via importScripts().
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { matchesPattern, matchesPatternWithPath };
}
