"""Smoke tests for the Phase 0 skeleton.

Phase 0 acceptance: the package installs, imports, and the CLI
surface (every planned subcommand) parses. Deeper behavior tests
arrive with each phase's modules.
"""

import subprocess
import sys

import keel


def test_version() -> None:
    assert keel.__version__ == "0.1.0"


def test_cli_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "keel", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "keel" in result.stdout


def test_cli_declares_all_subcommands() -> None:
    from keel.cli import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    for command in (
        "run",
        "show",
        "queue",
        "approve",
        "reject",
        "rollback",
        "eval",
        "cost",
        "audit",
        "mcp",
    ):
        assert command in help_text, f"missing subcommand: {command}"


def test_cli_version_flag() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "keel", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "0.1.0" in (result.stdout + result.stderr)
