<!-- love-render src=plan.json sha=0856a21c do not hand-edit -->

# E9-S2 SessionEnd cleanup and flush

Epic E9: Telemetry and audit. Sprint 9. Gate code-review.

## Why
As an operator, I want session state cleaned and metrics flushed however the session ends, so state directories do not accrete.

## Done when
- session_end.py flushes ledger buffers, renders pending scorecards, removes the session state dir, and stays fast (async where wired)

## Execution
- [ ] E9-S2-T1: session_end.py

