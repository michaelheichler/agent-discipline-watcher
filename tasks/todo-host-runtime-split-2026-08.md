# Todo for the Per-Host Runtime Split

**Superseded on 2026-08-30 by `spec-host-runtime-split-2026-08.md`.** Only Phase 6 below stays
live. Research overturned the three-runtime count, so a fresh breakdown follows the spec.

Desktop does share the Claude runtime, which this file got right. Cowork does not, which it
missed.

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

## Phase 4. Model providers
- [ ] 10. OMP internal model provider, split into wire contract plus two provider shapes
- [ ] 11. Claude agent hook provider at haiku, nested CLI removed
- [ ] 12. Open the OMP model picker to every authenticated model

## Checkpoint
- [ ] No host spawns a nested Claude CLI
- [ ] A local OMP model returns real judge verdicts

## Phase 5. Surface verification
- [ ] 13. Verify one Claude runtime gates terminal, Desktop, and web

## Checkpoint
- [ ] Every runtime runs standalone from `~/.adw`
- [ ] All three runtimes produce identical rule output on one fixture

## Blocked on a decision
- [ ] Close `plan-install-isolation-2026-08.md` as superseded, or finish it first
- [ ] Choose whether the shared core ships per host install or once for all hosts
- [ ] Choose direct HTTP in the OMP provider, or an upstream request for a host-side inference API

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
