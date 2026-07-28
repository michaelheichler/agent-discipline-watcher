---
name: block-stop-without-pytest
enabled: true
event: stop
action: block
conditions:
  - field: transcript
    operator: regex_match
    pattern: \bname"\s*:\s*"(?:Edit|Write|MultiEdit|NotebookEdit)"\s*,\s*"input"\s*:\s*\{[^{}]{0,300}?/hooks/(?:lib/)?[a-z0-9_]+\.py
  - field: transcript
    operator: not_contains
    pattern: pytest
---

**Do not end the turn yet. This session changed hook code and never ran the suite.**

The project rule is that every hook change lands with a test plus the full pytest gate. A claim of success without a run is itself a blocked finding in this repo.

Run it:

```
cd hooks && python3 -m pytest . lib -q
```

Then report the real result. If tests fail, say so and paste the output. Do not describe the change as done.

The first condition matches a recorded `Edit`, `Write`, `MultiEdit`, or `NotebookEdit` tool call whose own `input` object names a path under `hooks/`. Reading a hook file, grepping one, or naming one in prose does not match, because none of those produce an edit-tool `input` block. The bounded `[^{}]` window keeps the match inside a single tool call, so an edit to one file plus a read of another cannot combine into a false trigger.

One `pytest` run in the session clears the second condition.
