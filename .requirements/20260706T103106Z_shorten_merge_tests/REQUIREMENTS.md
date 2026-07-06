# Shorten Merge Config Tests

## As Is

`hooks/test_merge_configs.py` has a long Claude merge test function. Agent Discipline Watcher blocks the Stop hook with `clean_code/function_too_long`.

## To Be

The merge config tests keep the same behavior but move large fixtures, command execution, and repeated assertions into focused helper functions.

## Requirements

1. Preserve existing merge test coverage.
2. Shorten long test functions by extracting helpers.
3. Keep the test file simple and standard-library only.

## Acceptance Criteria

1. `python3 hooks/test_merge_configs.py` passes.
2. Agent Discipline Watcher no longer reports forced findings for `hooks/test_merge_configs.py`.
3. No production hook behavior changes.

## Testing Plan

1. Run the focused merge test file.
2. Run the scanner against the refactored test file.

## Implementation Plan

1. Extract fixture builders and merge runners from test functions.
2. Extract assertion helpers for Claude, Codex, and Pi merge outcomes.
3. Run focused tests and scanner verification.
