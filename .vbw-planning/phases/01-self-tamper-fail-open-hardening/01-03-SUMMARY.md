---
phase: 1
plan: 3
title: First-config-creation validation (reject rule-family kill and state/ledger root redirection)
status: complete
completed: 2026-08-05
tasks_completed: 3
tasks_total: 3
commit_hashes:
  - 563e8dd
  - 8282e51
  - 2d006e1
task_statuses:
  - task: Extend grants_escape to cover family kill and root redirection
    status: complete
    commit: 563e8dd
  - task: Apply the content gate on first config creation
    status: complete
    commit: 8282e51
  - task: Invariant and schema regression pass
    status: complete
    commit: 2d006e1
files_modified:
  - hooks/lib/protected.py
  - hooks/lib/test_protected.py
  - hooks/test_self_protection_invariants.py
deviations:
  - "The independent first-creation content route already existed, so task 2 added regression coverage without changing protected.py."
pre_existing_issues:
  - '{"test":"test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests","file":"hooks/test_plugin_wiring.py","error":"Strict plugin validation rejects the root CLAUDE.md warning."}'
ac_results:
  - criterion: "grants_escape returns True for a payload that disables every rule family, via the boolean switches or the gates map (REQ-01)"
    verdict: pass
    evidence: "test_all_family_disables_and_root_redirection_grant_an_escape"
  - criterion: "grants_escape returns True for a payload that sets state_root or ledger_root"
    verdict: pass
    evidence: "ATTACK coverage in hooks/lib/test_protected.py"
  - criterion: "path_findings on a not-yet-existing .agent-discipline.json with such a payload returns a finding, first creation is no longer unconditionally allowed"
    verdict: pass
    evidence: "test_first_creation_of_an_attack_config_blocks"
  - criterion: "A benign config that disables one rule family still creates cleanly, no new false blocks"
    verdict: pass
    evidence: "test_first_creation_of_a_benign_config_stays_allowed"
  - criterion: "Full suite stays at baseline plus new tests, only the pre-existing test_plugin_wiring strict-validator failure remains"
    verdict: pass
    evidence: "1006 passed, 1 documented pre-existing failure"
  - criterion: "hooks/lib/protected.py provides escape detection covering family switches, gates map, and root redirection"
    verdict: pass
    evidence: "563e8dd"
  - criterion: "hooks/lib/test_protected.py provides regression tests replaying the research attack payload"
    verdict: pass
    evidence: "563e8dd and 8282e51"
  - criterion: "hooks/lib/protected.py to hooks/lib/config.py: grants_escape uses flatten_settings and config family keys"
    verdict: pass
    evidence: "GATE_FAMILIES and flatten_settings imports in hooks/lib/protected.py"
  - criterion: "hooks/pre_write.py to hooks/lib/protected.py: path_findings content gate applies to config writes, including first creation"
    verdict: pass
    evidence: "test_an_attack_config_cannot_be_created_without_a_finding"
---

## What Was Built

- Rejected new config payloads that turn off every rule family or redirect the state or ledger roots.
- Locked first-creation behavior and the end-to-end PreToolUse invariant with focused regressions.

## Files Modified

- `hooks/lib/protected.py`: detects family-kill and root-redirection config escapes.
- `hooks/lib/test_protected.py`: covers attack, benign, and first-creation payloads.
- `hooks/test_self_protection_invariants.py`: proves the attack payload cannot create a config without a finding.
