<!-- love-render src=plan.json sha=0dae5af9 do not hand-edit -->

# E8-S1 Dead-end registry pipeline

Epic E8: Negative memory (dead-end registry). Sprint 8. Gate unit-testing.

## Why
As an operator, I want tried-and-reverted approaches remembered outside the repo and surfaced when they are about to be retried, so sessions stop rediscovering the same dead ends.

## Done when
- a repo-keyed JSONL store outside the repo with a schema of approach fingerprint, evidence pointer, created, and expiry
- miners on Stop and SubagentStop detect tried-and-reverted hunks from the session ledger and transcript
- UserPromptSubmit injects a DEAD END card on match, and the PreToolUse similarity check warns by default and blocks only when configured

## Execution
- [ ] E8-S1-T1: lib/deadends.py store plus similarity fingerprinting
- [ ] E8-S1-T2: Stop and SubagentStop dead-end miners
- [ ] E8-S1-T3: UserPromptSubmit dead-end warning card
- [ ] E8-S1-T4: PreToolUse reintroduction guard (warn-first)

