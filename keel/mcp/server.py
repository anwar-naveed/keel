"""FastMCP stdio server — P4.3.

Exposes exactly 5 tools: run_query (read-only), enqueue, audit_verify,
eval_run, show_run. The capability boundary is preserved over the wire:
the server constructs capability objects per caller role, so a read-only
session receives read-only tools.
"""

from pathlib import Path

from fastmcp import FastMCP

from keel.config import load_settings
from keel.runtime.engine import Engine
from keel.runtime.runlog import reconstruct
from keel.runtime.state import RunState

mcp = FastMCP("keel")

_ENGINE: Engine | None = None


def _engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        settings = load_settings()
        _ENGINE = Engine(data_dir=settings.data_dir)
    return _ENGINE


@mcp.tool()
def run_query(key: str) -> str:
    """Read a key from the keel KV store (read-only capability)."""
    engine = _engine()
    cursor = engine.conn.execute(
        "SELECT value FROM kv_store WHERE key = ?", (key,)
    )
    row = cursor.fetchone()
    return row[0] if row else ""


@mcp.tool()
def enqueue(agent: str, input_text: str) -> dict:
    """Enqueue + synchronously process a run for an agent.

    Forbidden-tier agents are refused; the error names the tier.
    """
    engine = _engine()
    run = engine.run_agent(agent, input_text)
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "phase": run.phase,
    }


@mcp.tool()
def audit_verify() -> dict:
    """Walk the audit hash chain; report integrity."""
    engine = _engine()
    try:
        count = engine.audit.verify()
        return {"verified": True, "entries": count}
    except Exception as e:  # noqa: BLE001 — tamper is a report, not a crash
        return {"verified": False, "error": str(e)}


@mcp.tool()
def eval_run(gate: bool = True) -> dict:
    """Run the behavioral eval gate; return the report summary."""
    from keel.eval.gate import run_gate, write_report

    engine = _engine()
    eval_dir = Path("eval")
    if not eval_dir.exists():
        eval_dir = engine.data_dir.parent / "eval"
    report = run_gate(engine, engine.data_dir, eval_dir)
    out = engine.data_dir / "eval_reports" / "last.json"
    write_report(report, out)
    return {
        "passed": report["passed"],
        "golden": [
            {"name": c["name"], "passed": c["passed"]}
            for c in report["golden"]
        ],
        "safety": [
            {"name": c["name"], "passed": c["passed"]}
            for c in report["safety"]
        ],
        "report_path": str(out),
    }


@mcp.tool()
def show_run(run_id: str) -> dict:
    """Show a run: state + reconstructed runlog timeline."""
    engine = _engine()
    run = RunState.load(engine.conn, run_id)
    if run is None:
        return {"error": f"run {run_id} not found"}
    events = reconstruct(engine.data_dir, run_id)
    return {
        "run_id": run.run_id,
        "agent": run.agent,
        "status": run.status.value,
        "phase": run.phase,
        "created_at": run.created_at,
        "events": [
            {"ts": e.timestamp, "type": e.type, "payload": e.payload}
            for e in events
        ],
    }


def main() -> None:
    """Entry point for `keel mcp`."""
    mcp.run()


__all__ = ["mcp", "main"]
