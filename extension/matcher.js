/**
 * HyprBlocker - URL pattern matching.
 *
 * Loaded by the service worker via importScripts() and by the bun test
 * suite via require(). This logic mirrors SiteBlocker.url_matches_pattern
 * in daemon/blocker.py — if you change matching behavior here, change it
 * there too (extension/matcher.test.js guards against drift).
 *
 * Literal `*` is a catch-all: every http(s) page except browser internals
 * (chrome:/chrome-extension:/about:/edge:/…) and loopback (localhost,
 * 127.0.0.1, ::1). If `*` appears alongside host patterns in the same list,
 * `*` dominates because it already matches every eligible URL.
 */

const PROTECTED_SCHEMES = [
    'chrome:',
    'chrome-extension:',
    'about:',
    'edge:',
    'brave:',
    'opera:',
    'vivaldi:',
    'moz-extension:',
    'devtools:',
    'view-source:',
];

const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '::1', '0.0.0.0'];

/**
 * Strip http(s) scheme and trailing slash; lowercase. Leaves `*` intact.
 */
function normalizeWebsitePattern(pattern) {
    pattern = String(pattern || '').toLowerCase().trim();
    if (pattern.startsWith('https://')) {
        pattern = pattern.substring(8);
    } else if (pattern.startsWith('http://')) {
        pattern = pattern.substring(7);
    }
    if (pattern.endsWith('/')) {
        pattern = pattern.slice(0, -1);
    }
    return pattern;
}

function isCatchAllPattern(pattern) {
    return normalizeWebsitePattern(pattern) === '*';
}

function hostnameIsLoopback(hostname) {
    let host = String(hostname || '').toLowerCase();
    if (host.startsWith('[') && host.includes(']')) {
        host = host.slice(1, host.indexOf(']'));
    }
    return LOOPBACK_HOSTS.indexOf(host) !== -1;
}

function stripHostPort(hostPort) {
    let host = String(hostPort || '').toLowerCase();
    if (!host) {
        return '';
    }
    if (host.startsWith('[')) {
        const end = host.indexOf(']');
        if (end !== -1) {
            return host.slice(1, end);
        }
    }
    const colonCount = (host.match(/:/g) || []).length;
    if (colonCount === 1) {
        return host.split(':')[0];
    }
    return host;
}

/**
 * True for chrome://, extension pages, about:, edge:, and loopback
 * (including the local daemon at 127.0.0.1:8765). Fail open: these must
 * stay reachable so the blocker itself keeps working.
 */
function isProtectedBrowserUrl(url) {
    const raw = String(url || '').trim();
    if (!raw) {
        return true;
    }
    const lower = raw.toLowerCase();
    if (lower.startsWith('about:')) {
        return true;
    }
    try {
        const href = lower.includes('://') || lower.startsWith('about:') ? raw : 'https://' + raw;
        const parsed = new URL(href);
        if (PROTECTED_SCHEMES.indexOf(parsed.protocol) !== -1) {
            return true;
        }
        if (hostnameIsLoopback(parsed.hostname)) {
            return true;
        }
        return false;
    } catch (error) {
        return true;
    }
}

function isHttpOrHttpsUrl(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:';
    } catch (error) {
        return false;
    }
}

/**
 * Catch-all `*` against a host/path string (with or without scheme).
 * http(s) only when a scheme is present; loopback never matches.
 */
function catchAllMatchesUrlPath(urlPath) {
    let path = String(urlPath || '').trim();
    if (!path) {
        return false;
    }
    const lower = path.toLowerCase();
    if (lower.startsWith('about:')) {
        return false;
    }
    if (lower.includes('://')) {
        const scheme = lower.split('://')[0];
        if (scheme !== 'http' && scheme !== 'https') {
            return false;
        }
        path = path.slice(path.indexOf('://') + 3);
    }
    const hostPort = path.split('/')[0].split('?')[0].split('#')[0];
    const hostname = stripHostPort(hostPort);
    if (!hostname || hostnameIsLoopback(hostname)) {
        return false;
    }
    return true;
}

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

    if (pattern === '*') {
        return Boolean(hostname) && !hostnameIsLoopback(hostname);
    }

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
 * - Catch-all: * matches every http(s) site (not internals / loopback)
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

    if (pattern === '*') {
        return catchAllMatchesUrlPath(urlPath);
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

/**
 * Intersection allow logic for a block field (`blocked` or `media_blocked`).
 * Browser internals and loopback always fail open.
 */
function evaluateUrlAgainstBlockField(url, blocks, field) {
    try {
        if (isProtectedBrowserUrl(url)) {
            return { blocked: false };
        }

        const href = String(url || '').trim();
        const parsed = new URL(
            href.includes('://') || href.toLowerCase().startsWith('about:')
                ? href
                : 'https://' + href
        );
        const hostname = parsed.hostname;
        const fullPath = hostname + parsed.pathname;
        const blockingBlocks = [];

        for (const block of blocks || []) {
            const patterns = block[field] || [];
            for (const pattern of patterns) {
                if (matchesPatternWithPath(fullPath, pattern)) {
                    blockingBlocks.push(block);
                    break;
                }
            }
        }

        if (blockingBlocks.length === 0) {
            return { blocked: false };
        }

        for (const block of blockingBlocks) {
            let urlAllowedByThisBlock = false;
            for (const pattern of block.allowed || []) {
                if (matchesPatternWithPath(fullPath, pattern)) {
                    urlAllowedByThisBlock = true;
                    break;
                }
            }
            if (!urlAllowedByThisBlock) {
                return {
                    blocked: true,
                    blockName: block.name,
                    hostname: hostname
                };
            }
        }

        return { blocked: false, allowed: true };
    } catch (error) {
        return { blocked: false };
    }
}

// Export for the bun test suite; the service worker gets these as globals
// via importScripts().
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        matchesPattern,
        matchesPatternWithPath,
        normalizeWebsitePattern,
        isCatchAllPattern,
        hostnameIsLoopback,
        isProtectedBrowserUrl,
        isHttpOrHttpsUrl,
        catchAllMatchesUrlPath,
        evaluateUrlAgainstBlockField,
    };
}
