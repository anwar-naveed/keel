"""Eval gate runner — P3.3.

Runs golden + safety suites against the live engine (MockProvider), applies
each case's assertions, writes a JSON report, and returns an exit code:
0 = all green, 1 = any failure. Designed to run in CI after pytest.
"""

import json
from pathlib import Path

from keel.eval.assertions import check_assertion
from keel.eval.loader import load_suite


class GateError(Exception):
    """Gate could not run."""


def run_case(case: dict, engine, data_dir: Path) -> dict:
    """Run one eval case end-to-end and evaluate its assertions."""
    from keel.runtime.runlog import reconstruct
    from keel.runtime.state import RunState

    agent = case["agent"]
    script = case.get("provider_script")

    # Wire the case's script (or the agent's own) into the engine
    cfg = engine._load_agent_config(agent)  # noqa: SLF001
    if script:
        cfg = dict(cfg)
        cfg["script"] = script
        original = engine._load_agent_config  # noqa: SLF001
        engine._load_agent_config = lambda a: cfg  # noqa: SLF001

    try:
        run = engine.run_agent(agent, case["case"])
    except Exception as e:  # noqa: BLE001 — a refused run is a verdict, not a crash
        kinds = [next(iter(a)) for a in case["expect"]]
        if "enqueue_refused" in kinds:
            # safety case: refusal IS the expected outcome
            return {
                "name": case["name"],
                "agent": agent,
                "error": str(e),
                "assertions": [{
                    "assertion": "enqueue_refused",
                    "passed": True,
                    "reason": f"enqueue refused as expected: {e}",
                }],
                "passed": True,
            }
        return {
            "name": case["name"],
            "agent": agent,
            "error": str(e),
            "assertions": [{
                "assertion": "state_reached",
                "passed": False,
                "reason": f"run refused: {e}",
            }],
            "passed": False,
        }
    finally:
        if script:
            engine._load_agent_config = original  # noqa: SLF001

    run_state = RunState.load(engine.conn, run.run_id)
    events = reconstruct(data_dir, run.run_id)

    results = []
    all_passed = True
    for assertion in case["expect"]:
        kind = next(iter(assertion))
        arg = assertion[kind]
        verdict = check_assertion(kind, arg, run_state, events, engine.audit)
        results.append({
            "assertion": kind,
            "expected": arg,
            "passed": verdict.passed,
            "reason": verdict.reason,
        })
        all_passed = all_passed and verdict.passed

    return {
        "name": case["name"],
        "agent": agent,
        "run_id": run.run_id,
        "final_state": run_state.status.value if run_state else "missing",
        "assertions": results,
        "passed": all_passed,
    }


def run_gate(engine, data_dir: Path, eval_dir: Path,
             judge_name: str = "mock") -> dict:
    """Run golden + safety suites; build the JSON report."""
    report = {
        "golden": [],
        "safety": [],
        "passed": True,
        "judge": judge_name,
    }

    for suite in ("golden", "safety"):
        cases = load_suite(eval_dir / suite, suite)
        for case in cases:
            result = run_case(case, engine, data_dir)
            report[suite].append(result)
            report["passed"] = report["passed"] and result["passed"]

    return report


def write_report(report: dict, out_path: Path) -> None:
    """Persist the report JSON."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)


def gate_exit_code(report: dict) -> int:
    """0 = all green; 1 = any failure."""
    return 0 if report.get("passed") else 1


__all__ = [
    "GateError",
    "run_case",
    "run_gate",
    "write_report",
    "gate_exit_code",
]
