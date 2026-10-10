"""Tests for config.py - P1.1"""

from pathlib import Path

import pytest

from keel.config import load_settings


def test_default_settings(monkeypatch):
    """Test default settings when no env vars are set."""
    monkeypatch.delenv("KEEL_PROVIDER", raising=False)
    monkeypatch.delenv("KEEL_DATA_DIR", raising=False)

    settings = load_settings()

    assert settings.provider == "mock"
    assert settings.data_dir == Path("data/")
    assert settings.db_path == Path("data/keel.db")
    assert settings.runlog_dir == Path("data/runs")


def test_custom_provider(monkeypatch):
    """Test custom provider from env."""
    monkeypatch.setenv("KEEL_PROVIDER", "ollama")
    monkeypatch.delenv("KEEL_DATA_DIR", raising=False)

    settings = load_settings()

    assert settings.provider == "ollama"


def test_custom_data_dir(monkeypatch):
    """Test custom data directory from env."""
    monkeypatch.delenv("KEEL_PROVIDER", raising=False)
    monkeypatch.setenv("KEEL_DATA_DIR", "/custom/path")

    settings = load_settings()

    assert settings.data_dir == Path("/custom/path")
    assert settings.db_path == Path("/custom/path/keel.db")
    assert settings.runlog_dir == Path("/custom/path/runs")


def test_data_dir_creates_paths(monkeypatch, tmp_path):
    """Test that data directory paths are properly constructed."""
    data_dir = tmp_path / "custom_data"
    monkeypatch.setenv("KEEL_DATA_DIR", str(data_dir))
    monkeypatch.delenv("KEEL_PROVIDER", raising=False)

    settings = load_settings()

    assert settings.data_dir == data_dir
    assert settings.db_path == data_dir / "keel.db"
    assert settings.runlog_dir == data_dir / "runs"


def test_settings_immutable():
    """Test that Settings is immutable (frozen dataclass)."""
    settings = load_settings()
    with pytest.raises(AttributeError):
        settings.provider = "invalid"
    with pytest.raises(AttributeError):
        settings.data_dir = Path("/invalid")
