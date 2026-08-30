# Todo: OMP ADW Configuration and Harness Separation

Source plan: `tasks/plan-omp-adw-config-2026-08.md`.

## Phase 0  Worktree reconciliation

- [x] Task 1  Reconcile the current uncommitted host changes

### Checkpoint 0

- [x] The dirty patch has one clear purpose per file.
- [x] Startup tests match implemented behavior.
- [x] ADW contract text reaches OMP without premature truncation.

## Phase 1  Shared ADW configuration contract

- [x] Task 2  Add the policy descriptor and configuration bridge

### Checkpoint 1

- [x] The bridge reads the same project file and effective defaults as hook execution.
- [x] Bridge writes reject protected weakening and preserve unrelated keys.
- [x] Bridge tests cover absent, malformed, legacy, and populated project files.

## Phase 2  OMP configuration screen

- [x] Task 3  Implement the ADW policy editor overlay
- [x] Task 4  Register ADW configuration commands and live apply

### Checkpoint 2

- [x] `/adw configure` opens the ADW editor in an interactive OMP session.
- [x] Saving changes `.agent-discipline.json` and affects the next watcher call.
- [x] `/advisor configure` and `WATCHDOG.yml` behavior is unchanged.

## Phase 3  Host parity and hardening

- [x] Task 5  Close OMP lifecycle and payload parity gaps
- [x] Task 6  Add separation, parity, and user-flow coverage
- [x] Task 7  Update integration documentation and verification commands

### Checkpoint 3

- [x] OMP reaches every equivalent ADW gate without weakening block behavior.
- [x] The ADW screen and the OMP advisor screen edit different files and runtimes.
- [x] Focused tests, the full suite, focused lint, shell checks, and Bun tests pass. Full lint reports two pre-existing import-order warnings.

## Standing constraints

- Keep the current open settings override plan intact.
- Do not use OMP's advisor runtime or `WATCHDOG.yml` for ADW policy.
- Keep Python policy resolution authoritative.
- Do not weaken always-blocking rules or make state and ledger roots editable.
- `ADW_ALLOW_PROTECTED_EDIT` never authorizes configuration-screen writes.
- Validate PostToolUse scan targets against trusted roots before reading files.
- Sanitize all policy and watcher-derived text before TUI or message delivery.
- Do not commit until the user requests a commit.
