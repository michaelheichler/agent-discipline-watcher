---
name: block-live-client-config-writes
enabled: true
event: file
action: block
tool_matcher: Write|Edit|MultiEdit
conditions:
  - field: file_path
    operator: regex_match
    pattern: (?:/(?:Users|home)/[^/]+|~)/(?:\.claude/(?:settings[\w.]*\.json|skills/|agents/|hooks/|commands/|CLAUDE\.md)|\.codex/|\.pi/|\.agents/|\.local/bin/|\.config/opencode/)
---

**Blocked: write to an installed client surface.**

That path is a live client install, not repo source. On this machine `~/.claude/settings.json` already points every Claude Code session at this working tree, so an edit there can break sessions outside this repo, and the next `install.sh` run overwrites it anyway.

Change the repo source instead:

| Live path | Repo source |
| --- | --- |
| `~/.claude/settings.json` | `hooks/claude-settings.snippet.json` and `hooks/merge-claude-settings.py` |
| `~/.codex/config.toml` | `hooks/codex-config.snippet.toml` and `hooks/merge-codex-config.py` |
| `~/.pi/agent/settings.json` | `hooks/merge-pi-settings.py` |
| `~/.config/opencode/plugins/agent-discipline-watcher.ts` | `opencode/agent-discipline-watcher.ts` |
| `~/.local/bin/agent-discipline` | `bin/agent-discipline` |

Prove the merged result against a sandbox HOME, then install.

Scratch and memory paths such as `~/.claude/jobs/` and `~/.claude/projects/` are not client config, so they pass.

Disable this rule only when the task is repairing a broken live install.
