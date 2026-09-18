# Personal fork notes — media-only blocking

This file tracks **Juan’s fork-only** change for native media / resource-type blocking  
(`juanmsmilla/HyprBlocker`, merged via PR #1 → `5eeaa0b`).  
Upstream `TTeuber/HyprBlocker` does not have this unless we open a PR later.

---

## What problem this solves

Normal **Blocked websites** kill the whole page (navigation → `blocked.html`).

**Media-blocked websites** leave the page open but cancel images, video, and audio  
the page tries to load (including CDN hosts like `googlevideo.com` when YouTube  
is the initiator).

Inspired by GateSentry MIME filtering — implemented **inside** the Chromium  
extension with `declarativeNetRequest`. No GateSentry / MITM proxy.

---

## How to use

1. Edit a block → field **Media-blocked websites** (newline-separated patterns).
2. Use the same pattern style as other website rules (`youtube.com`, `*.reddit.com`,  
   `youtube.com/shorts`, …).
3. Keep that host **out of** Blocked websites if you only want media stripped.
4. Enable the block. Reload the unpacked extension after updating files  
   (`chrome://extensions` → Load unpacked / Reload from  
   `~/.local/share/hyprblocker/extension/`).

Example:

| Field | Value |
|-------|--------|
| Blocked websites | *(empty or other sites)* |
| Media-blocked websites | `youtube.com` |
| Enabled | on |

→ YouTube UI loads; images / video / audio requests are cancelled.

If the same host is also in **Blocked websites**, full-page block still wins for  
navigation (you never stay on the site long enough for media rules to matter).

---

## What we changed (files)

### Daemon / data

| Piece | Change |
|-------|--------|
| `daemon/database.py` | New column `websites_media_blocked` (TEXT, newline list) |
| `daemon/migrations.py` | `migrate_websites_media_blocked` — `ALTER TABLE` if missing |
| `daemon/api/schemas.py` | Create/update/response fields for the new column |
| `daemon/api/routes/blocks.py` | Create / update / strict-add paths include media list |
| `daemon/api/routes/status.py` | `/api/blocked-sites` each block includes `media_blocked: []` |
| `daemon/grants/store.py` | Grants can overlay onto media-matching blocks’ `allowed[]` |

### Extension

| Piece | Change |
|-------|--------|
| `extension/manifest.json` | Permissions: `declarativeNetRequest`, `declarativeNetRequestWithHostAccess` |
| `extension/media.js` | Compile DNR rules from `media_blocked` + allows; match helpers |
| `extension/media.test.js` | Unit tests for compilation / intersection |
| `extension/background.js` | After fetching blocked-sites, refresh DNR dynamic + session rules |

### Desktop

| Piece | Change |
|-------|--------|
| `BlockModal` / `AddRulesModal` | “Media-blocked websites” textarea |
| Frontend types + `api_client` / `main.py` | Pass `websites_media_blocked` through |

### Docs / tests

- `README.md` — short usage note for the field  
- API / migration / grant tests extended  

---

## How it works (runtime)

```
Daemon (enabled blocks)
  → GET /api/blocked-sites
      blocks[].blocked[]        → full-page navigation block (existing)
      blocks[].media_blocked[]  → media-only patterns (new)
      blocks[].allowed[]        → allows / grants

Extension (poll + on update)
  → webNavigation: unchanged full-page redirect if blocked[] matches
  → declarativeNetRequest:
       • Domain patterns → dynamic rules on initiatorDomains
         (cancel image / media / object from that page, even if
          the file URL is on another host, e.g. googlevideo)
       • Also cancel XHR/other URLs that look like video/audio
         (.mp4, videoplayback, m3u8, …)
       • Path patterns (e.g. youtube.com/shorts) → session rules
         scoped to open tabs whose document URL matches
       • Never cancels main_frame (document) on this path
```

**Allow / grant caveat:** domain-wide allows can suppress host-wide media DNR.  
Path-only allows do **not** punch a hole in domain-wide media rules (DNR cannot  
exclude by initiator path) — fail-closed. Grants still attach via the existing  
full-page / store overlay path.

---

## Commits / PR

- PR: https://github.com/juanmsmilla/HyprBlocker/pull/1  
- Merge commit: `5eeaa0b`  
- Feature commit: `2da0572` — `feat: native media/resource-type blocking in the Chromium extension`

---

## Local install checklist (Omarchy)

After pulling `main`:

1. `systemctl --user restart hyprblocker` (runs migration)
2. Sync extension → `~/.local/share/hyprblocker/extension/`
3. Rebuild desktop if editing from GUI (`./install.sh --build`)
4. Reload unpacked extension in Chromium
5. Reopen `hyprblocker` GUI

Ask’s `/focus` only sets `enabled=true` on the block named `focus`; it does not  
change media vs page lists.
