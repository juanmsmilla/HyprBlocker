"""Tier-1 judge key resolution (R2).

The key must never live in world-readable /opt, so ``load_user_tier_config``
reads it from the user config dir first (root layout: seeded there by
install-root.sh) and only then falls back to the repo/code-root ``.env``
(dev checkout). Regression tests for the first-deploy finding where the root
layout resolved only ``/opt/hyprblocker/.env`` — deliberately excluded by the
installer — so every grant request instantly fail-closed denied.
"""

import pytest

from daemon import paths
from daemon.grants import openrouter


def _write_dotenv(path, key):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"OPENROUTER_API_KEY={key}\n")


def test_env_mapping_wins_over_dotenv_files():
    _write_dotenv(paths.config_dir() / ".env", "from-config-dir")
    cfg = openrouter.load_user_tier_config(env={"OPENROUTER_API_KEY": "from-env"})
    assert cfg.api_key == "from-env"


def test_config_dir_dotenv_preferred_over_code_root():
    _write_dotenv(paths.config_dir() / ".env", "from-config-dir")
    _write_dotenv(paths.code_root() / ".env", "from-code-root")
    cfg = openrouter.load_user_tier_config(env={})
    assert cfg.api_key == "from-config-dir"


def test_code_root_dotenv_is_the_fallback():
    _write_dotenv(paths.code_root() / ".env", "from-code-root")
    cfg = openrouter.load_user_tier_config(env={})
    assert cfg.api_key == "from-code-root"


def test_config_dir_dotenv_without_key_falls_through():
    # A .env that exists but lacks the key must not mask the fallback.
    dotenv = paths.config_dir() / ".env"
    dotenv.parent.mkdir(parents=True, exist_ok=True)
    dotenv.write_text("SOMETHING_ELSE=1\n")
    _write_dotenv(paths.code_root() / ".env", "from-code-root")
    cfg = openrouter.load_user_tier_config(env={})
    assert cfg.api_key == "from-code-root"


def test_explicit_dotenv_path_is_the_sole_candidate(tmp_path):
    explicit = tmp_path / "explicit.env"
    _write_dotenv(explicit, "explicit-key")
    _write_dotenv(paths.config_dir() / ".env", "from-config-dir")
    cfg = openrouter.load_user_tier_config(env={}, dotenv_path=explicit)
    assert cfg.api_key == "explicit-key"


def test_no_key_anywhere_raises():
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.load_user_tier_config(env={})
