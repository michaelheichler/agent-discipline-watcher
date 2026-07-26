<!-- love-render src=plan.json sha=b5fb4514 do not hand-edit -->

# E5-S2 SessionStart(compact) contract re-injection

Epic E5: Compaction resilience. Sprint 5. Gate code-review.

## Why
As an operator, I want the full discipline contract re-injected after compaction, so long sessions do not lose the rules.

## Done when
- session_start.py branches on source: compact gets the full contract plus a one-line snapshot summary, startup keeps today's line. Wiring already matches compact on Claude and Codex

## Execution
- [ ] E5-S2-T1: session_start.py compact-path enrichment plus janitor call

