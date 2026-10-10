"""Tests for meta/watch.py — P5.1. Drift detection on seeded runlogs."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from keel.meta.watch import digest, scan
from keel.runtime.runlog import record
from keel.runtime.state import RunState, RunStatus, init_db


def _seed_run(data_dir: Path, conn, agent: str, status: RunStatus,
              cost: float = 0.0, error: str | None = None,
              when: datetime | None = None):
    run_id = str(uuid.uuid4())
    when = when or datetime.now(UTC)
    run = RunState(
        run_id=run_id, agent=agent, status=status, phase="x",
        created_at=when.isoformat(), updated_at=when.isoformat(),
    )
    run.save(conn)
    if cost:
        record(data_dir, run_id, "cost", {"cost_usd": cost, "model": "m"})
    if error:
        record(data_dir, run_id, "tool_result", {
            "name": "db", "result": "", "error": error,
        })
    return run_id


def test_no_drift_clean_room(tmp_path):
    conn = init_db(tmp_path / "db")
    _seed_run(tmp_path, conn, "triage", RunStatus.DONE, cost=0.01)
    findings = scan(tmp_path, conn)
    assert findings == []


def test_repeated_failure_signature(tmp_path):
    conn = init_db(tmp_path / "db")
    for _ in range(3):
        _seed_run(
            tmp_path, conn, "flaky", RunStatus.FAILED,
            error="connection refused to provider",
        )
    findings = scan(tmp_path, conn)
    kinds = [f["kind"] for f in findings]
    assert "repeated_failure" in kinds
    f = next(f for f in findings if f["kind"] == "repeated_failure")
    assert "flaky" in f["agent"]
    assert "connection refused" in f["detail"]


def test_two_failures_do_not_trigger(tmp_path):
    conn = init_db(tmp_path / "db")
    for _ in range(2):
        _seed_run(tmp_path, conn, "ok", RunStatus.FAILED, error="x")
    findings = scan(tmp_path, conn)
    assert all(f["kind"] != "repeated_failure" for f in findings)


def test_cost_spike_detected(tmp_path):
    conn = init_db(tmp_path / "db")
    now = datetime.now(UTC)
    # 6 stable days
    for d in range(2, 8):
        _seed_run(
            tmp_path, conn, "spender", RunStatus.DONE, cost=0.010,
            when=now - timedelta(days=d),
        )
    # today: 3x the mean
    _seed_run(tmp_path, conn, "spender", RunStatus.DONE, cost=0.035)
    findings = scan(tmp_path, conn)
    spikes = [f for f in findings if f["kind"] == "cost_spike"]
    assert spikes, findings
    assert "spender" in spikes[0]["agent"]


def test_tool_error_rate(tmp_path):
    conn = init_db(tmp_path / "db")
    # 6 results, 4 with errors -> 66% > 20%
    for i in range(4):
        _seed_run(tmp_path, conn, f"a{i}", RunStatus.FAILED, error="boom")
    for i in range(2):
        _seed_run(tmp_path, conn, f"ok{i}", RunStatus.DONE)
    # add clean tool_results to the ok runs
    for i in range(2):
        run = RunState.list_all(conn)[i]
        record(tmp_path, run.run_id, "tool_result", {
            "name": "db", "result": "fine",
        })
    findings = scan(tmp_path, conn)
    rates = [f for f in findings if f["kind"] == "tool_error_rate"]
    assert rates
    assert "66%" in rates[0]["detail"] or "exceeds" in rates[0]["detail"]


def test_findings_persisted(tmp_path):
    conn = init_db(tmp_path / "db")
    for _ in range(3):
        _seed_run(tmp_path, conn, "flaky", RunStatus.FAILED, error="sig")
    scan(tmp_path, conn)
    cursor = conn.execute("SELECT COUNT(*) FROM findings")
    assert cursor.fetchone()[0] >= 1


def test_digest_empty_and_full(tmp_path):
    assert digest([]) == "meta watch: no drift detected."
    d = digest([{"kind": "repeated_failure", "agent": "x", "detail": "y"}])
    assert "1 finding" in d and "x" in d
