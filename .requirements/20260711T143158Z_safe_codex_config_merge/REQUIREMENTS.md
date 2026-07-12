# Safe Codex Config Merge

## As Is

The current merger preserves unrelated trailing TOML tables, including MCP servers, projects, and TUI state. It validates the merged TOML, then writes directly to the live config. It does not independently reject unexpected loss of unrelated top-level sections and does not replace the file atomically. An obsolete workstation copy predating the preservation fix remains runnable and has repeatedly removed unrelated configuration.

## To Be

The authoritative merger must preserve all unrelated top-level configuration, reject a merge that loses unrelated sections, and replace the live file atomically. The obsolete workstation tree must be removed. The workstation must receive a platform-specific configuration based on the clean Mac structure, with verified Linux paths and no global Agentic Love or marketplace plugin hooks.

## Requirements

1. Preserve unrelated top-level TOML sections during watcher installation.
2. Abort before replacing the live config if an unrelated top-level section disappears.
3. Write a validated merge to a temporary sibling file and atomically replace the destination.
4. Preserve the destination file mode when it already exists and use mode `0600` for a new config.
5. Back up the workstation config before synchronization.
6. Remove the obsolete workstation watcher tree at `/home/user/Development/skills/agent-discipline-watcher`.
7. Install platform-specific Mac and Arch Linux configs with the same global watcher and knowledge-search hook policy.
8. Register marketplaces on both systems without enabling marketplace plugin hooks.

## Acceptance Criteria

1. Existing Tux regression fixtures retain MCP, project, TUI, marketplace, plugin, and custom sections.
2. A synthetic destructive transform raises an error and leaves the original file unchanged.
3. Tests verify that replacement uses a sibling temporary file and leaves no temporary artifact.
4. Existing mode `0600` remains `0600`, and a newly created config is `0600`.
5. A timestamped workstation backup exists and parses as TOML.
6. The obsolete workstation tree no longer exists, while the authoritative skill symlink resolves correctly.
7. `codex --strict-config doctor` loads both configs, and every hook command resolves on its host.
8. Marketplace tables exist on both hosts, while no marketplace plugin is enabled and no marketplace hook is loaded from config.

## Testing Plan

- Extend the merger unit suite with destructive-section-loss, atomic replacement, and file-mode cases.
- Run the new tests before implementation and confirm they fail for the missing safeguards.
- Implement one safeguard at a time and rerun the focused suite after each change.
- Run the full watcher test suite.
- Parse both final configs with TOML and run strict Codex Doctor.
- Inventory MCP definitions, hook commands, marketplace tables, and path existence on both systems.

## Implementation Plan

1. Add tests for section-loss rejection and unchanged destination. Run them and confirm failure.
2. Add tests for atomic replacement and file modes. Run them and confirm failure.
3. Add an unrelated-section guard. Run the focused tests.
4. Add atomic replacement with mode preservation. Run the focused and full suites.
5. Copy only the hardened merger and tests to the workstation authoritative repository, then rerun its suite.
6. Back up the workstation config and delete the obsolete watcher tree.
7. Generate each host config from an explicit host template and verified paths, then install with atomic replacement.
8. Run end-to-end validation and compare the resulting policies.
