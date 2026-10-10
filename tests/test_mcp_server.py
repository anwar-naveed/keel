"""Tests for mcp/server.py — P4.4. Tool schemas + capability boundary."""

import pytest

fastmcp = pytest.importorskip("fastmcp")

from keel.mcp.server import mcp  # noqa: E402


def test_server_exposes_exactly_5_tools():
    import asyncio

    async def _tools():
        tools = await mcp.list_tools()
        return [t.name for t in tools]

    names = set(asyncio.run(_tools()))
    assert names == {
        "run_query", "enqueue", "audit_verify", "eval_run", "show_run",
    }


def test_run_query_reads_kv(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("KEEL_DATA_DIR", str(tmp_path))
    from keel.mcp import server

    # seed the store through the engine's own path
    engine = server._engine()  # noqa: SLF001
    engine.conn.execute(
        "INSERT INTO kv_store (key, value) VALUES ('mcp_k', 'mcp_v')"
    )
    engine.conn.commit()

    from fastmcp import Client

    async def _call():
        async with Client(mcp) as client:
            return await client.call_tool("run_query", {"key": "mcp_k"})

    result = asyncio.run(_call())
    assert "mcp_v" in str(result)


def test_enqueue_respects_forbidden_tier(tmp_path, monkeypatch):
    """Boundary over the wire: forbidden agents refused via MCP too."""
    import asyncio

    data_dir = tmp_path / "data"          # agents/ sits at data_dir.parent
    monkeypatch.setenv("KEEL_DATA_DIR", str(data_dir))
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "banned.yaml").write_text(
        "name: banned\ntier: forbidden\nprovider: mock\n"
        "system_prompt: |\n  nope\n"
    )
    from keel.mcp import server

    server._ENGINE = None  # noqa: SLF001 — force fresh engine on new env

    from fastmcp import Client

    async def _call():
        async with Client(mcp) as client:
            try:
                result = await client.call_tool(
                    "enqueue", {"agent": "banned", "input_text": "x"}
                )
            except Exception as e:  # noqa: BLE001 — refusal surfaces here
                return str(e)
            return str(result)

    out = asyncio.run(_call())
    assert "forbidden" in out, f"expected refusal, got: {out[:200]}"


def test_show_run_returns_timeline(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("KEEL_DATA_DIR", str(tmp_path))
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "ok.yaml").write_text(
        "name: ok\ntier: read_only\nprovider: mock\n"
        "system_prompt: |\n  fine\n"
    )
    (tmp_path / "s.yaml").write_text('- content: "hi"\n  tool_calls: []\n')
    from keel.mcp import server

    server._ENGINE = None  # noqa: SLF001
    engine = server._engine()  # noqa: SLF001
    engine._load_agent_config = lambda a: {  # noqa: SLF001
        "provider": "mock", "script": str(tmp_path / "s.yaml"),
        "system_prompt": "x", "tier": "read_only",
    }
    run = engine.run_agent("ok", "hello")

    from fastmcp import Client

    async def _call():
        async with Client(mcp) as client:
            return await client.call_tool(
                "show_run", {"run_id": run.run_id}
            )

    result = asyncio.run(_call())
    assert "events" in str(result) or "done" in str(result)
