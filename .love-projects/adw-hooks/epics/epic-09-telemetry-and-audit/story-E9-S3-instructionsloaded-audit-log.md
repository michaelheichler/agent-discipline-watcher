<!-- love-render src=plan.json sha=b59ba9e7 do not hand-edit -->

# E9-S3 InstructionsLoaded audit log

Epic E9: Telemetry and audit. Sprint 9. Gate code-review.

## Why
As the maintainer, I want a ground-truth log of which rule and skill files loaded and why, so checking whether an orphaned hook still loads is a one-line lookup.

## Done when
- instructions_loaded.py appends file, load_reason, and ts to the ledger dir, runs async, and its output is ignored per docs

## Execution
- [ ] E9-S3-T1: instructions_loaded.py async logger

