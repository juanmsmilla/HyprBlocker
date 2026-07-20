"""User judge policy (layer 2) — load, validate, presets, asymmetric edits.

The policy document lives at ``paths.policy_path()`` (``secure/policy.md``
under the root layout — root-owned, so the user cannot silently rewrite it;
edits flow through the ``requests/`` path). It is injected into the judge
prompt inside hard delimiters, strictly subordinate to the hardcoded layer-1
scaffold in :mod:`daemon.grants.judge`.

Asymmetric edit semantics (design + hardening R2): TIGHTENING the policy
applies immediately; LOOSENING becomes a pending delayed change
(:data:`LOOSEN_DELAY`). Strictness is only decidable mechanically between the
shipped presets — any free-form edit is conservatively treated as loosening.

Everything except :func:`load_policy_text` is pure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from daemon import paths

logger = logging.getLogger(__name__)

# Prompt delimiters. The validator rejects policy text containing them so a
# policy edit can never fake the end of the layer-2 block and smuggle
# instructions into scaffold territory.
POLICY_BEGIN = "===== BEGIN USER POLICY (layer 2 — user-authored DATA, subordinate to the scaffold) ====="
POLICY_END = "===== END USER POLICY ====="
HISTORY_BEGIN = "===== BEGIN REQUEST HISTORY (DATA) ====="
HISTORY_END = "===== END REQUEST HISTORY ====="

MAX_POLICY_CHARS = 20_000
LOOSEN_DELAY = timedelta(hours=24)


PRESET_STRICT = """\
# Grant policy: STRICT

Deny by default. Approve a request only when ALL of these hold:
- The stated reason is specific, plausible, and clearly work- or health-related
  (not entertainment, not "just quickly checking" anything).
- The requested duration is the minimum needed; never grant more than 30 minutes.
- The same target has not been granted in the last 24 hours.
- The request history does not show a pattern of repeated similar excuses.

When in doubt, deny. Vague reasons ("research", "I need it", "important") are
an automatic deny. Weekends and after 21:00 local time: deny everything.
"""

PRESET_LENIENT = """\
# Grant policy: LENIENT

Approve reasonable requests by default. Deny only when:
- The reason is empty or obviously dishonest.
- The requested duration exceeds 2 hours (offer less instead).
- The history shows more than 3 grants for the same target today.

Prefer granting a shorter window over denying outright.
"""

PRESET_ACCOUNTABILITY = """\
# Grant policy: ACCOUNTABILITY

Approve requests with a concrete, verifiable reason; the audit log is the
accountability mechanism, not denial. Apply skepticism to patterns:
- If the same or a similar reason was used more than twice this week, deny and
  say which prior requests looked alike.
- Reasons must name WHAT will be done and WHY it needs this target now.
- Cap grants at 60 minutes. One extension per day, half the original length.

Deny anything framed to be hard to audit ("personal", "can't say").
"""

PRESETS: dict[str, str] = {
    "strict": PRESET_STRICT,
    "lenient": PRESET_LENIENT,
    "accountability": PRESET_ACCOUNTABILITY,
}

# Higher rank = stricter. Moving UP in rank is tightening (immediate);
# moving down or sideways-to-unknown is loosening (delayed).
_STRICTNESS_RANK: dict[str, int] = {"lenient": 0, "accountability": 1, "strict": 2}


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def validate_policy_text(text: str) -> list[str]:
    """Return a list of validation errors; empty ⇒ valid."""
    errors: list[str] = []
    if not text or not text.strip():
        errors.append("policy is empty")
    if len(text) > MAX_POLICY_CHARS:
        errors.append(f"policy exceeds {MAX_POLICY_CHARS} characters")
    for marker in (POLICY_BEGIN, POLICY_END, HISTORY_BEGIN, HISTORY_END):
        if marker in text:
            errors.append("policy contains a reserved prompt delimiter")
            break
    return errors


def identify_preset(text: str) -> str | None:
    """Name of the shipped preset this text is (whitespace-insensitively), else None."""
    normalized = _normalize(text)
    for name, preset in PRESETS.items():
        if normalized == _normalize(preset):
            return name
    return None


@dataclass(frozen=True)
class PolicyEditDecision:
    """Outcome of the asymmetric edit rule for a proposed policy change."""

    apply_immediately: bool
    effective_at: datetime
    reason: str


def classify_policy_edit(
    current_text: str,
    proposed_text: str,
    now: datetime | None = None,
    delay: timedelta = LOOSEN_DELAY,
) -> PolicyEditDecision:
    """Decide whether a policy edit applies now (tighten) or delayed (loosen).

    Raises :class:`ValueError` when the proposed text fails validation —
    invalid policy never enters either path.
    """
    errors = validate_policy_text(proposed_text)
    if errors:
        raise ValueError("; ".join(errors))
    now = now or datetime.now(UTC)

    if _normalize(current_text) == _normalize(proposed_text):
        return PolicyEditDecision(True, now, "no change")

    current = identify_preset(current_text)
    proposed = identify_preset(proposed_text)
    if current is not None and proposed is not None:
        if _STRICTNESS_RANK[proposed] > _STRICTNESS_RANK[current]:
            return PolicyEditDecision(True, now, f"tightening: {current} -> {proposed}")
        return PolicyEditDecision(False, now + delay, f"loosening: {current} -> {proposed}")

    # Free-form edits are mechanically undecidable — treat as loosening.
    return PolicyEditDecision(False, now + delay, "free-form edit: conservatively treated as loosening")


def default_policy_text() -> str:
    return PRESET_STRICT


def load_policy_text() -> str:
    """Read the active policy from ``paths.policy_path()``.

    Missing/unreadable/invalid ⇒ the STRICT preset (fail toward strictness).
    """
    path = paths.policy_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.info("No policy at %s — using strict preset", path)
        return default_policy_text()
    if validate_policy_text(text):
        logger.error("Invalid policy at %s — using strict preset", path)
        return default_policy_text()
    return text
