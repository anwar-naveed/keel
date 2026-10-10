"""Tests for runtime/journal.py - P1.5"""

from keel.runtime.journal import Journal, JournalOp, apply_op, rollback, undo_op
from keel.runtime.state import RunState, init_db


def test_journal_append_and_apply(tmp_path):
    """Test that apply_op appends to journal and executes in one transaction."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    journal = Journal(conn)

    run_id = "test-run-123"
    run = RunState.create(run_id=run_id, agent="triage")
    run.save(conn)

    # Apply an insert operation
    op = JournalOp(
        run_id=run_id,
        op_type="insert_row",
        target="kv_store",
        before=None,
        after={"key": "test", "value": "data"},
    )

    apply_op(conn, journal, run_id, op)

    # Verify journal entry exists
    cursor = conn.execute("SELECT * FROM journal WHERE run_id = ?", (run_id,))
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][2] == "insert_row"  # op_type
    assert rows[0][3] == "kv_store"   # target

    # Verify KV table was created and data inserted
    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("test",))
    row = cursor.fetchone()
    assert row is not None
    assert row[1] == "data"

    conn.close()


def test_journal_undo_reverses(tmp_path):
    """Test that undo_op reverses the operation."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    journal = Journal(conn)

    run_id = "test-run-123"
    run = RunState.create(run_id=run_id, agent="triage")
    run.save(conn)

    # Apply insert
    op = JournalOp(
        run_id=run_id,
        op_type="insert_row",
        target="kv_store",
        before=None,
        after={"key": "test", "value": "data"},
    )
    apply_op(conn, journal, run_id, op)

    # Verify data exists
    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("test",))
    assert cursor.fetchone() is not None

    # Undo the operation
    undo_op(conn, journal, run_id, 1)  # seq 1

    # Verify data is gone
    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("test",))
    assert cursor.fetchone() is None

    conn.close()


def test_rollback_replays_all_undos(tmp_path):
    """Test that rollback reverses all operations in reverse order."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    journal = Journal(conn)

    run_id = "test-run-123"
    run = RunState.create(run_id=run_id, agent="triage")
    run.save(conn)

    # Apply multiple operations
    op1 = JournalOp(run_id=run_id, op_type="insert_row", target="kv_store",
                    before=None, after={"key": "a", "value": "1"})
    op2 = JournalOp(run_id=run_id, op_type="insert_row", target="kv_store",
                    before=None, after={"key": "b", "value": "2"})
    op3 = JournalOp(run_id=run_id, op_type="delete_row", target="kv_store",
                    before={"key": "a", "value": "1"}, after=None)

    apply_op(conn, journal, run_id, op1)
    apply_op(conn, journal, run_id, op2)
    apply_op(conn, journal, run_id, op3)

    # Verify state: a deleted, b exists
    cursor = conn.execute("SELECT key FROM kv_store")
    keys = [row[0] for row in cursor.fetchall()]
    assert "a" not in keys
    assert "b" in keys

    # Rollback all
    rollback(conn, journal, run_id)

    # Verify state restored to empty (before any ops)
    cursor = conn.execute("SELECT key FROM kv_store")
    keys = [row[0] for row in cursor.fetchall()]
    assert len(keys) == 0

    conn.close()


def test_crash_between_append_and_transition(tmp_path):
    """Test crash simulation: kill transaction mid-way, assert no half-applied state."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    journal = Journal(conn)

    run_id = "test-run-123"
    run = RunState.create(run_id=run_id, agent="triage")
    run.save(conn)

    # Start a transaction manually to simulate crash
    conn.execute("BEGIN")

    # Append to journal
    op = JournalOp(
        run_id=run_id,
        op_type="insert_row",
        target="kv_store",
        before=None,
        after={"key": "crash_test", "value": "data"},
    )
    journal.append(run_id, op)

    # Simulate crash - DON'T commit, just rollback the transaction
    conn.execute("ROLLBACK")

    # Verify no half-applied state
    cursor = conn.execute("SELECT * FROM journal WHERE run_id = ?", (run_id,))
    assert cursor.fetchone() is None  # Journal entry not committed

    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("crash_test",))
    assert cursor.fetchone() is None  # KV entry not committed

    conn.close()


def test_delete_row_operation(tmp_path):
    """Test delete_row operation and its reversal."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    journal = Journal(conn)

    run_id = "test-run-123"
    run = RunState.create(run_id=run_id, agent="triage")
    run.save(conn)

    # First insert a row
    conn.execute("INSERT INTO kv_store (key, value) VALUES (?, ?)", ("to_delete", "value"))
    conn.commit()

    # Verify it exists
    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("to_delete",))
    assert cursor.fetchone() is not None

    # Apply delete operation
    op = JournalOp(
        run_id=run_id,
        op_type="delete_row",
        target="kv_store",
        before={"key": "to_delete", "value": "value"},
        after=None,
    )
    apply_op(conn, journal, run_id, op)

    # Verify it's deleted
    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("to_delete",))
    assert cursor.fetchone() is None

    # Undo should restore it
    undo_op(conn, journal, run_id, 1)

    cursor = conn.execute("SELECT * FROM kv_store WHERE key = ?", ("to_delete",))
    row = cursor.fetchone()
    assert row is not None
    assert row[1] == "value"

    conn.close()


def test_journal_op_dataclass():
    """Test JournalOp dataclass."""
    op = JournalOp(
        run_id="run-1",
        seq=1,
        op_type="insert_row",
        target="kv_store",
        before=None,
        after={"key": "test"},
        applied_at="2024-01-01T00:00:00",
    )
    assert op.run_id == "run-1"
    assert op.seq == 1
    assert op.op_type == "insert_row"
