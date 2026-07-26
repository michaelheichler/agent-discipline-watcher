<!-- love-render src=plan.json sha=3d899cf9 do not hand-edit -->

# E10-S1 Prove and decide

Epic E10: Rollout, live verification, docs. Sprint 10. Gate code-review.

## Why
As the owner, I want live proof that the events fire as planned and an evidence-based decision on which gates go default-on, so rollout is a decision, not a hope.

## Done when
- E10-T0 first: a live session proves the Stop hook blocks and releases as documented, before any other new event goes live. The lead runs the install. This is the first pivot-or-persevere gate from validation.decision_rule
- E10-T1 then verifies the full surface: SubagentStop scan, UserPromptSubmit inject, ConfigChange block, PreCompact snapshot plus compact re-inject, with a heartbeat requirement (at least one ledger row per wired event during the session) and the installed client version recorded next to the results
- the gate promotion decision (observe to enforce) is recorded per family with the report's adjudicated false-signal rate and ledger numbers that justified it
- SKILL.md and README are updated with new events, config keys, the parity matrix with its fallback column, and kill-switches, and block messages are reviewed for actionability (the block message is ADW's whole UI)

## Execution
- [ ] E10-T0: Live Stop smoke (the MVP experiment)
- [ ] E10-T1: Full-event live verification
- [ ] E10-T2: Gate promotion decision (observe to enforce)
- [ ] E10-T3: SKILL.md plus README documentation pass

