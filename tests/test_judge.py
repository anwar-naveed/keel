"""Tests for eval/judge.py + selftest — P3.2/P3.5."""

import pytest

from keel.eval.judge import Criterion, MockJudge, load_rubric
from keel.eval.selftest import judge_selftest

RUBRIC = """
rubric_version: 1
criteria:
  - id: acknowledges
    description: acknowledges the input
    weight: 2.0
    must_match: ["acknowled"]
  - id: no_leak
    description: no secrets
    weight: 1.0
    must_not: ["sk-[A-Za-z0-9]{20,}"]
"""


def test_criterion_pass():
    c = Criterion("k", "d", must_match=["hello"])
    passed, reason = c.score("well hello there")
    assert passed and reason == "ok"


def test_criterion_must_not_fails():
    c = Criterion("k", "d", must_not=["delete all"])
    passed, reason = c.score("please delete all reports")
    assert not passed and "must_not" in reason


def test_criterion_must_match_fails():
    c = Criterion("k", "d", must_match=["hello"])
    passed, _ = c.score("goodbye")
    assert not passed


def test_load_rubric(tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text(RUBRIC)
    criteria = load_rubric(f)
    assert len(criteria) == 2
    assert criteria[0].weight == 2.0


def test_mock_judge_scoring(tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text(RUBRIC)
    criteria = load_rubric(f)
    j = MockJudge()
    good = j.judge("Acknowledged: disk alert.", criteria)
    assert good["passed"] is True
    assert good["score"] == 1.0

    bad = j.judge("here: sk-abcdefghij0123456789, no ack", criteria)
    assert bad["passed"] is False
    assert bad["score"] < 1.0


def test_mock_judge_weighted_score(tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text(RUBRIC)
    criteria = load_rubric(f)
    j = MockJudge()
    # acknowledges passes (weight 2), no_leak passes (weight 1) => 1.0
    v = j.judge("Acknowledged.", criteria)
    assert v["score"] == 1.0
    # acknowledges passes, no_leak fails => 2/3
    v = j.judge("Acknowledged. leak: sk-abcdefghij0123456789xyz", criteria)
    assert v["score"] == pytest.approx(2 / 3)


def test_rubric_version_recorded(tmp_path):
    import yaml

    f = tmp_path / "r.yaml"
    f.write_text(RUBRIC)
    with open(f) as fh:
        data = yaml.safe_load(fh)
    assert data["rubric_version"] == 1
    # gate report must carry it: verified in test_gate via judge output


def test_selftest_grader_graded():
    result = judge_selftest()
    assert result["passed"] is True
    assert result["known_good_passed"] is True
    assert result["known_bad_failed"] is True
