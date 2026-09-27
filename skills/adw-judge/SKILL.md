---
name: adw-judge
description: Select the ADW native Claude model-judging preset.
disable-model-invocation: true
argument-hint: <mixed|luna|luna-native|haiku|status>
---

Run the installed `adw-judge` executable exactly once with the one argument supplied after this skill name.

Use the normal Bash tool with the argument quoted as one value:

```sh
adw-judge "$ARGUMENTS"
```

The executable accepts only `mixed`, `luna`, `luna-native`, `haiku`, or `status`. It validates the value and replaces the managed settings block atomically, so settings hold one reviewer set. The plugin ships no reviewer of its own. If settings hold no managed block, SessionStart writes the `haiku` block. Each agent preset reviews on Stop only. `luna` keeps its command handler on PostToolUse and Stop. Claude watches settings-only changes automatically. Use `/reload-plugins` only after installing or updating plugin source.

Desktop or Cowork sessions have no reliable hook marker. For an explicit Haiku-only setup, set `ADW_CLAUDE_HAIKU_ONLY=1` and run `adw-judge haiku`.
