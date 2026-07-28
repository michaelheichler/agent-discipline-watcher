---
name: block-no-verify-commit
enabled: true
event: bash
action: block
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: git\s+commit\b[^\n]*(?:--no-verify|\s-n(?:\s|$))
---

**Blocked: commit that skips the commit gates.**

This repo ships a PreCommit route that scans staged files and blocks forced findings. Passing `--no-verify` or `-n` walks past it and lands the finding in history.

Fix the reported file, stage it, and commit again. If the finding looks wrong, read the scanner rule and the exact snippet before deciding the hook failed.

Note that `-n` on `git commit` means no-verify, while on `git log` and `git tag` it means a count. This rule only matches `git commit`.
