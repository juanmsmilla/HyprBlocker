# Portfolio Polish — Remaining Work

Items from the portfolio review that still need doing, roughly in order of impact.

## 1. Screenshots & demo (highest impact — only you can do this)

The README has a placeholder block waiting for these (`<!-- SCREENSHOTS -->` near the top).

- [ ] Capture: Dashboard, block configuration modal, Statistics page, the blocked page in a browser, tray menu
- [ ] Save as `docs/screenshots/*.png` and uncomment the block in README.md
- [ ] Ideally: a short GIF/webm of navigating to a blocked site and getting stopped (e.g. `wf-recorder` + `ffmpeg -i out.mkv -vf "fps=12,scale=800:-1" demo.gif`)
- [ ] Consider setting the GIF as the GitHub social preview image (repo Settings → Social preview)

## 2. Commit and push the current changes

Nothing from this polish pass has been committed yet. Suggested grouping:

- [ ] `fix: match subdomains for domain-only patterns in daemon (parity with extension)` — `daemon/blocker.py` + tests
- [ ] `chore: add ruff config and fix lint across daemon, apps, and frontend`
- [ ] `ci: add GitHub Actions workflow (ruff, pytest, frontend build)`
- [ ] `docs: rewrite README, add LICENSE, watchdog and technical docs`

Going forward, use descriptive conventional-style commit messages — reviewers do skim `git log`.

## 3. Testing depth

Current suite covers the pure logic (pattern matching, scheduling). Worth adding:

- [ ] **API tests** with FastAPI's `TestClient` + an in-memory SQLite database: block CRUD, lock-mode rejection (403 when locked), `/api/blocks/{id}/strict` only accepts *stricter* rules
- [ ] **Extension logic tests** — `matchesPattern`/`matchesPatternWithPath` in `background.js` duplicate the daemon's logic in JS; extract to a module and test with `bun test` (also guards against daemon/extension matching drift, which is a real bug class — one was found and fixed during this review)
- [ ] `lock_manager.py` and `time_verifier.py` unit tests (mock NTP)
- [ ] Coverage reporting in CI (`pytest --cov` + a badge)

## 4. Packaging cleanup

- [ ] Remove the `sys.path.insert` hack from daemon modules: make `daemon/` a proper package (add `__init__.py`, use `from daemon.x import y` or relative imports, run as `python -m daemon.main`). Update the systemd unit, PyInstaller specs, and `tests/conftest.py` accordingly.
- [ ] Decide on the multi-`pyproject.toml` layout: either a proper uv workspace (`[tool.uv.workspace]` at root) or collapse to a single project. Right now root + daemon + desktop-app + tray each have their own, with duplicated dependency lists.
- [ ] Rename packages from `website-blocker` to `hyprblocker` for brand consistency (README/GitHub already say HyprBlocker; executables, systemd unit, and config paths still say website-blocker — a rename touches `install.sh`, the `.service` file, and config dir migration, so do it deliberately or document why the internal name differs).

## 5. Frontend polish

- [ ] Fix the remaining ESLint warning in `src/pages/Settings.tsx` (wrap `loadBrowserEnforcementStatus` / `loadSafeSearchStatus` in `useCallback` and add them to the `useEffect` deps)
- [ ] Consider `--max-warnings 0` in the lint script once warnings are at zero, so CI catches regressions

## 6. Portfolio presentation (outside the repo)

- [ ] Write a short "case study" blog post or portfolio page: the cat-and-mouse security story (each bypass you found and how you closed it) is the narrative interviewers will remember. Good material already exists in `docs/TECHNICAL_CONCEPTS.md` and `docs/WATCHDOG.md`.
- [ ] Pin the repo on your GitHub profile
- [ ] Add a one-line project blurb + link on your resume; mention concrete specifics (FastAPI daemon, watchdog process mesh, NTP-verified locks, Manifest v3 extension with native messaging)

## 7. Nice-to-haves

- [ ] GitHub release (v0.1.0) with built artifacts once packaging is settled
- [ ] `CONTRIBUTING.md` — even a short one signals professionalism
- [ ] Architecture diagram as an image (draw.io/excalidraw) to complement the ASCII art
- [ ] Demo mode or seed data script so screenshots/demos are reproducible
