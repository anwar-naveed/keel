"""Tests for governance/tiers.py — P2.1."""

import pytest

from keel.governance.tiers import (
    CAPABILITIES,
    ForbiddenAgentError,
    Tier,
    UnknownTierError,
    can_enqueue,
    capabilities_for,
    tier_for,
)


def test_tier_registry_membership():
    assert {t.value for t in Tier} == {
        "read_only", "draft", "write_with_approval", "forbidden",
    }


def test_capability_sets():
    assert CAPABILITIES[Tier.READ_ONLY] == {"read", "query"}
    assert CAPABILITIES[Tier.DRAFT] == {"read", "query", "stage_write"}
    assert CAPABILITIES[Tier.WRITE_WITH_APPROVAL] == {
        "read", "query", "stage_write", "apply_write",
    }
    assert CAPABILITIES[Tier.FORBIDDEN] == set()


def test_tier_for_resolves_all():
    for t in Tier:
        assert tier_for(t.value) == t


def test_unknown_tier_names_itself():
    with pytest.raises(UnknownTierError) as exc:
        tier_for("admin")
    assert "admin" in str(exc.value)
    assert "read_only" in str(exc.value)  # error lists known tiers


def test_unknown_tier_suggests_close_match():
    with pytest.raises(UnknownTierError) as exc:
        tier_for("read-only")
    assert "did you mean 'read_only'" in str(exc.value)


def test_capabilities_for():
    assert capabilities_for("draft") == {"read", "query", "stage_write"}


def test_forbidden_cannot_enqueue():
    assert can_enqueue("forbidden") is False
    assert can_enqueue("read_only") is True
    with pytest.raises(ForbiddenAgentError):
        raise ForbiddenAgentError("spammer")


def test_lattice_ordering():
    """Each tier's capabilities are a superset of the one below."""
    assert CAPABILITIES[Tier.READ_ONLY] <= CAPABILITIES[Tier.DRAFT]
    assert CAPABILITIES[Tier.DRAFT] <= CAPABILITIES[Tier.WRITE_WITH_APPROVAL]
    assert CAPABILITIES[Tier.FORBIDDEN] <= CAPABILITIES[Tier.READ_ONLY]
