# ADR-001: SQLite single-writer runtime

## Context
keel needs durable run state, a queue, and a reversible-op journal with a
hard guarantee: a run's state change and its journaled side effects must
commit atomically. The deployment target is a single container on a VPS.

## Options
1. **Postgres + Redis queue** — the "obvious" production answer. Costs:
   two more services to operate, connection pools, migration tooling,
   and a distributed-consistency surface for zero benefit at this scale.
2. **SQLite (WAL mode) for everything** — one file, in-process,
   transactional by nature, ships inside Python's stdlib.

## Decision
SQLite in WAL mode, single-writer engine loop. The runs table, queue
metadata, journal, staging, and audit log all live in one database file;
every state transition and its side effects commit in one transaction.

## Consequences
- Durability is process-level: a SIGKILL mid-run leaves the run in
  `running`, and startup repair re-queues it (proven by test_durability.py).
- Scaling out means promoting the queue to Postgres/Redis later; the
  interfaces (Queue, Journal) were drawn to make that a swap, not a rewrite.
- Honest limitation: single worker, one container — stated in the README,
  not hidden.
