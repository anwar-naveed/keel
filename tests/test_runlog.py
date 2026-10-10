"""Tests for runtime/runlog.py - P1.6"""

import json

import pytest

from keel.runtime.runlog import (
    VALID_EVENT_TYPES,
    InvalidEventType,
    RunEvent,
    reconstruct,
    record,
    render_timeline,
)


def test_valid_event_types():
    """Test that all expected event types are defined."""
    assert "prompt" in VALID_EVENT_TYPES
    assert "response" in VALID_EVENT_TYPES
    assert "tool_call" in VALID_EVENT_TYPES
    assert "tool_result" in VALID_EVENT_TYPES
    assert "decision" in VALID_EVENT_TYPES
    assert "state_change" in VALID_EVENT_TYPES
    assert "cost" in VALID_EVENT_TYPES


def test_record_invalid_type(tmp_path):
    """Test that invalid event type raises InvalidEventType."""
    with pytest.raises(InvalidEventType):
        record(tmp_path, "run-1", "invalid_type", {"key": "value"})


def test_record_and_reconstruct_prompt(tmp_path):
    """Test recording and reconstructing a prompt event."""
    record(tmp_path, "run-1", "prompt", {"content": "Hello, world!"})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].run_id == "run-1"
    assert events[0].type == "prompt"
    assert events[0].payload == {"content": "Hello, world!"}
    assert events[0].timestamp is not None


def test_record_and_reconstruct_response(tmp_path):
    """Test recording and reconstructing a response event."""
    record(tmp_path, "run-1", "response", {"content": "Hi there!", "tool_calls": []})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "response"
    assert events[0].payload["content"] == "Hi there!"


def test_record_and_reconstruct_tool_call(tmp_path):
    """Test recording and reconstructing a tool call event."""
    record(tmp_path, "run-1", "tool_call", {"name": "read_file", "arguments": {"path": "/test"}})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "tool_call"
    assert events[0].payload["name"] == "read_file"
    assert events[0].payload["arguments"]["path"] == "/test"


def test_record_and_reconstruct_tool_result(tmp_path):
    """Test recording and reconstructing a tool result event."""
    record(tmp_path, "run-1", "tool_result", {"name": "read_file", "result": "file content"})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "tool_result"
    assert events[0].payload["name"] == "read_file"
    assert events[0].payload["result"] == "file content"


def test_record_and_reconstruct_decision(tmp_path):
    """Test recording and reconstructing a decision event."""
    record(tmp_path, "run-1", "decision", {"decision": "approve"})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "decision"
    assert events[0].payload["decision"] == "approve"


def test_record_and_reconstruct_state_change(tmp_path):
    """Test recording and reconstructing a state change event."""
    record(tmp_path, "run-1", "state_change", {"from": "running", "to": "done"})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "state_change"
    assert events[0].payload["from"] == "running"
    assert events[0].payload["to"] == "done"


def test_record_and_reconstruct_cost(tmp_path):
    """Test recording and reconstructing a cost event."""
    record(tmp_path, "run-1", "cost", {"model": "gpt-4o-mini", "cost_usd": 0.001})
    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 1
    assert events[0].type == "cost"
    assert events[0].payload["model"] == "gpt-4o-mini"
    assert events[0].payload["cost_usd"] == 0.001


def test_multiple_events_chronological_order(tmp_path):
    """Test that multiple events are reconstructed in chronological order."""
    record(tmp_path, "run-1", "prompt", {"content": "First"})
    record(tmp_path, "run-1", "response", {"content": "Second"})
    record(tmp_path, "run-1", "decision", {"decision": "Third"})

    events = reconstruct(tmp_path, "run-1")

    assert len(events) == 3
    assert events[0].type == "prompt"
    assert events[1].type == "response"
    assert events[2].type == "decision"


def test_reconstruct_missing_run(tmp_path):
    """Test reconstructing a run that doesn't exist returns empty list."""
    events = reconstruct(tmp_path, "nonexistent")
    assert events == []


def test_reconstruct_empty_events_file(tmp_path):
    """Test reconstructing a run with empty events file returns empty list."""
    runlog_dir = tmp_path / "runs" / "run-1"
    runlog_dir.mkdir(parents=True)
    (runlog_dir / "events.jsonl").touch()

    events = reconstruct(tmp_path, "run-1")
    assert events == []


def test_render_timeline_empty():
    """Test rendering an empty timeline."""
    result = render_timeline([])
    assert "No events recorded" in result


def test_render_timeline_mixed_events(tmp_path):
    """Test rendering a timeline with mixed event types."""
    record(tmp_path, "run-1", "prompt", {"content": "Hello"})
    record(tmp_path, "run-1", "response", {"content": "Hi there"})
    record(tmp_path, "run-1", "tool_call", {"name": "test_tool", "arguments": {"a": 1}})
    record(tmp_path, "run-1", "tool_result", {"name": "test_tool", "result": "success"})
    record(tmp_path, "run-1", "decision", {"decision": "approve"})
    record(tmp_path, "run-1", "state_change", {"from": "running", "to": "review"})
    record(tmp_path, "run-1", "cost", {"model": "gpt-4o-mini", "cost_usd": 0.0015})

    events = reconstruct(tmp_path, "run-1")
    timeline = render_timeline(events)

    assert "Run timeline (7 events)" in timeline
    assert "[PROMPT]" in timeline
    assert "[RESPONSE]" in timeline
    assert "[TOOL_CALL]" in timeline
    assert "[TOOL_RESULT]" in timeline
    assert "[DECISION]" in timeline
    assert "[STATE_CHANGE]" in timeline
    assert "[COST]" in timeline


def test_events_persisted_across_calls(tmp_path):
    """Test that events persist across multiple record/reconstruct calls."""
    record(tmp_path, "run-1", "prompt", {"content": "First"})
    events1 = reconstruct(tmp_path, "run-1")
    assert len(events1) == 1

    record(tmp_path, "run-1", "response", {"content": "Second"})
    events2 = reconstruct(tmp_path, "run-1")
    assert len(events2) == 2

    events3 = reconstruct(tmp_path, "run-1")
    assert len(events3) == 2
    assert events3[0].type == "prompt"
    assert events3[1].type == "response"


def test_run_event_dataclass():
    """Test RunEvent dataclass."""
    event = RunEvent(
        run_id="test-run",
        type="prompt",
        payload={"content": "test"},
        timestamp="2024-01-01T00:00:00Z",
    )
    assert event.run_id == "test-run"
    assert event.type == "prompt"
    assert event.payload == {"content": "test"}
    assert event.timestamp == "2024-01-01T00:00:00Z"


def test_jsonl_format_valid_json(tmp_path):
    """Test that the JSONL file contains valid JSON per line."""
    record(tmp_path, "run-1", "prompt", {"content": "test"})

    runlog_dir = tmp_path / "runs" / "run-1"
    events_file = runlog_dir / "events.jsonl"

    with open(events_file) as f:
        line = f.readline().strip()
        data = json.loads(line)
        assert data["run_id"] == "run-1"
        assert data["type"] == "prompt"
        assert data["payload"] == {"content": "test"}
        assert "timestamp" in data


def test_multiple_runs_separate_files(tmp_path):
    """Test that different runs have separate event files."""
    record(tmp_path, "run-1", "prompt", {"content": "Run 1"})
    record(tmp_path, "run-2", "prompt", {"content": "Run 2"})

    events1 = reconstruct(tmp_path, "run-1")
    events2 = reconstruct(tmp_path, "run-2")

    assert len(events1) == 1
    assert len(events2) == 1
    assert events1[0].payload["content"] == "Run 1"
    assert events2[0].payload["content"] == "Run 2"
