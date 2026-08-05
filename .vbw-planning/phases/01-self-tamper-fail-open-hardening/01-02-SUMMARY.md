---
phase: 1
plan: 2
title: Fail-closed malformed-payload handling across all four PreToolUse hooks
status: complete
completed: 2026-08-05
tasks_completed: 3
tasks_total: 3
commit_hashes:
  - 52542ee
  - b0b1720
  - 202cbc8
deviations:
  - "Refactored pre-MCP helpers to satisfy the local function-size gate."
pre_existing_issues:
  - '{"test":"test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests","file":"hooks/test_plugin_wiring.py","error":"Strict plugin validation rejects the root CLAUDE.md warning."}'
ac_results:
  - criterion: "hookio distinguishes a JSON parse failure from empty stdin: the two cases produce different values (REQ-01)"
    verdict: pass
    evidence: "hooks/lib/test_hookio.py"
  - criterion: "pre_write, pre_bash, pre_commit, and pre_mcp each return a deny decision when stdin held malformed JSON"
    verdict: pass
    evidence: "hooks/test_hooks.py and hooks/test_pre_bash.py"
  - criterion: "Empty stdin (genuinely nothing to check) still returns allow on all four hooks, no new false blocks"
    verdict: pass
    evidence: "hooks/test_hooks.py and hooks/test_pre_bash.py"
  - criterion: "pre_mcp still allows a well-formed payload with an empty session_id (legitimate session-less events keep working)"
    verdict: pass
    evidence: "test_pre_mcp_entry_allows_sessionless_payload"
  - criterion: "Full suite stays at baseline plus new tests, only the pre-existing test_plugin_wiring strict-validator failure remains"
    verdict: pass
    evidence: "997 passed, 1 documented pre-existing failure"
---

Malformed hook JSON now reaches a fail-closed decision in every PreToolUse entry script.

## What Was Built

- Added a distinct parse-failure sentinel and focused payload-reader tests.
- Denied malformed input in pre_write, pre_bash, pre_commit, and pre_mcp while retaining empty and session-less allow paths.
- Grounding: d05-formal-treatment-of-small-examples and s15-notes-on-data-structuring-i, postcondition stated, invariant is mutually exclusive input classes, variant is not applicable because no loop runs.

## Files Modified

- `hooks/lib/hookio.py`: returns a distinct malformed-payload sentinel.
- `hooks/lib/test_hookio.py`: covers empty, valid, and malformed input.
- `hooks/pre_write.py`: denies the malformed-payload sentinel.
- `hooks/pre_bash.py`: denies the malformed-payload sentinel and resolves existing type diagnostics.
- `hooks/pre_commit.py`: denies the malformed-payload sentinel.
- `hooks/pre_mcp.py`: denies the malformed-payload sentinel and keeps helper functions below the local size limit.
- `hooks/test_hooks.py`: verifies pre_write, pre_commit, and pre_mcp entry paths.
- `hooks/test_pre_bash.py`: verifies pre_bash entry paths.
