---
name: adw-judge
description: Select the ADW native Claude model-judging preset.
disable-model-invocation: true
argument-hint: <mixed|luna|haiku|sonnet|status>
---

Run the installed `adw-judge` executable exactly once with the one argument supplied after this skill name.

Use the normal Bash tool with the argument quoted as one value:

```sh
adw-judge "$ARGUMENTS"
```

The executable accepts only `mixed`, `luna`, `haiku`, `sonnet`, or `status`. It validates the value and writes the managed settings block atomically. Claude watches settings-only changes automatically. Use `/reload-plugins` only after installing or updating plugin source.
