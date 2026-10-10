"""Run log - P1.6

JSONL run log at data/runs/<run_id>/events.jsonl
Event types: prompt, response, tool_call, tool_result, decision, state_change, cost
record(run_id, type, payload); reconstruct(run_id) returns events
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class RunEvent:
    """A single event in a run log."""
    run_id: str
    type: str
    payload: dict[str, Any]
    timestamp: str


VALID_EVENT_TYPES = {
    "prompt",
    "response",
    "tool_call",
    "tool_result",
    "decision",
    "state_change",
    "cost",
}


class RunLogError(Exception):
    """Base runlog error."""
    pass


class InvalidEventType(RunLogError):
    """Unknown event type."""
    pass


def _get_runlog_dir(data_dir: Path) -> Path:
    """Get the runlog directory, creating it if needed."""
    runlog_dir = data_dir / "runs"
    runlog_dir.mkdir(parents=True, exist_ok=True)
    return runlog_dir


def _get_events_file(runlog_dir: Path, run_id: str) -> Path:
    """Get the events.jsonl file for a run, creating parent dir if needed."""
    run_dir = runlog_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "events.jsonl"


def record(data_dir: Path, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Record an event to the run log.

    Args:
        data_dir: Root data directory
        run_id: Run identifier
        event_type: One of VALID_EVENT_TYPES
        payload: Event-specific data

    Raises:
        InvalidEventType: If event_type is not valid
    """
    if event_type not in VALID_EVENT_TYPES:
        raise InvalidEventType(f"Invalid event type: {event_type}. Valid: {VALID_EVENT_TYPES}")

    runlog_dir = _get_runlog_dir(data_dir)
    events_file = _get_events_file(runlog_dir, run_id)

    event = RunEvent(
        run_id=run_id,
        type=event_type,
        payload=payload,
        timestamp=datetime.now(UTC).isoformat(),
    )

    with open(events_file, "a") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def reconstruct(data_dir: Path, run_id: str) -> list[RunEvent]:
    """Reconstruct all events for a run.

    Args:
        data_dir: Root data directory
        run_id: Run identifier

    Returns:
        List of RunEvent objects in chronological order
    """
    runlog_dir = _get_runlog_dir(data_dir)
    events_file = _get_events_file(runlog_dir, run_id)

    if not events_file.exists():
        return []

    events = []
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            events.append(RunEvent(**data))
    return events


def render_timeline(events: list[RunEvent]) -> str:
    """Render events as a human-readable timeline.

    Args:
        events: List of events to render

    Returns:
        Formatted timeline string
    """
    if not events:
        return "No events recorded."

    lines = [f"Run timeline ({len(events)} events):", ""]
    for event in events:
        ts = event.timestamp.replace("T", " ").split(".")[0]
        type_label = event.type.upper()
        if event.type == "prompt" or event.type == "response":
            content = event.payload.get("content", "")[:80]
            lines.append(f"  {ts} [{type_label}] {content}")
        elif event.type == "tool_call":
            name = event.payload.get("name", "unknown")
            args = event.payload.get("arguments", {})
            lines.append(f"  {ts} [{type_label}] {name}({args})")
        elif event.type == "tool_result":
            name = event.payload.get("name", "unknown")
            result = str(event.payload.get("result", ""))[:80]
            lines.append(f"  {ts} [{type_label}] {name} -> {result}")
        elif event.type == "decision":
            decision = event.payload.get("decision", "unknown")
            lines.append(f"  {ts} [{type_label}] {decision}")
        elif event.type == "state_change":
            from_state = event.payload.get("from", "?")
            to_state = event.payload.get("to", "?")
            lines.append(f"  {ts} [{type_label}] {from_state} -> {to_state}")
        elif event.type == "cost":
            amount = event.payload.get("cost_usd", 0.0)
            model = event.payload.get("model", "unknown")
            lines.append(f"  {ts} [{type_label}] {model}: ${amount:.6f}")
        else:
            lines.append(f"  {ts} [{type_label}] {event.payload}")

    return "\n".join(lines)


__all__ = [
    "RunEvent",
    "RunLogError",
    "InvalidEventType",
    "VALID_EVENT_TYPES",
    "record",
    "reconstruct",
    "render_timeline",
]
