"""AI-brokered scoped-grant system (root-migration phase 3).

INTEGRATION HOOKS — everything the integrator must wire into the shared files
this package deliberately does not touch:

1. ``daemon/api/routes/grants.py`` (NEW route module, integrator-owned):
   - ``POST /api/grants/request`` — body {url|argv, reason, minutes, tier}:
     build ``GrantRequest.new(...)``; ``audit.record_request(req)``; run
     ``judge.evaluate(req, policy_text=policy.load_policy_text(),
     audit_entries=audit.read_entries(), client=OpenRouterClient(
     openrouter.load_user_tier_config()))`` (tier 1 ONLY — see R2 note below);
     ``audit.record_decision(...)`` with the returned stage+transcript; on
     allow for tier 1, apply ``tier1.plan_allowlist_grant(url,
     active_blocks, verdict.minutes, now)`` through the block CRUD session and
     schedule expiry via ``tier1.plan_allowlist_expiry`` at
     ``plan.expires_at`` (APScheduler job or scheduler-loop sweep).
     Tier-3 requests: after local denylist+ratelimit, drop ONLY the raw
     request JSON into ``paths.requests_dir()/"grants"`` — never a verdict;
     the root enforcer judges (with secure/grant_broker.json creds) and
     executes via ``executor.validate_command`` (R2).
   - ``GET /api/grants`` — list pending/active/expired grants (persist active
     tier-1 plans wherever the integrator chooses: a small ``grants`` DB
     table or a JSON sidecar; this package keeps no store).
   - ``POST /api/grants/breakglass`` → ``breakglass.request_release()``;
     ``GET`` → ``breakglass.read_status()``.
2. ``daemon/api/app.py``: ``app.include_router(grants_router)``.
3. ``/api/status`` (status route + schemas.py): add ``grants`` summary
   (active count, rate-limit remaining) and ``breakglass`` state from
   ``breakglass.read_status().state``.
4. ``daemon/main.py``: on-startup sweep + periodic job expiring overdue
   tier-1 grants (apply ``plan_allowlist_expiry`` mutations) so grants
   still expire across daemon restarts.
5. Desktop/tray UI: Grants page + break-glass control per DESIGN_SPEC "UI".

SECURITY INVARIANTS THE WIRING MUST PRESERVE:
- Denylist and ratelimit run BEFORE the judge (``judge.evaluate`` enforces
  this ordering — use it, don't call ``judge_request`` directly from routes).
- R2: ``openrouter.load_user_tier_config`` (env/.env) is for tier 1 only.
  The tier-3/root judge config comes from root-owned
  ``secure/grant_broker.json``, passed explicitly as ``OpenRouterConfig`` by
  the ENFORCER — never read in the user daemon, never from config.json.
- No verdict artifact may ever transit the group-writable ``requests/`` dir.
- Every request AND decision goes through ``audit`` (world-readable JSONL).
"""

from daemon.grants.models import (  # noqa: F401
    MAX_GRANT_MINUTES,
    Grant,
    GrantRequest,
    GrantTier,
    Verdict,
)
