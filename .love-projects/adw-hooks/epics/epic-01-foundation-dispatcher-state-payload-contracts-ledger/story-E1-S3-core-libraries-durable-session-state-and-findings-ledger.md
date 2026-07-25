<!-- love-render src=plan.json sha=3cb07f1b do not hand-edit -->

# E1-S3 Core libraries: durable session state and findings ledger

Epic E1: Foundation: dispatcher, state, payload contracts, ledger. Sprint 1. Gate unit-testing.

## Why
As the ADW maintainer, I want one dispatch table, one payload contract, one state store, and one ledger, so that eleven new hooks share tested plumbing instead of reinventing it.

## Done when
- lib/session_state.py survives process restart and concurrent writers (atomic replace), keyed by session_id, and offers a sweep API that removes stale session dirs, the janitor for a missed SessionEnd
- every gate decision appends one JSONL ledger row with hook, rule, duration_ms, tool_use_id where present, and an outcome from the enum block, inject, would_block, no_edits, and record.py journals every successful edit (path, tool, ts) so completion gates know what changed this session
- every entry script runs through the shared main wrapper, which emits one observed heartbeat row per invocation, the denominator for the D7 metric and the producer for the E10-T1 heartbeat check

## Execution
- [x] E1-S1-T2: Durable session state store (lib/session_state.py)
- [ ] E1-S1-T4: Findings ledger, session edit journal, heartbeat wrapper, observe report

