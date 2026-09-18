/**
 * Tests for extension URL pattern matching (run with `bun test`).
 *
 * These mirror tests/test_blocker.py for SiteBlocker.url_matches_pattern —
 * the daemon and extension implement the same matching rules in two
 * languages, and this suite guards against them drifting apart (a real bug
 * class: one such mismatch was found and fixed in a past review).
 *
 * Interface note: the extension matcher receives "hostname/path" strings
 * (no protocol) because the service worker builds them from a parsed URL;
 * patterns may still carry a protocol since they come from user input.
 */

import { describe, expect, test } from 'bun:test';
import {
    matchesPattern,
    matchesPatternWithPath,
    isCatchAllPattern,
    isProtectedBrowserUrl,
    evaluateUrlAgainstBlockField,
} from './matcher.js';

describe('matchesPatternWithPath — domain-only patterns', () => {
    const matches = [
        'reddit.com',
        'reddit.com/',
        'reddit.com/r/programming',
        'www.reddit.com',
        'old.reddit.com',
        'old.reddit.com/r/linux',
        'REDDIT.COM',
    ];
    for (const url of matches) {
        test(`matches ${url}`, () => {
            expect(matchesPatternWithPath(url, 'reddit.com')).toBe(true);
        });
    }

    const rejects = [
        'notreddit.com',
        'reddit.com.evil.com',
        'example.com/reddit.com',
        'example.com',
    ];
    for (const url of rejects) {
        test(`rejects ${url}`, () => {
            expect(matchesPatternWithPath(url, 'reddit.com')).toBe(false);
        });
    }
});

describe('matchesPatternWithPath — path-specific patterns', () => {
    const matches = [
        'youtube.com/shorts',
        'youtube.com/shorts/abc123',
        'www.youtube.com/shorts',
        'youtube.com/shorts?feature=share',
    ];
    for (const url of matches) {
        test(`matches ${url}`, () => {
            expect(matchesPatternWithPath(url, 'youtube.com/shorts')).toBe(true);
        });
    }

    const rejects = [
        'youtube.com',
        'youtube.com/watch?v=abc',
        'youtube.com/feed',
        'youtube.com/shortsfilm', // prefix of the path segment, not a subpath
    ];
    for (const url of rejects) {
        test(`rejects ${url}`, () => {
            expect(matchesPatternWithPath(url, 'youtube.com/shorts')).toBe(false);
        });
    }
});

describe('matchesPatternWithPath — wildcard subdomain patterns', () => {
    const matches = ['old.reddit.com', 'www.reddit.com', 'a.b.reddit.com', 'reddit.com'];
    for (const url of matches) {
        test(`matches ${url}`, () => {
            expect(matchesPatternWithPath(url, '*.reddit.com')).toBe(true);
        });
    }

    const rejects = ['notreddit.com', 'reddit.com.evil.com'];
    for (const url of rejects) {
        test(`rejects ${url}`, () => {
            expect(matchesPatternWithPath(url, '*.reddit.com')).toBe(false);
        });
    }
});

describe('matchesPatternWithPath — normalization', () => {
    test('strips protocol from pattern', () => {
        expect(matchesPatternWithPath('reddit.com', 'https://reddit.com')).toBe(true);
        expect(matchesPatternWithPath('reddit.com', 'http://reddit.com')).toBe(true);
    });

    test('ignores trailing slash on pattern', () => {
        expect(matchesPatternWithPath('reddit.com', 'reddit.com/')).toBe(true);
    });

    test('is case insensitive', () => {
        expect(matchesPatternWithPath('WWW.Reddit.COM', 'Reddit.com')).toBe(true);
    });
});

describe('matchesPattern — hostname-only matching', () => {
    test('exact match', () => {
        expect(matchesPattern('reddit.com', 'reddit.com')).toBe(true);
    });

    test('subdomain matches domain pattern', () => {
        expect(matchesPattern('www.reddit.com', 'reddit.com')).toBe(true);
    });

    test('wildcard matches subdomains and bare domain', () => {
        expect(matchesPattern('old.reddit.com', '*.reddit.com')).toBe(true);
        expect(matchesPattern('reddit.com', '*.reddit.com')).toBe(true);
    });

    test('rejects lookalike domains', () => {
        expect(matchesPattern('notreddit.com', 'reddit.com')).toBe(false);
        expect(matchesPattern('reddit.com.evil.com', 'reddit.com')).toBe(false);
    });

    test('strips protocol and path from pattern', () => {
        expect(matchesPattern('reddit.com', 'https://reddit.com/r/all')).toBe(true);
    });
});

describe('catch-all * pattern', () => {
    test('isCatchAllPattern only accepts literal *', () => {
        expect(isCatchAllPattern('*')).toBe(true);
        expect(isCatchAllPattern(' * ')).toBe(true);
        expect(isCatchAllPattern('https://*')).toBe(true);
        expect(isCatchAllPattern('http*')).toBe(false);
        expect(isCatchAllPattern('*.reddit.com')).toBe(false);
        expect(isCatchAllPattern('*.*')).toBe(false);
        expect(isCatchAllPattern('reddit.com')).toBe(false);
    });

    test('matches every http(s) host/path', () => {
        expect(matchesPatternWithPath('example.com', '*')).toBe(true);
        expect(matchesPatternWithPath('example.com/foo', '*')).toBe(true);
        expect(matchesPatternWithPath('www.news.example.com/a/b', '*')).toBe(true);
        expect(matchesPatternWithPath('https://example.com/foo', '*')).toBe(true);
        expect(matchesPattern('example.com', '*')).toBe(true);
    });

    test('does not match loopback / daemon', () => {
        expect(matchesPatternWithPath('127.0.0.1', '*')).toBe(false);
        expect(matchesPatternWithPath('127.0.0.1:8765/api', '*')).toBe(false);
        expect(matchesPatternWithPath('localhost', '*')).toBe(false);
        expect(matchesPatternWithPath('localhost:8765/', '*')).toBe(false);
        expect(matchesPatternWithPath('http://127.0.0.1:8765/api', '*')).toBe(false);
        expect(matchesPatternWithPath('[::1]/', '*')).toBe(false);
        expect(matchesPattern('localhost', '*')).toBe(false);
    });

    test('does not match browser internals', () => {
        expect(matchesPatternWithPath('chrome://extensions', '*')).toBe(false);
        expect(matchesPatternWithPath('chrome-extension://abcdef/blocked.html', '*')).toBe(false);
        expect(matchesPatternWithPath('about:blank', '*')).toBe(false);
        expect(matchesPatternWithPath('edge://settings', '*')).toBe(false);
    });

    test('http* is not a catch-all and does not match random hosts', () => {
        expect(matchesPatternWithPath('example.com', 'http*')).toBe(false);
        expect(matchesPatternWithPath('https://example.com', 'http*')).toBe(false);
    });
});

describe('isProtectedBrowserUrl', () => {
    test('protects internals and loopback', () => {
        expect(isProtectedBrowserUrl('chrome://extensions')).toBe(true);
        expect(isProtectedBrowserUrl('chrome-extension://id/page.html')).toBe(true);
        expect(isProtectedBrowserUrl('about:blank')).toBe(true);
        expect(isProtectedBrowserUrl('edge://settings')).toBe(true);
        expect(isProtectedBrowserUrl('http://127.0.0.1:8765/api')).toBe(true);
        expect(isProtectedBrowserUrl('http://localhost:8765/')).toBe(true);
        expect(isProtectedBrowserUrl('https://localhost/')).toBe(true);
    });

    test('does not protect real websites', () => {
        expect(isProtectedBrowserUrl('https://example.com/')).toBe(false);
        expect(isProtectedBrowserUrl('http://openai.com/chat')).toBe(false);
        expect(isProtectedBrowserUrl('reddit.com')).toBe(false);
    });
});

describe('evaluateUrlAgainstBlockField — catch-all *', () => {
    const starBlock = [{ name: 'focus', blocked: ['*'], allowed: ['openai.com'] }];

    test('blocks every http(s) page except allows', () => {
        expect(evaluateUrlAgainstBlockField('https://example.com/', starBlock, 'blocked').blocked).toBe(true);
        expect(evaluateUrlAgainstBlockField('https://news.ycombinator.com/item?id=1', starBlock, 'blocked').blocked).toBe(true);
        expect(evaluateUrlAgainstBlockField('https://openai.com/', starBlock, 'blocked').blocked).toBe(false);
        expect(evaluateUrlAgainstBlockField('https://openai.com/', starBlock, 'blocked').allowed).toBe(true);
        expect(evaluateUrlAgainstBlockField('https://chat.openai.com/', starBlock, 'blocked').blocked).toBe(false);
    });

    test('never blocks internals or the local daemon', () => {
        expect(evaluateUrlAgainstBlockField('chrome://extensions', starBlock, 'blocked').blocked).toBe(false);
        expect(evaluateUrlAgainstBlockField('chrome-extension://abc/blocked.html', starBlock, 'blocked').blocked).toBe(false);
        expect(evaluateUrlAgainstBlockField('about:blank', starBlock, 'blocked').blocked).toBe(false);
        expect(evaluateUrlAgainstBlockField('http://127.0.0.1:8765/api/heartbeat', starBlock, 'blocked').blocked).toBe(false);
        expect(evaluateUrlAgainstBlockField('http://localhost:8765/', starBlock, 'blocked').blocked).toBe(false);
    });

    test('* alongside specific hosts still catch-alls that list', () => {
        const blocks = [{ name: 'focus', blocked: ['*', 'reddit.com'], allowed: [] }];
        expect(evaluateUrlAgainstBlockField('https://example.com/', blocks, 'blocked').blocked).toBe(true);
        expect(evaluateUrlAgainstBlockField('https://reddit.com/', blocks, 'blocked').blocked).toBe(true);
    });

    test('without * host patterns are unchanged', () => {
        const blocks = [{ name: 'focus', blocked: ['reddit.com'], allowed: [] }];
        expect(evaluateUrlAgainstBlockField('https://reddit.com/', blocks, 'blocked').blocked).toBe(true);
        expect(evaluateUrlAgainstBlockField('https://example.com/', blocks, 'blocked').blocked).toBe(false);
    });
});
