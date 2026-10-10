"""Runtime engine - P1.7

The main loop: dequeue → build capability set → provider.complete →
execute tool calls → journal writes → state transitions → gate check →
runlog everything.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from keel.config import load_settings
from keel.runtime.journal import Journal, JournalOp, apply_op
from keel.runtime.providers import (
    Provider,
    get_provider,
)
from keel.runtime.queue import Queue, QueueEntry
from keel.runtime.runlog import record
from keel.runtime.state import RunState, RunStatus, init_db


@dataclass
class ToolResult:
    """Result of a tool execution."""
    name: str
    result: str
    error: str | None = None


class EngineError(Exception):
    """Base engine error."""
    pass


class ToolExecutionError(EngineError):
    """Tool execution failed."""
    pass


class Engine:
    """Main runtime engine that processes queued runs."""

    def __init__(self, data_dir: Path | None = None):
        """Initialize the engine.

        Args:
            data_dir: Data directory path (defaults to settings)
        """
        settings = load_settings()
        self.data_dir = data_dir or settings.data_dir
        self.db_path = self.data_dir / "keel.db"
        self.conn = init_db(self.db_path)
        self.queue = Queue(self.conn)
        self.journal = Journal(self.conn)
        self.provider: Provider | None = None

    def _load_agent_config(self, agent_name: str) -> dict:
        """Hand-load agents/<name>.yaml (Phase 4 replaces with inventory loader)."""
        agent_file = self.data_dir.parent / "agents" / f"{agent_name}.yaml"
        if not agent_file.exists():
            agent_file = Path("agents") / f"{agent_name}.yaml"
        if not agent_file.exists():
            return {}
        with open(agent_file) as f:
            return yaml.safe_load(f) or {}

    def _get_provider(self, agent_name: str) -> Provider:
        """Get provider for an agent, wired from the agent YAML when present."""
        # Explicit override (tests / dependency injection) always wins
        if self.provider is not None:
            return self.provider
        agent_cfg = self._load_agent_config(agent_name)
        provider_name = agent_cfg.get("provider") or load_settings().provider

        if provider_name == "mock":
            script_path = agent_cfg.get("script")
            if script_path:
                return get_provider("mock", script_path=script_path)
            # no script configured: single acknowledge step so mock runs complete
            return get_provider(
                "mock",
                script_path=self._write_default_script(agent_name),
            )
        return get_provider(provider_name)

    def _write_default_script(self, agent_name: str) -> Path:
        """Write a minimal one-step mock script for agents without one."""
        script_dir = self.data_dir / "mock_scripts"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_file = script_dir / f"{agent_name}.yaml"
        if not script_file.exists():
            body = (
                f"- content: \"Acknowledged by {agent_name}.\"\n"
                "  tool_calls: []\n"
            )
            script_file.write_text(body)
        return script_file

    def _build_tool_set(self, run_id: str) -> list[dict]:
        """Build the tool set for the provider (Phase 1 stub: single KV db tool)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "db",
                    "description": (
                        "Key-value database tool. Use 'action' to specify "
                        "operation: 'read' or 'write'."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["read", "write"]},
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["action", "key"],
                    },
                },
            }
        ]

    def _execute_tool_call(self, run_id: str, tool_call: dict) -> ToolResult:
        """Execute a single tool call and journal the operation."""
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})

        # Record tool_call event
        record(self.data_dir, run_id, "tool_call", {"name": name, "arguments": args})

        if name != "db":
            result = ToolResult(
                name=name,
                result="",
                error=f"Unknown tool: {name}",
            )
            record(self.data_dir, run_id, "tool_result", {
                "name": name,
                "result": "",
                "error": result.error,
            })
            return result

        action = args.get("action")
        key = args.get("key", "")
        value = args.get("value", "")

        try:
            if action == "read":
                cursor = self.conn.execute(
                    "SELECT value FROM kv_store WHERE key = ?",
                    (key,),
                )
                row = cursor.fetchone()
                result_value = row[0] if row else ""
                result = ToolResult(name=name, result=result_value)

                # Record tool_result event
                record(self.data_dir, run_id, "tool_result", {"name": name, "result": result_value})

            elif action == "write":
                # Journal the write operation
                cursor = self.conn.execute(
                    "SELECT value FROM kv_store WHERE key = ?",
                    (key,),
                )
                row = cursor.fetchone()
                before_value = row[0] if row else None

                op = JournalOp(
                    run_id=run_id,
                    op_type="insert_row",
                    target="kv_store",
                    before=(
                        {"key": key, "value": before_value}
                        if before_value is not None
                        else None
                    ),
                    after={"key": key, "value": value},
                )
                apply_op(self.conn, self.journal, run_id, op)

                result = ToolResult(name=name, result=f"Written key: {key}")

                # Record tool_result event
                record(self.data_dir, run_id, "tool_result", {
                    "name": name,
                    "result": f"Written key: {key}",
                })

            else:
                result = ToolResult(
                    name=name,
                    result="",
                    error=f"Unknown db action: {action}",
                )
                record(self.data_dir, run_id, "tool_result", {
                    "name": name,
                    "result": "",
                    "error": result.error,
                })

        except Exception as e:
            result = ToolResult(name=name, result="", error=str(e))
            record(self.data_dir, run_id, "tool_result", {
                "name": name,
                "result": "",
                "error": str(e),
            })

        return result

    def _process_run(self, entry: QueueEntry) -> RunState:
        """Process a single run from claim to completion."""
        run_id = entry.run_id
        agent = entry.agent
        payload = entry.payload

        # Load run state (already RUNNING from queue.claim)
        run = RunState.load(self.conn, run_id)
        if run is None:
            raise EngineError(f"Run {run_id} not found")

        # Get provider
        provider = self._get_provider(agent)

        # System prompt: from the agent YAML, else a generic fallback
        agent_cfg = self._load_agent_config(agent)
        system_prompt = (
            agent_cfg.get("system_prompt")
            or f"You are {agent}. Process the input and use tools as needed."
        )

        # Build messages from payload
        messages = [{"role": "user", "content": payload.get("input", "")}]

        # Build tool set
        tools = self._build_tool_set(run_id)

        # Record prompt event
        record(self.data_dir, run_id, "prompt", {"content": messages[-1]["content"]})

        try:
            # Call provider
            response = provider.complete(system_prompt, messages, tools)

            # Record response event
            record(self.data_dir, run_id, "response", {"content": response.content})

            # Record cost event
            if response.usage.cost_usd > 0:
                record(self.data_dir, run_id, "cost", {
                    "model": (
                        provider.model
                        if hasattr(provider, "model")
                        else "unknown"
                    ),
                    "cost_usd": response.usage.cost_usd,
                })

            # Execute tool calls
            tool_results = []
            for tool_call in response.tool_calls:
                tool_result = self._execute_tool_call(run_id, tool_call)
                tool_results.append(tool_result)

                # If tool failed, mark run as failed
                if tool_result.error:
                    run = run.transition_to(RunStatus.FAILED, phase="tool_error")
                    run.save(self.conn)
                    record(self.data_dir, run_id, "state_change", {
                        "from": "running",
                        "to": "failed",
                    })
                    record(self.data_dir, run_id, "decision", {
                        "decision": "failed",
                        "reason": tool_result.error,
                    })
                    return run

            # Check if there are tool calls - if so, may need another provider call
            # For Phase 1, we do a single pass (no tool loop)
            if response.tool_calls:
                # Could do another iteration here, but Phase 1 keeps it simple
                pass

            # Determine final state
            # If no tool calls or all successful, transition to done (Phase 1: no review gate)
            run = run.transition_to(RunStatus.DONE, phase="completed")
            run.save(self.conn)

            record(self.data_dir, run_id, "state_change", {"from": "running", "to": "done"})
            record(self.data_dir, run_id, "decision", {"decision": "completed"})

            return run

        except Exception as e:
            # Reload run state to ensure we have current status
            run = RunState.load(self.conn, run_id)
            if run and run.status == RunStatus.RUNNING:
                run = run.transition_to(RunStatus.FAILED, phase="error")
                run.save(self.conn)
                record(self.data_dir, run_id, "state_change", {
                    "from": "running",
                    "to": "failed",
                })
                record(self.data_dir, run_id, "decision", {
                    "decision": "failed",
                    "reason": str(e),
                })

            raise EngineError(f"Run {run_id} failed: {e}") from e

    def process_one(self) -> RunState | None:
        """Process the next pending run. Returns the completed run state or None if queue empty."""
        # Reclaim stale entries first
        self.queue.reclaim_stale()

        # Get next pending
        entry = self.queue.next_pending()
        if entry is None:
            return None

        # Claim the run
        try:
            entry = self.queue.claim(entry.run_id)
        except ValueError:
            # Not pending anymore, skip
            return self.process_one()

        # Process the run
        return self._process_run(entry)

    def drain(self) -> list[RunState]:
        """Process all pending runs until queue is empty."""
        results = []
        while True:
            result = self.process_one()
            if result is None:
                break
            results.append(result)
        return results

    def run_agent(self, agent: str, input_text: str) -> RunState:
        """Enqueue and process a single agent run synchronously."""
        entry = self.queue.enqueue(agent, {"input": input_text})
        # Claim the run (transitions PENDING -> RUNNING)
        entry = self.queue.claim(entry.run_id)
        return self._process_run(entry)


__all__ = [
    "Engine",
    "EngineError",
    "ToolExecutionError",
    "ToolResult",
]
