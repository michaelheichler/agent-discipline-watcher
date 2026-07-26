<!-- love-render src=plan.json sha=37bf6be4 do not hand-edit -->

# E6-W E6 wiring

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate code-review.

## Why
As the ADW maintainer, I want the verification recipes reachable from record.py, stop.py, and task_completed.py per config.

## Done when
- record.py consults configured recipes post-edit, stop and task_completed run the full tier, snippets are updated where a new registration is needed, and every recipe is inert without the trust grant and observe-first per D7

## Execution
- [ ] E6-W-T1: Integrate verify recipes into the hook flow

