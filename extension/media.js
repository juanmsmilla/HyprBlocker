/**
 * HyprBlocker - Media / resource-type blocking helpers.
 *
 * Semantics (enforced in the Chromium extension via declarativeNetRequest):
 *
 * - `websites_blocked` still redirects navigations (see background.js).
 * - Literal `*` in `media_blocked` is a catch-all: strip media on every
 *   http(s) page except that block's allow list (and grants overlay).
 *   Browser internals and loopback (localhost / 127.0.0.1) are never
 *   catch-all targets — fail open so the daemon and chrome:// stay up.
 * - `media_blocked` (from `websites_media_blocked`) does **not** cancel
 *   main_frame / document navigations. Matching pages stay available.
 * - A media rule matches the **initiating document**: image/video/audio
 *   requested by that page (including CDN hosts like googlevideo.com) is
 *   cancelled. Domain-only patterns also cover embeds whose initiator is
 *   that host, even when the top-level tab is some other site.
 * - Path-specific patterns (youtube.com/shorts) use the same matcher as
 *   website blocks, applied to the tab's document URL. Chromium DNR cannot
 *   filter by initiator path, so those are tab-scoped session rules.
 * - Allow lists / grants: same intersection idea as full-page blocks — a
 *   URL's media is stripped if ANY media-blocking block matches and that
 *   block does not allow the URL. Domain-wide allows/grants on a host
 *   suppress host-wide initiator DNR for that block. Path-only allows do
 *   not punch a hole in domain-wide media rules (fail-closed: DNR has no
 *   initiator-path exclusion). Under catch-all `*`, a matching allow
 *   (domain or path) leaves that document's media intact via higher-priority
 *   session allow rules. Grants are requested against full-page
 *   `websites_blocked` matches; an existing grant also overlays onto
 *   media-matching blocks' allowed[].
 *
 * Resource types: image, media, object — plus xmlhttprequest/other whose
 * URL looks like typical video/audio (file extension or "videoplayback").
 */

const MEDIA_RESOURCE_TYPES = ['image', 'media', 'object'];
const MEDIA_FETCH_RESOURCE_TYPES = ['xmlhttprequest', 'other'];
// DASH/HLS and <video> fetches often show up as XHR rather than `media`.
const MEDIA_FETCH_REGEX =
    'videoplayback|\\.mp4|\\.m4v|\\.m4s|\\.m4a|\\.webm|\\.mp3|\\.m3u8|\\.ogg|\\.wav|\\.flac|\\.mov|\\.avi';

const DYNAMIC_RULE_ID_TYPES = 1;
const DYNAMIC_RULE_ID_FETCH = 2;
const DYNAMIC_RULE_ID_CDN = 3;
const DYNAMIC_RULE_ID_CDN_FETCH = 4;
const DYNAMIC_RULE_ID_ALLOW_TYPES = 5;
const DYNAMIC_RULE_ID_ALLOW_FETCH = 6;
const SESSION_RULE_ID_BASE = 1000;
const PROTECTED_DNR_DOMAINS = ['localhost', '127.0.0.1'];

/**
 * Strip scheme / trailing slash; lowercase. Does not remove path.
 */
function normalizeMediaPattern(pattern) {
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

function isPathSpecificPattern(pattern) {
    return normalizeMediaPattern(pattern).includes('/');
}

/**
 * Host used for DNR initiatorDomains (no wildcard, no path).
 */
function patternToInitiatorDomain(pattern) {
    let host = normalizeMediaPattern(pattern).split('/')[0];
    if (host.startsWith('*.')) {
        host = host.substring(2);
    }
    // DNR initiatorDomains are lowercase ASCII hostnames, no port/path.
    if (!host || host.includes(':') || host.includes(' ') || host.includes('*')) {
        return null;
    }
    return host;
}

function matchPath(urlPath, pattern) {
    // Service worker: importScripts('matcher.js') puts this on globalThis.
    // bun tests assign the same name before calling these helpers.
    return globalThis.matchesPatternWithPath(urlPath, pattern);
}

function patternIsCatchAll(pattern) {
    const fn = globalThis.isCatchAllPattern;
    if (typeof fn === 'function') {
        return fn(pattern);
    }
    return String(pattern || '').trim() === '*';
}

function hasMediaCatchAll(blocks) {
    for (const block of blocks || []) {
        for (const pattern of block.media_blocked || []) {
            if (patternIsCatchAll(pattern)) {
                return true;
            }
        }
    }
    return false;
}

function patternsMatchUrl(urlPath, patterns) {
    if (!patterns) {
        return false;
    }
    for (const pattern of patterns) {
        if (matchPath(urlPath, pattern)) {
            return true;
        }
    }
    return false;
}

/**
 * Intersection allow logic for media-only rules, mirroring shouldBlockUrl
 * but using each block's media_blocked list instead of blocked.
 *
 * @param {string} url
 * @param {Array<{name?: string, media_blocked?: string[], allowed?: string[]}>} blocks
 * @returns {{blocked: boolean, allowed?: boolean, blockName?: string, hostname?: string}}
 */
function shouldBlockMedia(url, blocks) {
    const evaluate = globalThis.evaluateUrlAgainstBlockField;
    if (typeof evaluate === 'function') {
        return evaluate(url, blocks, 'media_blocked');
    }
    try {
        const protectedFn = globalThis.isProtectedBrowserUrl;
        if (typeof protectedFn === 'function' && protectedFn(url)) {
            return { blocked: false };
        }
        const urlObj = new URL(url);
        const hostname = urlObj.hostname;
        const fullPath = hostname + urlObj.pathname;
        const blockingBlocks = [];

        for (const block of blocks || []) {
            if (patternsMatchUrl(fullPath, block.media_blocked)) {
                blockingBlocks.push(block);
            }
        }

        if (blockingBlocks.length === 0) {
            return { blocked: false };
        }

        for (const block of blockingBlocks) {
            if (!patternsMatchUrl(fullPath, block.allowed)) {
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

/**
 * Initiator hosts that should get a persistent DNR rule.
 *
 * Domain-only media patterns only. A block whose allow list covers the
 * whole host (e.g. a domain-wide grant) does not contribute that host —
 * otherwise grants could never unstrip media.
 */
function expandInitiatorAliases(domain) {
    const out = new Set([domain]);
    if (!domain.startsWith('www.')) {
        out.add('www.' + domain);
    }
    // Common app / mobile hosts for the sites we care about most.
    if (domain === 'youtube.com' || domain.endsWith('.youtube.com')) {
        out.add('m.youtube.com');
        out.add('music.youtube.com');
        out.add('www.youtube.com');
    }
    if (domain === 'x.com' || domain === 'twitter.com') {
        out.add('www.x.com');
        out.add('mobile.x.com');
        out.add('twitter.com');
        out.add('www.twitter.com');
        out.add('mobile.twitter.com');
        out.add('x.com');
    }
    return [...out];
}

/** CDN / media hosts to block by request URL when a site is media-blocked. */
function cdnRequestDomainsFor(domain) {
    if (domain === 'youtube.com' || domain.endsWith('.youtube.com')) {
        return [
            'googlevideo.com',
            'www.googlevideo.com',
            'ytimg.com',
            'i.ytimg.com',
            'i1.ytimg.com',
            'i9.ytimg.com',
            'yt3.ggpht.com',
            'ggpht.com',
        ];
    }
    if (domain === 'x.com' || domain === 'twitter.com') {
        return [
            'abs.twimg.com',
            'pbs.twimg.com',
            'video.twimg.com',
            'ton.twimg.com',
        ];
    }
    return [];
}

function collectMediaInitiatorDomains(blocks) {
    const domains = new Set();
    for (const block of blocks || []) {
        const media = block.media_blocked || [];
        const allowed = block.allowed || [];
        for (const pattern of media) {
            if (isPathSpecificPattern(pattern) || patternIsCatchAll(pattern)) {
                continue;
            }
            const domain = patternToInitiatorDomain(pattern);
            if (!domain) {
                continue;
            }
            const hostAllowed = allowed.some((p) => matchPath(domain, p) || matchPath('www.' + domain, p));
            if (hostAllowed) {
                continue;
            }
            for (const d of expandInitiatorAliases(domain)) {
                domains.add(d);
            }
        }
    }
    return [...domains].sort();
}

function collectMediaCdnRequestDomains(blocks) {
    const domains = new Set();
    for (const block of blocks || []) {
        const media = block.media_blocked || [];
        const allowed = block.allowed || [];
        for (const pattern of media) {
            if (isPathSpecificPattern(pattern) || patternIsCatchAll(pattern)) {
                continue;
            }
            const domain = patternToInitiatorDomain(pattern);
            if (!domain) {
                continue;
            }
            const hostAllowed = allowed.some((p) => matchPath(domain, p) || matchPath('www.' + domain, p));
            if (hostAllowed) {
                continue;
            }
            for (const d of cdnRequestDomainsFor(domain)) {
                domains.add(d);
            }
        }
    }
    return [...domains].sort();
}

function mediaBlockRule(id, condition) {
    return {
        id: id,
        priority: 1,
        action: { type: 'block' },
        condition: condition
    };
}

function mediaAllowRule(id, condition) {
    return {
        id: id,
        priority: 2,
        action: { type: 'allow' },
        condition: condition
    };
}

/**
 * Domain-wide allow hosts that shouldBlockMedia does not strip at `/`.
 * Path-only allows are left to tab session allow rules (DNR has no
 * initiator-path filter).
 */
function collectCatchAllMediaAllowDomains(blocks) {
    const candidates = new Set();
    for (const block of blocks || []) {
        for (const pattern of block.allowed || []) {
            if (isPathSpecificPattern(pattern) || patternIsCatchAll(pattern)) {
                continue;
            }
            const domain = patternToInitiatorDomain(pattern);
            if (!domain) {
                continue;
            }
            for (const d of expandInitiatorAliases(domain)) {
                candidates.add(d);
            }
        }
    }
    const allowed = [];
    for (const domain of candidates) {
        if (!shouldBlockMedia('https://' + domain + '/', blocks).blocked) {
            allowed.push(domain);
        }
    }
    return allowed.sort();
}

// Always-on CDNs for catch-all media (YouTube/X stream hosts). Video often
// arrives as XHR to these domains, not as resourceType "media".
const CATCH_ALL_MEDIA_CDN_DOMAINS = [
    'googlevideo.com',
    'www.googlevideo.com',
    'ytimg.com',
    'i.ytimg.com',
    'i1.ytimg.com',
    'i9.ytimg.com',
    'yt3.ggpht.com',
    'ggpht.com',
    'abs.twimg.com',
    'pbs.twimg.com',
    'video.twimg.com',
    'ton.twimg.com',
];

function buildCatchAllDynamicMediaRules(blocks) {
    const allowDomains = collectCatchAllMediaAllowDomains(blocks);
    const excludedInitiators = [...new Set([...PROTECTED_DNR_DOMAINS, ...allowDomains])].sort();
    const rules = [
        mediaBlockRule(DYNAMIC_RULE_ID_TYPES, {
            resourceTypes: MEDIA_RESOURCE_TYPES,
            excludedInitiatorDomains: excludedInitiators,
            excludedRequestDomains: PROTECTED_DNR_DOMAINS
        }),
        mediaBlockRule(DYNAMIC_RULE_ID_FETCH, {
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES,
            excludedInitiatorDomains: excludedInitiators,
            excludedRequestDomains: PROTECTED_DNR_DOMAINS
        }),
        // Hard block YouTube/X media CDNs (XHR/other + classic media types).
        mediaBlockRule(DYNAMIC_RULE_ID_CDN, {
            requestDomains: CATCH_ALL_MEDIA_CDN_DOMAINS,
            resourceTypes: MEDIA_RESOURCE_TYPES,
            excludedInitiatorDomains: allowDomains.length ? allowDomains : undefined
        }),
        mediaBlockRule(DYNAMIC_RULE_ID_CDN_FETCH, {
            requestDomains: CATCH_ALL_MEDIA_CDN_DOMAINS,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES,
            excludedInitiatorDomains: allowDomains.length ? allowDomains : undefined
        }),
        // urlFilter backup — does not depend on regexFilter validation.
        mediaBlockRule(DYNAMIC_RULE_ID_CDN_FETCH + 10, {
            urlFilter: '*videoplayback*',
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES,
            excludedInitiatorDomains: allowDomains.length ? allowDomains : [...PROTECTED_DNR_DOMAINS]
        })
    ];
    // Drop rules whose condition has undefined excludedInitiatorDomains key issues
    for (const rule of rules) {
        if (rule.condition.excludedInitiatorDomains === undefined) {
            delete rule.condition.excludedInitiatorDomains;
        }
    }
    if (allowDomains.length > 0) {
        rules.push(mediaAllowRule(DYNAMIC_RULE_ID_ALLOW_TYPES, {
            initiatorDomains: allowDomains,
            resourceTypes: MEDIA_RESOURCE_TYPES
        }));
        rules.push(mediaAllowRule(DYNAMIC_RULE_ID_ALLOW_FETCH, {
            initiatorDomains: allowDomains,
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES
        }));
        // Allow CDN media only when the page initiator is an allow-listed domain.
        rules.push(mediaAllowRule(DYNAMIC_RULE_ID_ALLOW_FETCH + 10, {
            initiatorDomains: allowDomains,
            requestDomains: CATCH_ALL_MEDIA_CDN_DOMAINS,
            resourceTypes: [...MEDIA_RESOURCE_TYPES, ...MEDIA_FETCH_RESOURCE_TYPES]
        }));
    }
    return rules;
}

/**
 * Persistent (dynamic) DNR rules.
 *
 * Host lists: initiatorDomains (+ CDN requestDomains) as before.
 * Catch-all `*`: global image/media/object (+ fetch regex) block, with
 * higher-priority allow / excludedInitiatorDomains for domain-wide allows
 * and always-excluded loopback. Does not include main_frame.
 */
function buildDynamicMediaRules(blocks) {
    if (hasMediaCatchAll(blocks)) {
        return buildCatchAllDynamicMediaRules(blocks);
    }
    const domains = collectMediaInitiatorDomains(blocks);
    const cdns = collectMediaCdnRequestDomains(blocks);
    const rules = [];
    if (domains.length > 0) {
        rules.push(mediaBlockRule(DYNAMIC_RULE_ID_TYPES, {
            initiatorDomains: domains,
            resourceTypes: MEDIA_RESOURCE_TYPES
        }));
        rules.push(mediaBlockRule(DYNAMIC_RULE_ID_FETCH, {
            initiatorDomains: domains,
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES
        }));
    }
    if (cdns.length > 0) {
        // Belt-and-suspenders: YouTube/X put bits on CDNs; initiator match can miss.
        rules.push(mediaBlockRule(DYNAMIC_RULE_ID_CDN, {
            requestDomains: cdns,
            resourceTypes: MEDIA_RESOURCE_TYPES
        }));
        rules.push(mediaBlockRule(DYNAMIC_RULE_ID_CDN_FETCH, {
            requestDomains: cdns,
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES
        }));
    }
    return rules;
}

/**
 * Tab-scoped session rules for path-specific media patterns (and as a
 * belt-and-suspenders for domain-only when the tab document matches).
 *
 * When catch-all `*` is active, pass allowTabIds so matching allow-list
 * documents (including path-specific allows) get higher-priority allow
 * rules that override the global dynamic block.
 */
function buildSessionMediaRules(tabIds, startId, allowTabIds) {
    const base = startId == null ? SESSION_RULE_ID_BASE : startId;
    const rules = [];
    let id = base;
    for (const tabId of tabIds || []) {
        rules.push(mediaBlockRule(id++, {
            tabIds: [tabId],
            resourceTypes: MEDIA_RESOURCE_TYPES
        }));
        rules.push(mediaBlockRule(id++, {
            tabIds: [tabId],
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES
        }));
    }
    for (const tabId of allowTabIds || []) {
        rules.push(mediaAllowRule(id++, {
            tabIds: [tabId],
            resourceTypes: MEDIA_RESOURCE_TYPES
        }));
        rules.push(mediaAllowRule(id++, {
            tabIds: [tabId],
            regexFilter: MEDIA_FETCH_REGEX,
            resourceTypes: MEDIA_FETCH_RESOURCE_TYPES
        }));
    }
    return rules;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        MEDIA_RESOURCE_TYPES,
        MEDIA_FETCH_RESOURCE_TYPES,
        MEDIA_FETCH_REGEX,
        DYNAMIC_RULE_ID_TYPES,
        DYNAMIC_RULE_ID_FETCH,
        DYNAMIC_RULE_ID_ALLOW_TYPES,
        DYNAMIC_RULE_ID_ALLOW_FETCH,
        SESSION_RULE_ID_BASE,
        PROTECTED_DNR_DOMAINS,
        normalizeMediaPattern,
        isPathSpecificPattern,
        patternToInitiatorDomain,
        hasMediaCatchAll,
        shouldBlockMedia,
        collectMediaInitiatorDomains,
        collectMediaCdnRequestDomains,
        collectCatchAllMediaAllowDomains,
        expandInitiatorAliases,
        buildDynamicMediaRules,
        buildSessionMediaRules
    };
}
