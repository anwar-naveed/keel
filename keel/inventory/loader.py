"""Agent inventory loader — P4.1.

Loads agents/*.yaml, validates the schema with actionable errors, rejects
duplicates, and builds capability-constrained tool objects at load time.
This replaces the P1.8 interim hand-loader in the engine.
"""

from pathlib import Path

import yaml

from keel.governance.capabilities import build_tool_for_tier
from keel.governance.tiers import UnknownTierError, tier_for


class InventoryError(Exception):
    """Agent inventory is invalid; message is actionable."""


REQUIRED_FIELDS = {"name", "tier", "provider", "system_prompt"}
VALID_PROVIDERS = {"mock", "ollama", "openai", "anthropic"}
OPTIONAL_FIELDS = {
    "description", "model", "script", "tools", "max_turns",
    "max_cost_usd", "schedule", "temperature",
}


class AgentSpec:
    """A validated agent definition."""

    def __init__(self, data: dict, source: Path):
        self.name = data["name"]
        self.tier = data["tier"]
        self.provider = data["provider"]
        self.system_prompt = data["system_prompt"]
        self.model = data.get("model")
        self.script = data.get("script")
        self.tools = data.get("tools", [])
        self.max_turns = data.get("max_turns", 3)
        self.max_cost_usd = float(data.get("max_cost_usd", 1.0))
        self.schedule = data.get("schedule")
        self.description = data.get("description", "")
        self.source = source

    def build_tool(self, conn, run_id, journal):
        """Capability-constrained tool object for this agent's tier."""
        return build_tool_for_tier(self.tier, conn, run_id, journal)


def _validate(data: dict, source: Path) -> None:
    """Raise InventoryError with actionable messages for every problem."""
    if not isinstance(data, dict):
        raise InventoryError(f"{source.name}: top level must be a mapping")
    missing = REQUIRED_FIELDS - set(data)
    if missing:
        raise InventoryError(
            f"{source.name}: missing required field(s): {sorted(missing)}"
        )
    unknown = set(data) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    if unknown:
        raise InventoryError(
            f"{source.name}: unknown field(s) {sorted(unknown)} "
            f"(known: {sorted(REQUIRED_FIELDS | OPTIONAL_FIELDS)})"
        )
    if data["provider"] not in VALID_PROVIDERS:
        raise InventoryError(
            f"{source.name}: provider '{data['provider']}' unknown. "
            f"Valid: {sorted(VALID_PROVIDERS)}"
        )
    try:
        tier_for(data["tier"])
    except UnknownTierError as e:
        raise InventoryError(f"{source.name}: {e}") from e


def load_inventory(inventory_dir: Path) -> dict[str, AgentSpec]:
    """Load every agents/*.yaml into {name: AgentSpec}. Duplicate names and
    schema problems raise InventoryError naming the file and the fix."""
    inventory_dir = Path(inventory_dir)
    if not inventory_dir.exists():
        raise InventoryError(f"inventory directory not found: {inventory_dir}")

    specs: dict[str, AgentSpec] = {}
    for f in sorted(inventory_dir.glob("*.yaml")):
        with open(f) as fh:
            data = yaml.safe_load(fh)
        _validate(data, f)
        name = data["name"]
        if name in specs:
            first = specs[name].source.name
            raise InventoryError(
                f"{f.name}: duplicate agent name '{name}' "
                f"(already defined in {first})"
            )
        specs[name] = AgentSpec(data, f)
    return specs


def load_agent(inventory_dir: Path, name: str) -> AgentSpec:
    """Load a single agent; error names the inventory and what's in it."""
    specs = load_inventory(inventory_dir)
    if name not in specs:
        raise InventoryError(
            f"agent '{name}' not found in {inventory_dir}. "
            f"Known agents: {sorted(specs)}"
        )
    return specs[name]


__all__ = ["AgentSpec", "InventoryError", "load_inventory", "load_agent"]
