"""Runtime queue - P1.3

enqueue(agent, payload), next_pending() FIFO by created_at,
claimed_at worker marker, single-worker v1.
Crash-mid-claim recovery: a row claimed >10min ago with
status pending+claim is reclaimable.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from keel.runtime.state import RunState, RunStatus


@dataclass
class QueueEntry:
    """A queue entry representing a run waiting to be processed."""
    run_id: str
    agent: str
    payload: dict
    status: RunStatus
    created_at: str
    claimed_at: str | None = None


class Queue:
    """Single-worker FIFO queue with crash recovery."""

    CLAIM_TIMEOUT_MINUTES = 10

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_claimed_at_column()

    def _ensure_claimed_at_column(self) -> None:
        """Add claimed_at column to runs table if it doesn't exist."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        if "claimed_at" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN claimed_at TEXT")
            self.conn.commit()

    def enqueue(self, agent: str, payload: dict) -> QueueEntry:
        """Add a new entry to the queue."""
        run_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()

        run = RunState.create(run_id=run_id, agent=agent, phase="queued")
        run.save(self.conn)

        # Store payload in a separate table or as JSON
        self._save_payload(run_id, payload)

        return QueueEntry(
            run_id=run_id,
            agent=agent,
            payload=payload,
            status=RunStatus.PENDING,
            created_at=created_at,
            claimed_at=None,
        )

    def _save_payload(self, run_id: str, payload: dict) -> None:
        """Save payload to database."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        if "payload" not in columns:
            self.conn.execute("ALTER TABLE runs ADD COLUMN payload TEXT")
            self.conn.commit()

        self.conn.execute(
            "UPDATE runs SET payload = ? WHERE id = ?",
            (json.dumps(payload), run_id)
        )
        self.conn.commit()

    def _load_payload(self, run_id: str) -> dict:
        """Load payload from database."""
        cursor = self.conn.execute("SELECT payload FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return {}

    def next_pending(self) -> QueueEntry | None:
        """Get the next pending entry in FIFO order."""
        # Check if payload column exists
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        has_payload = "payload" in columns

        if has_payload:
            cursor = self.conn.execute(
                """
                SELECT id, agent, payload, status, created_at, claimed_at
                FROM runs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (RunStatus.PENDING.value,)
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT id, agent, status, created_at, claimed_at
                FROM runs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (RunStatus.PENDING.value,)
            )

        row = cursor.fetchone()
        if row is None:
            return None

        if has_payload:
            payload = json.loads(row[2]) if row[2] else {}
            return QueueEntry(
                run_id=row[0],
                agent=row[1],
                payload=payload,
                status=RunStatus(row[3]),
                created_at=row[4],
                claimed_at=row[5],
            )
        else:
            return QueueEntry(
                run_id=row[0],
                agent=row[1],
                payload={},
                status=RunStatus(row[2]),
                created_at=row[3],
                claimed_at=row[4],
            )

    def claim(self, run_id: str) -> QueueEntry:
        """Mark an entry as claimed by the worker."""
        # Verify it's pending
        run = RunState.load(self.conn, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.status != RunStatus.PENDING:
            raise ValueError(f"Run {run_id} is not pending (status: {run.status.value})")

        claimed_at = datetime.now(UTC).isoformat()

        # Update run status to running and set claimed_at
        run = run.transition_to(RunStatus.RUNNING, phase="claimed")
        self.conn.execute(
            "UPDATE runs SET claimed_at = ? WHERE id = ?",
            (claimed_at, run_id)
        )
        run.save(self.conn)

        payload = self._load_payload(run_id)
        return QueueEntry(
            run_id=run_id,
            agent=run.agent,
            payload=payload,
            status=RunStatus.RUNNING,
            created_at=run.created_at,
            claimed_at=claimed_at,
        )

    def reclaim_stale(self) -> list[QueueEntry]:
        """Reclaim entries that were claimed but stale (>10 min ago)."""
        cutoff = datetime.now(UTC) - timedelta(minutes=self.CLAIM_TIMEOUT_MINUTES)
        cutoff_str = cutoff.isoformat()

        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        has_payload = "payload" in columns

        if has_payload:
            cursor = self.conn.execute(
                """
                SELECT id, agent, payload, status, created_at, claimed_at
                FROM runs
                WHERE status = ? AND claimed_at IS NOT NULL AND claimed_at < ?
                ORDER BY created_at ASC
                """,
                (RunStatus.RUNNING.value, cutoff_str)
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT id, agent, status, created_at, claimed_at
                FROM runs
                WHERE status = ? AND claimed_at IS NOT NULL AND claimed_at < ?
                ORDER BY created_at ASC
                """,
                (RunStatus.RUNNING.value, cutoff_str)
            )

        reclaimed = []
        for row in cursor.fetchall():
            run_id = row[0]
            # Transition back to pending (startup repair)
            run = RunState.load(self.conn, run_id)
            if run and run.status == RunStatus.RUNNING:
                run = run.transition_to(RunStatus.PENDING, phase="reclaimed")
                self.conn.execute(
                    "UPDATE runs SET claimed_at = NULL WHERE id = ?",
                    (run_id,)
                )
                run.save(self.conn)

                payload = (json.loads(row[2]) if row[2] else {}) if has_payload else {}

                reclaimed.append(QueueEntry(
                    run_id=run_id,
                    agent=row[1],
                    payload=payload,
                    status=RunStatus.PENDING,
                    created_at=row[4] if has_payload else row[3],
                    claimed_at=None,
                ))

        return reclaimed

    def list_pending(self) -> list[QueueEntry]:
        """List all pending entries."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        has_payload = "payload" in columns

        if has_payload:
            cursor = self.conn.execute(
                """
                SELECT id, agent, payload, status, created_at, claimed_at
                FROM runs
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (RunStatus.PENDING.value,)
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT id, agent, status, created_at, claimed_at
                FROM runs
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (RunStatus.PENDING.value,)
            )

        entries = []
        for row in cursor.fetchall():
            if has_payload:
                payload = json.loads(row[2]) if row[2] else {}
                entries.append(QueueEntry(
                    run_id=row[0],
                    agent=row[1],
                    payload=payload,
                    status=RunStatus(row[3]),
                    created_at=row[4],
                    claimed_at=row[5],
                ))
            else:
                entries.append(QueueEntry(
                    run_id=row[0],
                    agent=row[1],
                    payload={},
                    status=RunStatus(row[2]),
                    created_at=row[3],
                    claimed_at=row[4],
                ))
        return entries

    def list_claimed(self) -> list[QueueEntry]:
        """List all entries currently claimed by a worker (claimed_at set, pending)."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        columns = [row[1] for row in cursor.fetchall()]
        has_payload = "payload" in columns

        if has_payload:
            cursor = self.conn.execute(
                """
                SELECT id, agent, payload, status, created_at, claimed_at
                FROM runs
                WHERE status = ? AND claimed_at IS NOT NULL
                ORDER BY created_at ASC
                """,
                (RunStatus.PENDING.value,)
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT id, agent, status, created_at, claimed_at
                FROM runs
                WHERE status = ? AND claimed_at IS NOT NULL
                ORDER BY created_at ASC
                """,
                (RunStatus.PENDING.value,)
            )

        entries: list[QueueEntry] = []
        for row in cursor.fetchall():
            if has_payload:
                entries.append(QueueEntry(
                    run_id=row[0],
                    agent=row[1],
                    payload=self._load_payload(row[0]) if row[2] else {},
                    status=RunStatus(row[3]),
                    created_at=row[4],
                    claimed_at=row[5],
                ))
            else:
                entries.append(QueueEntry(
                    run_id=row[0],
                    agent=row[1],
                    payload={},
                    status=RunStatus(row[2]),
                    created_at=row[3],
                    claimed_at=row[4],
                ))
        return entries


__all__ = ["Queue", "QueueEntry"]
