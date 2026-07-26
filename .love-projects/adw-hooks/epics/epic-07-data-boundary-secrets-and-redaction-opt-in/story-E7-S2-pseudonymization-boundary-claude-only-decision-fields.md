<!-- love-render src=plan.json sha=b04826fe do not hand-edit -->

# E7-S2 Pseudonymization boundary (Claude-only decision fields)

Epic E7: Data boundary (secrets and redaction, opt-in). Sprint 7. Gate unit-testing.

## Why
As an operator, I want lower-risk identifiers consistently pseudonymized via updatedInput and updatedToolOutput with one stable mapping, so scrubbed sessions stay coherent.

## Done when
- lib/pseudonym.py holds the persistent mapping under an exclusive flock on a sidecar lockfile, with one synthetic replacement per matched value across concurrent invocations
- the input rewrite (updatedInput) runs first inside pre_write's orchestration and the output rewrite (updatedToolOutput) inside record.py's (D11), so rewrite-then-scan order is code, not racing hook registrations. Both default off, enabled only by data_boundary config
- documented Claude-only (the decision fields are unavailable elsewhere), with other clients getting the block tier only

## Execution
- [ ] E7-S2-T1: lib/pseudonym.py mapping store (keyed HMAC)
- [ ] E7-S2-T2: lib/redact_input.py wired first in pre_write (updatedInput)
- [ ] E7-S2-T3: lib/redact_output.py wired last in record.py (updatedToolOutput)

