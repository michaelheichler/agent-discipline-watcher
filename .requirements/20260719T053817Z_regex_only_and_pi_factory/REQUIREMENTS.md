# As Is

The shared Stop hook imports `model_jury.py`. The shell launcher prefers Python environments from `skill-model-loader` and Clean Coder. Pi auto-loads `team-runner-prompts.ts`, but that helper has no default extension factory.

# To Be

All Agent Discipline Watcher clients use only the shared regex scanner. The hook runtime has no model-loader path. Pi can load every installed TypeScript extension without rejecting the team-runner helper. Source changes reach the Mac and the x86_64 `x86-host` workstation through Git push and pull.

# Requirements

1. Remove model-backed jury execution and model-loader interpreter selection from the watcher.
2. Preserve deterministic regex scanning for Codex, Claude, and Pi.
3. Make `team-runner-prompts.ts` a valid Pi extension module without changing its helper behavior.
4. Synchronize both architectures through Git, without `rsync`.
5. Keep one Agent Discipline Watcher registration per lifecycle event or extension in every configured coding client on both machines.

# Acceptance Criteria

1. `gate.py` has no model-jury import or call, `run.sh` selects `python3`, and watcher runtime sources contain no model-loader integration.
2. Existing scanner, hook, merge, and Pi contract tests pass, including a Stop rescan regression.
3. The team-runner helper exports a default factory, its Bun tests pass, and Pi starts without the reported extension error.
4. Changes are committed and pushed. The Mac and `x86-host` checkouts resolve to the pushed commits, installations are refreshed, and client-specific smoke checks pass on both architectures.
5. Live Codex, Claude, Pi, and other detected coding-client configs contain no duplicate watcher hooks or extensions. Unrelated registrations remain intact.

# Testing Plan

1. Add source-contract tests that fail while the jury import and loader selection remain.
2. Add a Pi factory-contract assertion that fails while `team-runner-prompts.ts` lacks a default export.
3. Run focused tests after each implementation change.
4. Run full watcher tests, Bun team-runner tests, syntax checks, self-scan, Pi startup smoke checks, and remote equivalents.
5. Count watcher registrations in every detected live coding-client config after installation and confirm each expected event or extension appears once.

# Implementation Plan

1. Replace jury-specific tests with a regex-only Stop contract, then remove the shared jury call and model module. Run the focused Python tests.
2. Simplify `run.sh` to use `python3` and align documentation. Run hook, merge, and shell syntax tests.
3. Add a no-op default factory to the existing team-runner helper. Run its focused Bun suite and a Pi startup smoke check.
4. Commit and push each repository, pull on `x86-host`, reinstall through each repository's installer, and repeat architecture-specific smoke checks.
