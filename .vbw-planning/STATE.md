# State

**Project:** agent-discipline-watcher
**Milestone:** Milestone 1: Remediate Review Findings

## Current Phase
Phase: 2 of 5 (Scanning Escalation Correctness)
Plans: 0/0
Progress: 0%
Status: ready

## Phase Status
- **Phase 1 (Self Tamper Fail Open Hardening):** Complete
- **Phase 2 (Scanning Escalation Correctness):** Pending
- **Phase 3 (State Reporting Ledger Integrity):** Pending
- **Phase 4 (Hook Entry Script Correctness):** Pending
- **Phase 5 (Cli Install Time Config Merge Safety):** Pending

## Key Decisions
| Decision | Date | Rationale |
|----------|------|-----------|
| Scope this milestone to the Claude Code hook path only | 2026-08-04 | The June 2026 five-group review covered `hooks/` and `bin/` only. Findings specific to the OpenCode or Pi/Codex adapters are deferred, not skipped. |
| Map the 5 phases 1:1 to the review's 5 fan-out groups | 2026-08-04 | Each phase already has a scoped, live-reproduced finding set and a known passing test suite to fix forward against. No re-grouping needed. |

## Todos
- Audit `opencode/agent-discipline-watcher.ts` for the same defect classes found in the Python hook path (deferred, out of scope for Milestone 1, see REQUIREMENTS.md REQ-08)
- Audit `pi/extensions/` for the same defect classes found in the Python hook path (deferred, out of scope for Milestone 1, see REQUIREMENTS.md REQ-08)
- [KNOWN-ISSUE] hooks/test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests (hooks/test_plugin_wiring.py): claude plugin validate --strict returned 1 because the root CLAUDE.md is not ..., accepted as process-exception for this phase (phase 01, seen 1x) (see remediation/qa/round-01/R01-SUMMARY.md) (added 2026-08-05) (ref:0433480e)
- [KNOWN-ISSUE] test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests (hooks/test_plugin_wiring.py): Strict plugin validation rejects the root CLAUDE.md warning, accepted as process-exception for this phase (phase 01, seen 1x) (see remediation/qa/round-01/R01-SUMMARY.md) (added 2026-08-05) (ref:6f3983ae)
## Blockers
None

## Activity Log
- 2026-08-04: Created Milestone 1: Remediate Review Findings milestone (5 phases)
- 2026-08-05: Phase 1 (Self-Tamper & Fail-Open Hardening) built and verified. 4 plans, 12 tasks, 1 QA remediation round, UAT 8/8 pass.
