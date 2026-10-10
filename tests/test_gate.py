"""Tests for eval/gate.py — P3.3. Exit codes + the CI wiring contract."""

from pathlib import Path

from keel.eval.gate import gate_exit_code, run_case, run_gate, write_report
from keel.runtime.engine import Engine


def _wire(engine, cfg):
    engine._load_agent_config = lambda a: cfg  # noqa: SLF001


def test_run_case_pass(tmp_path):
    script = tmp_path / "s.yaml"
    script.write_text('- content: "ok"\n  tool_calls: []\n')
    engine = Engine(data_dir=tmp_path)
    _wire(engine, {
        "provider": "mock", "script": str(script),
        "system_prompt": "x", "tier": "read_only",
    })
    case = {
        "name": "ok_case", "agent": "triage", "case": "hi",
        "expect": [{"state_reached": "done"}, {"runlog_complete": True}],
    }
    result = run_case(case, engine, tmp_path)
    assert result["passed"] is True


def test_run_case_assertion_fail(tmp_path):
    script = tmp_path / "s.yaml"
    script.write_text('- content: "ok"\n  tool_calls: []\n')
    engine = Engine(data_dir=tmp_path)
    _wire(engine, {
        "provider": "mock", "script": str(script),
        "system_prompt": "x", "tier": "read_only",
    })
    case = {
        "name": "bad_case", "agent": "triage", "case": "hi",
        "expect": [{"state_reached": "failed"}],  # will actually be done
    }
    result = run_case(case, engine, tmp_path)
    assert result["passed"] is False
    assert result["assertions"][0]["passed"] is False


def test_run_case_refused_run_is_verdict(tmp_path):
    """forbidden_enqueue: the enqueue refusal is a FAIL verdict with reason."""
    engine = Engine(data_dir=tmp_path)
    _wire(engine, {
        "provider": "mock", "system_prompt": "x", "tier": "forbidden",
    })
    case = {
        "name": "forbidden", "agent": "banned_agent", "case": "hi",
        "expect": [{"state_reached": "failed"}],
    }
    result = run_case(case, engine, tmp_path)
    # refused run cannot reach any state -> not passed
    assert result["passed"] is False
    assert "refused" in result["assertions"][0]["reason"]


def test_gate_exit_code_contract():
    assert gate_exit_code({"passed": True}) == 0
    assert gate_exit_code({"passed": False}) == 1


def test_run_gate_writes_report(tmp_path):
    script = tmp_path / "s.yaml"
    script.write_text('- content: "ok"\n  tool_calls: []\n')
    engine = Engine(data_dir=tmp_path)
    _wire(engine, {
        "provider": "mock", "script": str(script),
        "system_prompt": "x", "tier": "read_only",
    })
    eval_dir = tmp_path / "eval"
    (eval_dir / "golden").mkdir(parents=True)
    (eval_dir / "golden" / "g.yaml").write_text(
        "name: g\nagent: triage\ncase: hi\nsuite: golden\n"
        "expect:\n  - state_reached: done\n"
    )
    report = run_gate(engine, tmp_path, eval_dir)
    assert len(report["golden"]) == 1
    assert report["passed"] is True

    out = tmp_path / "last.json"
    write_report(report, out)
    import json

    loaded = json.loads(out.read_text())
    assert loaded["passed"] is True


def test_repo_suites_load_and_shape():
    """The shipped eval/ tree must load cleanly (CI gate depends on it)."""
    from keel.eval.loader import load_suite

    repo_eval = Path("/workspace/eval") if Path("/workspace/eval").exists() \
        else Path("eval")
    golden = load_suite(repo_eval / "golden", "golden")
    safety = load_suite(repo_eval / "safety", "safety")
    assert len(golden) >= 4
    assert len(safety) >= 4
    names = {c["name"] for c in golden + safety}
    assert {
        "triage_classify", "triage_injection", "draft_staging", "qa_gate",
        "injection_write", "overbudget", "forbidden_enqueue", "audit_tamper",
    } <= names
