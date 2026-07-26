<!-- love-render src=plan.json sha=0dae5af9 do not hand-edit -->

# E4-S4 First-touch fact-forcing gate (opt-in)

Epic E4: Self-protection and scope discipline. Sprint 4. Gate code-review.

## Why
As an operator, I want the first edit to each file per session to force an explicit impact statement, so change-impact thinking happens before the write, not after.

## Done when
- default off. When on, the first Edit or Write per file per session is denied with an instruction to state importers and callers, affected APIs, and the current instruction. The denial marks the file acknowledged in session state so the retry passes
- destructive Bash (rm -rf and configured patterns) gets the same one-pause gate requiring listed targets and a rollback plan

## Execution
- [ ] E4-S4-T1: First-touch gate in pre_write plus the Bash destructive gate

