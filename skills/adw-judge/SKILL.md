---
name: adw-judge
description: Select the ADW native Claude model-judging preset.
disable-model-invocation: true
argument-hint: <mixed|luna|status>
---

Run the installed `adw-judge` executable exactly once with the one argument supplied after this skill name.

Use the normal Bash tool with the argument quoted as one value:

```sh
adw-judge "$ARGUMENTS"
```

The executable accepts only `mixed`, `luna`, or `status`. It validates the value. It replaces the managed settings block atomically, so settings hold one reviewer set.

The plugin ships no reviewer of its own. If settings hold no managed block, SessionStart writes the `mixed` block. If settings hold an old agent block, SessionStart replaces it with the `mixed` block.

`mixed` runs one Sonnet 5.5 review per Stop through the `claude` CLI. The call has no tools and fires no nested hooks. `luna` keeps its command handler on PostToolUse and Stop.

Claude watches settings-only changes automatically. Use `/reload-plugins` only after installing or updating plugin source.
