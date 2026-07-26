<!-- love-render src=plan.json sha=37bf6be4 do not hand-edit -->

# E2-S3 TaskCompleted gate

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate code-review.

## Why
As an operator, I want a task blocked from completing while its changed files carry findings or its verify matrix fails, so that a bad done lands per task, not at turn end.

## Done when
- task_completed.py uses the corrected fields (task_id, task_subject, optional teammate and team) and the corrected control (exit 2 or continue false), not the disproven task_result or decision-block fields
- scans files recorded as changed this session (ledger) and, when configured, runs the verify matrix scoped by changed-file categories
- documented as Claude-only until the parity matrix says otherwise

## Execution
- [ ] E2-S3-T1: task_completed.py verification gate

