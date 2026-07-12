# As Is

The global agent-discipline-watcher embeds the former Professional Agent Helper persona in SessionStart and UserPromptSubmit. Removing the standalone PAH hook and repository does not stop those injections.

# To Be

The watcher keeps ledger cleanup and its PreToolUse, PreCommit, PostToolUse, and Stop enforcement. It does not inject PAH text at session start or on user prompts, and its installers do not configure UserPromptSubmit.

# Requirements

1. SessionStart must clear the watcher ledger and emit only the compact discipline reminder.
2. The watcher must not route or install UserPromptSubmit.
3. Active Mac and Tux configurations must contain no watcher UserPromptSubmit hook.
4. Canonical Claude configuration must contain no PAH hook.

# Acceptance Criteria

1. SessionStart output contains the compact watcher reminder and no PAH text.
2. `run.sh UserPromptSubmit` is unsupported, and installer output omits that event.
3. Fresh Codex rollouts on both machines contain no PAH developer injection.
4. Repository and live configuration searches find no active PAH hook commands.

# Testing Plan

1. Update hook tests to reject PAH content and require the compact SessionStart message.
2. Update merge tests to assert UserPromptSubmit is not installed.
3. Run the watcher test suite.
4. Run fresh Codex sessions on Mac and Tux and inspect their new rollout files.
5. Initialize Linkup and Library MCP over authenticated HTTP and run Codex Doctor.

# Implementation Plan

1. Change tests to describe the PAH-free behavior and confirm they fail.
2. Remove persona use and UserPromptSubmit routing from the watcher.
3. Remove UserPromptSubmit from installer snippets and live configuration.
4. Synchronize the focused watcher changes to Tux.
5. Run unit, configuration, and fresh-session verification.
