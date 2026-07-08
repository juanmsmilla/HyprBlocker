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
import { matchesPattern, matchesPatternWithPath } from './matcher.js';

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
