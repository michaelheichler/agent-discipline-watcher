# Todo: ADW settings.json override + hook ejection fix + worktree cleanup

## Phase 1: Settings.json override message
- [x] Task 1: Update `LIVE_ACTION` in `hooks/lib/protected.py` to name `ADW_ALLOW_PROTECTED_EDIT`
- [x] Task 2: Add/extend a test asserting the `live_client_surface` action text names the env var

### Checkpoint
- [x] Focused pytest passes (`protected` / `self_protection`)
- [x] Full suite clean (1055 passed, 213 subtests). pylint not available in this environment,
      not run.

## Phase 1b: Comment-scanner Python string-masking bug (found mid-task, not in original scope)
- [x] Root cause found: `.py` files were never string-masked before comment scanning, so a
      string literal starting with `//`/`/*` after whitespace was misread as a real comment,
      and an unclosed `/*` (e.g. a glob fixture like `"generated/*"`) swallowed the rest of the
      file via `BLOCK_COMMENT_RE`'s `\Z` fallback.
- [x] Fix: `mask_python_strings` (tokenize-based) in `hooks/lib/markup.py`, wired through a new
      `comment_scan_source` dispatcher, called from `hooks/lib/scanner.py`.
- [x] Verified 3 ways: direct repro script, `pre_write._edit_findings`, `pre_write.run()`. Full
      suite green (1055 passed).
- [ ] Regression test in `hooks/lib/test_scanner.py` still blocked live: this session's live
      PreToolUse hook runs from the globally installed plugin cache, not this dev repo, so it's
      still running the pre-fix scanner and rejects any edit to that file (the `"generated/*"`
      landmine already corrupts the whole file under the old, unmasked scan). Needs the plugin
      cache refreshed from this commit before that test can land.

## Phase 2: Live verification of turn continuation (Problem 2: ejection)
- [x] Static review: no ejection path found in current hook source. `PreToolUse` uses
      `permissionDecision: deny` (always continues), `PostToolUse`/`PostToolBatch` never emit a
      raw `decision: block` (always `advise()`), `Stop`/`SubagentStop` use their native,
      non-ejecting block-until-resolved semantics. All confirmed against the official Claude
      Code hooks reference.
- [ ] Task 3: Refresh the installed plugin (you're handling this: `claude marketplace update
      <marketplace>` then `claude plugin install <plugin>`).
- [ ] Task 4: Live probe after refresh: one blocked write, one retry that resolves it, one
      Stop-hook forced continuation. Confirm none end the turn early.

### Checkpoint
- [ ] Live probe confirms block-then-continue
- [ ] Any surviving ejection written up as its own follow-up bug, not patched speculatively

## Phase 3: Repo cleanup
- [x] Task 5: Removed the 4 clean stale worktrees and branches: `audit-pre-autorewrite-matrix`,
      `review-strict-hardblock-final`, `test-pre-autorewrite-parity`,
      `fix-restore-pre-autorewrite-standard`
- [x] Discarded and removed `fix-strict-hardblock-contract` and `test-strict-hardblock-contract`
      too, per your decision after reviewing their diffs (duplicated main's already-shipped fix
      via a different, conflicting implementation)

## Phase 4: Review
- [ ] Task 6: `Workflow` run of `/code-review-and-quality` over the committed diff (Opus 5,
      medium effort broad review + Sonnet 5, high effort checkups). Apply confirmed findings

## Complete
- [ ] All acceptance criteria met, suite green, review findings resolved or deferred with reason
