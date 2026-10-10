# ADR-002: Capabilities, not permissions — impossible writes

## Context
Prompt-injection defense by instruction ("never write") is a request, not
a guarantee. A model that complies with a jailbreak will attempt the write.
The runtime must survive the model being hostile.

## Options
1. **Permission checks** — wrap tools with `if allowed:` guards. The check
   can be bypassed, forgotten, or refactor away; the write exists as code.
2. **Capability objects** — build the tool object per tier such that
   unauthorized methods DO NOT EXIST as attributes.

## Decision
Capability objects (ADR-002 pattern): `ReadOnlyDB` has `select` and nothing
else — no `write`, no `update`, no `delete` attribute anywhere. A jailbroken
model calling `db.write` gets AttributeError at the tool boundary. The
write is structurally impossible, not forbidden.

## Consequences
- `hasattr(tool, "write") == False` is testable — and tested
  (test_capabilities.py::test_injection_cannot_write).
- Adding a tier means adding a class with exactly the granted methods.
- The engine routes every tool call through the capability object; there is
  no code path to a raw SQL write from a model turn.
