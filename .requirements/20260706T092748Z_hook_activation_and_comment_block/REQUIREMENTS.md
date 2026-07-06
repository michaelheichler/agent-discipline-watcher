# Hook Activation And Comment Block

## As Is

The combined PreToolUse scanner allows consecutive leading comment lines in code files because clean-code checks run one line at a time. The Claude hook snippet only matches `Write|Edit|MultiEdit`. The docs describe installation but do not clearly say Codex hook config changes may still need `/hooks` review and trust.

## To Be

The combined scanner force-blocks 2+ consecutive leading comment lines in code files while keeping single terse why comments allowed. The block guidance tells agents to move source narration to a wiki page, creating or updating one as needed. Claude config coverage includes the old write/edit matchers without adding duplicate lifecycle hooks. Codex docs and installer output distinguish global install from hook approval.

## Requirements

1. Detect 2+ consecutive leading comment lines in code files as a clean-code finding.
2. Exempt prose documentation and config formats from the comment-block rule.
3. Keep a single leading comment line allowed by this rule.
4. Make PreToolUse block the two-line comment write case.
5. Restore Claude matcher coverage for `NotebookEdit` and `apply_patch` while keeping one combined hook per lifecycle.
6. Update docs and install output so Codex install does not imply hook approval.

## Acceptance Criteria

1. `scan_all("sample.py", "# first line\n# second line\nprint(1)\n", {"punctuation": false, "english": false})` returns a forced clean-code finding whose rule is `prose_comment_block`.
2. The same text in `.md`, `.toml`, `.yaml`, or `.json` does not produce `prose_comment_block`.
3. `scan_all("sample.py", "# reset before enable\nreset()\n", ...)` does not produce `prose_comment_block`.
4. `pre_write.run` returns `{"decision":"block", ...}` for the reported two-line Python comment case and includes `clean_code/prose_comment_block` in the reason.
5. Merged Claude settings contain one watcher PreToolUse entry and one watcher PostToolUse entry, each with `NotebookEdit` and `apply_patch` in the matcher.
6. README, SKILL, and installer output say Codex hooks are installed globally but may require `/hooks` approval after hook command changes.

## Testing Plan

- Add scanner tests for code comment blocks, single comments, and doc/config exemptions.
- Add PreToolUse regression coverage for the reported two-line write.
- Add merge test assertions for the restored Claude matchers and single lifecycle entry.
- Run the requested focused and full verification commands.

## Implementation Plan

1. Add failing scanner and PreToolUse regression tests, then run focused tests.
2. Add a small whole-file clean-code pass in `hooks/lib/scanner.py` for consecutive leading comment lines in non-prose, non-config files.
3. Update `hooks/claude-settings.snippet.json` and merge assertions for the matcher union.
4. Update README, SKILL, and installer output with the Codex `/hooks` activation caveat.
5. Run all requested verification commands.
