<!-- love-render src=plan.json sha=37535ee8 do not hand-edit -->

# E7-H Human policy gate

Epic E7: Data boundary (secrets and redaction, opt-in). Sprint 7. Gate code-review.

## Why
As the owner, I decide the redaction policy (identifier classes, retention of the mapping store, custody and rotation of the HMAC key, who may enable data_boundary mode) before the tier can be switched on.

## Done when
- a short written policy in the repo docs covering identifier classes, mapping retention, and HMAC key custody plus rotation, and data_boundary mode refuses to enable without it

## Execution
- [ ] E7-H-T1: Redaction policy decision

