"""Review gate — P2.3.

Runs whose tier is write_with_approval enter `review` state with their
writes parked in staging. `keel approve <run>` applies the staged ops
(journaled, then done); `keel reject <run>` drops staging (rolled_back).
Both paths emit audit entries.
"""

import hashlib
import sqlite3
from datetime import UTC, datetime

from keel.runtime.journal import JournalOp, apply_op
from keel.runtime.state import RunState, RunStatus


class ReviewError(Exception):
    """Base review error."""


class NotInReviewError(ReviewError):
    """Approve/reject attempted on a run that is not in review."""

    def __init__(self, run_id: str, status: str):
        super().__init__(
            f"run {run_id} is not in review (status: {status})"
        )


def _ensure_staging_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS staging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            staged_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _ensure_review_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_tokens (
            run_id TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def issue_review_token(conn: sqlite3.Connection, run_id: str) -> str:
    """Issue a single-use review token for a run (approve path)."""
    _ensure_review_table(conn)
    token = hashlib.sha256(
        f"{run_id}:{datetime.now(UTC).isoformat()}".encode()
    ).hexdigest()
    conn.execute(
        "INSERT OR REPLACE INTO review_tokens (run_id, token, issued_at, used) "
        "VALUES (?, ?, ?, 0)",
        (run_id, token, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    return token


def verify_review_token(conn: sqlite3.Connection, run_id: str,
                        token: str) -> bool:
    """Verify a review token for a run; single-use."""
    _ensure_review_table(conn)
    cursor = conn.execute(
        "SELECT token, used FROM review_tokens WHERE run_id = ?",
        (run_id,),
    )
    row = cursor.fetchone()
    if row is None or row[0] != token or row[1]:
        return False
    conn.execute(
        "UPDATE review_tokens SET used = 1 WHERE run_id = ?", (run_id,)
    )
    conn.commit()
    return True


def approve(conn: sqlite3.Connection, journal, data_dir, run_id: str,
            audit_log) -> RunState:
    """Approve a run in review: apply staged writes (journaled), go done.

    Emits an audit entry; returns the new run state.
    """
    _ensure_staging_table(conn)
    run = RunState.load(conn, run_id)
    if run is None or run.status != RunStatus.REVIEW:
        status = run.status.value if run else "missing"
        raise NotInReviewError(run_id, status)

    # Fetch staged writes
    cursor = conn.execute(
        "SELECT id, key, value FROM staging WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    )
    staged = cursor.fetchall()
    if not staged:
        raise ReviewError(f"run {run_id} has no staged writes to approve")

    # Apply each staged write through the journal
    for _staging_id, key, value in staged:
        op = JournalOp(
            run_id=run_id,
            op_type="insert_row",
            target="kv_store",
            before=None,
            after={"key": key, "value": value},
        )
        apply_op(conn, journal, run_id, op)

    # Clear staging for this run
    conn.execute("DELETE FROM staging WHERE run_id = ?", (run_id,))
    conn.commit()

    # Transition to done
    run = run.transition_to(RunStatus.DONE, phase="approved")
    run.save(conn)

    audit_log.append(
        actor="reviewer",
        action="approve",
        run_id=run_id,
        detail=f"applied {len(staged)} staged write(s)",
    )
    return run


def reject(conn: sqlite3.Connection, data_dir, run_id: str,
           audit_log) -> RunState:
    """Reject a run in review: drop staged writes, roll back to rolled_back.

    Emits an audit entry; returns the new run state.
    """
    _ensure_staging_table(conn)
    run = RunState.load(conn, run_id)
    if run is None or run.status != RunStatus.REVIEW:
        status = run.status.value if run else "missing"
        raise NotInReviewError(run_id, status)

    # Drop staging
    cursor = conn.execute(
        "DELETE FROM staging WHERE run_id = ?", (run_id,)
    )
    dropped = cursor.rowcount
    conn.commit()

    # Transition to rolled_back
    run = run.transition_to(RunStatus.ROLLED_BACK, phase="rejected")
    run.save(conn)

    audit_log.append(
        actor="reviewer",
        action="reject",
        run_id=run_id,
        detail=f"dropped {dropped} staged write(s)",
    )
    return run


__all__ = [
    "ReviewError",
    "NotInReviewError",
    "issue_review_token",
    "verify_review_token",
    "approve",
    "reject",
]
