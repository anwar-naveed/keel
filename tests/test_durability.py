"""THE durability test — P1.9.

Spawns the engine as a subprocess, lets it process a run with a bomb hook
(a MockProvider step that sleeps), SIGKILLs it mid-provider-call, restarts
the engine on the same data dir, and asserts the interrupted run was
repaired (re-queued and completed), the journal is intact, and the runlog
reconstructs the full story INCLUDING the kill (startup-repair events).
"""

import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from keel.runtime.engine import Engine
from keel.runtime.runlog import reconstruct
from keel.runtime.state import RunState, RunStatus, init_db

WORKER_SCRIPT = textwrap.dedent("""\
    import sys
    from pathlib import Path

    from keel.runtime.engine import Engine

    data_dir = Path(sys.argv[1])
    engine = Engine(data_dir=data_dir)
    engine.drain()
""")


def _make_script(path: Path) -> None:
    """Mock script whose first step sleeps (the bomb hook) then writes."""
    path.write_text(
        "- content: \"thinking...\"\n"
        "  sleep: 30\n"
        "  tool_calls:\n"
        "    - name: \"db\"\n"
        '      arguments: {"action": "write", "key": "durable", "value": "yes"}\n'
        "- content: \"done\"\n"
        "  tool_calls: []\n"
    )


def test_sigkill_durability(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    script_file = tmp_path / "bomb_script.yaml"
    _make_script(script_file)

    # 1. Enqueue a run with the bomb provider (sleeping step)
    engine = Engine(data_dir=data_dir)
    engine.provider = None  # use agent-config wiring
    (tmp_path / "agents").mkdir(exist_ok=True)
    (tmp_path / "agents" / "bomb.yaml").write_text(
        "name: bomb\n"
        "provider: mock\n"
        f'script: "{script_file}"\n'
        "system_prompt: |\n"
        "  You are the bomb agent.\n"
    )
    # point agent lookup at tmp inventory
    engine._load_agent_config = lambda agent: {  # noqa: SLF001
        "provider": "mock",
        "script": str(script_file),
        "system_prompt": "You are the bomb agent.",
    }
    entry = engine.queue.enqueue("bomb", {"input": "survive the kill"})
    run_id = entry.run_id
    engine.conn.close()

    # 2. Spawn the worker subprocess (drain loop) on the same data dir
    proc = subprocess.Popen(
        [sys.executable, "-c", WORKER_SCRIPT, str(data_dir)],
        cwd=str(Path.cwd()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 3. Wait until the run is RUNNING (claimed), i.e. inside the sleeping step
    import time

    conn = init_db(data_dir / "keel.db")
    deadline = time.time() + 15
    running = False
    while time.time() < deadline:
        run = RunState.load(conn, run_id)
        if run is not None and run.status == RunStatus.RUNNING:
            running = True
            break
        time.sleep(0.1)
    assert running, "run never reached RUNNING before kill"
    conn.close()

    # 4. SIGKILL the worker mid-provider-call
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)

    # 5. Restart the engine on the same data dir -> startup repair must fire
    engine2 = Engine(data_dir=data_dir)  # __init__ runs repair_interrupted()

    run = RunState.load(engine2.conn, run_id)
    assert run is not None
    assert run.status == RunStatus.PENDING, (
        f"interrupted run not re-queued, status={run.status}"
    )

    # 6. Re-wire the (now-consumed) script and let the restarted engine finish it
    engine2._load_agent_config = lambda agent: {  # noqa: SLF001
        "provider": "mock",
        "script": str(script_file),
        "system_prompt": "You are the bomb agent.",
    }
    # fresh script file so the restarted run starts from step 0
    _make_script(script_file)
    engine2.provider = None
    # The sleeping step would stall the test; shrink the sleep for replay.
    script_file.write_text(
        "- content: \"thinking...\"\n"
        "  sleep: 0.1\n"
        "  tool_calls:\n"
        "    - name: \"db\"\n"
        '      arguments: {"action": "write", "key": "durable", "value": "yes"}\n'
        "- content: \"done\"\n"
        "  tool_calls: []\n"
    )
    result = engine2.process_one()
    assert result is not None
    assert result.status == RunStatus.DONE, (
        f"restarted run did not complete, status={result.status}"
    )

    # 7. Journal intact: the write op is journaled exactly once, applied once
    ops = engine2.journal.get_ops(run_id)
    inserts = [op for op in ops if op.op_type == "insert_row"]
    assert len(inserts) == 1, f"expected 1 journaled write, got {len(inserts)}"
    cur = engine2.conn.execute(
        'SELECT value FROM kv_store WHERE key = "durable"'
    )
    row = cur.fetchone()
    assert row is not None and row[0] == "yes"

    # 8. Runlog reconstructs the full story INCLUDING the kill
    events = reconstruct(data_dir, run_id)
    types = [e.type for e in events]
    assert "state_change" in types
    assert "decision" in types
    assert "cost" in types or "response" in types  # provider call recorded
    # the kill story: a requeue decision + state_change running->pending
    requeue_events = [
        e for e in events
        if e.type == "state_change"
        and e.payload.get("from") == "running"
        and e.payload.get("to") == "pending"
    ]
    assert requeue_events, "runlog missing the startup-repair state_change"
    assert any(
        e.type == "decision" and e.payload.get("decision") == "requeue"
        for e in events
    ), "runlog missing the requeue decision"

    # 9. repaired count from the restart engine (before replay finished it)
    # repair already ran inside Engine.__init__ at step 5
    engine2.conn.close()
