---
phase: 1
round: 1
title: Amend plan 01-04 to record the failure.py refactor delivery deviation
type: remediation
status: complete
completed: 2026-08-05
tasks_completed: 1
tasks_total: 1
commit_hashes:
  - b16e85ea0fc0edb807883d44790ce2e592c02ca5
files_modified:
  - .vbw-planning/phases/01-self-tamper-fail-open-hardening/01-04-PLAN.md
deviations:
  - "DEV-01: Recorded the historical refactor scope deviation through a documentation-only plan amendment."
known_issue_outcomes:
  - '{"test":"hooks/test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests","file":"hooks/test_plugin_wiring.py","error":"claude plugin validate --strict returned 1 because the root CLAUDE.md is not loaded as project context","disposition":"accepted-process-exception","rationale":"Pre-existing strict-validator failure that predates this phase (present at commit 8166ccf) and sits outside Milestone 1 REQ-01 self-tamper hook-path scope, per the REQ-08 out-of-scope precedent in REQUIREMENTS.md. Plugin-validator strictness is a separate concern from hook hardening. Verified non-blocking carryover for this phase."}'
  - '{"test":"test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests","file":"hooks/test_plugin_wiring.py","error":"Strict plugin validation rejects the root CLAUDE.md warning.","disposition":"accepted-process-exception","rationale":"Same root cause as the sibling entry: pre-existing strict-validator failure at commit 8166ccf, out of REQ-01 scope. Tracked separately because it entered the registry from 01-02-SUMMARY.md with distinct wording. Verified non-blocking carryover for this phase."}'
---

Recorded the DEV-01 delivery deviation and its pre-completion correction.

## Task 1: Amend 01-04-PLAN.md with a Delivery Note recording the DEV-01 deviation

### What Was Built
- Added a Delivery Note that records the initial dead helpers and their removal in commit `ebd4ec2`.
- Recorded the AP-01 clean result and the remediation round 01 plan-amendment resolution.

### Files Modified
- `.vbw-planning/phases/01-self-tamper-fail-open-hardening/01-04-PLAN.md`: appended the historical delivery record.

### Known Issue Outcomes
- `hooks/test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests` (`hooks/test_plugin_wiring.py`): `accepted-process-exception`: Pre-existing strict-validator failure that predates this phase (present at commit 8166ccf) and sits outside Milestone 1 REQ-01 self-tamper hook-path scope, per the REQ-08 out-of-scope precedent in REQUIREMENTS.md. Plugin-validator strictness is a separate concern from hook hardening. Verified non-blocking carryover for this phase.
- `test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests` (`hooks/test_plugin_wiring.py`): `accepted-process-exception`: Same root cause as the sibling entry: pre-existing strict-validator failure at commit 8166ccf, out of REQ-01 scope. Tracked separately because it entered the registry from 01-02-SUMMARY.md with distinct wording. Verified non-blocking carryover for this phase.

### Deviations
- DEV-01: Recorded the historical refactor scope deviation through a documentation-only plan amendment.