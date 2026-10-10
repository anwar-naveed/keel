"""Tests for governance/audit.py — P2.4. Chain verifies; tamper breaks it."""

import pytest

from keel.governance.audit import AuditLog, AuditTamperedError


@pytest.fixture
def audit(tmp_path):
    from keel.runtime.state import init_db

    conn = init_db(tmp_path / "keel.db")
    log = AuditLog(conn)
    yield conn, log
    conn.close()


def test_chain_verifies(audit):
    conn, log = audit
    for i in range(5):
        log.append(actor="engine", action="run_done", run_id=f"r{i}")
    assert log.verify() == 5


def test_genesis_links(audit):
    conn, log = audit
    log.append(actor="engine", action="boot")
    first = log.entries()[0]
    assert first["prev_hash"] == "0" * 64


def test_tamper_breaks_chain(audit):
    conn, log = audit
    log.append(actor="engine", action="run_done", run_id="r1")
    log.append(actor="engine", action="run_done", run_id="r2")
    log.append(actor="engine", action="run_done", run_id="r3")

    # Direct sqlite edit — the white-box attack
    conn.execute(
        "UPDATE audit_log SET detail = 'falsified' WHERE seq = 2"
    )
    conn.commit()

    with pytest.raises(AuditTamperedError) as exc:
        log.verify()
    assert exc.value.seq == 2


def test_row_deletion_breaks_chain(audit):
    conn, log = audit
    log.append(actor="engine", action="a", run_id="r1")
    log.append(actor="engine", action="b", run_id="r2")

    conn.execute("DELETE FROM audit_log WHERE seq = 1")
    conn.commit()

    with pytest.raises(AuditTamperedError):
        log.verify()


def test_hash_chaining_is_order_sensitive(audit):
    conn, log = audit
    log.append(actor="a", action="first")
    log.append(actor="a", action="second")
    e1, e2 = log.entries()
    assert e2["prev_hash"] == e1["entry_hash"]
    assert e1["entry_hash"] != e2["entry_hash"]
