<!-- love-render src=plan.json sha=cf7a7885 do not hand-edit -->

# E6-S4 Content-hashed typecheck gate

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate unit-testing.

## Why
As an operator, I want fresh type errors blocked cheaply after typed-language edits, so cross-file type breakage is caught before review.

## Done when
- locate the owning package, run the no-output typecheck, cache keyed by config-file hashes (the verified prior art) with a full-input hash as stretch, block on fresh errors, and offer an uncached full check at completion

## Execution
- [ ] E6-S4-T1: lib/typecheck.py cached gate

