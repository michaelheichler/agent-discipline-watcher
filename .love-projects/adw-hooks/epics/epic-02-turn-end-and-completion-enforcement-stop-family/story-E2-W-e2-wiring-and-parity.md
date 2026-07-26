<!-- love-render src=plan.json sha=0856a21c do not hand-edit -->

# E2-W E2 wiring and parity

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate code-review.

## Why
As the ADW maintainer, I want the E2 events registered on every client that supports them, so the gates actually fire on all four clients or the gap is a documented fact.

## Done when
- E2-W-T0 wires the Stop event alone and heads the shared-file chain, so E10-T0 can smoke the riskiest bet before anything else goes live
- the Claude snippet then gains SubagentStop, TaskCompleted, PostToolBatch, PostToolUseFailure, and the mcp__* PreToolUse consult entries, with run.sh routing each event, only after E10-T0 passes
- the Codex TOML gains the events the parity matrix confirms, and HOOK_LIFECYCLES covers each of them (E1-S2-T2 groundwork)
- the OpenCode and Pi adapters are extended in their own tasks below for every plan event their APIs support, and every gate's parity row records wired, degraded, or not-available per client (D10)
- install.sh and merge scripts stay idempotent on re-run, proven by a sandbox install into a temporary HOME with every merged client config parsed back cleanly

## Execution
- [x] E2-W-T0: Wire Stop only (the MVP slice)
- [ ] E2-W-T1: Wire the remaining E2 events on Claude and Codex (post-smoke)
- [ ] E2-W-T2: Extend the OpenCode adapter (all plan events its API supports)
- [ ] E2-W-T3: Extend the Pi adapter (post-hoc surfaces only, with its own tests)

