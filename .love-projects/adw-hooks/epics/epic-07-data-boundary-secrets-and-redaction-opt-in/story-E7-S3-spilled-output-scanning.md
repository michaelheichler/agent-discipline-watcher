<!-- love-render src=plan.json sha=b59ba9e7 do not hand-edit -->

# E7-S3 Spilled-output scanning

Epic E7: Data boundary (secrets and redaction, opt-in). Sprint 7. Gate code-review.

## Why
As an operator, I want spill stubs (truncated, preview, and output-file indirection) scanned at their source up to 1 MiB, so hidden content is part of the payload.

## Done when
- lib/spill.py recognizes the stub heuristics, reads the spilled path capped at 1 MiB, runs block rules against the hidden content, and is wired from record.py

## Execution
- [ ] E7-S3-T1: lib/spill.py plus record.py integration

