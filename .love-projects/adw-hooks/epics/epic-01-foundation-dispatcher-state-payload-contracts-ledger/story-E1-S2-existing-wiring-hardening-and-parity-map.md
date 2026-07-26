<!-- love-render src=plan.json sha=b02c4752 do not hand-edit -->

# E1-S2 Existing-wiring hardening and parity map

Epic E1: Foundation: dispatcher, state, payload contracts, ledger. Sprint 1. Gate code-review.

## Why
As the ADW maintainer, I want the existing wiring scoped tighter and a per-client event availability matrix, so that new-event wiring tasks have a factual basis per client.

## Done when
- the Claude snippet's Bash pre-commit hook carries the documented if filter for git commit while pre_commit.py's own parser stays as the cross-client backstop
- an async-flag policy exists: log-only hooks declare async true in the Claude snippet
- a parity matrix (README section) states, per client and per event used in this plan, wired or degraded or not-available, from each client's primary docs, including the Pi post-hoc-only and OpenCode injection-only-Stop limits
- HOOK_LIFECYCLES in merge-codex-config.py lists every event ADW wires, with a merge test asserting the list matches the snippet

## Execution
- [x] E1-S2-T1: if-field scoping plus async flag policy on the Claude snippet
- [x] E1-S2-T2: Cross-client event parity matrix plus merge-script generalization

