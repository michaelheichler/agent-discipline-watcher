<!-- love-render src=plan.json sha=b04826fe do not hand-edit -->

# E6-S3 Baseline-aware lint delta gate

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate unit-testing.

## Why
As an operator, I want only newly introduced lint diagnostics blocked, so legacy debt stays visible without freezing work.

## Done when
- the baseline is captured lazily once per session on the first post-edit check (keyed by session_id in session state, which keeps all work inside lib and avoids owning session_start.py), post-edit lint runs on the touched file or package and blocks only new diagnostics in structured file, line, and rule form, and the baseline recomputes on base-revision or lint-config change

## Execution
- [ ] E6-S3-T1: lib/lint_delta.py plus lazy baseline capture

