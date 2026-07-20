"""AI-brokered scoped-grant API (tier 1) + break-glass control.

Tier 1 (blocker-rule exceptions) is the day-to-day win and needs no root: a
request runs through the denylist → ratelimit → judge pipeline, and on *allow*
an entry is written to the grant store, which the ``/api/blocked-sites`` endpoint
overlays onto the browser's allowlist at read time (see
:mod:`daemon.grants.store`). Nothing here mutates block rows (review M6).

Tier 3 (root command execution) is intentionally NOT served here — it belongs to
the root enforcer, which judges with its own root-owned credentials. This route
never touches the root credential or executes anything privileged.

The judge client is built lazily via :func:`_judge_client` so tests can inject a
stub and never hit the network.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from daemon.grants import audit, judge, openrouter, policy, ratelimit, store
from daemon.grants import breakglass as breakglass_mod
from daemon.grants.models import MAX_GRANT_MINUTES, GrantRequest, GrantTier, Verdict
from daemon.grants.tier1 import normalize_url_pattern

from ..schemas import (
    ActiveGrantResponse,
    BreakGlassResponse,
    GrantDecisionResponse,
    GrantRequestBody,
    GrantsListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/grants", tags=["grants"])


def _enforced_target(request_url: str, verdict_scope: str) -> str:
    """The URL the overlay should actually grant — the narrower of request/scope.

    The overlay key is derived from this. We use the judge's ``scope`` when it is
    non-empty and no broader than the request (its normalized pattern starts with
    the request's — i.e. same host, equal-or-deeper path), otherwise the raw
    request URL. This guarantees a grant can never enforce something broader than
    both the user asked for and the judge approved.
    """
    scope = (verdict_scope or "").strip()
    if not scope:
        return request_url
    req_pat = normalize_url_pattern(request_url)
    scope_pat = normalize_url_pattern(scope)
    # scope is no broader than the request iff it is the request pattern or a
    # deeper path under the same host.
    if scope_pat == req_pat or scope_pat.startswith(req_pat + "/"):
        return scope
    return request_url


def _judge_client():
    """Build the tier-1 (user-daemon) judge client, or None if unconfigured.

    Overridable in tests. Returns None when no OpenRouter key is available, which
    the caller turns into a fail-closed deny (never an exception to the user).
    """
    try:
        return openrouter.OpenRouterClient(openrouter.load_user_tier_config())
    except openrouter.OpenRouterError as e:
        logger.warning("Tier-1 judge unavailable: %s", e)
        return None


@router.post("/request", response_model=GrantDecisionResponse)
async def request_grant(body: GrantRequestBody):
    """Request a time-limited blocker-rule exception (tier 1)."""
    now = datetime.now(UTC)
    minutes = max(1, min(body.minutes, MAX_GRANT_MINUTES))
    request = GrantRequest.new(
        tier=GrantTier.BLOCK_EXCEPTION,
        target=body.url,
        reason=body.reason,
        minutes=minutes,
        now=now,
    )
    audit.record_request(request)

    client = _judge_client()
    if client is None:
        verdict = Verdict.deny("Judge unavailable (no broker configured) — denied (fail closed)")
        stage, transcript = "judge", []
    else:
        verdict, transcript, stage = judge.evaluate(
            request,
            policy_text=policy.load_policy_text(),
            audit_entries=audit.read_entries(),
            client=client,
            now=now,
        )
    audit.record_decision(request, verdict, stage, transcript)

    expires_at: str | None = None
    if verdict.allowed:
        granted_minutes = min(verdict.minutes, MAX_GRANT_MINUTES)
        expiry = now + timedelta(minutes=granted_minutes)
        # Enforce the judge's (possibly narrowed) scope, never broader than the
        # request. If the judge narrowed the target — e.g. request "youtube.com",
        # verdict scope "youtube.com/watch?v=x" — the overlay must grant only the
        # narrower pattern, not the whole domain (review finding).
        enforced_url = _enforced_target(body.url, verdict.scope)
        grant = store.make_active_grant(
            grant_id=request.id,
            url=enforced_url,
            scope=verdict.scope,
            reason=verdict.reason,
            granted_at=now,
            expires_at=expiry,
        )
        store.add_grant(grant, now)
        expires_at = expiry.isoformat()

    return GrantDecisionResponse(
        decision=verdict.decision,
        stage=stage,
        reason=verdict.reason,
        granted_minutes=verdict.minutes if verdict.allowed else 0,
        expires_at=expires_at,
    )


@router.get("", response_model=GrantsListResponse)
async def list_grants():
    """List active (unexpired) tier-1 grants and remaining rate-limit budget."""
    now = datetime.now(UTC)
    active = store.active_grants(store.load(), now)
    rl = ratelimit.check(audit.read_entries(), now, tier=GrantTier.BLOCK_EXCEPTION)
    return GrantsListResponse(
        active=[
            ActiveGrantResponse(
                id=g.id,
                url=g.url,
                scope=g.scope,
                reason=g.reason,
                granted_at=g.granted_at,
                expires_at=g.expires_at,
            )
            for g in active
        ],
        rate_limit_remaining=rl.remaining,
    )


@router.post("/breakglass", response_model=BreakGlassResponse)
async def request_breakglass():
    """Start the non-cancelable break-glass countdown (drops the trigger file)."""
    status = breakglass_mod.request_release()
    return _breakglass_response(status)


@router.get("/breakglass", response_model=BreakGlassResponse)
async def get_breakglass():
    """Read the current break-glass status."""
    return _breakglass_response(breakglass_mod.read_status())


def _breakglass_response(status) -> BreakGlassResponse:
    return BreakGlassResponse(
        state=status.state,
        triggered_at=status.requested_at.isoformat() if status.requested_at else None,
        release_at=status.release_at.isoformat() if status.release_at else None,
    )
