<!-- love-render src=plan.json sha=b04826fe do not hand-edit -->

# E4-S5 Cross-call behavioral taint sequences

Epic E4: Self-protection and scope discipline. Sprint 4. Gate unit-testing.

## Why
As an operator, I want read-secret-then-network and download-then-execute sequences blocked, so multi-step exfiltration patterns are caught that single-payload scans cannot see.

## Done when
- record.py (PostToolUse) appends tool events to a session event log, and lib/taint.py evaluates a small named-rule set (sensitive-read-then-network, write-then-build poisoning, sensitive-read-then-MCP) on PreToolUse for Bash, Write, and Edit
- rules also block Bash commands manipulating ADW's own config or allowlist
- each rule has a named id in block reasons and ledger rows

## Execution
- [ ] E4-S5-T1: lib/taint.py sequence rules plus the event log feed

