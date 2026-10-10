"""Tests for eval/loader.py — P3.1b. Case schema errors are actionable."""

import pytest

from keel.eval.loader import CaseError, load_case, load_suite


def _write(tmp_path, content, name="case.yaml"):
    f = tmp_path / name
    f.write_text(content)
    return f


def test_valid_case_loads(tmp_path):
    f = _write(tmp_path, """
name: my_case
agent: triage
case: "hello"
expect:
  - state_reached: done
""")
    case = load_case(f)
    assert case["name"] == "my_case"
    assert case["suite"] == "golden"  # default


def test_missing_keys_named(tmp_path):
    f = _write(tmp_path, """
agent: triage
case: "hello"
""")
    with pytest.raises(CaseError) as exc:
        load_case(f)
    assert "name" in str(exc.value)


def test_empty_expect_rejected(tmp_path):
    f = _write(tmp_path, """
name: x
agent: triage
case: "hello"
expect: []
""")
    with pytest.raises(CaseError) as exc:
        load_case(f)
    assert "expect" in str(exc.value)


def test_unknown_assertion_names_valids(tmp_path):
    f = _write(tmp_path, """
name: x
agent: triage
case: "hello"
expect:
  - wrong_assertion: 1
""")
    with pytest.raises(CaseError) as exc:
        load_case(f)
    assert "state_reached" in str(exc.value)  # valid list shown


def test_multi_key_assertion_rejected(tmp_path):
    f = _write(tmp_path, """
name: x
agent: triage
case: "hello"
expect:
  - state_reached: done
    no_tool_call: db
""")
    with pytest.raises(CaseError) as exc:
        load_case(f)
    assert "single-key" in str(exc.value)


def test_bad_suite_rejected(tmp_path):
    f = _write(tmp_path, """
name: x
agent: triage
case: "hello"
suite: weird
expect:
  - state_reached: done
""")
    with pytest.raises(CaseError) as exc:
        load_case(f)
    assert "suite" in str(exc.value)


def test_load_suite_filters(tmp_path):
    d = tmp_path / "suite"
    d.mkdir()
    _write(d,
           "name: g\nagent: a\ncase: c\nsuite: golden\n"
           "expect:\n  - state_reached: done\n", "a.yaml")
    _write(d,
           "name: s\nagent: a\ncase: c\nsuite: safety\n"
           "expect:\n  - state_reached: done\n", "b.yaml")
    golden = load_suite(d, "golden")
    assert len(golden) == 1 and golden[0]["name"] == "g"
