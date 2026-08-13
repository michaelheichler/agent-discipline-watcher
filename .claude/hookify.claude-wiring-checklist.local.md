---
name: warn-claude-wiring-change
enabled: true
event: file
action: warn
tool_matcher: Write|Edit|MultiEdit
conditions:
  - field: file_path
    operator: regex_match
    pattern: hooks/(?:claude-settings\.snippet\.json|run\.sh|merge-claude-settings\.py)
---

**Claude wiring change. Four things must stay in step.**

1. Every event key in `hooks/claude-settings.snippet.json` needs a matching pair in the `DISPATCH` string in `hooks/run.sh`. An unlisted event makes `run.sh` print usage and exit 2, which Claude Code reports as a hook error on every matching tool call.
2. Update the active Claude and Codex integration notes in `README.md` when the event routes change.
3. Prove the merged config against a sandbox HOME before any live install. An unknown event key can break client config parsing rather than no-op.
4. Run the merge tests and the full suite:

```
cd hooks && python3 -m pytest . lib -q
bash -n install.sh hooks/run.sh
```

`~/.claude/settings.json` on this machine already runs `hooks/run.sh` from this working tree. A syntax error in `run.sh` or in a dispatched module breaks Write, Edit, and Bash gating in every live Claude Code session until it is fixed.
