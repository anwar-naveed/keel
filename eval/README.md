# keel eval — behavioral cases

Add a case in ~10 lines:

```yaml
name: my_case
agent: triage            # any agent in agents/
suite: golden            # or safety
case: "the input text"
provider_script: "agents/scripts/my_mock.yaml"  # optional
expect:
  - state_reached: done
  - no_tool_call: db
  - cost_within: {max_usd: 0.01}
```

Assertions: `state_reached`, `tool_call_sequence`, `no_tool_call`,
`tier_held`, `audit_integrity`, `runlog_complete`, `cost_within`.

Run: `docker compose exec keel-dev keel eval --gate` (exit 1 on any fail).
