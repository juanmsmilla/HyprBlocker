"""Thin OpenRouter chat client over stdlib urllib. No new dependencies.

Credential handling (hardening R2 — read carefully before wiring):

- ROOT tier (tier-3, executed by the root enforcer): the model name, base URL,
  and API key MUST be injected by the caller from the root-owned
  ``secure/grant_broker.json`` (root, 0600). They must NEVER come from
  ``config.json``, a user-writable ``.env``, or process environment inherited
  from the user — any user-writable source would let the user point the "judge"
  at a server that always answers ``{"decision": "allow"}`` and have root
  execute the result. This module therefore takes the full
  :class:`OpenRouterConfig` as a constructor argument and never goes looking
  for credentials on its own.

- Tier 1 (user daemon, no root power): :func:`load_user_tier_config` MAY read
  ``OPENROUTER_API_KEY`` / ``OPENROUTER_MODEL`` from the environment or a
  repo-root ``.env`` — forging tier-1 verdicts only widens the user's own
  browser allowlist, which the user could edit anyway in user layout.

Failure semantics: any network / HTTP / response-shape problem raises
:class:`OpenRouterError`; callers MUST treat that as deny (fail closed).
Secrets never enter prompts, logs, or exception messages.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from daemon import paths

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-sonnet-5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_ATTEMPTS = 2


class OpenRouterError(RuntimeError):
    """Any failure talking to OpenRouter. Callers must fall back to deny."""


@dataclass(frozen=True)
class OpenRouterConfig:
    """Connection settings. See the module docstring for where these may come from."""

    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL

    def __repr__(self) -> str:  # never leak the key via repr/logging
        return f"OpenRouterConfig(model={self.model!r}, base_url={self.base_url!r}, api_key=***)"


class OpenRouterClient:
    """Minimal chat-completions client.

    ``urlopen`` is injectable for tests — the test suite must never hit the
    network.
    """

    def __init__(
        self,
        config: OpenRouterConfig,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        attempts: int = DEFAULT_ATTEMPTS,
        urlopen: Callable[..., object] | None = None,
    ) -> None:
        if not config.api_key:
            raise OpenRouterError("No API key configured")
        self._config = config
        self._timeout = timeout
        self._attempts = max(1, attempts)
        self._urlopen = urlopen or urllib.request.urlopen

    def chat(self, messages: list[dict[str, str]]) -> str:
        """Send a chat completion request; return the assistant message text.

        Raises :class:`OpenRouterError` on any failure — callers deny.
        """
        payload = json.dumps({"model": self._config.model, "messages": messages}).encode("utf-8")
        request = urllib.request.Request(
            url=self._config.base_url.rstrip("/") + "/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                with self._urlopen(request, timeout=self._timeout) as response:  # type: ignore[call-arg]
                    body = response.read()
                return self._extract_content(body)
            except OpenRouterError:
                raise  # malformed response — retrying won't fix the shape
            except Exception as e:  # URLError, HTTPError, timeout, OSError...
                last_error = e
                logger.warning("OpenRouter attempt %d/%d failed: %s", attempt, self._attempts, type(e).__name__)
        raise OpenRouterError(f"OpenRouter unreachable after {self._attempts} attempts: {type(last_error).__name__}")

    @staticmethod
    def _extract_content(body: bytes) -> str:
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise OpenRouterError(f"Malformed OpenRouter response: {type(e).__name__}") from e
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("Empty completion content")
        return content


def _parse_dotenv(text: str) -> dict[str, str]:
    """Parse trivial ``KEY=VALUE`` lines (comments and blanks ignored)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("'\"")
    return result


def load_user_tier_config(
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> OpenRouterConfig:
    """Build a config for the TIER-1 (user daemon) judge only.

    Resolution order: explicit ``env`` mapping (or ``os.environ``), then a
    ``.env`` file at the repo/code root. Raises :class:`OpenRouterError` when
    no key is found — the caller denies.

    NEVER use this for the tier-3/root path; see the module docstring (R2).
    """
    import os

    env = env if env is not None else os.environ
    key = env.get("OPENROUTER_API_KEY", "")
    model = env.get("OPENROUTER_MODEL", "")
    if not key:
        dotenv = dotenv_path or paths.code_root() / ".env"
        try:
            values = _parse_dotenv(dotenv.read_text(encoding="utf-8"))
        except OSError:
            values = {}
        key = values.get("OPENROUTER_API_KEY", "")
        model = model or values.get("OPENROUTER_MODEL", "")
    if not key:
        raise OpenRouterError("OPENROUTER_API_KEY not configured (env or .env)")
    return OpenRouterConfig(api_key=key, model=model or DEFAULT_MODEL)
