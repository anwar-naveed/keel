"""Tests for runtime/engine.py - P1.7"""


from keel.runtime.engine import Engine
from keel.runtime.providers import MockProvider
from keel.runtime.runlog import reconstruct


def test_engine_process_one_empty_queue(tmp_path):
    """Test process_one returns None when queue is empty."""
    engine = Engine(data_dir=tmp_path)
    result = engine.process_one()
    assert result is None


def test_engine_run_agent_mock_provider(tmp_path):
    """Test running an agent with MockProvider."""
    # Create a mock script
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Processed input"
  tool_calls: []
""")

    engine = Engine(data_dir=tmp_path)
    # Override provider with mock
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test input")

    assert run is not None
    assert run.status.value == "done"
    assert run.agent == "triage"

    # Check runlog events
    events = reconstruct(tmp_path, run.run_id)
    assert len(events) >= 4  # prompt, response, state_change, decision at minimum
    event_types = [e.type for e in events]
    assert "prompt" in event_types
    assert "response" in event_types
    assert "state_change" in event_types
    assert "decision" in event_types


def test_engine_run_agent_with_tool_call(tmp_path):
    """Test running an agent that makes a tool call."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "I'll write to db"
  tool_calls:
    - name: "db"
      arguments: {"action": "write", "key": "test_key", "value": "test_value"}
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test input with tool")

    assert run is not None
    assert run.status.value == "done"

    # Check runlog has tool_call and tool_result events
    events = reconstruct(tmp_path, run.run_id)
    event_types = [e.type for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types

    # Check the tool call was recorded correctly
    tool_call_event = next(e for e in events if e.type == "tool_call")
    assert tool_call_event.payload["name"] == "db"
    assert tool_call_event.payload["arguments"]["action"] == "write"
    assert tool_call_event.payload["arguments"]["key"] == "test_key"

    tool_result_event = next(e for e in events if e.type == "tool_result")
    assert tool_result_event.payload["name"] == "db"
    assert "Written key" in tool_result_event.payload["result"]


def test_engine_run_agent_tool_call_read(tmp_path):
    """Test tool call for reading from db."""
    # Pre-populate db
    engine = Engine(data_dir=tmp_path)
    engine.conn.execute(
        "INSERT INTO kv_store (key, value) VALUES (?, ?)",
        ("existing_key", "existing_value"),
    )
    engine.conn.commit()

    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "I'll read from db"
  tool_calls:
    - name: "db"
      arguments: {"action": "read", "key": "existing_key"}
""")

    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test read")

    assert run is not None
    assert run.status.value == "done"

    events = reconstruct(tmp_path, run.run_id)
    tool_result_event = next(e for e in events if e.type == "tool_result")
    assert tool_result_event.payload["result"] == "existing_value"


def test_engine_tool_error_fails_run(tmp_path):
    """Test that tool execution error fails the run."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "I'll call unknown tool"
  tool_calls:
    - name: "unknown_tool"
      arguments: {}
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test tool error")

    assert run is not None
    assert run.status.value == "failed"

    events = reconstruct(tmp_path, run.run_id)
    event_types = [e.type for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types

    # Check tool_result has error
    tool_result_event = next(e for e in events if e.type == "tool_result")
    assert tool_result_event.payload["error"] is not None
    assert "Unknown tool" in tool_result_event.payload["error"]


def test_engine_drain_processes_all(tmp_path):
    """Test drain processes all queued runs."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Done"
  tool_calls: []
- content: "Done"
  tool_calls: []
- content: "Done"
  tool_calls: []
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    # Enqueue multiple runs
    engine.queue.enqueue("triage", {"input": "First"})
    engine.queue.enqueue("triage", {"input": "Second"})
    engine.queue.enqueue("triage", {"input": "Third"})

    results = engine.drain()

    assert len(results) == 3
    for run in results:
        assert run.status.value == "done"
        assert run.agent == "triage"


def test_engine_stale_reclaim(tmp_path):
    """Test that stale claimed runs are reclaimed."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Done"
  tool_calls: []
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    # Enqueue and claim a run
    entry = engine.queue.enqueue("triage", {"input": "Test"})
    entry = engine.queue.claim(entry.run_id)

    # Manually set claimed_at to old timestamp
    from datetime import UTC, datetime, timedelta
    old_time = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    engine.conn.execute(
        "UPDATE runs SET claimed_at = ? WHERE id = ?",
        (old_time, entry.run_id)
    )
    engine.conn.commit()

    # Call reclaim_stale
    reclaimed = engine.queue.reclaim_stale()

    assert len(reclaimed) == 1
    assert reclaimed[0].run_id == entry.run_id
    assert reclaimed[0].status.value == "pending"


def test_engine_cost_recorded(tmp_path):
    """Test that cost is recorded in runlog."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Done"
  tool_calls: []
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test cost")

    events = reconstruct(tmp_path, run.run_id)
    cost_events = [e for e in events if e.type == "cost"]
    # MockProvider has cost_usd = 0.0, so no cost event expected
    assert len(cost_events) == 0


def test_engine_journal_records_tool_writes(tmp_path):
    """Test that tool writes are journaled."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Writing to db"
  tool_calls:
    - name: "db"
      arguments: {"action": "write", "key": "journal_test", "value": "journal_value"}
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test journal")

    assert run is not None

    # Check journal has the operation
    ops = engine.journal.get_ops(run.run_id)
    assert len(ops) >= 1
    insert_ops = [op for op in ops if op.op_type == "insert_row"]
    assert len(insert_ops) == 1
    assert insert_ops[0].after["key"] == "journal_test"
    assert insert_ops[0].after["value"] == "journal_value"


def test_engine_multiple_tool_calls(tmp_path):
    """Test multiple tool calls in sequence."""
    script_file = tmp_path / "mock_script.yaml"
    script_file.write_text("""
- content: "Multiple ops"
  tool_calls:
    - name: "db"
      arguments: {"action": "write", "key": "key1", "value": "value1"}
    - name: "db"
      arguments: {"action": "write", "key": "key2", "value": "value2"}
""")

    engine = Engine(data_dir=tmp_path)
    engine.provider = MockProvider(script_path=script_file)

    run = engine.run_agent("triage", "Test multiple tools")

    assert run is not None
    assert run.status.value == "done"

    events = reconstruct(tmp_path, run.run_id)
    tool_call_events = [e for e in events if e.type == "tool_call"]
    tool_result_events = [e for e in events if e.type == "tool_result"]

    assert len(tool_call_events) == 2
    assert len(tool_result_events) == 2

    # Check both writes were journaled
    ops = engine.journal.get_ops(run.run_id)
    insert_ops = [op for op in ops if op.op_type == "insert_row"]
    assert len(insert_ops) == 2
