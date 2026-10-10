# keel

A tiny, production-shaped agent runtime: **durable by default, gated by
design, evaluated before it ships.**

keel runs LLM agents with the boring parts done right — runs survive a
`kill -9`, forbidden writes are structurally impossible (not politely
declined), every decision is audited, and a behavioral eval gate runs in
CI on every push.

## The problem

Most agent demos are a `while True:` loop around a chat API. When you need
the real thing, you discover the missing 90%: what happens when the model
half-finishes and the process dies? When a prompt injection tells it to
delete the database? When a "small refactor" silently breaks the one
guarantee your product depends on? keel is the 90% — small enough to read
in an afternoon (~1,900 LOC), shaped like a production system.

## 5-minute quickstart (Docker, zero keys, zero cost)

```bash
git clone https://github.com/anwar-naveed/keel && cd keel
docker compose up -d                      # pulls the CI-built image
docker compose exec keel-dev make demo    # run + queue + eval gate
docker compose exec keel-dev pytest -q    # 162 tests, mock provider only
```

No API keys. No GPU. The MockProvider carries every test and CI run —
real-model adapters (Ollama/OpenAI/Anthropic) ship in code and are
covered by mocked-HTTP tests; point `KEEL_PROVIDER` at one when you have
the hardware or the key.

## Architecture

```
             ┌──────────────────────────────────────────────┐
             │                  keel engine                 │
             │                                              │
 enqueue ───▶│  queue ──▶ state machine ──▶ provider ──▶    │
             │   │           (SQLite WAL)      adapters    │
             │   │              │    │          mock/       │
             │   │              │    │          ollama/     │
             │   ▼              ▼    ▼          openai/     │
             │  gate:      journal  runlog     anthropic    │
             │  tiers ──▶  (undo)   (events)                │
             │   │                                        │
             │   ├──▶ review gate ──▶ approve / reject     │
             │   └──▶ audit chain (sha256 hash-linked)     │
             └──────────────────────────────────────────────┘
                    │                    │
              MCP server           meta agent
             (5 tools, stdio)    (keel watching keel)
```

| Guarantee | Mechanism | Proof |
|---|---|---|
| Runs survive SIGKILL | startup repair: `running→pending`, re-queued | `tests/test_durability.py` |
| Forbidden writes are impossible | capability objects: the method does not exist | `tests/test_capabilities.py::test_injection_cannot_write` |
| Staged writes need a human | review gate: `running→review`, `keel approve/reject` | `tests/test_review.py` |
| The audit log is tamper-evident | sha256 hash chain, `keel audit verify` | `tests/test_audit.py` |
| Behavior can't silently regress | eval gate in CI: golden + safety suites | `keel eval --gate` (exit 1) |
| Adding agent #31 is a file drop | YAML inventory, validated at load | `tests/test_inventory.py::test_thirty_first_agent` |

## Supabase mapping (why this shape)

keel is deliberately built in the shape the Supabase AI Platform team
describes — the same problems, minus the Postgres:

| Supabase posting language | keel module |
|---|---|
| durable execution / retries | `runtime/state.py` + startup repair |
| tool calling with safety | `governance/capabilities.py` |
| human-in-the-loop approvals | `governance/review.py` |
| audit / compliance | `governance/audit.py` (hash-chained) |
| evals before shipping | `eval/` (gate wired into CI) |
| MCP integration | `mcp/server.py` (FastMCP, 5 tools) |

## Philosophy

- **Impossible, not forbidden.** A read-only agent's tool object has no
  `write` attribute at all. A jailbroken model gets `AttributeError`.
  See `docs/adr-002-impossible-writes.md`.
- **Behavioral evals, not string matches.** Cases assert states, tool
  boundaries, audit integrity, and cost — the model's prose is not under
  test. The judge is graded too (`eval/selftest.py`).
- **The runtime watches itself.** `keel meta` scans runlogs for repeated
  failures, cost spikes, and tool-error drift — an agent watching the
  agents.
- **Zero secrets by design.** CI needs no keys; MockProvider + MockJudge
  carry everything. A secret-scan job still runs as a tripwire.

## ADRs

- [ADR-001 — SQLite single-writer runtime](docs/adr-001-runtime.md)
- [ADR-002 — Capabilities, not permissions: impossible writes](docs/adr-002-impossible-writes.md)
- [ADR-003 — MCP as the external surface](docs/adr-003-mcp-boundary.md)
- [Eval philosophy](docs/eval-philosophy.md)
- [Demo script (6 beats)](docs/DEMO.md)

## What this is NOT

- No web UI. The CLI + MCP server are the surfaces.
- Single worker, single container — stated, not hidden (ADR-001's
  promotion path).
- Not LangChain/LangGraph — no orchestration graphs, no framework lock-in.
- No vector store, no RAG, no Kubernetes.

## Development

```bash
docker compose exec keel-dev make test   # pytest in the container
docker compose exec keel-dev make lint   # ruff in the container
docker compose exec keel-dev keel eval --gate
```

Everything runs inside Docker. The image is built by GitHub Actions and
pulled from Docker Hub — nothing is built or installed on your host.
Ollama is wired for GPU hosts but commented out in compose (uncomment,
pull a model, switch `KEEL_PROVIDER=ollama`).

## Roadmap

- multi-worker queue promotion (Postgres/Redis)
- MCP over HTTP/SSE transport
- rubric judge backends beyond mock/ollama
- scheduled agents (cron-style triggers)

## License

MIT © 2026 Naveed Anwar
