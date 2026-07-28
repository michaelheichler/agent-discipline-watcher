---
name: block-discipline-bypass
enabled: true
event: bash
action: block
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: (?:ADW_FUNC_BLOCK_LINES|ADW_FILE_BLOCK_LINES|CLEANCODER_FUNC_BLOCK_LINES|CLEANCODER_FILE_BLOCK_LINES|ADW_MAX_SCAN_BYTES|ADW_ALLOW_PROTECTED_EDIT)\s*=|\b(?:rm|unlink|shred)\b[^\n]*?(?:\.agent-discipline\b|agent-discipline/(?:state|ledger))
---

**Blocked: raising a cap or deleting watcher state to clear a finding.**

Two moves land here:

1. Setting `ADW_FUNC_BLOCK_LINES`, `ADW_FILE_BLOCK_LINES`, `ADW_MAX_SCAN_BYTES`, or `ADW_ALLOW_PROTECTED_EDIT` on a command line, or their accepted `CLEANCODER_` aliases. These override the length and size caps read by `hooks/lib/scanner.py`, or grant the protected-path escape. Raising a cap hides the finding without fixing the shape.
2. Removing `.agent-discipline.json` or the state under `~/.agent-discipline` with `rm`, `unlink`, or `shred`. That drops project config and session state that the gates depend on.

Defaults for reference: function cap 80 lines, file cap 1000 lines, scan cap 1000000 bytes.

Do the work instead. Extract helpers until each function does one thing, or split the file into focused modules.

If a cap needs a permanent change, put it in `.agent-discipline.json` as an explicit, reviewed decision and say why.
