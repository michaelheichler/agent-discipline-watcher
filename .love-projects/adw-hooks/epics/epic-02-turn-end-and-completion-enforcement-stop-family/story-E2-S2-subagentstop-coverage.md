<!-- love-render src=plan.json sha=966c7260 do not hand-edit -->

# E2-S2 SubagentStop coverage

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate code-review.

## Why
As an operator, I want delegated work held to the same turn-end discipline, so that a subagent cannot hand back unproved claims invisibly.

## Done when
- subagent_stop.py scans the subagent's last_assistant_message with the same rules as stop.py
- agent_type matcher support is documented, and ledger rows carry agent_id and agent_type

## Execution
- [x] E2-S2-T1: subagent_stop.py scan

