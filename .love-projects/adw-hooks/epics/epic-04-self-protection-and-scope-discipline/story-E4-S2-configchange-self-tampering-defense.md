<!-- love-render src=plan.json sha=b59ba9e7 do not hand-edit -->

# E4-S2 ConfigChange self-tampering defense

Epic E4: Self-protection and scope discipline. Sprint 4. Gate code-review.

## Why
As an operator, I want mid-session changes to ADW's hook registration blocked, so a prompt-injected instruction cannot silently disable enforcement.

## Done when
- config_change.py blocks changes whose source is user_settings, project_settings, local_settings, or skills when the changed file matches ADW wiring or skill files
- policy_settings changes are logged only, since the docs say blocking is ignored there

## Execution
- [ ] E4-S2-T1: config_change.py hook

