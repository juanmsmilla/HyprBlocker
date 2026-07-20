"""Hardcoded denylist — the reject-before-judge boundary.

"The AI decides *within* the sandbox, never *about* it." This module is a pure
predicate that runs BEFORE the judge ever sees a request: anything referencing
the blocker's own installation, state, services, privilege plumbing, or an
attempt to disable/modify enforcement or the judge policy is denied
deterministically, with no LLM involved (design invariant 4 + hardening R2).

Pure logic only — no I/O, no network. Scans every text surface of a request
(target, reason, argv) case-insensitively. Deny-biased by design: a false
positive costs the user a re-worded request; a false negative costs the
sandbox.
"""

from __future__ import annotations

import re

from daemon.grants.models import GrantRequest

# Each rule is (label, compiled pattern). Labels surface in audit entries and
# deny verdicts so the user can see exactly which rule fired.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("blocker code directory", re.compile(r"/opt/hyprblocker", re.IGNORECASE)),
    ("blocker state directory", re.compile(r"/var/lib/hyprblocker", re.IGNORECASE)),
    ("systemd", re.compile(r"\bsystemd\b|\bsystemctl\b|/etc/systemd|/usr/lib/systemd", re.IGNORECASE)),
    ("sudoers", re.compile(r"\bsudoers?\b|\bvisudo\b|/etc/sudoers", re.IGNORECASE)),
    (
        "hyprblocker unit/service",
        re.compile(r"hyprblocker[-.](service|enforcer|breakglass|timer)", re.IGNORECASE),
    ),
    (
        "hyprblocker group / membership tools",
        re.compile(
            r"hyprblocker\s+group|\bgroup\s+hyprblocker\b"
            r"|\bgpasswd\b|\bgroupmod\b|\bgroupdel\b|\bgroupadd\b|\busermod\b|\buserdel\b",
            re.IGNORECASE,
        ),
    ),
    ("credential file", re.compile(r"root_credential|\bcredentials?\b", re.IGNORECASE)),
    ("grant broker secrets", re.compile(r"grant_broker", re.IGNORECASE)),
    (
        "secure state files",
        re.compile(
            r"\b(lock|breakglass|enforcement|enforcer_state)\.json\b|\bpolicy\.md\b|\bgrants\.log\b",
            re.IGNORECASE,
        ),
    ),
    (
        "enforcement tampering",
        re.compile(
            r"\b(disable|bypass|stop|kill|remove|uninstall|weaken|circumvent|pause|suspend|turn\s+off)\b"
            r"[^.\n]{0,60}\b(enforc\w*|blocker|blocking|watchdog|daemon|lock\w*|extension)",
            re.IGNORECASE,
        ),
    ),
    (
        "policy/instruction override",
        re.compile(
            r"\b(ignore|override|disregard|forget|reinterpret|rewrite|modify|edit|change|replace|update)\b"
            r"[^.\n]{0,60}\b(polic\w*|instructions?|rules?|scaffold|meta[- ]?rules?|system\s+prompt|prompt)",
            re.IGNORECASE,
        ),
    ),
    ("settings lock", re.compile(r"settings[\s_-]*lock", re.IGNORECASE)),
)


def find_denials(*texts: str | None) -> list[str]:
    """Return the labels of every denylist rule matched by any of ``texts``.

    Empty result means the texts are clean. Order follows rule order; each
    label appears at most once.
    """
    hits: list[str] = []
    for label, pattern in _RULES:
        for text in texts:
            if text and pattern.search(text):
                hits.append(label)
                break
    return hits


def check_request(request: GrantRequest) -> list[str]:
    """Scan every text surface of a grant request. Empty list ⇒ clean."""
    argv_text = " ".join(request.argv) if request.argv else None
    return find_denials(request.target, request.reason, argv_text)


def is_denied(request: GrantRequest) -> bool:
    """True if the request must be rejected before the judge ever runs."""
    return bool(check_request(request))
