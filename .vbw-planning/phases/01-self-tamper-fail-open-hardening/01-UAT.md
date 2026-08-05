---
phase: 1
plan_count: 5
status: complete
started: 2026-08-05
completed: 2026-08-05
total_tests: 8
passed: 8
skipped: 0
issues: 0
---

Phase 1 (Self-Tamper & Fail-Open Hardening) UAT: 4 documented-deviation reviews plus one lightweight confirmation checkpoint per plan. All work in this phase is internal hook-classifier hardening with no UI surface.

## Tests

### D01: Review summary deviation

- **Source:** Summary deviation review
- **Deviation Signature:** 8efe20850420f47137d14de08eef4b26d565c270549cff78043af902a6d144c3
- **Source Plan:** 2
- **Source Summary:** 01-02-SUMMARY.md
- **Deviation:** Refactored pre-MCP helpers to satisfy the local function-size gate.
- **Plan:** 01-02, Fail-closed malformed-payload handling across all four PreToolUse hooks
- **Scenario:** Review a documented implementation deviation from SUMMARY.md
- **Expected:** Human confirms whether this documented deviation is acceptable for this phase.
- **Result:** pass
- **Disposition:** accepted-process-exception

### D02: Review summary deviation

- **Source:** Summary deviation review
- **Deviation Signature:** 9177af87badfc9d04cdeab917bc3d462ff4a0f7c6a397a30f104338858b2fdca
- **Source Plan:** 3
- **Source Summary:** 01-03-SUMMARY.md
- **Deviation:** The independent first-creation content route already existed, so task 2 added regression coverage without changing protected.py.
- **Plan:** 01-03, First-config-creation validation (reject rule-family kill and state/ledger root redirection)
- **Scenario:** Review a documented implementation deviation from SUMMARY.md
- **Expected:** Human confirms whether this documented deviation is acceptable for this phase.
- **Result:** pass
- **Disposition:** accepted-process-exception

### D03: Review summary deviation

- **Source:** Summary deviation review
- **Deviation Signature:** c1257a4a4548718d3ff3a00c7fb0742658b8f922bef63b78dc6e595f494dd04f
- **Source Plan:** 4
- **Source Summary:** 01-04-SUMMARY.md
- **Deviation:** AI Craftsman PY002 required extracting oversized failure helpers.
- **Plan:** 01-04, Renderer output sanitization and payloads type-check simplification
- **Scenario:** Review a documented implementation deviation from SUMMARY.md
- **Expected:** Human confirms whether this documented deviation is acceptable for this phase.
- **Result:** pass
- **Disposition:** accepted-process-exception

### D04: Review summary deviation

- **Source:** Summary deviation review
- **Deviation Signature:** 6adf89d983dc62de7561feae41daf63fc6a46b78ffdb56e2902d7f8a10ff4d3c
- **Source Plan:** R01
- **Source Summary:** remediation/qa/round-01/R01-SUMMARY.md
- **Deviation:** DEV-01: Recorded the historical refactor scope deviation through a documentation-only plan amendment.
- **Plan:** R01, Amend plan 01-04 to record the failure.py refactor delivery deviation
- **Scenario:** Review a documented implementation deviation from SUMMARY.md
- **Expected:** Human confirms whether this documented deviation is acceptable for this phase.
- **Result:** pass
- **Disposition:** accepted-process-exception

### P01-T01: Self-tamper hardening confirmation

- **Plan:** 01-01, protected.py path classification hardening
- **Scenario:** No UI surface. Confirm you are comfortable with the hardened self-tamper behavior. Plugin cache paths are no longer exempt, symlinks to protected paths are now caught, and rm -rf on ~/.claude or ~/.codex is blocked.
- **Expected:** Behavior matches your intent for how the watcher should protect itself.
- **Result:** pass

### P02-T01: Fail-closed hook confirmation

- **Plan:** 01-02, Fail-closed malformed-payload handling
- **Scenario:** No UI surface. Confirm you are comfortable that a malformed hook payload now denies the tool call instead of silently allowing it, across Write, Bash, git commit, and MCP hooks.
- **Expected:** Behavior matches your intent for fail-closed hook handling.
- **Result:** pass

### P03-T01: Config first-creation confirmation

- **Plan:** 01-03, First-config-creation validation
- **Scenario:** No UI surface. Confirm you are comfortable that creating a new .agent-discipline.json that disables every rule family or redirects state/ledger roots is now blocked, while a normal single-family config still creates cleanly.
- **Expected:** Behavior matches your intent for config bootstrap safety.
- **Result:** pass

### P04-T01: Renderer sanitization confirmation

- **Plan:** 01-04, Renderer output sanitization and payloads type-check simplification
- **Scenario:** No UI surface. Confirm you are comfortable that hook output rendered from scanned file content can no longer inject ANSI control sequences or fabricate Markdown headings or fences.
- **Expected:** Behavior matches your intent for hook output safety.
- **Result:**
