"""Governance tiers — P2.1.

Tier registry with capability sets. `forbidden` agents cannot even be
enqueued — enforced at queue entry and the error names the tier.
"""

from enum import StrEnum


class Tier(StrEnum):
    """Governance tiers, least to most privileged."""

    READ_ONLY = "read_only"
    DRAFT = "draft"
    WRITE_WITH_APPROVAL = "write_with_approval"
    FORBIDDEN = "forbidden"


# Capability sets per tier. Capabilities are structural: a capability absent
# from the set means the tool object built for the agent has NO method for it
# (ADR-002: impossible, not forbidden).
CAPABILITIES: dict[Tier, set[str]] = {
    Tier.READ_ONLY: {"read", "query"},
    Tier.DRAFT: {"read", "query", "stage_write"},
    Tier.WRITE_WITH_APPROVAL: {"read", "query", "stage_write", "apply_write"},
    Tier.FORBIDDEN: set(),
}

VALID_CAPABILITIES = {"read", "query", "stage_write", "apply_write"}


class UnknownTierError(Exception):
    """Raised when an agent YAML names a tier that is not registered."""

    def __init__(self, tier: str):
        self.tier = tier
        known = ", ".join(t.value for t in Tier)
        suggestion = ""
        # actionable error: suggest close matches
        close = [t.value for t in Tier if t.value.replace("_", "-") == tier]
        if close:
            suggestion = f" — did you mean '{close[0]}'?"
        super().__init__(
            f"tier '{tier}' unknown{suggestion}. Known tiers: {known}"
        )


class ForbiddenAgentError(Exception):
    """Raised when enqueueing an agent whose tier is `forbidden`."""

    def __init__(self, agent: str):
        self.agent = agent
        super().__init__(
            f"agent '{agent}' has tier 'forbidden' and cannot be enqueued"
        )


def tier_for(name: str) -> Tier:
    """Resolve a tier name; raise UnknownTierError with a helpful message."""
    try:
        return Tier(name)
    except ValueError:
        raise UnknownTierError(name) from None


def capabilities_for(name: str) -> set[str]:
    """Capability set for a tier name."""
    return set(CAPABILITIES[tier_for(name)])


def can_enqueue(name: str) -> bool:
    """Forbidden agents are rejected at queue entry."""
    return tier_for(name) != Tier.FORBIDDEN


__all__ = [
    "Tier",
    "CAPABILITIES",
    "VALID_CAPABILITIES",
    "UnknownTierError",
    "ForbiddenAgentError",
    "tier_for",
    "capabilities_for",
    "can_enqueue",
]
