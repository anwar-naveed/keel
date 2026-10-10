"""CLI entry point for keel."""

import argparse
import logging
import sys
from pathlib import Path

from keel.config import load_settings
from keel.runtime.engine import Engine
from keel.runtime.runlog import reconstruct
from keel.runtime.state import RunState, init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keel",
        description=(
            "keel - A tiny, production-shaped agent runtime: "
            "durable by default, gated by design, evaluated "
            "before it ships."
        ),
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="<command>",
        help="Available commands",
        required=True,
    )

    # run command
    run_parser = subparsers.add_parser("run", help="Run an agent")
    run_parser.add_argument("agent", help="Agent name (e.g., triage)")
    run_parser.add_argument("input", help="Input for the agent")

    # show command
    show_parser = subparsers.add_parser("show", help="Show run details")
    show_parser.add_argument(
        "run_id", nargs="?", help="Run ID (optional, latest if omitted)"
    )

    # queue command
    subparsers.add_parser("queue", help="Show queue status")

    # approve command
    approve_parser = subparsers.add_parser(
        "approve", help="Approve a staged run"
    )
    approve_parser.add_argument("run_id", help="Run ID to approve")

    # reject command
    reject_parser = subparsers.add_parser(
        "reject", help="Reject a staged run"
    )
    reject_parser.add_argument("run_id", help="Run ID to reject")

    # rollback command
    rollback_parser = subparsers.add_parser(
        "rollback", help="Rollback a run"
    )
    rollback_parser.add_argument("run_id", help="Run ID to rollback")

    # eval command
    eval_parser = subparsers.add_parser("eval", help="Run evaluations")
    eval_parser.add_argument(
        "--gate", action="store_true", help="Run eval gate (exit 1 on fail)"
    )

    # cost command
    cost_parser = subparsers.add_parser("cost", help="Show cost report")
    cost_parser.add_argument("--agent", help="Filter by agent name")
    cost_parser.add_argument(
        "--days", type=int, default=7, help="Days to look back (default 7)"
    )

    # audit command
    audit_parser = subparsers.add_parser("audit", help="Audit operations")
    audit_subparsers = audit_parser.add_subparsers(
        dest="audit_command", required=True
    )
    audit_subparsers.add_parser(
        "verify", help="Verify audit chain integrity"
    )

    # mcp command
    subparsers.add_parser("mcp", help="Start MCP server")

    return parser


def _get_engine(data_dir: Path | None = None) -> Engine:
    """Get engine instance with settings."""
    settings = load_settings()
    if data_dir is None:
        data_dir = settings.data_dir
    return Engine(data_dir=data_dir)


def _get_latest_run_id(data_dir: Path) -> str | None:
    """Get the latest run ID from the database."""
    db_path = data_dir / "keel.db"
    if not db_path.exists():
        return None
    conn = init_db(db_path)
    cursor = conn.execute(
        "SELECT id FROM runs ORDER BY created_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    return row[0] if row else None


def cmd_run(args: argparse.Namespace) -> int:
    """Run an agent."""
    engine = _get_engine()
    run = engine.run_agent(args.agent, args.input)
    logger.info("Run %s completed with status: %s", run.run_id, run.status.value)
    if run.status.value == "failed":
        return 1
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show run details."""
    engine = _get_engine()
    run_id = args.run_id or _get_latest_run_id(engine.data_dir)
    if run_id is None:
        logger.error("No runs found")
        return 1

    run = RunState.load(engine.conn, run_id)
    if run is None:
        logger.error("Run %s not found", run_id)
        return 1

    logger.info("Run ID: %s", run.run_id)
    logger.info("Agent: %s", run.agent)
    logger.info("Status: %s", run.status.value)
    logger.info("Phase: %s", run.phase)
    logger.info("Created: %s", run.created_at)
    logger.info("Updated: %s", run.updated_at)

    # Show runlog events
    events = reconstruct(engine.data_dir, run_id)
    if events:
        logger.info("\n--- Events ---")
        for event in events:
            logger.info(
                "  [%s] %s: %s",
                event.timestamp,
                event.type,
                event.payload,
            )

    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    """Show queue status."""
    engine = _get_engine()
    queue = engine.queue

    # Pending = queued, not yet claimed (FIFO head first)
    pending = queue.list_pending()
    logger.info("Pending: %d", len(pending))
    for entry in pending:
        logger.info("  %s - %s - %s", entry.run_id, entry.agent, entry.status.value)

    # Claimed = currently held by a worker
    claimed = queue.list_claimed()
    logger.info("Claimed: %d", len(claimed))
    for entry in claimed:
        logger.info("  %s - %s - %s", entry.run_id, entry.agent, entry.status.value)

    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Approve a staged run (Phase 2 stub)."""
    logger.info("Approve not implemented in Phase 1: %s", args.run_id)
    return 1


def cmd_reject(args: argparse.Namespace) -> int:
    """Reject a staged run (Phase 2 stub)."""
    logger.info("Reject not implemented in Phase 1: %s", args.run_id)
    return 1


def cmd_rollback(args: argparse.Namespace) -> int:
    """Rollback a run (Phase 2 stub)."""
    logger.info("Rollback not implemented in Phase 1: %s", args.run_id)
    return 1


def cmd_eval(args: argparse.Namespace) -> int:
    """Run evaluations (Phase 2 stub)."""
    logger.info("Eval not implemented in Phase 1")
    return 1


def cmd_cost(args: argparse.Namespace) -> int:
    """Show cost report (Phase 2 stub)."""
    logger.info("Cost report not implemented in Phase 1")
    return 1


def cmd_audit(args: argparse.Namespace) -> int:
    """Audit operations (Phase 2 stub)."""
    logger.info("Audit not implemented in Phase 1")
    return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Start MCP server (Phase 2 stub)."""
    logger.info("MCP server not implemented in Phase 1")
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Dispatch to command handler
    handlers = {
        "run": cmd_run,
        "show": cmd_show,
        "queue": cmd_queue,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "rollback": cmd_rollback,
        "eval": cmd_eval,
        "cost": cmd_cost,
        "audit": cmd_audit,
        "mcp": cmd_mcp,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
