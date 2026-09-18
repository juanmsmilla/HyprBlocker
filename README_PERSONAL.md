# Personal fork changelog — juanmsmilla/HyprBlocker

Notes for **this fork only**. Upstream is `TTeuber/HyprBlocker` (`upstream` remote).  
Local remotes: `origin` → this fork, `upstream` → TTeuber.

Do not assume upstream has any of the below unless we open a PR to them later.

---

## Summary of fork features

| Feature | What it does | Main commit(s) |
|---------|----------------|----------------|
| **Delay before unblock** | Queues deletes / loosens / delay-off for N minutes; cancelable | `5cafd53` |
| **Delay log + 1 MiB rotate** | `~/.config/hyprblocker/unblock_delay.log`, size-rotated | part of delay work + follow-ups |
| **Cancel delay in Blocks** | Actions column shows Cancel delay when a block change is pending | same era as delay |
| **Media-only blocking** | Page stays up; image/video/audio requests cancelled | PR #1 → `5eeaa0b` / `2da0572` |
| **Catch-all `*`** | `*` in blocked or media-blocked = every http(s) URL; allows are exceptions | this PR |

Related outside this repo: ask app `/focus` enables the HyprBlocker block named `focus` via `PUT /api/blocks/{id}` on `127.0.0.1:8765` (not a HyprBlocker CLI).

---

## 1. Cancelable delay before unblock

### Intent
When delay is on, weakening protections waits N minutes and can be canceled  
(impulse control). Tightening stays immediate.

### Behavior
- Settings: toggle + minutes; pending list + Cancel; delay log panel.
- Delayed: delete block, disable block, loosen rules, **turn delay off** or **lower minutes**.
- Immediate: enable block, add stricter rules, raise delay minutes, etc.
- New request for the same target restarts the full wait; Cancel aborts.
- Blocks UI: when a block has a pending delete/disable, Actions shows **Cancel delay**  
  only (edit/disable/delete hidden); status shows “Delay pending”.
- Settings cancel still works for settings-kind pending jobs.

### Main pieces
- `daemon/pending_unblock.py` — queue, apply job, event log, **1 MiB rotate**  
  (keeps `.1` `.2` `.3`)
- Config: `unblock_delay_enabled`, `unblock_delay_minutes`
- API: blocks/settings return `202` when queued; `/api/pending-unblocks`;  
  `/api/settings/unblock-delay` + `/log`
- Daemon job every ~5s applies due pending items
- Desktop Settings + Blocks + bridges in `api_client` / `main.py`

### Ops notes
- Log path: `~/.config/hyprblocker/unblock_delay.log` (append; not cleared on reboot).
- GUI “Failed to load delay settings” was caused by a **stale pyinstaller binary**  
  (web assets updated without `--build`). Fix: `./install.sh --build` so bridge  
  methods exist; delay load toasts now name which step failed (`status` / `pending` / `log`).

### Backup before prototype
`~/Work/focus/backups/hyprblocker-pre-delay-prototype-20260917-234126`

---

## 2. Media-only blocking (native extension)

### Intent
Block **media** from sites without blocking the **page** (GateSentry-style idea,  
no GateSentry / MITM).

### Behavior
- New field: **Media-blocked websites** → DB `websites_media_blocked`.
- Patterns: same style as other website rules (`youtube.com`, path patterns, …), plus literal `*` for every http(s) page.
- Page navigations are **not** redirected by this field.
- Extension cancels `image` / `media` / `object` (and typical video/audio fetches)  
  initiated by matching pages — including CDN hosts (e.g. `googlevideo.com`).
- Full **Blocked websites** behavior unchanged (still → `blocked.html`).
- Same host in both lists: navigation block still applies when you hit the site.

### Main pieces
- Daemon: column + migration; schemas; blocks CRUD; `/api/blocked-sites` →  
  `media_blocked[]`; grants overlay awareness
- Extension: `media.js`, DNR permissions, `background.js` refreshes rules on poll
- Desktop: BlockModal / AddRulesModal field; types + API client

### How runtime works (short)
1. Daemon exposes enabled blocks’ `media_blocked` patterns.
2. Extension builds Chromium **declarativeNetRequest** rules:
   - domain patterns → dynamic rules on **initiator** domains;
   - path patterns → tab-scoped session rules (DNR can’t filter initiator by path);
   - never cancels `main_frame` on this path.
3. Also cancels XHR/other URLs that look like video/audio (`.mp4`, `videoplayback`, …).

### Allow / grant caveat
Domain-wide allows can suppress host-wide media DNR. Path-only allows do **not**  
punch a hole in domain-wide media rules (fail-closed). Grants still go through the  
existing store overlay path.

### Verify
1. Reload unpacked extension (`~/.local/share/hyprblocker/extension/`).
2. Put host only in Media-blocked → page loads, media stripped.
3. Put host in Blocked websites → full-page block as before.
4. Restart daemon after pull so migration runs; rebuild desktop for GUI field  
   (`./install.sh --build`).

### PR
https://github.com/juanmsmilla/HyprBlocker/pull/1

---

## 3. Catch-all `*` (full-page + media)

### Intent
Default-deny the whole web, then allow exceptions. Same `*` in **Blocked websites**
(navigation → `blocked.html`) and **Media-blocked websites** (strip media, page stays).

### Behavior
- Literal `*` only (`http*` is not a catch-all).
- Allowed websites on that block are the exceptions (grants overlay still applies).
- Never matches `chrome://`, `chrome-extension://`, `about:`, `edge:`, or
  `localhost` / `127.0.0.1` (daemon `:8765`). Fail closed on real sites; fail open
  on internals.
- If `*` and specific hosts share a list, `*` dominates.
- Without `*`, host/path media DNR is unchanged (initiatorDomains + CDN).

### Verify
1. Reload unpacked extension.
2. Block with `websites_blocked: *` and `websites_allowed: openai.com` → random
   sites redirect to blocked.html; openai loads.
3. Block with `websites_media_blocked: *` and allow `openai.com` → random sites
   lose images/video; openai keeps media. `chrome://extensions` and
   `http://127.0.0.1:8765` still work.
4. Block without `*` is unchanged.

### PR
(this change)

---


## Local layout (Omarchy)

| What | Where |
|------|--------|
| Clone | `~/Work/focus/HyprBlocker` |
| Daemon | `systemctl --user` unit `hyprblocker`, `127.0.0.1:8765` |
| Extension (installed) | `~/.local/share/hyprblocker/extension/` |
| Desktop / tray | `~/.local/bin/hyprblocker`, `hyprblocker-tray` |
| Config / delay log | `~/.config/hyprblocker/` |

After pulling fork `main`: restart daemon → sync extension → rebuild desktop if  
needed → reload extension → reopen GUI.

---

## Intentionally not in this fork (yet)

- YouTube **channel-id** allows (plan only: `~/Work/focus/IDEA_youtube_channels.md`)
- GateSentry as a plugin / remote (rejected; media is native DNR instead)
- `hyprblockerctl` CLI (ask `/focus` uses HTTP; GUI binary has no enable subcommand)
