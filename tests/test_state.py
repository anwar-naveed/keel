"""Tests for runtime/state.py - P1.2"""

import pytest

from keel.runtime.state import InvalidTransition, RunState, RunStatus, init_db


def test_legal_transitions():
    """Test all legal state transitions."""
    # pending -> running
    assert RunState.can_transition(RunStatus.PENDING, RunStatus.RUNNING)
    # running -> review, done, failed
    assert RunState.can_transition(RunStatus.RUNNING, RunStatus.REVIEW)
    assert RunState.can_transition(RunStatus.RUNNING, RunStatus.DONE)
    assert RunState.can_transition(RunStatus.RUNNING, RunStatus.FAILED)
    # review -> done, rolled_back
    assert RunState.can_transition(RunStatus.REVIEW, RunStatus.DONE)
    assert RunState.can_transition(RunStatus.REVIEW, RunStatus.ROLLED_BACK)
    # startup repair: running -> pending (interrupted run re-queued)
    assert RunState.can_transition(RunStatus.RUNNING, RunStatus.PENDING)


def test_illegal_transitions_rejected():
    """Test that illegal transitions raise InvalidTransition."""
    # pending cannot go directly to done, failed, review, rolled_back
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.PENDING, RunStatus.DONE)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.PENDING, RunStatus.FAILED)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.PENDING, RunStatus.REVIEW)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.PENDING, RunStatus.ROLLED_BACK)

    # running cannot go to pending (except startup repair which is special)
    # Actually running -> pending IS allowed for startup repair
    # So this should be allowed
    assert RunState.can_transition(RunStatus.RUNNING, RunStatus.PENDING)

    # done cannot transition to anything
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.DONE, RunStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.DONE, RunStatus.FAILED)

    # failed cannot transition to anything
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.FAILED, RunStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.FAILED, RunStatus.DONE)

    # rolled_back cannot transition to anything
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.ROLLED_BACK, RunStatus.RUNNING)
    with pytest.raises(InvalidTransition):
        RunState.transition(RunStatus.ROLLED_BACK, RunStatus.DONE)


def test_run_state_creation():
    """Test creating a new run state."""
    run = RunState.create(
        run_id="test-123",
        agent="triage",
        phase="init"
    )
    assert run.run_id == "test-123"
    assert run.agent == "triage"
    assert run.status == RunStatus.PENDING
    assert run.phase == "init"
    assert run.created_at is not None
    assert run.updated_at is not None


def test_run_state_transition():
    """Test transitioning a run state."""
    run = RunState.create(run_id="test-123", agent="triage")

    # pending -> running
    run = run.transition_to(RunStatus.RUNNING, phase="executing")
    assert run.status == RunStatus.RUNNING
    assert run.phase == "executing"

    # running -> done
    run = run.transition_to(RunStatus.DONE, phase="complete")
    assert run.status == RunStatus.DONE
    assert run.phase == "complete"


def test_invalid_transition_raises():
    """Test that invalid transition on instance raises."""
    run = RunState.create(run_id="test-123", agent="triage")
    run = run.transition_to(RunStatus.RUNNING)
    run = run.transition_to(RunStatus.DONE)

    # done cannot go to running
    with pytest.raises(InvalidTransition):
        run.transition_to(RunStatus.RUNNING)


def test_db_init_creates_runs_table(tmp_path):
    """Test that init_db creates the runs table with correct schema."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='runs'")
    schema = cursor.fetchone()[0]

    assert "id TEXT PRIMARY KEY" in schema
    assert "agent TEXT" in schema
    assert "status TEXT" in schema
    assert "phase TEXT" in schema
    assert "created_at TEXT" in schema
    assert "updated_at TEXT" in schema

    conn.close()


def test_save_and_load_run(tmp_path):
    """Test saving and loading a run from the database."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    run = RunState.create(run_id="test-123", agent="triage", phase="init")
    run.save(conn)

    loaded = RunState.load(conn, "test-123")
    assert loaded.run_id == "test-123"
    assert loaded.agent == "triage"
    assert loaded.status == RunStatus.PENDING
    assert loaded.phase == "init"

    conn.close()


def test_update_run_status(tmp_path):
    """Test updating run status in database."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    run = RunState.create(run_id="test-123", agent="triage")
    run.save(conn)

    run = run.transition_to(RunStatus.RUNNING, phase="executing")
    run.save(conn)

    loaded = RunState.load(conn, "test-123")
    assert loaded.status == RunStatus.RUNNING
    assert loaded.phase == "executing"

    conn.close()


def test_startup_repair_running_to_pending(tmp_path):
    """Test startup repair: interrupted running run gets re-queued to pending."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    # Simulate a run that was running but interrupted
    run = RunState.create(run_id="test-123", agent="triage")
    run = run.transition_to(RunStatus.RUNNING, phase="executing")
    run.save(conn)

    # On startup, repair running -> pending
    loaded = RunState.load(conn, "test-123")
    assert loaded.status == RunStatus.RUNNING

    # This is the startup repair transition
    repaired = loaded.transition_to(RunStatus.PENDING, phase="requeued")
    assert repaired.status == RunStatus.PENDING
    assert repaired.phase == "requeued"
    repaired.save(conn)

    # Verify it's now pending
    loaded2 = RunState.load(conn, "test-123")
    assert loaded2.status == RunStatus.PENDING
    assert loaded2.phase == "requeued"

    conn.close()


def test_list_runs(tmp_path):
    """Test listing all runs."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)

    run1 = RunState.create(run_id="run-1", agent="triage")
    run1.save(conn)

    run2 = RunState.create(run_id="run-2", agent="triage")
    run2 = run2.transition_to(RunStatus.RUNNING)
    run2.save(conn)

    runs = RunState.list_all(conn)
    assert len(runs) == 2

    conn.close()


def test_invalid_transition_exception_message():
    """Test that InvalidTransition has useful message."""
    with pytest.raises(InvalidTransition) as exc_info:
        RunState.transition(RunStatus.DONE, RunStatus.RUNNING)

    assert "done" in str(exc_info.value).lower()
    assert "running" in str(exc_info.value).lower()
