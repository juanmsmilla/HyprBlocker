"""Tier-3 constrained-grammar command validation. Validation ONLY — no execution.

The root enforcer (``enforcer/``) is the only component that ever executes an
approved command; this module is the shared, pure grammar both sides agree on:
the judge picks from it, and the enforcer re-validates against it immediately
before exec (never trusting anything that transited the group-writable
``requests/`` directory — hardening R2).

The grammar is a closed set of argv TEMPLATES: literal tokens plus typed
placeholders with fullmatch regexes. There is NO free-form escape hatch — no
``bash``, no ``sh -c``, no shell interpretation of any kind. A request either
matches one template exactly (same arity, same literals, placeholder values
passing their regex AND the denylist) or it is rejected.

Validation returns the template's CANONICAL absolute-path argv, so even a
matching request cannot smuggle in a lookalike binary path.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from daemon.grants import denylist


class CommandRejected(ValueError):
    """The requested argv does not fit the grammar. Callers deny."""


@dataclass(frozen=True)
class Placeholder:
    """A typed template slot; the value must fullmatch ``pattern``."""

    name: str
    pattern: re.Pattern[str]


# Conservative Arch package-name charset. Deliberately excludes anything a
# shell (which we never invoke anyway) or pacman itself could misparse — and
# a leading '-' can never be mistaken for a flag.
PACKAGE_NAME = Placeholder("package", re.compile(r"[a-z0-9][a-z0-9@._+-]{0,63}"))


@dataclass(frozen=True)
class CommandTemplate:
    """One allowlisted command shape."""

    name: str
    description: str
    argv: tuple[str | Placeholder, ...]


# The closed grammar. Growing it is a code change (root-owned once installed),
# never a runtime/config decision.
GRAMMAR: tuple[CommandTemplate, ...] = (
    CommandTemplate(
        name="pacman-upgrade",
        description="Full system upgrade (pacman -Syu)",
        argv=("/usr/bin/pacman", "-Syu", "--noconfirm"),
    ),
    CommandTemplate(
        name="pacman-install",
        description="Install one package from the repositories",
        argv=("/usr/bin/pacman", "-S", "--noconfirm", PACKAGE_NAME),
    ),
    CommandTemplate(
        name="flatpak-update",
        description="Update all flatpaks",
        argv=("/usr/bin/flatpak", "update", "-y"),
    ),
)


@dataclass(frozen=True)
class ValidatedCommand:
    """A request that matched the grammar — canonical argv, ready to describe."""

    template_name: str
    description: str
    argv: tuple[str, ...]


def _literal_matches(literal: str, requested: str, position: int) -> bool:
    """Literal token comparison; argv[0] also accepts the bare basename."""
    if requested == literal:
        return True
    if position == 0 and "/" not in requested:
        return requested == literal.rsplit("/", 1)[-1]
    return False


def _match_template(template: CommandTemplate, requested: Sequence[str]) -> tuple[str, ...] | None:
    if len(requested) != len(template.argv):
        return None
    canonical: list[str] = []
    for i, (slot, value) in enumerate(zip(template.argv, requested, strict=True)):
        if isinstance(slot, Placeholder):
            if not slot.pattern.fullmatch(value):
                return None
            canonical.append(value)
        else:
            if not _literal_matches(slot, value, i):
                return None
            canonical.append(slot)
    return tuple(canonical)


def validate_command(requested: Sequence[str]) -> ValidatedCommand:
    """Validate a requested argv against the grammar.

    Returns the canonicalized command or raises :class:`CommandRejected`.
    Every argument (including placeholder values) is additionally screened
    through the hardcoded denylist, so e.g. a package name referencing the
    blocker or systemd can never be approved.
    """
    requested = [str(arg) for arg in requested]
    if not requested:
        raise CommandRejected("Empty command")

    hits = denylist.find_denials(" ".join(requested))
    if hits:
        raise CommandRejected(f"Command hits denylist: {', '.join(hits)}")
    if any("hyprblocker" in arg.lower() for arg in requested):
        raise CommandRejected("Command references the blocker itself")

    for template in GRAMMAR:
        canonical = _match_template(template, requested)
        if canonical is not None:
            return ValidatedCommand(
                template_name=template.name,
                description=template.description,
                argv=canonical,
            )
    raise CommandRejected(f"No grammar template matches: {requested[0]!r} ({len(requested)} args)")


def describe(command: ValidatedCommand) -> str:
    """Human-readable one-liner for audit entries and UI confirmation."""
    return f"{command.description}: `{' '.join(command.argv)}`"


def grammar_summary() -> list[str]:
    """The allowed command shapes, for the UI and the judge prompt."""
    lines = []
    for template in GRAMMAR:
        shape = " ".join(
            f"<{slot.name}>" if isinstance(slot, Placeholder) else slot for slot in template.argv
        )
        lines.append(f"{template.name}: {shape} — {template.description}")
    return lines
