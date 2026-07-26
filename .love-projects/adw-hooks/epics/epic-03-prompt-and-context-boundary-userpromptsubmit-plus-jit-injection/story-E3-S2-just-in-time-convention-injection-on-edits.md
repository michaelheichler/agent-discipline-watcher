<!-- love-render src=plan.json sha=966c7260 do not hand-edit -->

# E3-S2 Just-in-time convention injection on edits

Epic E3: Prompt and context boundary (UserPromptSubmit plus JIT injection). Sprint 3. Gate code-review.

## Why
As an operator, I want path-scoped conventions injected at the moment of the edit, so guidance arrives before the model commits to an approach instead of only rejecting after.

## Done when
- pre_write.py consults a path-glob-to-snippet map (config) and returns the snippet as context alongside allow
- injection happens at most once per file per session (session state)

## Execution
- [ ] E3-S2-T1: Path-scoped JIT convention injection in pre_write

