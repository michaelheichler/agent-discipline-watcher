<!-- love-render src=plan.json sha=9ecf862e do not hand-edit -->

# E6-S5 Impact-selected tests on edits

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate unit-testing.

## Why
As an operator, I want the affected tests run immediately after a source edit, so behavioral evidence arrives per edit, not per turn.

## Done when
- adapters for jest --findRelatedTests and pytest-testmon, failing assertions returned as blocking feedback, and the full suite reserved for Stop, TaskCompleted, or commit

## Execution
- [ ] E6-S5-T1: lib/impacted.py test selection adapters

