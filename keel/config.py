"""Configuration settings for keel - P1.1

Dataclass settings from environment variables:
- KEEL_PROVIDER (default "mock")
- KEEL_DATA_DIR (default "data/")
- KEEL_PROVIDERS_CONFIG (default "config/providers.json")
Derived paths: db_path (data/keel.db), runlog_dir (data/runs)
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Configuration error with actionable message."""
    pass


@dataclass(frozen=True)
class Settings:
    """Immutable configuration settings for keel."""

    provider: str
    data_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "keel.db"

    @property
    def runlog_dir(self) -> Path:
        return self.data_dir / "runs"


def load_settings() -> Settings:
    """Load settings from environment variables."""
    provider = os.getenv("KEEL_PROVIDER", "mock")
    data_dir_str = os.getenv("KEEL_DATA_DIR", "data/")
    data_dir = Path(data_dir_str)

    return Settings(provider=provider, data_dir=data_dir)


def load_providers_config(config_path: str | Path | None = None) -> dict:
    """Load provider configuration from JSON file.

    Args:
        config_path: Path to providers.json. If None, uses KEEL_PROVIDERS_CONFIG
                     env var or defaults to 'config/providers.json'.

    Returns:
        Dictionary with provider configurations.

    Raises:
        ConfigError: If config file is missing or invalid JSON.
    """
    if config_path is None:
        config_path = os.getenv("KEEL_PROVIDERS_CONFIG", "config/providers.json")

    path = Path(config_path)
    if not path.is_absolute():
        # Try relative to current working directory first
        path = Path.cwd() / path
        if not path.exists():
            # Try relative to module directory
            path = Path(__file__).parent.parent / config_path

    if not path.exists():
        raise ConfigError(
            f"Provider config file not found: {config_path}. "
            f"Set KEEL_PROVIDERS_CONFIG env var or create config/providers.json"
        )

    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in provider config {config_path}: {e}") from e


__all__ = ["Settings", "load_settings", "ConfigError", "load_providers_config"]
# trigger build-image
