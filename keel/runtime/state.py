"""Runtime state machine - P1.2

SQLite runs table: id TEXT PK, agent TEXT, status TEXT, phase TEXT, created_at TEXT, updated_at TEXT
Statuses: pending|running|review|done|failed|rolled_back
Transitions map:
  pending->running
  running->{review,done,failed}
  review->{done,rolled_back}
  startup-repair running->pending (interrupted run re-queued on init)
Illegal transition raises InvalidTransition (custom exception).
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Optional


class RunStatus(StrEnum):
    """Run status values."""
    PENDING = "pending"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# Legal transitions: from_status -> set of allowed to_status
TRANSITIONS = {
    RunStatus.PENDING: {RunStatus.RUNNING},
    RunStatus.RUNNING: {
        RunStatus.REVIEW,
        RunStatus.DONE,
        RunStatus.FAILED,
        RunStatus.PENDING,  # PENDING for startup repair
    },
    RunStatus.REVIEW: {RunStatus.DONE, RunStatus.ROLLED_BACK},
    RunStatus.DONE: set(),
    RunStatus.FAILED: set(),
    RunStatus.ROLLED_BACK: set(),
}


class InvalidTransition(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, from_status: RunStatus, to_status: RunStatus):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Invalid transition from {from_status.value} to {to_status.value}"
        )


@dataclass(frozen=True)
class RunState:
    """Immutable run state."""

    run_id: str
    agent: str
    status: RunStatus
    phase: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(cls, run_id: str, agent: str, phase: str = "init") -> "RunState":
        """Create a new run in PENDING status."""
        return cls(
            run_id=run_id,
            agent=agent,
            status=RunStatus.PENDING,
            phase=phase,
        )

    @classmethod
    def can_transition(cls, from_status: RunStatus, to_status: RunStatus) -> bool:
        """Check if a transition is legal."""
        return to_status in TRANSITIONS.get(from_status, set())

    @classmethod
    def transition(cls, from_status: RunStatus, to_status: RunStatus) -> None:
        """Validate a transition, raise InvalidTransition if illegal."""
        if not cls.can_transition(from_status, to_status):
            raise InvalidTransition(from_status, to_status)

    def transition_to(self, new_status: RunStatus, phase: str | None = None) -> "RunState":
        """Return a new RunState with the transition applied."""
        self.__class__.transition(self.status, new_status)
        return RunState(
            run_id=self.run_id,
            agent=self.agent,
            status=new_status,
            phase=phase if phase is not None else self.phase,
            created_at=self.created_at,
            updated_at=datetime.now(UTC).isoformat(),
        )

    def save(self, conn: sqlite3.Connection) -> None:
        """Save this run state to the database."""
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (id, agent, status, phase, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.run_id,
                self.agent,
                self.status.value,
                self.phase,
                self.created_at,
                self.updated_at,
            ),
        )
        conn.commit()

    @classmethod
    def load(cls, conn: sqlite3.Connection, run_id: str) -> Optional["RunState"]:
        """Load a run state from the database."""
        cursor = conn.execute(
            "SELECT id, agent, status, phase, created_at, updated_at FROM runs WHERE id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return cls(
            run_id=row[0],
            agent=row[1],
            status=RunStatus(row[2]),
            phase=row[3],
            created_at=row[4],
            updated_at=row[5],
        )

    @classmethod
    def list_all(cls, conn: sqlite3.Connection) -> list["RunState"]:
        """List all runs, ordered by created_at DESC."""
        cursor = conn.execute(
            "SELECT id, agent, status, phase, created_at, updated_at "
            "FROM runs ORDER BY created_at DESC"
        )
        return [
            cls(
                run_id=row[0],
                agent=row[1],
                status=RunStatus(row[2]),
                phase=row[3],
                created_at=row[4],
                updated_at=row[5],
            )
            for row in cursor.fetchall()
        ]


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the database with WAL mode and create the runs table.

    check_same_thread=False: the MCP server dispatches tool calls on a
    worker thread; keel is single-writer (ADR-001) so cross-thread access
    is serialized by design.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


__all__ = [
    "RunStatus",
    "RunState",
    "InvalidTransition",
    "init_db",
    "TRANSITIONS",
]
