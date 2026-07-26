<!-- love-render src=plan.json sha=b59ba9e7 do not hand-edit -->

# E6-S1 Verify runner core

Epic E6: Repo verification tier (config-driven quality gates, trust-gated, observe-first). Sprint 6. Gate unit-testing.

## Why
As the ADW maintainer, I want one runner for repo-declared checks with changed-file category mapping, so six quality gates share one execution and reporting path.

## Done when
- lib/verify.py: a declared matrix in .agent-discipline.json (category to commands), changed-file-to-category mapping, fail-fast, per-command timeout, compact structured failures, ledger rows with elapsed time
- trust boundary (D12): command-bearing config is inert until a user-owned grant exists at ~/.agent-discipline/trust/<repo-fingerprint>, written by the installed CLI 'agent-discipline trust' run in the repo. Without it every recipe no-ops with a visible note. Commands execute as argv lists, never through a shell
- an end-to-end test proves the documented command works from a temporary target repo after a sandbox install: trust, revoke, and moved-repo, so the boundary is usable, not just fail-closed

## Execution
- [ ] E6-S1-T1: lib/verify.py runner with the trust boundary

