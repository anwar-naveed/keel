"""Runtime engine - P1.7

The main loop: dequeue → build capability set → provider.complete →
execute tool calls → journal writes → state transitions → gate check →
runlog everything.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from keel.config import load_settings
from keel.governance.audit import AuditLog
from keel.governance.capabilities import build_tool_for_tier
from keel.governance.tiers import ForbiddenAgentError, tier_for
from keel.governance.tiers import Tier as GovernanceTier
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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "keel.db"
        self.conn = init_db(self.db_path)
        self.queue = Queue(self.conn)
        self.journal = Journal(self.conn)
        self.audit = AuditLog(self.conn)
        # ensure staging table exists from the start (review gate reads it)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS staging (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                staged_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self.provider: Provider | None = None
        self.repair_interrupted()

    def repair_interrupted(self) -> int:
        """Startup repair: re-queue runs stuck in `running` from a previous
        process (crash/kill). Returns number of repaired runs."""
        repaired = 0
        cursor = self.conn.execute(
            "SELECT id FROM runs WHERE status = ?", (RunStatus.RUNNING.value,)
        )
        for (run_id,) in cursor.fetchall():
            run = RunState.load(self.conn, run_id)
            if run is None:
                continue
            run = run.transition_to(RunStatus.PENDING, phase="requeued-after-crash")
            run.save(self.conn)
            # clear the stale claim marker so the queue hands it out again
            self.conn.execute(
                "UPDATE runs SET claimed_at = NULL WHERE id = ?", (run_id,)
            )
            self.conn.commit()
            record(self.data_dir, run_id, "state_change", {
                "from": "running", "to": "pending", "reason": "startup repair",
            })
            record(self.data_dir, run_id, "decision", {
                "decision": "requeue", "reason": "interrupted run re-queued on init",
            })
            repaired += 1
        return repaired

    def _load_agent_config(self, agent_name: str) -> dict:
        """Load agent config via the inventory loader (P4.1).

        Falls back to the interim hand-load ONLY when the inventory dir is
        absent (tests inject configs by monkeypatching this method anyway).
        """
        from keel.inventory.loader import InventoryError, load_agent

        candidates = [
            self.data_dir.parent / "agents",
            Path("agents"),
        ]
        for inv_dir in candidates:
            if not (inv_dir / f"{agent_name}.yaml").exists():
                continue
            try:
                spec = load_agent(inv_dir, agent_name)
            except InventoryError:
                continue
            return {
                "name": spec.name,
                "tier": spec.tier,
                "provider": spec.provider,
                "model": spec.model,
                "script": spec.script,
                "system_prompt": spec.system_prompt,
                "tools": spec.tools,
                "max_turns": spec.max_turns,
                "max_cost_usd": spec.max_cost_usd,
            }
        # interim fallback: bare hand-load without inventory validation
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

    def _execute_capability_call(self, run_id: str, tool, tool_call: dict) -> ToolResult:
        """Execute one tool call through the capability object (P2.2).

        The structural boundary: only methods the tier granted exist on the
        tool object. An injected `write` on a read-only tool raises
        AttributeError here — journaled as a failed tool call, run fails.
        """
        name = tool_call.get("name", "")
        args = tool_call.get("arguments", {})
        record(self.data_dir, run_id, "tool_call", {"name": name, "arguments": args})

        try:
            if name == "db":
                action = args.get("action")
                key = args.get("key", "")
                value = args.get("value", "")
                if action == "read":
                    out = tool.select(key)
                elif action == "write":
                    # Structural gate: read_only has no stage_write;
                    # draft/write_with_approval park the write in staging.
                    out = tool.stage_write(key, value)
                    out = f"Staged key: {key} (awaiting review)"
                else:
                    out = ""
                    result = ToolResult(name=name, result="", error=f"Unknown db action: {action}")
                    record(self.data_dir, run_id, "tool_result", {
                        "name": name, "result": "", "error": result.error,
                    })
                    return result
                result = ToolResult(name=name, result=str(out))
            else:
                result = ToolResult(name=name, result="", error=f"Unknown tool: {name}")
            record(self.data_dir, run_id, "tool_result", {
                "name": name,
                "result": result.result,
                **({"error": result.error} if result.error else {}),
            })
        except AttributeError as e:
            # The impossible write: tier never granted this capability.
            result = ToolResult(
                name=name, result="",
                error=f"capability denied (structurally): {e}",
            )
            record(self.data_dir, run_id, "tool_result", {
                "name": name, "result": "",
                "error": f"capability denied (structurally): {e}",
            })
            record(self.data_dir, run_id, "decision", {
                "decision": "tool_denied",
                "reason": f"method '{name}' not on capability object for tier",
            })
            self.audit.append(
                actor="engine", action="tool_denied", run_id=run_id,
                detail=f"{name}: {e}",
            )
        except Exception as e:
            result = ToolResult(name=name, result="", error=str(e))
            record(self.data_dir, run_id, "tool_result", {
                "name": name, "result": "", "error": str(e),
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

        # Build the capability-constrained tool object for this run's tier (P2.2/P2.5)
        tier_name = agent_cfg.get("tier", "read_only")
        tool = build_tool_for_tier(tier_name, self.conn, run_id, self.journal)

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

            # Execute tool calls through the capability object
            tool_results = []
            for tool_call in response.tool_calls:
                tool_result = self._execute_capability_call(
                    run_id, tool, tool_call
                )
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

            # Gate check (P2.3): write_with_approval runs with staged writes
            # hold in REVIEW for human approve/reject; everything else completes.
            tier_name = agent_cfg.get("tier", "read_only")
            staged_cursor = self.conn.execute(
                "SELECT COUNT(*) FROM staging WHERE run_id = ?", (run_id,)
            )
            has_staged = staged_cursor.fetchone()[0] > 0

            if tier_for(tier_name) == GovernanceTier.WRITE_WITH_APPROVAL and has_staged:
                run = run.transition_to(RunStatus.REVIEW, phase="staged-writes")
                run.save(self.conn)
                record(self.data_dir, run_id, "state_change", {
                    "from": "running", "to": "review",
                })
                record(self.data_dir, run_id, "decision", {
                    "decision": "hold_for_review",
                    "reason": "staged writes require approval",
                })
                self.audit.append(
                    actor="engine", action="held_for_review", run_id=run_id,
                    detail=f"{has_staged and 'staged write(s) awaiting approval'}",
                )
                return run

            run = run.transition_to(RunStatus.DONE, phase="completed")
            run.save(self.conn)

            record(self.data_dir, run_id, "state_change", {"from": "running", "to": "done"})
            record(self.data_dir, run_id, "decision", {"decision": "completed"})
            self.audit.append(
                actor="engine", action="run_completed", run_id=run_id,
            )

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
        """Enqueue and process a single agent run synchronously.

        Enqueue gate (P2.1): forbidden-tier agents are refused at queue
        entry; the error names the tier.
        """
        agent_cfg = self._load_agent_config(agent)
        tier_name = agent_cfg.get("tier", "read_only")
        if tier_for(tier_name) == GovernanceTier.FORBIDDEN:
            self.audit.append(
                actor="queue", action="enqueue_refused", run_id=None,
                detail=f"agent '{agent}' tier 'forbidden' cannot be enqueued",
            )
            raise ForbiddenAgentError(agent)
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
