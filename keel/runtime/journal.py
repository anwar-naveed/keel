"""Reversible operation journal - P1.5

Ops table: journal(run_id, seq INTEGER, op_type, target, before, after,
applied_at)
apply_op(run_id, op) appends + executes inside ONE sqlite transaction that
also covers the state change (WAL mode).
undo_op reverses in reverse-seq order; rollback(run_id) replays undo for
all ops.
Ops for Phase 1: only "insert_row" (into a generic KV table the engine
owns) and "delete_row"
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class JournalOp:
    """A journal entry representing a reversible operation."""
    run_id: str
    seq: int = 0
    op_type: str = ""
    target: str = ""
    before: dict | None = None
    after: dict | None = None
    applied_at: str = ""


class Journal:
    """Reversible operation journal with transactional guarantees."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create journal and kv_store tables if they don't exist."""
        # Journal table
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                op_type TEXT NOT NULL,
                target TEXT NOT NULL,
                before TEXT,
                after TEXT,
                applied_at TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            )
            """
        )

        # Generic KV store table for Phase 1 operations
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def append(self, run_id: str, op: JournalOp) -> int:
        """Append an operation to the journal, returns sequence number."""
        # Get next sequence number
        cursor = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM journal WHERE run_id = ?",
            (run_id,)
        )
        seq = cursor.fetchone()[0]

        applied_at = datetime.now(UTC).isoformat()

        self.conn.execute(
            """
            INSERT INTO journal (run_id, seq, op_type, target, before, after, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                seq,
                op.op_type,
                op.target,
                json.dumps(op.before) if op.before is not None else None,
                json.dumps(op.after) if op.after is not None else None,
                applied_at,
            )
        )

        op.seq = seq
        op.applied_at = applied_at

        return seq

    def get_ops(self, run_id: str) -> list[JournalOp]:
        """Get all operations for a run in sequence order."""
        cursor = self.conn.execute(
            """
            SELECT run_id, seq, op_type, target, before, after, applied_at
            FROM journal
            WHERE run_id = ?
            ORDER BY seq ASC
            """,
            (run_id,)
        )

        ops = []
        for row in cursor.fetchall():
            before = json.loads(row[4]) if row[4] else None
            after = json.loads(row[5]) if row[5] else None
            ops.append(JournalOp(
                run_id=row[0],
                seq=row[1],
                op_type=row[2],
                target=row[3],
                before=before,
                after=after,
                applied_at=row[6],
            ))
        return ops

    def get_last_seq(self, run_id: str) -> int:
        """Get the last sequence number for a run."""
        cursor = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM journal WHERE run_id = ?",
            (run_id,)
        )
        return cursor.fetchone()[0]


def apply_op(conn: sqlite3.Connection, journal: Journal, run_id: str,
             op: JournalOp) -> int:
    """Apply an operation: append to journal + execute in ONE transaction."""
    # Both journal append and KV operation in same transaction
    seq = journal.append(run_id, op)

    # Execute the operation
    is_insert = (op.op_type == "insert_row" and op.target == "kv_store"
                 and op.after and "key" in op.after and "value" in op.after)
    is_delete = (op.op_type == "delete_row" and op.target == "kv_store"
                 and op.before and "key" in op.before)
    if is_insert:
        conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (op.after["key"], op.after["value"])
        )
    if is_delete:
        conn.execute(
            "DELETE FROM kv_store WHERE key = ?",
            (op.before["key"],)
        )

    conn.commit()
    return seq


def undo_op(conn: sqlite3.Connection, journal: Journal, run_id: str,
            seq: int) -> None:
    """Undo a specific operation by sequence number."""
    # Get the operation
    cursor = conn.execute(
        "SELECT op_type, target, before, after FROM journal WHERE run_id = ? AND seq = ?",
        (run_id, seq)
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Operation {seq} not found for run {run_id}")

    op_type, target, before_json, after_json = row
    before = json.loads(before_json) if before_json else None
    after = json.loads(after_json) if after_json else None

    # Reverse the operation
    is_insert_undo = (op_type == "insert_row" and target == "kv_store"
                      and after and "key" in after)
    is_delete_undo = (op_type == "delete_row" and target == "kv_store"
                      and before and "key" in before and "value" in before)
    if is_insert_undo:
        # Insert -> Delete
        conn.execute("DELETE FROM kv_store WHERE key = ?", (after["key"],))
    if is_delete_undo:
        # Delete -> Insert (restore)
        conn.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (before["key"], before["value"])
        )

    conn.commit()


def rollback(conn: sqlite3.Connection, journal: Journal, run_id: str) -> int:
    """Rollback all operations for a run in reverse sequence order."""
    ops = journal.get_ops(run_id)

    # Undo in reverse order
    for op in reversed(ops):
        if op.seq > 0:
            undo_op(conn, journal, run_id, op.seq)

    conn.commit()
    return len(ops)


__all__ = [
    "Journal",
    "JournalOp",
    "apply_op",
    "undo_op",
    "rollback",
]
