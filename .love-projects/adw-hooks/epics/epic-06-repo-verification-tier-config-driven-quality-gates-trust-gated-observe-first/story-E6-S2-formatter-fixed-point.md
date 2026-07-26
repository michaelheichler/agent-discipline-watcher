<!-- love-render src=plan.json sha=9ecf862e do not hand-edit -->

# E6-S2 Formatter fixed-point

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate code-review.

## Why
As an operator, I want touched files formatted to a fixed point after each edit with non-convergence blocking, so formatting noise never reaches review.

## Done when
- a config map from language to formatter runs on the touched file only, check-mode verifies convergence, changed bytes return the path as context to force a reread, and crashes or non-convergence block
- opt-in: this is ADW's only mutating hook and the config key says so explicitly

## Execution
- [ ] E6-S2-T1: lib/format_fix.py post-edit formatter recipe

