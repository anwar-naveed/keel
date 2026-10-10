"""Tests for governance/review.py — P2.3."""

import pytest

from keel.governance.audit import AuditLog
from keel.governance.review import (
    NotInReviewError,
    ReviewError,
    approve,
    issue_review_token,
    reject,
    verify_review_token,
)
from keel.runtime.journal import Journal
from keel.runtime.queue import Queue
from keel.runtime.state import RunState, RunStatus, init_db


@pytest.fixture
def env(tmp_path):
    conn = init_db(tmp_path / "keel.db")
    journal = Journal(conn)
    audit = AuditLog(conn)
    queue = Queue(conn)
    # ensure staging table exists (as the engine would via StagingDB)
    from keel.governance.capabilities import StagingDB
    StagingDB(conn, "setup", journal)
    yield conn, journal, audit, queue, tmp_path
    conn.close()


def _stage_one_write(conn, run_id, key="target", value="staged"):
    conn.execute(
        "INSERT INTO staging (run_id, key, value, staged_at) "
        "VALUES (?, ?, ?, '2026-01-01T00:00:00Z')",
        (run_id, key, value),
    )
    conn.commit()


def _make_review_run(conn, queue, run_id=None, agent="qa_review"):
    entry = queue.enqueue(agent, {"input": "check the report"})
    run = RunState.load(conn, entry.run_id)
    run = run.transition_to(RunStatus.RUNNING, phase="claimed")
    run.save(conn)
    run = run.transition_to(RunStatus.REVIEW, phase="staged-writes")
    run.save(conn)
    return run


def test_approve_applies_staged_writes(env):
    conn, journal, audit, queue, data_dir = env
    run = _make_review_run(conn, queue)
    _stage_one_write(conn, run.run_id, "report", "final")

    approved = approve(conn, journal, data_dir, run.run_id, audit)
    assert approved.status == RunStatus.DONE

    cursor = conn.execute(
        "SELECT value FROM kv_store WHERE key = 'report'"
    )
    assert cursor.fetchone()[0] == "final"

    # staging cleared
    cursor = conn.execute(
        "SELECT COUNT(*) FROM staging WHERE run_id = ?", (run.run_id,)
    )
    assert cursor.fetchone()[0] == 0

    # audit entry emitted
    entries = audit.entries()
    assert any(
        e["action"] == "approve" and e["run_id"] == run.run_id
        for e in entries
    )


def test_reject_drops_staged_writes(env):
    conn, journal, audit, queue, data_dir = env
    run = _make_review_run(conn, queue)
    _stage_one_write(conn, run.run_id, "report", "never-lands")

    rejected = reject(conn, data_dir, run.run_id, audit)
    assert rejected.status == RunStatus.ROLLED_BACK

    cursor = conn.execute(
        "SELECT value FROM kv_store WHERE key = 'report'"
    )
    assert cursor.fetchone() is None

    # audit entry emitted
    entries = audit.entries()
    assert any(
        e["action"] == "reject" and e["run_id"] == run.run_id
        for e in entries
    )


def test_approve_requires_review_state(env):
    conn, journal, audit, queue, data_dir = env
    entry = queue.enqueue("qa_review", {"input": "x"})
    # still pending, never entered review
    with pytest.raises(NotInReviewError):
        approve(conn, journal, data_dir, entry.run_id, audit)


def test_approve_without_staged_writes_is_error(env):
    conn, journal, audit, queue, data_dir = env
    run = _make_review_run(conn, queue)
    with pytest.raises(ReviewError):
        approve(conn, journal, data_dir, run.run_id, audit)


def test_review_token_lifecycle(env):
    conn, *_ = env
    token = issue_review_token(conn, "run-x")
    assert verify_review_token(conn, "run-x", token) is True
    assert verify_review_token(conn, "run-x", "wrong") is False
