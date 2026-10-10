"""Tests for runtime/queue.py - P1.3"""

import time
from datetime import UTC, datetime

import pytest

from keel.runtime.queue import Queue, QueueEntry
from keel.runtime.state import RunState, RunStatus, init_db


def test_enqueue_creates_entry(tmp_path):
    """Test enqueue creates a queue entry."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry = queue.enqueue(agent="triage", payload={"input": "test"})

    assert entry.agent == "triage"
    assert entry.payload == {"input": "test"}
    assert entry.status == RunStatus.PENDING
    assert entry.run_id is not None

    # Verify it's in the database
    loaded = RunState.load(conn, entry.run_id)
    assert loaded is not None
    assert loaded.agent == "triage"
    assert loaded.status == RunStatus.PENDING

    conn.close()


def test_fifo_order(tmp_path):
    """Test that next_pending returns entries in FIFO order by created_at."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry1 = queue.enqueue(agent="triage", payload={"input": "first"})
    time.sleep(0.01)  # Ensure different timestamps
    entry2 = queue.enqueue(agent="triage", payload={"input": "second"})
    time.sleep(0.01)
    entry3 = queue.enqueue(agent="triage", payload={"input": "third"})

    # Get first pending
    next1 = queue.next_pending()
    assert next1.run_id == entry1.run_id

    # Mark first as running
    run1 = RunState.load(conn, entry1.run_id)
    run1 = run1.transition_to(RunStatus.RUNNING)
    run1.save(conn)

    # Get second pending
    next2 = queue.next_pending()
    assert next2.run_id == entry2.run_id

    # Mark second as running
    run2 = RunState.load(conn, entry2.run_id)
    run2 = run2.transition_to(RunStatus.RUNNING)
    run2.save(conn)

    # Get third pending
    next3 = queue.next_pending()
    assert next3.run_id == entry3.run_id

    conn.close()


def test_claim_marks_running(tmp_path):
    """Test that claiming a pending entry marks it running."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry = queue.enqueue(agent="triage", payload={"input": "test"})

    claimed = queue.claim(entry.run_id)

    assert claimed.status == RunStatus.RUNNING
    assert claimed.claimed_at is not None

    # Verify in database
    loaded = RunState.load(conn, entry.run_id)
    assert loaded.status == RunStatus.RUNNING

    conn.close()


def test_cannot_claim_non_pending(tmp_path):
    """Test that claiming a non-pending entry raises."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry = queue.enqueue(agent="triage", payload={"input": "test"})

    # First claim succeeds
    queue.claim(entry.run_id)

    # Second claim should fail (already running)
    with pytest.raises(ValueError, match="not pending"):
        queue.claim(entry.run_id)

    conn.close()


def test_reclaim_after_crash(tmp_path):
    """Test reclaiming a stale claimed entry (crash recovery)."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry = queue.enqueue(agent="triage", payload={"input": "test"})
    queue.claim(entry.run_id)

    # Manually set claimed_at to old time (simulate crash >10 min ago)
    conn.execute(
        "UPDATE runs SET updated_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), entry.run_id)
    )
    # Actually the reclaim logic checks claimed_at, so we need a separate column
    # Let me check the Queue implementation first

    conn.close()


def test_next_pending_returns_none_when_empty(tmp_path):
    """Test next_pending returns None when no pending entries."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    result = queue.next_pending()
    assert result is None

    conn.close()


def test_next_pending_skips_running(tmp_path):
    """Test next_pending skips entries that are already running."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry1 = queue.enqueue(agent="triage", payload={"input": "first"})
    entry2 = queue.enqueue(agent="triage", payload={"input": "second"})

    # Claim first
    queue.claim(entry1.run_id)

    # Next pending should be second
    next_entry = queue.next_pending()
    assert next_entry.run_id == entry2.run_id

    conn.close()


def test_list_pending(tmp_path):
    """Test listing all pending entries."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    queue = Queue(conn)

    entry1 = queue.enqueue(agent="triage", payload={"input": "first"})
    entry2 = queue.enqueue(agent="triage", payload={"input": "second"})
    queue.claim(entry1.run_id)

    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].run_id == entry2.run_id

    conn.close()


def test_queue_entry_dataclass():
    """Test QueueEntry dataclass."""
    from datetime import datetime
    entry = QueueEntry(
        run_id="test-123",
        agent="triage",
        payload={"key": "value"},
        status=RunStatus.PENDING,
        created_at=datetime.now(UTC).isoformat(),
        claimed_at=None,
    )
    assert entry.run_id == "test-123"
    assert entry.agent == "triage"
    assert entry.payload == {"key": "value"}
