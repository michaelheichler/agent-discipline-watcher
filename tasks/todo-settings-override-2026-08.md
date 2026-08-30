# Todo for the settings override, hook ejection, and worktree cleanup

Plan lives in [plan-settings-override-2026-08.md](plan-settings-override-2026-08.md). Status
verified on 2026-08-30 against the source, because the plan file boxes were never ticked.

## Phase 1. Settings override message

- [x] Task 1. `LIVE_ACTION` in `hooks/lib/protected.py` names `ADW_ALLOW_PROTECTED_EDIT`.
      Confirmed at `protected.py:21`, `AUTH_ENV = "ADW_ALLOW_PROTECTED_EDIT"`.
- [x] Task 2. A test asserts the `live_client_surface` action text names the env var.
- [x] Checkpoint. Focused pytest passes and the full suite runs clean.

## Phase 1b. Python string masking in the comment scanner

Found mid-task, outside the original scope.

- [x] Root cause. `.py` files reached the comment scan unmasked, so a string literal opening
      with a slash pair read as a real comment. An unclosed block opener then swallowed the
      rest of the file through the regex fallback.
- [x] Fix. `mask_python_strings` in `hooks/lib/markup.py`, dispatched through
      `comment_scan_source` and called from `hooks/lib/scanner.py:263`.
- [x] Regression test landed. `test_scanner.py:5` imports `mask_python_strings`, line 391
      tests it, and the `"generated/*"` fixture sits at lines 290 and 521 without corrupting
      the file.

## Phase 2. Turn continuation after a block

- [x] Static review found no ejection path. `PreToolUse` denies through `permissionDecision`,
      which always continues. `PostToolUse` and `PostToolBatch` advise rather than block.
      `Stop` and `SubagentStop` use their native block-until-resolved semantics.
- [x] Task 3. Plugin refreshed from the marketplace.
- [x] Task 4. Live probe run. One blocked write, one retry that resolved it, and one forced
      Stop continuation. None ended the turn early.
- [x] Checkpoint. Live probe confirms block then continue.

## Phase 3. Repo cleanup

- [x] Task 5. Removed four clean stale worktrees and their branches, named
      `audit-pre-autorewrite-matrix`, `review-strict-hardblock-final`,
      `test-pre-autorewrite-parity`, and `fix-restore-pre-autorewrite-standard`.
- [x] Discarded `fix-strict-hardblock-contract` and `test-strict-hardblock-contract` as well,
      because both duplicated a fix already on main through a conflicting implementation.

## Phase 4. Review

- [ ] Task 6. Run `/code-review-and-quality` over the committed diff. This is the one item
      still open, and it stays optional until the host runtime split lands, because that work
      rewrites the same files.

## Notes

A separate weakening audit on 2026-08-30 covered this window and found nothing wrong in these
changes. Its two live findings sit in `spec-host-runtime-split-2026-08.md` under Further Notes.
