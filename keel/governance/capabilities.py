"""Capability objects — P2.2.

The structural core of keel governance (ADR-002): a capability the tier does
not grant simply does not exist as a method on the tool object handed to the
provider. `hasattr` is the contract. A prompt-injected model that attempts
`db.write` on a read-only tool gets AttributeError at the tool boundary —
the write is impossible, not merely forbidden.

- ReadOnlyDB: `select` only. No write/update/delete attributes exist.
- StagingDB: `stage_write` lands rows in the `staging` table + journal.
- GatedDB: extends staging; `apply` requires a review token issued by
  review.py.
"""

import sqlite3
from dataclasses import dataclass

from keel.runtime.journal import JournalOp


class CapabilityError(Exception):
    """Base capability error."""


class ReviewRequiredError(CapabilityError):
    """Apply attempted without a valid review token."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(
            f"run {run_id} holds staged writes awaiting review — "
            "apply requires an approved review token (keel approve)"
        )


@dataclass
class StagedWrite:
    """A write parked in staging, awaiting review."""

    staging_id: int
    run_id: str
    key: str
    value: str


class ReadOnlyDB:
    """Read-only KV tool. The ONLY method is `select`.

    There is intentionally NO write/update/delete attribute anywhere on this
    class — that absence is the security model (ADR-002).
    """

    def __init__(self, conn: sqlite3.Connection, run_id: str):
        self._conn = conn
        self.run_id = run_id

    def select(self, key: str) -> str:
        """Read a key from the KV store. Empty string if absent."""
        cursor = self._conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else ""


class StagingDB(ReadOnlyDB):
    """Draft-tier tool: reads work; writes park in `staging`, never applied."""

    def __init__(self, conn: sqlite3.Connection, run_id: str, journal):
        super().__init__(conn, run_id)
        self._journal = journal
        self._ensure_staging_table()

    def _ensure_staging_table(self) -> None:
        self._conn.execute(
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
        self._conn.commit()

    def stage_write(self, key: str, value: str) -> int:
        """Park a write in staging. NOT applied to kv_store. Returns id."""
        from datetime import UTC, datetime

        cursor = self._conn.execute(
            """
            INSERT INTO staging (run_id, key, value, staged_at)
            VALUES (?, ?, ?, ?)
            """,
            (self.run_id, key, value, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()
        return cursor.lastrowid

    def list_staged(self, run_id: str | None = None) -> list[StagedWrite]:
        """List staged writes for this (or a given) run."""
        target = run_id or self.run_id
        cursor = self._conn.execute(
            "SELECT id, run_id, key, value FROM staging WHERE run_id = ?",
            (target,),
        )
        return [
            StagedWrite(staging_id=row[0], run_id=row[1], key=row[2], value=row[3])
            for row in cursor.fetchall()
        ]

    def drop_staged(self, run_id: str | None = None) -> int:
        """Delete staged writes (used by reject). Returns count dropped."""
        target = run_id or self.run_id
        cursor = self._conn.execute(
            "DELETE FROM staging WHERE run_id = ?", (target,)
        )
        self._conn.commit()
        return cursor.rowcount


class GatedDB(StagingDB):
    """write_with_approval tool: staged writes; apply needs a review token."""

    def apply(self, review_token: str, key: str, value: str, staging_id: int) -> str:
        """Apply one staged write. review_token must have been issued by
        keel.governance.review for this run (approve path)."""
        from keel.governance.review import verify_review_token

        if not verify_review_token(self._conn, self.run_id, review_token):
            raise ReviewRequiredError(self.run_id)

        # Remove from staging
        self._conn.execute(
            "DELETE FROM staging WHERE id = ?", (staging_id,)
        )
        # Apply for real, journaled
        op = JournalOp(
            run_id=self.run_id,
            op_type="insert_row",
            target="kv_store",
            before=None,
            after={"key": key, "value": value},
        )
        from keel.runtime.journal import apply_op

        apply_op(self._conn, self._journal, self.run_id, op)
        return f"Applied key: {key}"


def build_tool_for_tier(tier_name: str, conn: sqlite3.Connection,
                        run_id: str, journal) -> ReadOnlyDB:
    """Factory: build the capability object for a tier. This is where the
    boundary becomes structural — the object built carries exactly the
    methods the tier allows."""
    from keel.governance.tiers import Tier, tier_for

    tier = tier_for(tier_name)
    if tier == Tier.READ_ONLY:
        return ReadOnlyDB(conn, run_id)
    if tier == Tier.DRAFT:
        return StagingDB(conn, run_id, journal)
    if tier == Tier.WRITE_WITH_APPROVAL:
        return GatedDB(conn, run_id, journal)
    # forbidden: no tool at all — and enqueue was already refused
    raise CapabilityError("tier 'forbidden' gets no tool object")


__all__ = [
    "ReadOnlyDB",
    "StagingDB",
    "GatedDB",
    "StagedWrite",
    "CapabilityError",
    "ReviewRequiredError",
    "build_tool_for_tier",
]
