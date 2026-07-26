<!-- love-render src=plan.json sha=966c7260 do not hand-edit -->

# E9-S1 Dead-rules compliance telemetry

Epic E9: Telemetry and audit. Sprint 9. Gate unit-testing.

## Why
As the maintainer, I want CLAUDE.md parsed into atomic rules with per-rule relevance and violation tallies and a worst-first scorecard, so the next prose rule worth converting into a deterministic blocker is a measurement, not a guess.

## Done when
- SessionStart parses CLAUDE.md into numbered rules, PostToolUse tallies, and SessionEnd renders the worst-first scorecard to the ledger dir

## Execution
- [ ] E9-S1-T1: lib/dead_rules.py plus its three hook integrations

