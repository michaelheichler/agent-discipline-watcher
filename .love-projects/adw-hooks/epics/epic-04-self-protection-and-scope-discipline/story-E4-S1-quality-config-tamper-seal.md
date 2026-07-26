<!-- love-render src=plan.json sha=9ecf862e do not hand-edit -->

# E4-S1 Quality-config tamper seal

Epic E4: Self-protection and scope discipline. Sprint 4. Gate unit-testing.

## Why
As an operator, I want edits to linter, formatter, typecheck, hook, and ignore configs and to ADW's own wiring blocked unless explicitly authorized, so the agent cannot green-light checks by weakening the checker.

## Done when
- a protected-path policy in lib/protected.py blocks edits to existing protected files, allows first-time creation, and fails closed on stat errors (EACCES and EPERM treated as exists)
- case-insensitive basename matching for case-insensitive filesystems
- explicit authorization via config or a documented env var, with authorized changes invalidating cached verify results and landing in the ledger
- new blanket suppressions in source edits (file-level lint disables, blanket type-ignores) are blocked unless policy permits them

## Execution
- [ ] E4-S1-T1: Tamper seal in pre_write (merges the ECC config lock and the tamper seal)

