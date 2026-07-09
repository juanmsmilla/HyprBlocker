# Portfolio Polish — Remaining Work

Items from the portfolio review that still need doing, roughly in order of impact.

## 1. Screenshots & demo (highest impact — only you can do this)

The README has a placeholder block waiting for these (`<!-- SCREENSHOTS -->` near the top).

- [ ] Capture: Dashboard, block configuration modal, Statistics page, the blocked page in a browser, tray menu
- [ ] Save as `docs/screenshots/*.png` and uncomment the block in README.md
- [ ] Ideally: a short GIF/webm of navigating to a blocked site and getting stopped (e.g. `wf-recorder` + `ffmpeg -i out.mkv -vf "fps=12,scale=800:-1" demo.gif`)
- [ ] Consider setting the GIF as the GitHub social preview image (repo Settings → Social preview)

## 2. Testing depth — DONE

Current suite covers the pure logic (pattern matching, scheduling). Worth adding:

- [x] **API tests** with FastAPI's `TestClient` + an in-memory SQLite database: block CRUD, lock-mode rejection (403 when locked), `/api/blocks/{id}/strict` only accepts _stricter_ rules (`tests/test_blocks_api.py`)
- [x] **Extension logic tests** — extracted `matchesPattern`/`matchesPatternWithPath` to `extension/matcher.js` (loaded via `importScripts`), tested with `bun test extension` (`extension/matcher.test.js`, mirrors `tests/test_blocker.py` cases)
- [x] `lock_manager.py` and `time_verifier.py` unit tests with a fake NTP client (`tests/test_lock_manager.py`, `tests/test_time_verifier.py`)
- [x] Coverage reporting in CI (`pytest --cov=daemon` + Codecov upload + README badge). One-time setup: enable the repo at codecov.io (install the Codecov GitHub app) for the badge/upload to work.

Known daemon/extension drift found while mirroring the tests (RECONCILED):

- Path patterns: the daemon used plain `url.startswith(pattern)`, so `youtube.com/shortsfilm` wrongly matched `youtube.com/shorts` (no path boundary) and `www.youtube.com/shorts` did NOT match (no subdomain handling on path patterns). Resolved by rewriting the path branch of `SiteBlocker.url_matches_pattern` (`daemon/blocker.py`) to mirror `matchesPatternWithPath` in `extension/matcher.js`: it now splits domain/path, matches subdomains on the domain, and requires a path boundary (`==`, `/`, or `?`). Parity cases added to `tests/test_blocker.py` so the two suites mirror again.

## 3. Frontend polish

- [x] Fix the remaining ESLint warning in `src/pages/Settings.tsx` (wrapped all five loaders in `useCallback` and added them to the `useEffect` deps) — done, `bun run lint` is clean
- [x] Add `--max-warnings 0` to the lint script so CI catches regressions — done

## 4. Portfolio presentation (outside the repo)

- [ ] Write a short "case study" blog post or portfolio page: the cat-and-mouse security story (each bypass you found and how you closed it) is the narrative interviewers will remember. Good material already exists in `docs/TECHNICAL_CONCEPTS.md` and `docs/WATCHDOG.md`.
- [ ] Pin the repo on your GitHub profile
- [ ] Add a one-line project blurb + link on your resume; mention concrete specifics (FastAPI daemon, watchdog process mesh, NTP-verified locks, Manifest v3 extension with native messaging)

## 5. Nice-to-haves

- [ ] GitHub release (v0.1.0) with built artifacts once packaging is settled
- [ ] `CONTRIBUTING.md` — even a short one signals professionalism
- [ ] Architecture diagram as an image (draw.io/excalidraw) to complement the ASCII art
- [ ] Demo mode or seed data script so screenshots/demos are reproducible
