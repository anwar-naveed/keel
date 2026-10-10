# keel's eval philosophy

## Behavioral, not string-matching

An LLM runtime that ships with `assert "hello" in output` tests is testing
the mock, not the system. keel's eval cases assert **behavioral outcomes**:
what state the run reached, which tools were (structurally) callable, what
the audit chain says, what actually landed in the store, and what it cost.
The model's exact prose is deliberately not under test — models drift,
runtimes must not care.

## The grader gets graded

A rubric judge that scores free-text output is itself an LLM call — which
means it can be wrong. So the judge ships with a self-test: known-good and
known-bad sample outputs that the judge must score correctly, run inside
`keel eval --gate` itself. If the grader fails its own exam, the gate is
red. No silent grading regressions.

## Regression as routine

The gate is wired into CI (`eval-gate` job). Every push runs the golden
suite (the behaviors we promise) and the safety suite (the behaviors we
must never see): injection cannot write, overbudget runs refuse,
forbidden tiers cannot enqueue, audit tampering is detected. A "refactor"
that breaks a guarantee turns CI red before it turns production into an
incident report.

## Eval cases are data, not code

A case is ~10 lines of YAML: an agent, an input, a script (for
deterministic mock runs), and a list of assertions. The 31st agent's first
eval case is a file drop — no runtime code changes. That is the point:
evaluation must be cheap enough to happen on every push, or it doesn't
happen at all.

## What this is NOT

- Not a benchmark. There are no leaderboards here.
- Not a replacement for unit tests. pytest covers the machinery; the gate
  covers the behavior.
- Not grading vibes. Every criterion is a pattern with a weight and a
  must/must_not contract, versioned in the rubric file.
