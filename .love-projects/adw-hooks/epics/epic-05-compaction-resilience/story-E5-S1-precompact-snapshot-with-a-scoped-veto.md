<!-- love-render src=plan.json sha=445cf8f0 do not hand-edit -->

# E5-S1 PreCompact snapshot with a scoped veto

Epic E5: Compaction resilience. Sprint 5. Gate code-review.

## Why
As an operator, I want session discipline state snapshotted before compaction, and compaction vetoed only while a blocking gate is unresolved, so enforcement context cannot be summarized away mid-gate.

## Done when
- pre_compact.py writes the snapshot (active leases, ack sets, streaks, pending block state) to session state and handles the manual and auto matchers
- the veto (block decision) fires only when a blocking gate is mid-flight, and the default is allow

## Execution
- [ ] E5-S1-T1: pre_compact.py snapshot and scoped veto

