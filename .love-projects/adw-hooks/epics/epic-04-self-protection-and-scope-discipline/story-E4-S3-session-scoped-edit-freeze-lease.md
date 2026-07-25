<!-- love-render src=plan.json sha=28c6dd7d do not hand-edit -->

# E4-S3 Session-scoped edit freeze lease

Epic E4: Self-protection and scope discipline. Sprint 4. Gate code-review.

## Why
As an operator, I want an opt-in freeze command that denies edits outside a directory boundary until I widen it, so scope creep is structurally impossible during focused work.

## Done when
- CLI subcommands freeze, unfreeze, and status write the lease to session state
- pre_write denies (permissionDecision deny) resolved paths outside the boundary with the lease named in the reason

## Execution
- [ ] E4-S3-T1: Freeze lease (CLI plus pre_write deny)

