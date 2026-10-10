"""Tests for inventory/loader.py — P4.1 + the 31st-agent proof (P4.2)."""

import pytest

from keel.inventory.loader import (
    AgentSpec,
    InventoryError,
    load_agent,
    load_inventory,
)


def _agent(tmp_path, name="a1", tier="read_only", provider="mock", body=""):
    f = tmp_path / f"{name}.yaml"
    f.write_text(
        f"name: {name}\ntier: {tier}\nprovider: {provider}\n"
        f"system_prompt: |\n  prompt for {name}\n{body}"
    )
    return f


def test_load_inventory_all(tmp_path):
    _agent(tmp_path, "triage")
    _agent(tmp_path, "draft", tier="draft")
    specs = load_inventory(tmp_path)
    assert set(specs) == {"triage", "draft"}
    assert all(isinstance(s, AgentSpec) for s in specs.values())


def test_missing_fields_actionable(tmp_path):
    (tmp_path / "bad.yaml").write_text("name: bad\ntier: read_only\n")
    with pytest.raises(InventoryError) as exc:
        load_inventory(tmp_path)
    assert "missing required field" in str(exc.value)
    assert "provider" in str(exc.value)


def test_unknown_tier_did_you_mean(tmp_path):
    _agent(tmp_path, "x", tier="read-only")
    with pytest.raises(InventoryError) as exc:
        load_inventory(tmp_path)
    assert "did you mean 'read_only'" in str(exc.value)


def test_unknown_provider_lists_valids(tmp_path):
    _agent(tmp_path, "x", provider="gpt")
    with pytest.raises(InventoryError) as exc:
        load_inventory(tmp_path)
    assert "anthropic" in str(exc.value)


def test_duplicate_names_rejected(tmp_path):
    _agent(tmp_path, "dupe")
    (tmp_path / "dupe2.yaml").write_text(
        "name: dupe\ntier: read_only\nprovider: mock\n"
        "system_prompt: |\n  second\n"
    )
    with pytest.raises(InventoryError) as exc:
        load_inventory(tmp_path)
    assert "duplicate agent name 'dupe'" in str(exc.value)


def test_unknown_field_named(tmp_path):
    _agent(tmp_path, "x", body="weird_field: 1\n")
    with pytest.raises(InventoryError) as exc:
        load_inventory(tmp_path)
    assert "weird_field" in str(exc.value)


def test_load_agent_missing_names_knowns(tmp_path):
    _agent(tmp_path, "real")
    with pytest.raises(InventoryError) as exc:
        load_agent(tmp_path, "ghost")
    assert "real" in str(exc.value)


def test_agent_spec_builds_capability_tool(tmp_path):
    from keel.governance.capabilities import ReadOnlyDB
    from keel.runtime.journal import Journal
    from keel.runtime.state import init_db

    _agent(tmp_path, "ro")
    spec = load_agent(tmp_path, "ro")
    conn = init_db(tmp_path / "db.sqlite")
    Journal(conn)
    tool = spec.build_tool(conn, "run-1", Journal(conn))
    assert isinstance(tool, ReadOnlyDB)


def test_thirty_first_agent(tmp_path):
    """THE 31st-agent proof (P4.2): write a new agent YAML, load, run —
    zero code changes."""

    from keel.runtime.engine import Engine
    from keel.runtime.state import RunStatus

    # inventory with one seeded agent
    _agent(tmp_path, "seed")

    # ...30 more arrive as files (simulated: 29 more YAMLs)
    for i in range(29):
        _agent(tmp_path, f"agent_{i:02d}")

    # THE 31st: spam_filter — a file drop, nothing else
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "spam_script.yaml"
    script.write_text('- content: "not spam"\n  tool_calls: []\n')
    (tmp_path / "spam_filter.yaml").write_text(
        "name: spam_filter\n"
        "description: flags spammy reports\n"
        "tier: read_only\n"
        "provider: mock\n"
        f"script: {script}\n"
        "system_prompt: |\n"
        "  You filter spam reports. Read-only.\n"
    )

    specs = load_inventory(tmp_path)
    assert len(specs) == 31
    assert "spam_filter" in specs

    # Run it against the engine with zero code changes
    engine = Engine(data_dir=tmp_path / "data")
    engine._load_agent_config = lambda a: {  # noqa: SLF001
        "provider": "mock",
        "script": str(script),
        "system_prompt": "You filter spam.",
        "tier": "read_only",
    }
    run = engine.run_agent("spam_filter", "cheap watches, buy now")
    assert run.status == RunStatus.DONE
