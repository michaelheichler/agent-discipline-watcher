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

## Phase 4. Model providers
- [ ] 10. OMP internal model provider, split into wire contract plus two provider shapes
- [x] 11. Claude agent hook provider at haiku, nested CLI removed, `8bb4ba3` and `7bf4397`
- [x] 12. Open the OMP model picker to every authenticated model. `selectableModels` filtered to
      Anthropic Haiku, so the native catalogue could offer a model the picker then hid and the
      config layer then refused. Both filters are gone and only sanitising and a 256 cap remain.
- [x] 12b. The Luna worker deadline test is back, without the marker file it used to race. Five
      consecutive runs pass. The deadline assertion never flaked, only the marker did.

## Checkpoint
- [x] No host spawns a nested Claude CLI. Two spawn sites went, not one. The second one lived in
      `evals/measure_judge_stage.py`, and a source-level test fails if either returns.
- [ ] A local OMP model returns real judge verdicts
- [x] `judge_model.py` has no callers left once the CLI path goes. That module is gone, and the
      haiku-only config rule went with it, because it refused every model OMP offers.

## Phase 5. Surface verification
- [ ] 13. Verify one Claude runtime gates terminal, Desktop, and web

## Checkpoint
- [ ] Every runtime runs standalone from `~/.adw`
- [ ] All four runtimes produce identical rule output on one fixture

## Blocked on a decision
- [x] `plan-install-isolation-2026-08.md` finished rather than superseded. Both it and its todo
      sit in `tasks/done/` with no open item left.
- [x] The OMP transport question has an answer and was never open. OMP runs pure native through
      the model catalogue. No SDK, no CLI, no direct HTTP.

## Settled since this file opened
- [x] The shared core ships vendored per host, written by `hooks/build_runtime.py`

## Phase 6. Optional cleanup
- [x] 14a. The rendering cluster moved to `claude_presets.py`, and the status reading moved to
      `judge_status.py`. 997 lines down to 929, with 25 tests on the two new modules. The gate
      forced this. The file crossed `file_too_long` mid-change and refused every further edit
      until the split landed.
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
