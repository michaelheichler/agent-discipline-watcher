---
name: block-live-client-config-via-shell
enabled: true
event: bash
action: block
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: (?:\$HOME|~|/(?:Users|home)/[^/]+)/(?:\.claude/(?:settings|skills)|\.codex/config|\.codex/hooks|\.pi/agent/settings|\.agents/skills|\.config/opencode/|\.local/bin/agent-discipline)
  - field: command
    operator: regex_match
    pattern: (?:(?<![2>])>|\btee\b|\bsed\s+-i|\b(?:cp|mv|ln|rm|truncate|chmod|dd)\b)
---

**Blocked: shell command that mutates a live client install.**

The file gate covers Write, Edit, and MultiEdit. A redirect, `tee`, `sed -i`, `cp`, `mv`, `ln`, `rm`, or `dd` reaches the same path through Bash, so it is gated here too.

Reading is allowed. Use `cat`, `grep`, `python3 -m json.tool`, or `git diff` to inspect a live file. Stderr handling does not count as a mutation, so `2>/dev/null`, `2>>log`, and `2>&1` all pass. A real write redirect in the same command still blocks.

To change what gets installed, edit the repo source and prove the merge against a sandbox HOME:

```
HOME="$(mktemp -d)" ./install.sh -y
```

A real reinstall is a user decision. Ask first.

Backing a live file up with `cp` also lands here. Do the backup outside the agent session, or disable this rule for that step.
