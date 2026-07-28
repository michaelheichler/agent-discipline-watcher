---
name: block-unsandboxed-install
enabled: true
event: bash
action: block
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: (?:^|[;&|(]\s*|\b(?:python3?|sh|bash|zsh|dash|command|env|exec|sudo|nohup|time)\s+)(?:[\w./-]*/)?(?:install\.sh|merge-claude-settings\.py|merge-codex-config\.py|merge-pi-settings\.py)\b
  - field: command
    operator: not_contains
    pattern: HOME=
---

**Blocked: installer or merge script aimed at the real HOME.**

`install.sh` and the merge scripts rewrite `~/.claude/settings.json`, `~/.codex/config.toml`, and `~/.pi/agent/settings.json`. The README states the rule for this repo: an unknown event key can break client config parsing rather than no-op, so every new wiring proves the merged config in a sandbox HOME before any live install.

Run it against a throwaway HOME:

```
HOME="$(mktemp -d)" ./install.sh -y
HOME="$(mktemp -d)" python3 hooks/merge-claude-settings.py --help
```

Then read the merged file back and check the event keys, matchers, and command paths.

A command that sets `HOME=` passes this rule. Reinstalling for real is a user decision, so ask before doing it.

The pattern matches an installer only in command position, at the start of the command, after a shell separator, or after an interpreter. Naming the script in a string, a grep, or a syntax check such as `bash -n install.sh` does not trigger it.
