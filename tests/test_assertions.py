"""Tests for eval/assertions.py — P3.1. Each assertion, pass and fail path."""

from keel.eval.assertions import check_assertion
from keel.governance.audit import AuditLog
from keel.governance.tiers import Tier
from keel.runtime.runlog import RunEvent
from keel.runtime.state import RunState, RunStatus


def _run(status=RunStatus.DONE):
    return RunState.create("r1", "triage").transition_to(
        RunStatus.RUNNING
    ).transition_to(status)


def _events(*specs):
    return [
        RunEvent(run_id="r1", type=t, payload=p, timestamp="2026-01-01T00:00:00Z")
        for t, p in specs
    ]


def _audit(tmp_path, entries=1):
    from keel.runtime.state import init_db

    conn = init_db(tmp_path / "a.db")
    log = AuditLog(conn)
    for i in range(entries):
        log.append(actor="engine", action="run_done", run_id=f"r{i}")
    return log


def test_state_reached_pass_fail():
    v = check_assertion("state_reached", "done", _run(), [], None)
    assert v.passed
    v = check_assertion("state_reached", "failed", _run(), [], None)
    assert not v.passed
    assert "!=" in v.reason


def test_no_tool_call_pass_fail():
    events = _events(("tool_call", {"name": "db", "arguments": {}}))
    v = check_assertion("no_tool_call", "http", _run(), events, None)
    assert v.passed
    v = check_assertion("no_tool_call", "db", _run(), events, None)
    assert not v.passed


def test_tool_call_sequence_exact(tmp_path):
    events = _events(
        ("tool_call", {"name": "db", "arguments": {"action": "read"}}),
        ("tool_call", {"name": "db", "arguments": {"action": "write"}}),
    )
    v = check_assertion(
        "tool_call_sequence", [["db", "read"], ["db", "write"]],
        _run(), events, None,
    )
    assert v.passed
    v = check_assertion(
        "tool_call_sequence", [["db", "write"], ["db", "read"]],
        _run(), events, None,
    )
    assert not v.passed


def test_audit_integrity(tmp_path):
    audit = _audit(tmp_path, entries=2)
    v = check_assertion("audit_integrity", True, _run(), [], audit)
    assert v.passed
    # tamper
    audit.conn.execute("UPDATE audit_log SET detail='x' WHERE seq=1")
    audit.conn.commit()
    from keel.governance.audit import AuditTamperedError
    try:
        audit.verify()
        tampered = False
    except AuditTamperedError:
        tampered = True
    assert tampered


def test_runlog_complete(tmp_path):
    full = _events(
        ("prompt", {"content": "x"}),
        ("response", {"content": "y"}),
        ("state_change", {"from": "running", "to": "done"}),
        ("decision", {"decision": "completed"}),
    )
    v = check_assertion("runlog_complete", True, _run(), full, None)
    assert v.passed
    partial = full[:2]
    v = check_assertion("runlog_complete", True, _run(), partial, None)
    assert not v.passed
    assert "state_change" in v.reason


def test_cost_within():
    events = _events(("cost", {"cost_usd": 0.005}))
    v = check_assertion("cost_within", {"max_usd": 0.01}, _run(), events, None)
    assert v.passed
    v = check_assertion("cost_within", {"max_usd": 0.001}, _run(), events, None)
    assert not v.passed


def test_tier_held_validates_name():
    v = check_assertion("tier_held", "bogus-tier", _run(), [], None)
    assert not v.passed
    v = check_assertion("tier_held", Tier.READ_ONLY.value, _run(), [], None)
    assert v.passed


def test_unknown_assertion():
    v = check_assertion("nope", 1, _run(), [], None)
    assert not v.passed
    assert "unknown" in v.reason
