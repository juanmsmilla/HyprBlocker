# Desktop App UI Improvements

Backlog from a UI review of the desktop app (July 2026). The first section records
what was already implemented so this document stands alone; everything below it is
still open, roughly ordered by impact.

## Done (July 2026)

- **Dashboard** shows which blocks are active right now vs. scheduled vs. off, with
  time windows ("Until 17:00", "Weekdays, 09:00–17:00"), computed client-side by
  `frontend/src/lib/blocks.ts` (mirrors `daemon/scheduler.py` semantics). Status
  headline is green/red based on daemon state.
- **Statistics** got real content: a 14-day bar chart, "Most Blocked" top-targets
  list, and a recent-events feed, backed by a new `GET /api/stats/details` endpoint
  (tested in `tests/test_stats_api.py`). Gradient tiles replaced with flat cards.
  Chart color `--color-chart: #4a8ecb` was validated for contrast/chroma against
  the card surface.
- **Blocks table** status column now shows Active now / Scheduled / Off instead of
  Enabled/Disabled. Native `confirm()` replaced with a themed `ConfirmDialog` that
  names the block being deleted. Empty state has an "Add Your First Block" button.
- **Daemon-down banner** in the Layout with the `systemctl` command to restart.
- **Loading states**: pages use the context `loading` flag (`PageLoading` spinner)
  instead of flashing zeros.
- **Browsers page** grace-period countdown is now server-driven (polls
  `GET /api/grace-period`), so it survives navigation and reflects grace periods
  started from the tray. Blocks/browsers joined the 5-second context poll. The
  extension-setup card hides once all browsers are compliant.
- **Fixes along the way**: block events now stored in local time (was UTC, which
  shifted daily stat windows); `/api/stats` week/month math uses `timedelta`
  (old `.replace()` logic could crash on month boundaries); Pydantic class-based
  `Config` deprecation removed; browser icon mapping deduplicated; initial page
  can be set via URL hash (`#stats`), useful for dev deep-links.

## Open items

### 1. Compute lock times server-side

Both the settings lock (`Settings.tsx`) and block locks (`LockModal.tsx`) compute
`lock_until` from the **local clock** and send an absolute timestamp, while the
whole point of the lock system is NTP-verified time. `BlocksTable` also evaluates
"is locked" with `new Date()`.

- Add duration-based lock endpoints (send `duration_seconds`, daemon computes
  `lock_until` from NTP-verified time).
- Include `locked: bool` in the `/api/blocks` response so the UI doesn't need a
  `lock-status` round trip before every edit/toggle/delete click.

### 2. Refactor Settings.tsx (~560 lines)

Five near-identical load/toggle/toast handler pairs. Extract:

- a `useSetting(getter, setter)` hook,
- a `SettingToggle` component (and use a real switch control, not a checkbox),
- a `DurationInput` (number + unit select) — currently duplicated three times
  (lock, extend, LockModal),
- one "Settings are locked" banner at the top of the page instead of a notice
  repeated in every card.

### 3. BlockModal validation

You can currently save a time-range block with no days selected, or a block with
no rules at all. Add inline validation and hints (e.g. warn on `https://`
prefixes or full URLs pasted into the websites field, since patterns are
domain/path based).

### 4. Blocks table interaction polish

Three text buttons per row is heavy. Use a toggle switch for enabled and icon
buttons for edit/delete. Make the rules column expandable (or a tooltip) so the
rules of a block are visible without opening the edit modal.

### 5. Real browser logos

Emoji browser icons look unpolished for a portfolio project. Replace with small
inline SVG logos (or a neutral monochrome glyph set) in `lib/api.ts:getBrowserIcon`.

### 6. Statistics depth

- `block_events` has no `block_id`, so events can't be attributed to the block
  that caused them. Adding it would enable a per-block breakdown.
- Hour-of-day histogram ("when do I get blocked most?").
- Make the stat-tile ranges consistent with the timeline (the chart is 14 days,
  tiles are today/week/month).

### 7. Dashboard/Browsers overlap

The Dashboard browser card duplicates the Browsers page. Slim it to a one-line
compliance summary that links to the Browsers page.

### 8. Accessibility

- `Modal` has no focus trap and doesn't restore focus on close.
- Icon-only controls (modal close X, lock button in the table) need `aria-label`s.
- Badge colors are the only distinction between some states for colorblind users —
  the icons added on the Dashboard help; do the same in the table.

### 9. Frontend tests

There is no frontend test setup. `lib/blocks.ts` re-implements the daemon's
schedule logic and would drift silently — a small vitest suite mirroring
`tests/test_scheduler.py` cases would catch that.

### 10. Misc

- Sidebar "Website Blocker" title could use the app icon; consider showing the
  active-block count as a badge on the Blocks nav item.
- `api_client.py` / `main.py` still have verbose `print()` debugging in
  `update_block` paths; route through `logging` or remove.
- Settings "About" card hardcodes version 1.0.0; read it from one source of truth.
