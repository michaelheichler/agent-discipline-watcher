<!-- love-render src=plan.json sha=9a6a469f do not hand-edit -->

# E8-W E8 wiring

Epic E8: Negative memory (dead-end registry). Sprint 8. Gate code-review.

## Why
As the ADW maintainer, I want the registry flush wired into PreCompact and SessionEnd.

## Done when
- pre_compact and session_end flush pending mining state, and no new events are needed

## Execution
- [ ] E8-W-T1: Registry lifecycle wiring

