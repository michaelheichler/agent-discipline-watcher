<!-- love-render src=plan.json sha=6583ad64 do not hand-edit -->

# E2-S1 Stop gate

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate code-review.

## Why
As an operator, I want the turn blocked when the final message claims done without evidence or violates prose discipline, so that unproved claims never end a turn silently.

## Done when
- stop.py scans last_assistant_message with the existing scanner families plus an unproved-done rule in lib/done_claims.py (done, fixed, complete, or passing language with no verification evidence in the message), keeping scanner.py untouched
- stop_hook_active is honored with no re-block loops, and the documented cap of eight consecutive blocks is respected by design
- the optional verify mode runs trusted repo-declared commands, ships in observe per D7, and blocks on failure only once the family is promoted to enforce
- every decision lands in the ledger

## Execution
- [x] E2-S1-T1: stop.py discipline plus unproved-done gate
- [ ] E2-S1-T2: Verify-command Stop gate (deterministic test gate)

