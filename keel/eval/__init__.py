"""keel.eval — behavioral evaluation harness (Phase 3)."""

from keel.eval.assertions import ASSERTIONS, Verdict, check_assertion
from keel.eval.gate import gate_exit_code, run_case, run_gate, write_report
from keel.eval.judge import MockJudge, OllamaJudge, load_rubric
from keel.eval.loader import CaseError, load_case, load_suite
from keel.eval.selftest import judge_selftest

__all__ = [
    "ASSERTIONS", "Verdict", "check_assertion",
    "gate_exit_code", "run_case", "run_gate", "write_report",
    "MockJudge", "OllamaJudge", "load_rubric",
    "CaseError", "load_case", "load_suite",
    "judge_selftest",
]
