---
name: block-project-config-silencing
enabled: true
event: file
action: block
tool_matcher: Write|Edit|MultiEdit
conditions:
  - field: file_path
    operator: ends_with
    pattern: .agent-discipline.json
---

**Blocked: edit to the project gate config.**

`.agent-discipline.json` holds the check switches, gate states, kill switches, and path exemptions. It is gitignored, so a change here is invisible in review and silences findings for every later session in this project.

The skill contract is explicit: do not change config to get past a finding unless the user asked for configuration work.

Fix the reported file instead. Keep the fix narrow, and rewrite the offending sentence, comment, test, or function.

Two rules ignore this config anyway. `suppression_escape_hatch` and `what_comment` block on every scanned file, whatever the switches say.

If the user did ask for config work, use the CLI, which validates what it writes:

```
agent-discipline configure
agent-discipline configure --checks punctuation,english,clean_code
```
