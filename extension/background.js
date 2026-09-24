/**
 * HyprBlocker - Background Service Worker
 * Handles heartbeat, site blocking, and communication with the daemon.
 */

// Pattern matching lives in matcher.js so it can be unit-tested with bun
// (provides matchesPattern and matchesPatternWithPath as globals).
// Media DNR compilation lives in media.js (shouldBlockMedia, build*MediaRules).
importScripts('matcher.js');
importScripts('media.js');

const DAEMON_URL = 'http://127.0.0.1:8765';
const HEARTBEAT_INTERVAL = 30000; // 30 seconds
const RULES_REFRESH_INTERVAL = 5000; // 5 seconds

let browserPID = null;
let blocksData = [];  // Array of {id, name, priority, blocked[], allowed[], media_blocked[]}
let safeSearchEnabled = false;  // Safe search enforcement setting
let heartbeatIntervalId = null;
let rulesRefreshIntervalId = null;

// Deduplication to prevent multiple redirects for same navigation
const BLOCK_CACHE_DURATION = 2000; // 2 seconds
const recentBlocks = new Map(); // Map<tabId, {url: string, timestamp: number}>

// Initialize on install
chrome.runtime.onInstalled.addListener(async () => {
    console.log('HyprBlocker extension installed');
    await initialize();
});

// Initialize on browser startup
chrome.runtime.onStartup.addListener(async () => {
    console.log('Browser started - initializing HyprBlocker');
    await initialize();
});

/**
 * Initialize the extension
 */
async function initialize() {
    await getBrowserPID();
    await fetchBlockedSites();

    const incognitoAllowed = await isAllowedIncognitoAccess();
    console.log('Extension incognito access:', incognitoAllowed ? 'ENABLED' : 'DISABLED');
    if (!incognitoAllowed) {
        console.warn('WARNING: Extension does not have incognito permission - browser will be NON-COMPLIANT');
    }

    startHeartbeat();
    startRulesRefresh();
}

/**
 * Get browser PID via native messaging
 * Waits for native messaging to complete or timeout before returning.
 * This prevents the race condition where first heartbeat uses fallback PID.
 */
async function getBrowserPID() {
    const NATIVE_MSG_TIMEOUT = 3000; // 3 second timeout for native messaging

    return new Promise((resolve) => {
        let resolved = false;

        const doResolve = (pid, source) => {
            if (!resolved) {
                resolved = true;
                browserPID = pid;
                console.log(`Browser PID set from ${source}:`, browserPID);
                resolve(browserPID);
            }
        };

        // Generate fallback PID (used if native messaging fails/times out)
        const fallbackPID = hashCode(chrome.runtime.id + Date.now());

        // Timeout fallback - ensures we don't wait forever
        const timeout = setTimeout(() => {
            console.warn('⚠️ Native messaging timeout, using fallback PID:', fallbackPID);
            doResolve(fallbackPID, 'timeout');
        }, NATIVE_MSG_TIMEOUT);

        try {
            const port = chrome.runtime.connectNative('com.hyprblocker.host');

            port.onMessage.addListener((message) => {
                if (message.pid) {
                    clearTimeout(timeout);
                    console.log('✅ Got real browser PID from native host:', message.pid);
                    console.log('Extension ID:', chrome.runtime.id);
                    doResolve(message.pid, 'native messaging');
                }
                if (message.error) {
                    clearTimeout(timeout);
                    console.error('❌ Native host error:', message.error);
                    console.warn('⚠️ Using fallback PID:', fallbackPID);
                    doResolve(fallbackPID, 'native error');
                }
            });

            port.onDisconnect.addListener(() => {
                clearTimeout(timeout);
                if (chrome.runtime.lastError) {
                    console.error('❌ Native messaging disconnected:', chrome.runtime.lastError.message);
                    console.warn('⚠️ Using fallback PID:', fallbackPID, '- Browser may be killed!');
                    console.info('ℹ️ Extension ID:', chrome.runtime.id);
                    console.info('ℹ️ Check native messaging manifest for ID mismatch');
                }
                doResolve(fallbackPID, 'disconnect');
            });

            port.postMessage({ action: 'get_pid' });
        } catch (error) {
            clearTimeout(timeout);
            console.error('❌ Native messaging error:', error);
            console.warn('⚠️ Using fallback PID:', fallbackPID, '- Browser may be killed!');
            console.info('ℹ️ Extension ID:', chrome.runtime.id);
            doResolve(fallbackPID, 'error');
        }
    });
}

/**
 * Simple hash function for fallback PID generation
 */
function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash);
}

/**
 * Count visible browser windows that the extension can see
 * Used to detect unmonitored profiles (guest profiles, etc.)
 */
async function getVisibleWindowCount() {
    try {
        // Only count 'normal' and large 'popup' windows
        // Excludes: devtools, panel, and tiny extension popups
        const windows = await chrome.windows.getAll({ windowTypes: ['normal', 'popup'] });
        let count = 0;
        for (const window of windows) {
            // Normal windows always count
            // Popup windows only count if they're large enough to be a real browser window
            if (window.type === 'normal' || (window.type === 'popup' && window.width > 400)) {
                count++;
            }
        }
        return count;
    } catch (error) {
        console.error('Failed to count windows:', error);
        return null; // Return null to indicate failure (not 0)
    }
}

/**
 * Check if any window is in incognito mode
 */
async function isIncognitoWindow() {
    try {
        const windows = await chrome.windows.getAll();

        // Check if ANY window is in incognito mode (not just focused)
        for (const window of windows) {
            if (window.incognito) {
                return true;
            }
        }

        return false;
    } catch (error) {
        console.error('Failed to check incognito status:', error);
        return false;
    }
}

/**
 * Check if extension is allowed to run in incognito mode
 */
async function isAllowedIncognitoAccess() {
    return new Promise((resolve) => {
        try {
            chrome.extension.isAllowedIncognitoAccess((isAllowed) => {
                if (chrome.runtime.lastError) {
                    console.error('Failed to check incognito access:', chrome.runtime.lastError);
                    resolve(false);
                } else {
                    resolve(isAllowed);
                }
            });
        } catch (error) {
            console.error('Exception checking incognito access:', error);
            resolve(false);
        }
    });
}

/**
 * Detect browser name from user agent
 */
function getBrowserName() {
    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes('firefox')) return 'firefox';
    if (userAgent.includes('edg/')) return 'edge';
    if (userAgent.includes('brave')) return 'brave';
    if (userAgent.includes('chrome')) return 'chrome';
    if (userAgent.includes('chromium')) return 'chromium';
    if (userAgent.includes('opera') || userAgent.includes('opr/')) return 'opera';
    if (userAgent.includes('vivaldi')) return 'vivaldi';
    return 'unknown';
}

/**
 * Send heartbeat to daemon
 */
async function sendHeartbeat() {
    try {
        const isIncognito = await isIncognitoWindow();
        const incognitoAllowed = await isAllowedIncognitoAccess();
        const windowCount = await getVisibleWindowCount();

        const response = await fetch(`${DAEMON_URL}/api/heartbeat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pid: browserPID,
                browser: getBrowserName(),
                incognito: isIncognito,
                incognito_enabled: incognitoAllowed,
                extension_id: chrome.runtime.id,
                window_count: windowCount,
                timestamp: Date.now()
            })
        });

        if (response.ok) {
            console.log('Heartbeat sent successfully');
            // Update badge to show connected
            chrome.action.setBadgeText({ text: '' });
            chrome.action.setBadgeBackgroundColor({ color: '#4CAF50' });
        } else {
            console.error('Heartbeat failed:', response.status);
            chrome.action.setBadgeText({ text: '!' });
            chrome.action.setBadgeBackgroundColor({ color: '#F44336' });
        }
    } catch (error) {
        console.error('Failed to send heartbeat:', error);
        chrome.action.setBadgeText({ text: '!' });
        chrome.action.setBadgeBackgroundColor({ color: '#F44336' });
    }
}

/**
 * Start the heartbeat loop
 */
function startHeartbeat() {
    // Clear any existing interval
    if (heartbeatIntervalId) {
        clearInterval(heartbeatIntervalId);
    }

    // Send immediately
    sendHeartbeat();

    // Then send every 30 seconds
    heartbeatIntervalId = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL);
}

/**
 * Fetch blocked sites from daemon
 */
async function fetchBlockedSites() {
    try {
        const response = await fetch(`${DAEMON_URL}/api/blocked-sites`);

        if (!response.ok) {
            console.error('Failed to fetch blocked sites:', response.status);
            return;
        }

        const data = await response.json();

        blocksData = (data.blocks || []).map((block) => ({
            ...block,
            media_blocked: block.media_blocked || []
        }));
        safeSearchEnabled = data.safe_search_enabled || false;

        console.log('Blocks data updated:', blocksData.length, 'blocks');
        console.log('Safe search enforcement:', safeSearchEnabled ? 'ENABLED' : 'DISABLED');

        // Store in local storage for popup access
        chrome.storage.local.set({
            blocksData: blocksData,
            safeSearchEnabled: safeSearchEnabled
        });

        await refreshMediaNetRequestRules();

    } catch (error) {
        console.error('Failed to fetch blocked sites:', error);
    }
}

/**
 * Start the rules refresh loop
 */
function startRulesRefresh() {
    // Clear any existing interval
    if (rulesRefreshIntervalId) {
        clearInterval(rulesRefreshIntervalId);
    }

    // Refresh every minute
    rulesRefreshIntervalId = setInterval(fetchBlockedSites, RULES_REFRESH_INTERVAL);
}

/**
 * Install declarativeNetRequest rules that cancel image/media/object (and
 * typical video/audio XHR) without touching main_frame navigations.
 *
 * Dynamic rules cover domain-only media patterns via initiatorDomains,
 * or a global catch-all when `*` is in media_blocked.
 * Session rules cover the current tab when its document URL matches
 * (path-specific patterns and allow-list evaluation). Catch-all also
 * installs session *allow* rules on allowed http(s) tabs.
 *
 * @param {Object<number, string>} [pendingNavigations] tabId → URL for
 *   navigations that have not yet committed (tabs.query still has the old URL).
 */
async function refreshMediaNetRequestRules(pendingNavigations) {
    if (!chrome.declarativeNetRequest) {
        console.warn('declarativeNetRequest unavailable — media blocking disabled');
        return;
    }

    try {
        const dynamicRules = buildDynamicMediaRules(blocksData);
        const existingDynamic = await chrome.declarativeNetRequest.getDynamicRules();
        await chrome.declarativeNetRequest.updateDynamicRules({
            removeRuleIds: existingDynamic.map((rule) => rule.id),
            addRules: []
        });
        // Add one-by-one so a single invalid rule (e.g. regex) does not abort the rest.
        let added = 0;
        for (const rule of dynamicRules) {
            try {
                await chrome.declarativeNetRequest.updateDynamicRules({ addRules: [rule] });
                added += 1;
            } catch (ruleError) {
                console.error('Media DNR dynamic rule failed:', rule.id, ruleError, rule);
            }
        }
        console.log('Media DNR dynamic rules added:', added, '/', dynamicRules.length);

        const urlByTab = pendingNavigations || {};
        const tabs = await chrome.tabs.query({});
        const mediaTabIds = [];
        const allowTabIds = [];
        const catchAll = hasMediaCatchAll(blocksData);
        const seen = new Set();

        const classifyTab = (tabId, url) => {
            if (url && shouldBlockMedia(url, blocksData).blocked) {
                mediaTabIds.push(tabId);
            } else if (catchAll && url && isHttpOrHttpsUrl(url) && !isProtectedBrowserUrl(url)) {
                allowTabIds.push(tabId);
            }
        };

        for (const tab of tabs) {
            if (tab.id == null) {
                continue;
            }
            seen.add(tab.id);
            classifyTab(tab.id, urlByTab[tab.id] || tab.url);
        }
        for (const [tabIdStr, url] of Object.entries(urlByTab)) {
            const tabId = Number(tabIdStr);
            if (seen.has(tabId)) {
                continue;
            }
            classifyTab(tabId, url);
        }
        const sessionRules = buildSessionMediaRules(mediaTabIds, null, catchAll ? allowTabIds : []);
        const existingSession = await chrome.declarativeNetRequest.getSessionRules();
        await chrome.declarativeNetRequest.updateSessionRules({
            removeRuleIds: existingSession.map((rule) => rule.id),
            addRules: sessionRules
        });

        console.log(
            'Media DNR rules updated:',
            dynamicRules.length, 'dynamic,',
            sessionRules.length, 'session (', mediaTabIds.length, 'tabs)'
        );
    } catch (error) {
        console.error('Failed to update media DNR rules:', error);
    }
}

/**
 * Check if a URL should be blocked.
 * Highest priority band among blocks whose blocked list matches; inside that
 * band the URL is allowed only if every one of them allows it.
 */
function shouldBlockUrl(url) {
    const result = evaluateUrlAgainstBlockField(url, blocksData, 'blocked');
    if (result.blocked) {
        console.log('🚫 URL blocked by block:', result.blockName, '→', url);
    } else if (result.allowed) {
        console.log('✅ URL allowed by all blocking blocks →', url);
    }
    return result;
}

/**
 * Check if we should attempt to block a navigation
 * Returns false if we recently blocked this URL in this tab
 */
function shouldAttemptBlock(tabId, url) {
    const now = Date.now();
    const cached = recentBlocks.get(tabId);

    if (cached && cached.url === url) {
        const timeSinceBlock = now - cached.timestamp;
        if (timeSinceBlock < BLOCK_CACHE_DURATION) {
            console.log('⏭️ Skipping duplicate block (already blocked', timeSinceBlock, 'ms ago)');
            return false;
        }
    }

    return true;
}

/**
 * Record that we blocked a URL in a tab
 */
function recordBlock(tabId, url) {
    recentBlocks.set(tabId, {
        url: url,
        timestamp: Date.now()
    });

    // Clean up old entries to prevent memory leak
    if (recentBlocks.size > 100) {
        const cutoff = Date.now() - BLOCK_CACHE_DURATION;
        for (const [tid, block] of recentBlocks.entries()) {
            if (block.timestamp < cutoff) {
                recentBlocks.delete(tid);
            }
        }
    }
}

/**
 * Enforce safe search on search engine URLs
 * Returns {redirect: boolean, newUrl: string} if redirect is needed
 */
function enforceSafeSearch(url) {
    try {
        const urlObj = new URL(url);
        const hostname = urlObj.hostname.toLowerCase();

        // Google Safe Search: safe=active
        if (hostname.includes('google.') && urlObj.pathname.startsWith('/search')) {
            if (urlObj.searchParams.get('safe') !== 'active') {
                urlObj.searchParams.set('safe', 'active');
                return { redirect: true, newUrl: urlObj.toString() };
            }
        }

        // Bing Safe Search: adlt=strict
        if (hostname.includes('bing.com') && urlObj.pathname.startsWith('/search')) {
            if (urlObj.searchParams.get('adlt') !== 'strict') {
                urlObj.searchParams.set('adlt', 'strict');
                return { redirect: true, newUrl: urlObj.toString() };
            }
        }

        // DuckDuckGo Safe Search: kp=1
        if (hostname.includes('duckduckgo.com')) {
            if (urlObj.searchParams.get('kp') !== '1') {
                urlObj.searchParams.set('kp', '1');
                return { redirect: true, newUrl: urlObj.toString() };
            }
        }

        return { redirect: false };
    } catch (error) {
        console.error('Error enforcing safe search:', error);
        return { redirect: false };
    }
}

/**
 * Handle navigation blocking for any webNavigation event
 */
async function handleNavigationBlock(details, eventName) {
    // Only handle main frame navigation
    if (details.frameId !== 0) {
        return;
    }

    // Safe search enforcement (before blocking check)
    if (safeSearchEnabled) {
        const safeSearchResult = enforceSafeSearch(details.url);
        if (safeSearchResult.redirect) {
            console.log(`🔍 [${eventName}] Enforcing safe search:`, details.url, '→', safeSearchResult.newUrl);
            try {
                await chrome.tabs.update(details.tabId, { url: safeSearchResult.newUrl });
                return;  // Stop here, don't check for blocking
            } catch (error) {
                console.error('Failed to enforce safe search:', error);
            }
        }
    }

    // Check deduplication cache
    if (!shouldAttemptBlock(details.tabId, details.url)) {
        return;
    }

    const result = shouldBlockUrl(details.url);

    if (result.blocked) {
        console.log(`🚫 [${eventName}] Blocking:`, result.hostname, 'matched pattern:', result.pattern);

        // Record this block to prevent duplicates
        recordBlock(details.tabId, details.url);

        // Redirect to blocked page
        const blockedUrl = chrome.runtime.getURL('blocked.html') +
            '?url=' + encodeURIComponent(details.url) +
            '&site=' + encodeURIComponent(result.hostname);

        try {
            await chrome.tabs.update(details.tabId, { url: blockedUrl });
        } catch (error) {
            console.error('Failed to redirect to blocked page:', error);
        }
    }
}

/**
 * PRIMARY: Catch navigation before it starts (URL bar, new tabs)
 */
chrome.webNavigation.onBeforeNavigate.addListener(async (details) => {
    // Session media rules must be in place before subresources of the new
    // document start (path-specific media patterns are tab-scoped).
    if (details.frameId === 0) {
        await refreshMediaNetRequestRules({ [details.tabId]: details.url });
    }
    await handleNavigationBlock(details, 'onBeforeNavigate');
});

/**
 * SECONDARY: Catch same-origin navigations that onBeforeNavigate misses
 */
chrome.webNavigation.onCommitted.addListener(async (details) => {
    await handleNavigationBlock(details, 'onCommitted');
});

/**
 * SAFETY NET: Catch anything that got committed but not blocked
 */
chrome.webNavigation.onDOMContentLoaded.addListener(async (details) => {
    await handleNavigationBlock(details, 'onDOMContentLoaded');
});

/**
 * CRITICAL: Catch SPA navigation (YouTube, Twitch, Reddit, etc.)
 * Fires when sites use history.pushState/replaceState for client-side routing
 */
chrome.webNavigation.onHistoryStateUpdated.addListener(async (details) => {
    if (details.frameId === 0) {
        await refreshMediaNetRequestRules({ [details.tabId]: details.url });
    }
    await handleNavigationBlock(details, 'onHistoryStateUpdated');
});

/**
 * Clean up block cache when tabs are closed
 */
chrome.tabs.onRemoved.addListener((tabId) => {
    recentBlocks.delete(tabId);
    refreshMediaNetRequestRules();
});

/**
 * Handle messages from popup or content scripts
 */
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'getStatus') {
        sendResponse({
            pid: browserPID,
            browser: getBrowserName(),
            blockedSitesCount: blocksData.length,
            daemonUrl: DAEMON_URL
        });
    } else if (message.action === 'refreshRules') {
        fetchBlockedSites().then(() => {
            sendResponse({ success: true, count: blocksData.length });
        });
        return true; // Keep channel open for async response
    } else if (message.action === 'checkUrl') {
        const result = shouldBlockUrl(message.url);
        sendResponse(result);
    }
});

/**
 * Handle alarms for periodic tasks (more reliable than setInterval in service workers)
 */
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === 'heartbeat') {
        sendHeartbeat();
    } else if (alarm.name === 'refreshRules') {
        fetchBlockedSites();
    }
});

// Create alarms for periodic tasks
chrome.alarms.create('heartbeat', { periodInMinutes: 0.5 }); // 30 seconds
chrome.alarms.create('refreshRules', { periodInMinutes: 1 }); // 1 minute

// Initial setup when service worker starts
initialize();
