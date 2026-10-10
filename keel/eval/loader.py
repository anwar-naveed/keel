"""Eval case loader — P3.1b.

YAML case schema:
    name: triage_classify
    agent: triage
    suite: golden | safety
    case: "input text given to the agent"
    provider_script: path (optional; defaults to agent's own script)
    expect:            # at least one assertion
      - state_reached: done
      - tool_call_sequence: []
      - no_tool_call: db
      - tier_held: read_only
      - audit_integrity: true
      - runlog_complete: true
      - cost_within: {max_usd: 0.01}
"""

from pathlib import Path

import yaml


class CaseError(Exception):
    """Eval case is malformed; message is actionable."""


REQUIRED_KEYS = {"name", "agent", "case", "expect"}
VALID_ASSERTIONS = {
    "enqueue_refused",
    "state_reached",
    "tool_call_sequence",
    "no_tool_call",
    "tier_held",
    "audit_integrity",
    "runlog_complete",
    "cost_within",
}


def load_case(path: Path) -> dict:
    """Load and validate one eval case YAML. Raises CaseError with the
    exact problem and how to fix it."""
    path = Path(path)
    if not path.exists():
        raise CaseError(f"case file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise CaseError(f"{path.name}: top level must be a mapping")

    missing = REQUIRED_KEYS - set(data)
    if missing:
        raise CaseError(
            f"{path.name}: missing required key(s): {sorted(missing)}"
        )

    if not isinstance(data["expect"], list) or not data["expect"]:
        raise CaseError(
            f"{path.name}: 'expect' must be a non-empty list of assertions"
        )

    for i, assertion in enumerate(data["expect"]):
        if not isinstance(assertion, dict) or len(assertion) != 1:
            raise CaseError(
                f"{path.name}: expect[{i}] must be a single-key mapping "
                f"like 'state_reached: done' (got: {assertion!r})"
            )
        kind = next(iter(assertion))
        if kind not in VALID_ASSERTIONS:
            raise CaseError(
                f"{path.name}: expect[{i}] unknown assertion '{kind}'. "
                f"Valid: {sorted(VALID_ASSERTIONS)}"
            )

    data.setdefault("suite", "golden")
    if data["suite"] not in ("golden", "safety"):
        raise CaseError(
            f"{path.name}: suite must be 'golden' or 'safety' "
            f"(got {data['suite']!r})"
        )
    return data


def load_suite(suite_dir: Path, suite: str) -> list[dict]:
    """Load every case of a suite from a directory."""
    suite_dir = Path(suite_dir)
    if not suite_dir.exists():
        return []  # a repo may ship only one suite
    cases = []
    for f in sorted(suite_dir.glob("*.yaml")):
        case = load_case(f)
        if case["suite"] == suite:
            cases.append(case)
    return cases


__all__ = ["CaseError", "load_case", "load_suite", "VALID_ASSERTIONS"]
