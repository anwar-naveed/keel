"""Configuration settings for keel - P1.1

Dataclass settings from environment variables:
- KEEL_PROVIDER (default "mock")
- KEEL_DATA_DIR (default "data/")
Derived paths: db_path (data/keel.db), runlog_dir (data/runs)
"""

import os
from dataclasses import dataclass
from pathlib import Path


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


__all__ = ["Settings", "load_settings"]
# trigger build-image
