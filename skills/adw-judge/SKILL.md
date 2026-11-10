---
name: adw-judge
description: Select the Luna review preset for Claude Code or show its status.
disable-model-invocation: true
argument-hint: <luna|status>
---

Run the installed `adw-judge` executable exactly once with the one argument supplied after this skill name.

Use the normal Bash tool with the argument quoted as one value:

```sh
adw-judge "$ARGUMENTS"
```

The executable accepts only `luna` or `status`. Selecting `luna` replaces the managed settings block atomically, so settings hold one reviewer set. `status` reports the current setup without changing it.

The plugin ships no reviewer of its own. If settings hold no managed block, SessionStart writes the `luna` block. If settings hold a retired agent block or Sonnet handler, SessionStart replaces it with the `luna` block.

`luna` runs a command handler on PostToolUse and Stop through the Codex runtime, and ADW never calls headless Claude. When Luna is unavailable, the Stop shows one line, findings stay queued, and the review pauses for 300 seconds.

Claude watches settings-only changes automatically. Use `/reload-plugins` only after installing or updating plugin source.
