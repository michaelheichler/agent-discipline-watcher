---
name: block-discipline-bypass
enabled: true
event: bash
action: block
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: (?:CLEANCODER_FUNC_BLOCK_LINES|CLEANCODER_FILE_BLOCK_LINES|ADW_MAX_SCAN_BYTES)\s*=|rm\s+[^\n]*\.agent-discipline
---

**Blocked: raising a cap or deleting watcher state to clear a finding.**

Two moves land here:

1. Setting `CLEANCODER_FUNC_BLOCK_LINES`, `CLEANCODER_FILE_BLOCK_LINES`, or `ADW_MAX_SCAN_BYTES` on a command line. These override the length and size caps read by `hooks/lib/scanner.py`. Raising a cap hides the finding without fixing the shape.
2. Removing `.agent-discipline.json` or the state under `~/.agent-discipline`. That drops project config and session state that the gates depend on.

Defaults for reference: function cap 80 lines, file cap 1000 lines, scan cap 1000000 bytes.

Do the work instead. Extract helpers until each function does one thing, or split the file into focused modules.

If a cap needs a permanent change, put it in `.agent-discipline.json` as an explicit, reviewed decision and say why.
