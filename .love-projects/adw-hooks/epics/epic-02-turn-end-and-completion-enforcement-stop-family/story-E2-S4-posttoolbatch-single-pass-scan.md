<!-- love-render src=plan.json sha=445cf8f0 do not hand-edit -->

# E2-S4 PostToolBatch single-pass scan

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate code-review.

## Why
As an operator, I want one coherent block message per parallel edit batch, so that findings across simultaneous writes are deduplicated and cross-file patterns are visible.

## Done when
- record.py's per-call scan stays canonical and is never suppressed or buffered (D13)
- batch.py correlates via tool_use_id (payload contract and ledger row field) between the tool_calls array and the batch's PostToolUse rows, and reports only new cross-file findings, so its dedupe is of its own output and nothing is lost if PostToolBatch never fires
- when live payloads lack tool_use_id, batch.py drops ledger dedupe and restricts itself to intrinsically cross-file rules, the degraded mode D13 documents

## Execution
- [ ] E2-S4-T1: batch.py additive cross-file pass (D13)

