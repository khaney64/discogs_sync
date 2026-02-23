"""Token and configuration persistence."""

from __future__ import annotations

import json
from pathlib import Path

from .exceptions import ConfigError

DEFAULT_CONFIG_DIR = Path.home() / ".discogs-sync"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


def get_config_path() -> Path:
    return DEFAULT_CONFIG_FILE


def load_config() -> dict:
    """Load configuration from disk. Returns empty dict if file doesn't exist."""
    path = get_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"Failed to read config file {path}: {e}") from e


def save_config(config: dict) -> None:
    """Save configuration to disk."""
    path = get_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Failed to write config file {path}: {e}") from e


def get_tokens() -> dict | None:
    """Return stored OAuth tokens, or None if not configured."""
    config = load_config()
    token = config.get("access_token")
    secret = config.get("access_token_secret")
    if token and secret:
        return {
            "access_token": token,
            "access_token_secret": secret,
            "consumer_key": config.get("consumer_key", ""),
            "consumer_secret": config.get("consumer_secret", ""),
            "username": config.get("username"),
        }
    return None


def save_tokens(
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    username: str | None = None,
) -> None:
    """Store OAuth tokens to config file."""
    config = load_config()
    config.update(
        {
            "consumer_key": consumer_key,
            "consumer_secret": consumer_secret,
            "access_token": access_token,
            "access_token_secret": access_token_secret,
            "username": username,
        }
    )
    save_config(config)


def clear_tokens() -> None:
    """Remove stored OAuth tokens."""
    config = load_config()
    for key in ["access_token", "access_token_secret", "username"]:
        config.pop(key, None)
    save_config(config)
