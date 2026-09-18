/**
 * Tests for media-rule matching and DNR compilation (run with `bun test`).
 *
 * Pattern matching reuses matcher.js (same rules as websites_blocked).
 * shouldBlockMedia is the extension-side intersection allow logic for
 * websites_media_blocked — keep it aligned with shouldBlockUrl in
 * background.js / SiteBlocker.is_site_blocked in daemon/blocker.py.
 */

import { describe, expect, test } from 'bun:test';
import {
    matchesPatternWithPath,
    isCatchAllPattern,
    isProtectedBrowserUrl,
    evaluateUrlAgainstBlockField,
} from './matcher.js';
import {
    MEDIA_FETCH_RESOURCE_TYPES,
    MEDIA_RESOURCE_TYPES,
    collectMediaInitiatorDomains,
    collectCatchAllMediaAllowDomains,
    hasMediaCatchAll,
    isPathSpecificPattern,
    patternToInitiatorDomain,
    shouldBlockMedia,
    buildDynamicMediaRules,
    buildSessionMediaRules,
} from './media.js';

// matcher.js is a sibling importScripts global in the service worker; the
// media helpers call these by name. Expose them for bun.
globalThis.matchesPatternWithPath = matchesPatternWithPath;
globalThis.isCatchAllPattern = isCatchAllPattern;
globalThis.isProtectedBrowserUrl = isProtectedBrowserUrl;
globalThis.evaluateUrlAgainstBlockField = evaluateUrlAgainstBlockField;

describe('pattern helpers', () => {
    test('domain-only vs path-specific', () => {
        expect(isPathSpecificPattern('youtube.com')).toBe(false);
        expect(isPathSpecificPattern('https://youtube.com/')).toBe(false);
        expect(isPathSpecificPattern('youtube.com/shorts')).toBe(true);
        expect(isPathSpecificPattern('*.reddit.com')).toBe(false);
    });

    test('initiator domain strips wildcard, scheme, path', () => {
        expect(patternToInitiatorDomain('youtube.com')).toBe('youtube.com');
        expect(patternToInitiatorDomain('*.reddit.com')).toBe('reddit.com');
        expect(patternToInitiatorDomain('https://www.youtube.com/shorts')).toBe('www.youtube.com');
        expect(patternToInitiatorDomain('')).toBe(null);
        expect(patternToInitiatorDomain('*.*')).toBe(null);
    });
});

describe('shouldBlockMedia — intersection allow logic', () => {
    const youtubeMedia = [
        { name: 'focus', media_blocked: ['youtube.com'], allowed: [] },
    ];

    test('domain media pattern strips media on that host and subdomains', () => {
        expect(shouldBlockMedia('https://youtube.com/watch?v=1', youtubeMedia).blocked).toBe(true);
        expect(shouldBlockMedia('https://www.youtube.com/', youtubeMedia).blocked).toBe(true);
        expect(shouldBlockMedia('https://m.youtube.com/shorts', youtubeMedia).blocked).toBe(true);
    });

    test('unlisted host is not media-blocked', () => {
        expect(shouldBlockMedia('https://example.com/', youtubeMedia).blocked).toBe(false);
    });

    test('full-page blocked list is ignored — media uses media_blocked only', () => {
        const blocks = [
            { name: 'focus', blocked: ['reddit.com'], media_blocked: [], allowed: [] },
        ];
        expect(shouldBlockMedia('https://reddit.com/', blocks).blocked).toBe(false);
    });

    test('path-specific media pattern does not match other paths', () => {
        const blocks = [
            { name: 'shorts', media_blocked: ['youtube.com/shorts'], allowed: [] },
        ];
        expect(shouldBlockMedia('https://youtube.com/shorts/abc', blocks).blocked).toBe(true);
        expect(shouldBlockMedia('https://www.youtube.com/shorts', blocks).blocked).toBe(true);
        expect(shouldBlockMedia('https://youtube.com/watch?v=1', blocks).blocked).toBe(false);
        expect(shouldBlockMedia('https://youtube.com/', blocks).blocked).toBe(false);
    });

    test('allow list on the same block exempts matching URLs', () => {
        const blocks = [
            {
                name: 'focus',
                media_blocked: ['reddit.com'],
                allowed: ['reddit.com/r/programming'],
            },
        ];
        expect(shouldBlockMedia('https://reddit.com/r/funny', blocks).blocked).toBe(true);
        expect(shouldBlockMedia('https://reddit.com/r/programming', blocks).blocked).toBe(false);
        expect(shouldBlockMedia('https://reddit.com/r/programming', blocks).allowed).toBe(true);
    });

    test('intersection: every media-blocking block must allow', () => {
        const blocks = [
            { name: 'a', media_blocked: ['reddit.com'], allowed: ['reddit.com'] },
            { name: 'b', media_blocked: ['reddit.com'], allowed: [] },
        ];
        expect(shouldBlockMedia('https://reddit.com/', blocks).blocked).toBe(true);
        expect(shouldBlockMedia('https://reddit.com/', blocks).blockName).toBe('b');
    });

    test('intersection: allowed by all matching media blocks', () => {
        const blocks = [
            { name: 'a', media_blocked: ['reddit.com'], allowed: ['reddit.com'] },
            { name: 'b', media_blocked: ['reddit.com'], allowed: ['reddit.com'] },
        ];
        expect(shouldBlockMedia('https://reddit.com/', blocks).blocked).toBe(false);
        expect(shouldBlockMedia('https://reddit.com/', blocks).allowed).toBe(true);
    });

    test('invalid URL is not blocked', () => {
        expect(shouldBlockMedia('not a url', youtubeMedia).blocked).toBe(false);
    });
});

describe('DNR compilation', () => {
    test('domain-only media patterns become initiatorDomains rules', () => {
        const rules = buildDynamicMediaRules([
            { media_blocked: ['youtube.com', 'reddit.com'], allowed: [] },
        ]);
        expect(rules.length).toBe(4); // initiator types+fetch + CDN types+fetch
        expect(rules[0].action.type).toBe('block');
        expect(rules[0].condition.initiatorDomains).toEqual([
            'm.youtube.com', 'music.youtube.com', 'reddit.com', 'www.reddit.com', 'www.youtube.com', 'youtube.com',
        ]);
        expect(rules[0].condition.resourceTypes).toEqual(MEDIA_RESOURCE_TYPES);
        expect(rules[0].condition.resourceTypes).not.toContain('main_frame');
        expect(rules[1].condition.regexFilter).toContain('videoplayback');
        expect(rules[1].condition.resourceTypes).toEqual(MEDIA_FETCH_RESOURCE_TYPES);
    });

    test('path-specific patterns are not compiled into initiatorDomains', () => {
        const domains = collectMediaInitiatorDomains([
            { media_blocked: ['youtube.com/shorts'], allowed: [] },
        ]);
        expect(domains).toEqual([]);
        expect(buildDynamicMediaRules([
            { media_blocked: ['youtube.com/shorts'], allowed: [] },
        ])).toEqual([]);
    });

    test('wildcard media pattern uses the base domain', () => {
        expect(collectMediaInitiatorDomains([
            { media_blocked: ['*.reddit.com'], allowed: [] },
        ])).toEqual(['reddit.com', 'www.reddit.com']);
    });

    test('domain-wide allow/grant suppresses initiator DNR for that host', () => {
        expect(collectMediaInitiatorDomains([
            { media_blocked: ['youtube.com'], allowed: ['youtube.com'] },
        ])).toEqual([]);
    });

    test('path-only allow does not suppress host-wide initiator DNR', () => {
        expect(collectMediaInitiatorDomains([
            { media_blocked: ['youtube.com'], allowed: ['youtube.com/watch'] },
        ])).toEqual(['m.youtube.com', 'music.youtube.com', 'www.youtube.com', 'youtube.com']);
    });

    test('empty media lists produce no dynamic rules', () => {
        expect(buildDynamicMediaRules([])).toEqual([]);
        expect(buildDynamicMediaRules([{ media_blocked: [], allowed: [] }])).toEqual([]);
    });

    test('session rules are tab-scoped and do not include main_frame', () => {
        const rules = buildSessionMediaRules([42, 7]);
        expect(rules.length).toBe(4);
        expect(rules[0].condition.tabIds).toEqual([42]);
        expect(rules[0].condition.resourceTypes).not.toContain('main_frame');
        expect(rules[2].condition.tabIds).toEqual([7]);
        expect(rules.some((r) => r.condition.regexFilter)).toBe(true);
    });

    test('session allow rules are higher priority than block rules', () => {
        const rules = buildSessionMediaRules([1], 1000, [2]);
        expect(rules.length).toBe(4);
        expect(rules[0].action.type).toBe('block');
        expect(rules[2].action.type).toBe('allow');
        expect(rules[2].priority).toBeGreaterThan(rules[0].priority);
        expect(rules[2].condition.tabIds).toEqual([2]);
        expect(rules[2].condition.resourceTypes).not.toContain('main_frame');
    });
});

describe('shouldBlockMedia — catch-all *', () => {
    const starMedia = [
        { name: 'focus', media_blocked: ['*'], allowed: ['openai.com'] },
    ];

    test('strips media on every http(s) page except allows', () => {
        expect(shouldBlockMedia('https://example.com/', starMedia).blocked).toBe(true);
        expect(shouldBlockMedia('https://news.ycombinator.com/', starMedia).blocked).toBe(true);
        expect(shouldBlockMedia('https://openai.com/', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('https://openai.com/chat', starMedia).allowed).toBe(true);
        expect(shouldBlockMedia('https://chat.openai.com/', starMedia).blocked).toBe(false);
    });

    test('never strips media on internals or the local daemon', () => {
        expect(shouldBlockMedia('chrome://extensions', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('chrome-extension://abc/popup.html', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('about:blank', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('edge://settings', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('http://127.0.0.1:8765/', starMedia).blocked).toBe(false);
        expect(shouldBlockMedia('http://localhost:8765/api', starMedia).blocked).toBe(false);
    });

    test('path-specific allow unstrips that document under *', () => {
        const blocks = [
            { name: 'focus', media_blocked: ['*'], allowed: ['example.com/docs'] },
        ];
        expect(shouldBlockMedia('https://example.com/docs', blocks).blocked).toBe(false);
        expect(shouldBlockMedia('https://example.com/other', blocks).blocked).toBe(true);
    });

    test('without * host media patterns are unchanged', () => {
        const blocks = [{ name: 'focus', media_blocked: ['youtube.com'], allowed: [] }];
        expect(shouldBlockMedia('https://youtube.com/watch', blocks).blocked).toBe(true);
        expect(shouldBlockMedia('https://example.com/', blocks).blocked).toBe(false);
    });
});

describe('DNR compilation — catch-all *', () => {
    test('hasMediaCatchAll detects *', () => {
        expect(hasMediaCatchAll([{ media_blocked: ['*'] }])).toBe(true);
        expect(hasMediaCatchAll([{ media_blocked: ['youtube.com', '*'] }])).toBe(true);
        expect(hasMediaCatchAll([{ media_blocked: ['youtube.com'] }])).toBe(false);
        expect(hasMediaCatchAll([{ media_blocked: ['http*'] }])).toBe(false);
    });

    test('global block rules have no initiatorDomains and exclude loopback', () => {
        const rules = buildDynamicMediaRules([
            { media_blocked: ['*'], allowed: [] },
        ]);
        expect(rules.length).toBe(2);
        expect(rules[0].action.type).toBe('block');
        expect(rules[0].condition.initiatorDomains).toBeUndefined();
        expect(rules[0].condition.resourceTypes).toEqual(MEDIA_RESOURCE_TYPES);
        expect(rules[0].condition.resourceTypes).not.toContain('main_frame');
        expect(rules[0].condition.excludedRequestDomains).toEqual(['localhost', '127.0.0.1']);
        expect(rules[0].condition.excludedInitiatorDomains).toEqual(['127.0.0.1', 'localhost']);
        expect(rules[1].condition.regexFilter).toContain('videoplayback');
        expect(rules[1].condition.resourceTypes).toEqual(MEDIA_FETCH_RESOURCE_TYPES);
        expect(rules[1].condition.regexFilter.includes('(')).toBe(false);
    });

    test('domain-wide allow becomes higher-priority initiator allow', () => {
        const blocks = [{ media_blocked: ['*'], allowed: ['openai.com'] }];
        expect(collectCatchAllMediaAllowDomains(blocks)).toEqual(['openai.com', 'www.openai.com']);
        const rules = buildDynamicMediaRules(blocks);
        expect(rules.length).toBe(4);
        const allow = rules.filter((r) => r.action.type === 'allow');
        expect(allow.length).toBe(2);
        expect(allow[0].priority).toBeGreaterThan(rules[0].priority);
        expect(allow[0].condition.initiatorDomains).toEqual(['openai.com', 'www.openai.com']);
        expect(rules[0].condition.excludedInitiatorDomains).toEqual([
            '127.0.0.1', 'localhost', 'openai.com', 'www.openai.com',
        ]);
    });

    test('path-only allow does not get a host-wide initiator allow', () => {
        const blocks = [{ media_blocked: ['*'], allowed: ['openai.com/docs'] }];
        expect(collectCatchAllMediaAllowDomains(blocks)).toEqual([]);
        const rules = buildDynamicMediaRules(blocks);
        expect(rules.every((r) => r.action.type === 'block')).toBe(true);
    });

    test('* dominates mixed media lists for DNR (no host initiator rules)', () => {
        const rules = buildDynamicMediaRules([
            { media_blocked: ['*', 'youtube.com'], allowed: [] },
        ]);
        expect(rules[0].condition.initiatorDomains).toBeUndefined();
        expect(hasMediaCatchAll([{ media_blocked: ['*', 'youtube.com'] }])).toBe(true);
    });
});
