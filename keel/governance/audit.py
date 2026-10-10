"""Hash-chained append-only audit log — P2.4.

Entries: {seq, ts, actor, action, run_id, prev_hash, body_hash}.
body_hash = sha256(canonical json of the entry body);
entry_hash = sha256(prev_hash + body_hash).
`keel audit verify` walks the chain; any tamper breaks verification.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime


class AuditError(Exception):
    """Base audit error."""


class AuditTamperedError(AuditError):
    """The chain does not verify — an entry was altered or removed."""

    def __init__(self, seq: int, reason: str):
        self.seq = seq
        self.reason = reason
        super().__init__(f"audit chain tampered at seq {seq}: {reason}")


GENESIS_HASH = "0" * 64


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            run_id TEXT,
            detail TEXT,
            prev_hash TEXT NOT NULL,
            body_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _body_hash(entry: dict) -> str:
    """sha256 over canonical json of the entry body (excluding hashes)."""
    body = {
        "seq": entry["seq"],
        "ts": entry["ts"],
        "actor": entry["actor"],
        "action": entry["action"],
        "run_id": entry["run_id"],
        "detail": entry["detail"],
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _entry_hash(prev_hash: str, body_hash: str) -> str:
    return hashlib.sha256((prev_hash + body_hash).encode()).hexdigest()


class AuditLog:
    """Append-only hash-chained audit log backed by SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        _ensure_table(conn)

    def append(self, actor: str, action: str, run_id: str | None = None,
               detail: str | None = None) -> int:
        """Append an entry; hash-chained to the previous entry."""
        cursor = self.conn.execute(
            "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        )
        row = cursor.fetchone()
        prev_hash = row[0] if row else GENESIS_HASH

        seq_cursor = self.conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM audit_log"
        )
        seq = seq_cursor.fetchone()[0] + 1

        ts = datetime.now(UTC).isoformat()
        body_hash = _body_hash({
            "seq": seq,
            "ts": ts,
            "actor": actor,
            "action": action,
            "run_id": run_id,
            "detail": detail,
        })
        entry_hash = _entry_hash(prev_hash, body_hash)

        self.conn.execute(
            """
            INSERT INTO audit_log
                (seq, ts, actor, action, run_id, detail, prev_hash,
                 body_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (seq, ts, actor, action, run_id, detail, prev_hash,
             body_hash, entry_hash),
        )
        self.conn.commit()
        return seq

    def entries(self) -> list[dict]:
        """All entries in seq order."""
        cursor = self.conn.execute(
            "SELECT seq, ts, actor, action, run_id, detail, prev_hash, "
            "body_hash, entry_hash FROM audit_log ORDER BY seq ASC"
        )
        return [
            {
                "seq": r[0], "ts": r[1], "actor": r[2], "action": r[3],
                "run_id": r[4], "detail": r[5], "prev_hash": r[6],
                "body_hash": r[7], "entry_hash": r[8],
            }
            for r in cursor.fetchall()
        ]

    def verify(self) -> int:
        """Walk the chain. Returns number of verified entries.
        Raises AuditTamperedError on the first inconsistency."""
        prev = GENESIS_HASH
        count = 0
        for e in self.entries():
            if e["prev_hash"] != prev:
                raise AuditTamperedError(
                    e["seq"], "prev_hash does not chain to previous entry"
                )
            expected_body = _body_hash(e)
            if e["body_hash"] != expected_body:
                raise AuditTamperedError(
                    e["seq"], "body_hash mismatch (entry edited in place)"
                )
            expected_entry = _entry_hash(e["prev_hash"], e["body_hash"])
            if e["entry_hash"] != expected_entry:
                raise AuditTamperedError(
                    e["seq"], "entry_hash mismatch"
                )
            prev = e["entry_hash"]
            count += 1
        return count


__all__ = [
    "AuditLog",
    "AuditError",
    "AuditTamperedError",
    "GENESIS_HASH",
]
