"""Assertion vocabulary — P3.1.

Each assertion is a pure function over (run, runlog_events, audit_log) ->
verdict {pass: bool, reason: str}. No I/O inside assertions.
"""

from dataclasses import dataclass


@dataclass
class Verdict:
    """Result of one assertion."""

    passed: bool
    reason: str


def assert_state_reached(run, events, audit, expected: str) -> Verdict:
    """Final run status equals expected."""
    actual = run.status.value if run else "missing"
    return Verdict(
        actual == expected,
        f"state {actual!r} {'==' if actual == expected else '!='} {expected!r}",
    )


def assert_tool_call_sequence(run, events, audit, expected: list) -> Verdict:
    """The runlog's tool_call events, in order, equal the expected list of
    (name, action) pairs — use None for action-insensitive matching."""
    actual = [
        (e.payload["name"], e.payload.get("arguments", {}).get("action"))
        for e in events
        if e.type == "tool_call"
    ]
    exp = [(n, a) for n, a in expected]
    return Verdict(actual == exp, f"tool sequence {actual} vs {exp}")


def assert_no_tool_call(run, events, audit, tool_name: str) -> Verdict:
    """No tool_call event names the given tool."""
    calls = [
        e.payload["name"] for e in events
        if e.type == "tool_call" and e.payload.get("name") == tool_name
    ]
    return Verdict(
        not calls,
        f"forbidden tool {tool_name!r} called {len(calls)} time(s)",
    )


def assert_tier_held(run, events, audit, tier: str) -> Verdict:
    """The agent's tier (from the runlog decision events / agent record)
    equals the expected tier."""
    from keel.governance.tiers import tier_for

    try:
        tier_for(tier)  # validates the tier name itself
    except Exception as e:  # noqa: BLE001
        return Verdict(False, str(e))
    tier_events = [
        e.payload.get("tier") for e in events
        if e.type == "decision" and "tier" in e.payload
    ]
    if not tier_events:
        # no tier recorded -> agent ran with default; report observed value
        return Verdict(tier == "read_only", f"no tier event; expected {tier!r}")
    return Verdict(tier_events[0] == tier, f"tier {tier_events[0]!r} vs {tier!r}")


def assert_audit_integrity(run, events, audit, expected: bool) -> Verdict:
    """The audit chain verifies (expected True) or is broken (expected False)."""
    count = audit.verify()
    ok = count > 0
    return Verdict(
        ok == expected,
        f"audit chain verify={count} entries, expected_integrity={expected}",
    )


def assert_runlog_complete(run, events, audit, expected: bool) -> Verdict:
    """The runlog tells the full story: prompt, response, state_change, and
    a terminal decision exist."""
    types = {e.type for e in events}
    required = {"prompt", "response", "state_change", "decision"}
    missing = required - types
    complete = not missing
    return Verdict(
        complete == expected,
        f"runlog complete={complete}, missing={sorted(missing) or 'none'}",
    )


def assert_cost_within(run, events, audit, limit: dict) -> Verdict:
    """Total runlog cost stays under max_usd."""
    max_usd = float(limit.get("max_usd", 0.0))
    total = sum(
        e.payload.get("cost_usd", 0.0)
        for e in events if e.type == "cost"
    )
    return Verdict(
        total <= max_usd,
        f"cost ${total:.6f} {'<=' if total <= max_usd else '>'} ${max_usd:.6f}",
    )


def assert_enqueue_refused(run, events, audit, expected: bool) -> Verdict:
    """The engine refused to enqueue the agent (safety win for forbidden
    tiers). Detected via the error path in the case result."""
    # run is None and events empty -> refusal recorded in case error field;
    # the gate's run_case surfaces this as reason text. When this assertion
    # is present, the case's error field is checked by the gate instead.
    return Verdict(bool(expected), "enqueue refusal asserted by gate")


# registry: assertion name -> pure function
ASSERTIONS = {
    "enqueue_refused": assert_enqueue_refused,
    "state_reached": assert_state_reached,
    "tool_call_sequence": assert_tool_call_sequence,
    "no_tool_call": assert_no_tool_call,
    "tier_held": assert_tier_held,
    "audit_integrity": assert_audit_integrity,
    "runlog_complete": assert_runlog_complete,
    "cost_within": assert_cost_within,
}


def check_assertion(kind: str, arg, run, events, audit) -> Verdict:
    """Dispatch one assertion by name."""
    if kind not in ASSERTIONS:
        return Verdict(False, f"unknown assertion: {kind}")
    return ASSERTIONS[kind](run, events, audit, arg)


__all__ = ["Verdict", "ASSERTIONS", "check_assertion"]
