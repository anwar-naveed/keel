"""Rubric judge — P3.2.

MockJudge scores deterministically (regex/keyword criteria); OllamaJudge
returns structured verdicts per criterion via stdlib HTTP. OllamaJudge is
code-complete but never exercised live on this host (no GPU); CI and local
runs use MockJudge.
"""

import re


class JudgeError(Exception):
    """Base judge error."""


class Criterion:
    """One rubric criterion: id, description, weight, must_not patterns."""

    def __init__(self, cid: str, description: str, weight: float = 1.0,
                 must_not: list[str] | None = None,
                 must_match: list[str] | None = None):
        self.id = cid
        self.description = description
        self.weight = weight
        self.must_not = [re.compile(p, re.IGNORECASE) for p in (must_not or [])]
        self.must_match = [re.compile(p, re.IGNORECASE) for p in (must_match or [])]

    def score(self, text: str) -> tuple[bool, str]:
        """Score text against this criterion."""
        for pat in self.must_not:
            if pat.search(text):
                return False, f"must_not pattern matched: {pat.pattern!r}"
        for pat in self.must_match:
            if not pat.search(text):
                return False, f"must_match pattern missed: {pat.pattern!r}"
        return True, "ok"


def load_rubric(path) -> list[Criterion]:
    """Load a rubric YAML: criteria: [{id, description, weight, must_not}]."""
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "criteria" not in data:
        raise JudgeError(f"rubric {path}: missing 'criteria' list")
    criteria = []
    for c in data["criteria"]:
        criteria.append(Criterion(
            cid=c["id"],
            description=c.get("description", ""),
            weight=float(c.get("weight", 1.0)),
            must_not=c.get("must_not", []),
            must_match=c.get("must_match", []),
        ))
    return criteria


class MockJudge:
    """Deterministic judge: pure pattern matching over rubric criteria."""

    name = "mock"

    def judge(self, text: str, criteria: list[Criterion]) -> dict:
        """Score every criterion; return structured verdict."""
        results = []
        total = 0.0
        earned = 0.0
        for c in criteria:
            passed, reason = c.score(text)
            results.append({
                "id": c.id,
                "description": c.description,
                "passed": passed,
                "reason": reason,
                "weight": c.weight,
            })
            total += c.weight
            if passed:
                earned += c.weight
        return {
            "judge": self.name,
            "criteria": results,
            "score": earned / total if total else 0.0,
            "passed": all(r["passed"] for r in results),
        }


class OllamaJudge:
    """Structured judge via Ollama chat API (stdlib HTTP).

    Code-complete, never exercised live on this host (no GPU). CI uses
    MockJudge by design.
    """

    name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None):
        import os

        self.base_url = (
            base_url
            or os.getenv("KEEL_OLLAMA_URL")
            or "http://ollama:11434"
        )
        self.model = model or os.getenv("KEEL_OLLAMA_MODEL") or "llama3.1:8b"

    def judge(self, text: str, criteria: list[Criterion]) -> dict:
        """Ask the model to score each criterion; parse structured output."""
        import json
        import urllib.request

        rubric_text = "\n".join(
            f"- {c.id}: {c.description}" for c in criteria
        )
        prompt = (
            "Score the TEXT against each rubric criterion. "
            "Reply with ONLY a JSON object: "
            '{"criteria": [{"id": "<id>", "passed": true|false, '
            '"reason": "<short>"}]}\n\n'
            f"RUBRIC:\n{rubric_text}\n\nTEXT:\n{text}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
        }
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
        body = json.loads(result["message"]["content"])
        by_id = {c["id"]: c for c in body.get("criteria", [])}
        results = []
        total = 0.0
        earned = 0.0
        for c in criteria:
            got = by_id.get(c.id, {})
            passed = bool(got.get("passed", False))
            results.append({
                "id": c.id,
                "description": c.description,
                "passed": passed,
                "reason": got.get("reason", "missing from judge response"),
                "weight": c.weight,
            })
            total += c.weight
            if passed:
                earned += c.weight
        return {
            "judge": self.name,
            "criteria": results,
            "score": earned / total if total else 0.0,
            "passed": all(r["passed"] for r in results),
        }


def get_judge(name: str = "mock", **kwargs):
    """Judge registry."""
    if name == "mock":
        return MockJudge()
    if name == "ollama":
        return OllamaJudge(**kwargs)
    raise JudgeError(f"unknown judge: {name}")


__all__ = [
    "Criterion",
    "MockJudge",
    "OllamaJudge",
    "JudgeError",
    "load_rubric",
    "get_judge",
]
