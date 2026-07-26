<!-- love-render src=plan.json sha=fd7f0750 do not hand-edit -->

# E6-S6 Differential coverage ratchet

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate code-review.

## Why
As an operator, I want changed-line coverage below policy blocked at completion or commit, so new debt is stopped while legacy coverage stays visible.

## Done when
- diff-cover and coverage.py integration, changed-line and changed-branch thresholds, and rejection of a drop from the base-branch baseline

## Execution
- [ ] E6-S6-T1: lib/coverage_gate.py ratchet

