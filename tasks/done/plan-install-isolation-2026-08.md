# Implementation Plan: Isolated ADW Installation

## Overview
Install ADW into a user-owned path under `~/.adw/install` instead of wiring clients directly to the checkout. Client configuration and stable compatibility links must reference the isolated installation copy, so moving or deleting a development checkout cannot alter an installed deployment.

## Architecture Decisions
- Use `~/.adw/install/agent-discipline-watcher` as the default installed code root.
- Copy the checkout into a staging directory and replace the managed install directory, rather than symlinking it to the checkout.
- Keep `~/.adw/state`, reports, caches, and runtimes separate from installed code.
- Keep `AGENT_DISCIPLINE_WATCHER_HOME` as an explicit override for tests and advanced installations.
- Make both the combined installer and direct OMP installer write only installed-root paths into client configuration.

## Task List
### Phase 1: Contract
- [ ] Define the installed-root helper and copy semantics.
- [ ] Update runner resolution and installer path contracts.

### Checkpoint: Contract
- [ ] Tests describe checkout isolation and preserve existing client settings.

### Phase 2: Installers
- [ ] Deploy a copied ADW tree under `~/.adw/install`.
- [ ] Point OMP, Codex, Claude legacy, and local command links at the installed copy.
- [ ] Keep direct OMP installation consistent with the combined installer.

### Checkpoint: Installers
- [ ] A temporary checkout can be moved after install without breaking configured paths.

### Phase 3: Documentation and Verification
- [ ] Document the distinction between checkout, installed code, runtime data, and project policy.
- [ ] Run focused tests and shell checks.
- [ ] Verify local and workstation installation paths.

### Checkpoint: Complete
- [ ] No installed configuration points into a development checkout.
- [ ] OMP, Codex, and hook runner paths resolve from the isolated install root.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Copying stale files into the install | Medium | Replace a managed staging copy and exclude VCS, cache, and runtime directories. |
| Existing user-managed symlinks or directories | High | Refuse to overwrite foreign paths and preserve only installer-owned replacements. |
| Existing client settings contain checkout paths | High | Merge current settings against the installed root and test migration behavior. |

## Open Questions
- None. The default installed code root is `~/.adw/install/agent-discipline-watcher`.
