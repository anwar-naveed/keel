"""CLI entry point for keel."""

import argparse
import sys


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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Command implementations land in later phases; all are accepted
    # and acknowledged for now.
    _ = args

    return 0


if __name__ == "__main__":
    sys.exit(main())
