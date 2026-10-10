# ADR-003: MCP as the external surface

## Context
keel's runtime is a single-writer SQLite loop. External callers (IDEs,
other agents, dashboards) need controlled access: run agents, read state,
verify audit, trigger evals — without sharing the database file or the
Python process.

## Options
1. **REST API** — a server, ports, auth middleware, OpenAPI doc to
   maintain. Overkill for a single-node runtime.
2. **MCP (Model Context Protocol) over stdio** — the emerging standard
   for tool exposure to LLM clients; FastMCP gives schema generation,
   validation, and client tooling for free.

## Decision
FastMCP stdio server (`keel mcp`) exposing exactly 5 tools: run_query,
enqueue, audit_verify, eval_run, show_run. The governance boundary is
preserved over the wire: enqueue routes through the engine's enqueue gate
(forbidden tiers refused) and every tool call lands in the same audit
chain the CLI path uses.

## Consequences
- One external surface to document and secure; MCP clients get typed
  schemas for free.
- Stdio only for v1 — transport promotion (SSE/HTTP) is a config change
  in FastMCP, not a rewrite.
- The 5-tool surface is deliberately small: every tool maps to a
  capability the runtime already enforces; MCP adds nothing the engine
  would not already allow.
