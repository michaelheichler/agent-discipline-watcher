# Precommit Command Parsing

## As Is

`hooks/pre_commit.py` detects `git commit` by scanning all shell tokens. That treats `echo git commit` as a commit. It also recognizes `git -C repo commit` but scans the payload cwd instead of the repo passed with `-C`. The hook also reads working-tree files instead of staged blobs and can miss staged files when the payload cwd is a repo subdirectory.

## To Be

The PreCommit hook only scans actual command segments. It scans staged blob contents from the correct repo root for direct `git commit`, `git -C repo commit`, and `cd repo && git commit`.

## Requirements

1. Non-command text such as `echo git commit` must allow.
2. `git commit -m x` must scan the payload cwd.
3. `git -C dirty-repo commit -m x` must scan `dirty-repo`.
4. `cd dirty-repo && git commit -m x` must scan `dirty-repo`.
5. Preserve the existing compact report schema.
6. Scan staged blob content, not working-tree content.
7. Resolve repo root before joining staged repo-relative paths.
8. Exempt standard license, copyright, shebang, and encoding header runs from the clean-code comment-block rule.
9. Detect actual commit commands after common separators, simple pipelines, `command`, and `env` wrappers.
10. Collect and scan every actual commit cwd in a shell command, not just the first one.
11. Treat `SPDX-FileCopyrightText:` as a standard header.

## Acceptance Criteria

1. Hook tests show `echo git commit` returns `{}` even when the cwd has staged forced findings.
2. Hook tests show `git -C dirty-repo commit -m x` blocks findings staged in `dirty-repo`.
3. Hook tests show `cd dirty-repo && git commit -m x` blocks findings staged in `dirty-repo`.
4. Hook tests show bad staged content blocks even if the worktree is later clean.
5. Hook tests show clean staged content allows even if the worktree is later dirty.
6. Hook tests show payload cwd under a repo subdirectory still scans staged repo-root paths.
7. Scanner tests show SPDX plus copyright headers are allowed while normal two-line narrative blocks still block.
8. Hook tests show pipeline, `command`, `env`, simple grouped subshell, and multi-commit command forms scan the intended repos.
9. Scanner tests show `SPDX-FileCopyrightText:` plus `SPDX-License-Identifier:` is allowed.
10. Existing direct commit and non-commit tests still pass.

## Testing Plan

- Extend `hooks/test_hooks.py` with reviewer repro cases.
- Extend `hooks/lib/test_scanner.py` with license-header and normal-block coverage.
- Run the requested hook, scanner, merge, config, compile, and shell syntax checks.

## Implementation Plan

1. Add failing tests for `echo git commit`, `git -C`, `cd && git commit`, staged blob reads, subdir cwd, wrappers, pipelines, grouping, multiple commits, and SPDX headers.
2. Replace the boolean parser with a command-segment parser that returns all repo cwds for actual commit segments.
3. Resolve repo root and scan staged blobs with existing scanner and compact report output.
4. Add a narrow header exemption to the prose comment block detector.
