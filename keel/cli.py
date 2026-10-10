"""CLI entry point for keel."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keel",
        description="keel - A tiny, production-shaped agent runtime: durable by default, gated by design, evaluated before it ships.",
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
    show_parser.add_argument("run_id", nargs="?", help="Run ID (optional, shows latest if omitted)")

    # queue command
    queue_parser = subparsers.add_parser("queue", help="Show queue status")

    # approve command
    approve_parser = subparsers.add_parser("approve", help="Approve a staged run")
    approve_parser.add_argument("run_id", help="Run ID to approve")

    # reject command
    reject_parser = subparsers.add_parser("reject", help="Reject a staged run")
    reject_parser.add_argument("run_id", help="Run ID to reject")

    # rollback command
    rollback_parser = subparsers.add_parser("rollback", help="Rollback a run")
    rollback_parser.add_argument("run_id", help="Run ID to rollback")

    # eval command
    eval_parser = subparsers.add_parser("eval", help="Run evaluations")
    eval_parser.add_argument("--gate", action="store_true", help="Run eval gate (exit 1 on failure)")

    # cost command
    cost_parser = subparsers.add_parser("cost", help="Show cost report")
    cost_parser.add_argument("--agent", help="Filter by agent name")
    cost_parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")

    # audit command
    audit_parser = subparsers.add_parser("audit", help="Audit operations")
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_subparsers.add_parser("verify", help="Verify audit chain integrity")

    # mcp command
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # For now, just print what would be done
    if args.command == "run":
        print(f"Would run agent: {args.agent} with input: {args.input}")
    elif args.command == "show":
        run_id = args.run_id or "latest"
        print(f"Would show run: {run_id}")
    elif args.command == "queue":
        print("Would show queue status")
    elif args.command == "approve":
        print(f"Would approve run: {args.run_id}")
    elif args.command == "reject":
        print(f"Would reject run: {args.run_id}")
    elif args.command == "rollback":
        print(f"Would rollback run: {args.run_id}")
    elif args.command == "eval":
        if args.gate:
            print("Would run eval gate")
        else:
            print("Would run evaluations")
    elif args.command == "cost":
        print(f"Would show cost report (agent={args.agent}, days={args.days})")
    elif args.command == "audit" and args.audit_command == "verify":
        print("Would verify audit chain")
    elif args.command == "mcp":
        print("Would start MCP server")

    return 0


if __name__ == "__main__":
    sys.exit(main())