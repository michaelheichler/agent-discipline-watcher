# Todo for the Per-Host Runtime Split

**Live tracker.** `spec-host-runtime-split-2026-08.md` holds the requirements,
`plan-host-runtime-split-2026-08.md` holds the task detail, and
`decisions-host-split-2026-08.md` holds the settled decisions with their evidence.

Phases 1 to 3 shipped on 2026-08-30 in commit `53fed2c`, tagged `v0.20.11`. Suite at 2018
passing and 18 skipped, plus 60 passing Bun tests.

Desktop does share the Claude runtime, which this file got right from the start. Cowork does
not, which it missed until the research corrected the count to four.

## Phase 1. Contract, done 2026-08-30
- [x] 1. Runtime manifest and host identity, four hosts in `lib/host.py`
- [x] 2. Collector schema under `~/.adw`, tolerant of a partial tree
- [x] 3. Host model provider seam, no judge touches `subprocess`

## Checkpoint
- [x] Host identity resolves for all four, collector loads with runtimes absent, full suite green

## Phase 2. Packaging, done 2026-08-30
- [x] 4. Shared core that names no host, locked by `lib/test_core_boundary.py`
- [x] 5. Claude runtime, serving terminal, IDE, Desktop, and web
- [x] 6. Codex runtime, pinned to OpenAI models
- [x] 7. OMP runtime, plus the Cowork runtime the four-host roster added

## Checkpoint
- [x] Each runtime passes its own tests with the other three deleted, `test_runtime_isolation.py`
- [x] Fixture scan matches across all four runtimes and the source, `test_runtime_parity.py`

## Phase 3. Installers, done 2026-08-30
- [x] 8. Per-host installer entrypoints, plus the router and the picker
- [x] 9. Claude runtime ships through plugin `hooks/hooks.json`, no settings merge

## Checkpoint
- [x] A Claude install leaves no OMP or Codex file on disk
- [x] A moved checkout does not break an installed runtime
- [x] Choosing nothing touches no file

## The updater, done 2026-08-30
- [x] `hooks/claude_cache_nuke.py` clears the Claude plugin cache and never `~/.adw`
- [x] `commands/update.md` gives the agent and the user one runbook
- [x] A Claude install refreshes the plugin by default, `ADW_SKIP_PLUGIN=1` opts out

## Phase 4. Model providers, next
- [ ] 10. OMP internal model provider, split into wire contract plus two provider shapes
- [ ] 11. Claude agent hook provider at haiku, nested CLI removed
- [ ] 12. Open the OMP model picker to every authenticated model
- [ ] 12b. Settle the judge model question, and restore the deleted worker-deadline test

## Checkpoint
- [ ] No host spawns a nested Claude CLI
- [ ] A local OMP model returns real judge verdicts
- [ ] The recorded precision numbers match the model that actually reads

## Phase 5. Surface verification
- [ ] 13. Verify one Claude runtime gates terminal, Desktop, and web

## Checkpoint
- [ ] Every runtime runs standalone from `~/.adw`
- [ ] All four runtimes produce identical rule output on one fixture

## Blocked on a decision
- [ ] Close `plan-install-isolation-2026-08.md` as superseded, or finish it first
- [ ] Choose direct HTTP in the OMP provider, or an upstream request for a host-side inference API

## Settled since this file opened
- [x] The shared core ships vendored per host, written by `hooks/build_runtime.py`

## Phase 6. Optional cleanup
- [ ] 14a. Move the rendering and managed hook clusters out of `claude_native.py`, 173 measured
      lines from ranges 567 to 709 and 333 to 362. Lands near 819 lines. Pure functions, and a
      missed caller fails loudly.
- [ ] 14b. Move the transaction cluster only, 84 measured lines from range 249 to 332. Lands near
      735 lines and clears the 750 threshold.
- [ ] 14b needs a three-layer boundary first, because a plain import either way cycles. Layer zero
      is `claude_base.py` with `PRESETS`, `TRANSACTION_VERSION`, `CORRUPT_SUFFIX`, `_validate_preset`,
      and the path helpers, none of them patched. Layer one takes both `MAX_CORRUPT_*` bounds and the
      reader as arguments, because the reader stack runs through the patched `_leaf_lstat`. Layer two
      stays `claude_native.py`. Layer zero also unblocks 14a, which needs `_validate_preset`.
- [ ] Leave `_recover_unlocked` in `claude_native.py`. It calls the monkeypatched writes at 400,
      408, and 413, so a plain move would bind those names at import time and the patches would
      stop biting with no test failing.
- [ ] Keep the atomic write primitives and all six patch targets in `claude_native.py`. No wrappers.
