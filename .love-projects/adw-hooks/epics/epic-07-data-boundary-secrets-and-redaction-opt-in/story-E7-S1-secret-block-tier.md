<!-- love-render src=plan.json sha=cf7a7885 do not hand-edit -->

# E7-S1 Secret block tier

Epic E7: Data boundary (secrets and redaction, opt-in). Sprint 7. Gate unit-testing.

## Why
As an operator, I want true secrets (key, token, and credential patterns) blocked at write, commit, and prompt, so secrets never pass a boundary in plain form.

## Done when
- a new secrets scanner family, config-gated, with a reviewed pattern set and per-rule ids, available to every scan_all caller: pre_write and pre_commit pick it up with no file edits, and the prompt boundary consumes it through E3-S1-T1's scanner integration
- blocked values never reach the ledger or reports in plain form (fingerprint only)

## Execution
- [ ] E7-S1-T1: Secrets family in the scanner

