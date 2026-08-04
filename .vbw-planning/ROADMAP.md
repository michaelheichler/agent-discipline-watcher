# agent-discipline-watcher Roadmap

**Goal:** agent-discipline-watcher

**Scope:** 5 phases

## Progress
| Phase | Status | Plans | Tasks | Commits |
|-------|--------|-------|-------|---------|
| 1 | Pending | 0 | 0 | 0 |
| 2 | Pending | 0 | 0 | 0 |
| 3 | Pending | 0 | 0 | 0 |
| 4 | Pending | 0 | 0 | 0 |
| 5 | Pending | 0 | 0 | 0 |

---

## Phase List
- [ ] [Phase 1: Self-Tamper & Fail-Open Hardening](#phase-1-self-tamper-fail-open-hardening)
- [ ] [Phase 2: Scanning & Escalation Correctness](#phase-2-scanning-escalation-correctness)
- [ ] [Phase 3: State, Reporting & Ledger Integrity](#phase-3-state-reporting-ledger-integrity)
- [ ] [Phase 4: Hook Entry Script Correctness](#phase-4-hook-entry-script-correctness)
- [ ] [Phase 5: CLI & Install-Time Config Merge Safety](#phase-5-cli-install-time-config-merge-safety)

---

## Phase 1: Self-Tamper & Fail-Open Hardening

**Goal:** Close both Critical bypasses in protected.py and make every PreToolUse hook fail closed on malformed input, restoring the watcher's core self-protection guarantee.

**Requirements:** REQ-01

**Success Criteria:**
- path_findings() flags a Write to the live plugin-cache path (protected.py plugin-root exemption removed)
- protected.py resolves symlinks and collapses .. before comparing against protected targets
- hookio.py distinguishes a JSON parse failure from an empty object, and pre_write.py, pre_bash.py, pre_commit.py, pre_mcp.py all deny on that distinct failure
- First-config-creation rejects a payload that disables every rule family or redirects state/ledger roots
- rm -rf on a protected root directory (~/.claude, ~/.codex) is classified
- render.py escapes control characters and Markdown syntax in rendered paths and excerpts
- payloads.py type-check helper simplified to type(value) is T

**Dependencies:** None

---

## Phase 2: Scanning & Escalation Correctness

**Goal:** Fix the config-merge, cache, and visibility bugs in the scanner and Haiku escalation path so rule gates and escalation verdicts behave as documented.

**Requirements:** REQ-02

**Success Criteria:**
- rule_gates config override merges by key, a partial override no longer resets unrelated defaults
- Kill-switch config path requires an exact boolean True to disable a rule family
- Escalation cache key includes model and prompt version, a config change invalidates stale cache entries
- Escalation budget is shared per hook invocation (not reset per scan_all call), bounding worst-case API stalls
- Escalation failure (missing key, bad response, cache or network error) emits one bounded diagnostic instead of failing silently
- Escalation prompt isolates the candidate comment as data and includes scope context
- markup.py no longer treats escaped currency notation as a math delimiter
- A new test_escalate.py exists covering the escalation module directly, and the README documents the ANTHROPIC_API_KEY requirement

**Dependencies:** Phase 1

---

## Phase 3: State, Reporting & Ledger Integrity

**Goal:** Fix the baseline, commit-review, ledger, and adjudication bugs that let real violations go unreported or falsely report success.

**Requirements:** REQ-03

**Success Criteria:**
- Baseline subtraction only credits a removed instance to a new finding on the same changed line or hunk, not any same-family match
- Commit review handles non-ASCII git patch headers and propagates a git show failure instead of treating it as no findings
- False-signal rate denominator is keyed on (session_id, turn_id), not turn_id alone
- A crashed or partial ledger append cannot poison the next row, and a malformed row is surfaced, not silently skipped
- bin/agent-discipline adjudicate returns a failure exit code when the ledger write fails, instead of printing success
- Ledger and adjudication storage default to private file modes (0600 files, 0700 directories)
- session_state.py cleanup either coordinates through the same lock inode or is deleted (no production callers found)
- Baseline diff no longer runs an O(n squared) comparison on large unchanged files

**Dependencies:** Phase 2

---

## Phase 4: Hook Entry Script Correctness

**Goal:** Fix the per-event bugs in the twelve hook entry scripts that let protected paths, wrong-repo commits, and installer scope leak through, and correct session turn tracking.

**Requirements:** REQ-04

**Success Criteria:**
- An apply-patch delete of a protected path is checked and blocked, not silently skipped
- pre_commit.py's cd parsing determines the real commit cwd or denies when it cannot, instead of scanning a cwd the shell never used
- A HOME= reassignment's shell scope is tracked per segment, not applied globally to every installer check
- record.py's success and backoff clearing is wired for all PostToolUse events, not only write tools
- The first user turn has a valid turn ID from SessionStart, and Stop's heartbeat stamps the turn that just completed
- PostToolBatch reads a bounded per-turn index instead of rescanning the entire lifetime ledger
- Shared logic currently imported from failure.py's private symbols is promoted into hooks/lib/

**Dependencies:** Phase 3

---

## Phase 5: CLI & Install-Time Config Merge Safety

**Goal:** Fix the install-time settings mergers and CLI validation gaps that can silently corrupt a user's host config or the false-signal rate.

**Requirements:** REQ-05

**Success Criteria:**
- merge-claude-settings.py's legacy-pruning is scoped to actual hook lifecycle entries, verified against a reproduction that previously deleted an unrelated setting
- merge-codex-config.py's TOML inline-table handling either refuses unsupported shapes or uses a parser-aware transform, verified against the nested-inline-table reproduction
- skill_dir is shell-quoted before interpolation in both installer templates
- merge-claude-settings.py and merge-pi-settings.py share Codex's atomic, mode-preserving write helper
- --false-signal validates the referenced ledger row and stores one effective verdict per (family, ref_ts)
- bin/agent-discipline and bin/adw-cli share one review-argument parser instead of two that can drift
- All changes verified against the existing 66-test CLI/dispatch suite plus new regression tests for each fix

**Dependencies:** Phase 4

