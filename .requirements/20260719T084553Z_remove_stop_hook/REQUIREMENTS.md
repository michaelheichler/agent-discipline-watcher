# Remove Stop Hook

## As Is

The watcher blocks direct write slop in PreToolUse and blocks remaining forced findings in PostToolUse. It also retains a Stop hook, a file ledger, and a Pi agent-end fallback.

## To Be

Only write-time regex enforcement remains. PreToolUse prevents known slop before a write. PostToolUse immediately blocks forced findings visible after a write. No watcher Stop or Pi agent-end callback is registered. A Stop callback cached by an already-running client exits silently without scanning.

## Requirements

1. Remove watcher Stop registrations from Claude and Codex while preserving unrelated Stop hooks.
2. Remove the Stop scanner, ledger, and Pi agent-end fallback while silently ignoring stale Stop calls.
3. Keep immediate forced-finding blocks in PostToolUse and Pi tool results.
4. Keep installation idempotent across Claude, Codex, and Pi.

## Acceptance Criteria

1. Reinstalling removes stale watcher Stop commands and leaves unrelated Stop commands unchanged.
2. The runtime contains no Stop scanner, gate, ledger, or Pi agent-end handler, and a stale Stop call exits successfully without output.
3. Forced punctuation still makes PostToolUse exit 2 and Pi return an error result.
4. Two installs produce one watcher registration per remaining lifecycle.

## Testing Plan

- Change config merge and runtime contract tests first and prove they fail.
- Run focused tests after the smallest implementation change.
- Run the complete suite, syntax checks, two installs, and live config audits on both machines.

## Implementation Plan

1. Update tests to require no watcher Stop or agent-end path.
2. Delete Stop and ledger code, then simplify PostToolUse and Pi.
3. Remove Stop snippets and documentation.
4. Verify and install on both machines.
