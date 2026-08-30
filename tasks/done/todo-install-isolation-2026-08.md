# Todo: Isolated ADW Installation

Source plan: tasks/plan-install-isolation-2026-08.md.

## Phase 1: Contract
- [x] Define installed-root helper and copy semantics
- [x] Update runner resolution and installer path contracts
- [x] Checkpoint: tests describe checkout isolation

## Phase 2: Installers
- [x] Deploy copied ADW tree under `~/.adw/install`
- [x] Point clients and command links at installed copy
- [x] Keep direct OMP installation consistent
- [x] Checkpoint: moving checkout does not break install

## Phase 3: Documentation and Verification
- [x] Document checkout, install, runtime, and project policy roots
- [x] Run focused tests and shell checks
- [x] Verify local and workstation installation paths
- [x] Checkpoint: installed configuration has no checkout paths
