# Precommit And Rule Floor

## As Is

The combined watcher scans writes and records edited files, but it has no Bash `git commit` guard. The source scanner has only part of the old deterministic clean-code, punctuation, and English floors. Claude and Codex snippets do not include a Bash PreToolUse group for commit checks.

## To Be

The combined watcher keeps the one-skill design and restores the missing deterministic checks. Bash commands that are not `git commit` allow. Bash `git commit` scans staged ACM files in the hook working directory and blocks forced findings with file, line, family, rule, and action. Claude and Codex snippets keep write scanning and add the Bash commit guard.

## Requirements

1. Add a combined PreCommit hook route for Bash `git commit` commands.
2. Scan staged files with `git diff --cached --name-only --diff-filter=ACM` and `scan_all`.
3. Restore deterministic clean-code floors for task markers, change-history comments, multi-line Python docstrings, size limits, and hollow tests.
4. Restore deterministic punctuation floors for spaced hyphens, `its'`, comma splice advisory, quote punctuation advisory, and prose sanitizing.
5. Restore deterministic English floors for filler openers, expletive there, and prose sanitizing.
6. Update Claude and Codex snippets and merge tests for the Bash group.

## Acceptance Criteria

1. Non-commit Bash commands return allow.
2. Staged `git commit` with forced scanner findings returns block.
3. Block rows include file, line, family, rule, and action.
4. Clean-code tests cover each restored deterministic rule and docs or config exemptions.
5. Punctuation tests cover each restored deterministic rule and code or markup sanitizing.
6. English tests cover each restored deterministic rule and code or quote sanitizing.
7. Merge tests prove write matchers remain and Bash PreToolUse is present.

## Testing Plan

- Extend scanner tests for deterministic rule coverage.
- Extend hook tests for PreCommit allow and block behavior.
- Extend merge tests for Claude and Codex Bash matcher groups.
- Run the requested focused checks, compile check, and shell syntax check.

## Implementation Plan

1. Add failing tests for PreCommit, scanner rules, and merge matcher parity.
2. Add `hooks/pre_commit.py` and route `PreCommit` in `hooks/run.sh`.
3. Add the scanner rules in `hooks/lib/scanner.py`.
4. Add Bash matcher groups to Claude and Codex snippets.
5. Run all requested commands and any added test file.
