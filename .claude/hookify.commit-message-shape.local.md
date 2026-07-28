---
name: warn-commit-message-shape
enabled: true
event: bash
action: warn
tool_matcher: Bash
conditions:
  - field: command
    operator: regex_match
    pattern: git\s+commit\b
  - field: command
    operator: regex_match
    pattern: -m\s+["'](?!\$\(|(?:E\d+-S\d+(?:-T\d+)?\s+|Q\d+\s+)?(?:feat|fix|test|docs|ci|refactor|chore|perf|build|style)\()
---

**Commit subject does not match the history in this repo.**

Shape used by every recent commit:

```
E3-S1 feat(hooks): block at-file bypasses (E3-S1-T2)
Q1 fix(scanner): name the config dotfiles instead of exempting every dotfile
docs(plan): close E3-S1-T2 at-file gate
E1-S1-T3 test(hooks): payload contract module with documented-schema tests
```

Rules that fall out of it:

- Optional work id first, either `E<n>-S<n>` with an optional `-T<n>`, or `Q<n>`.
- Then a conventional type with a scope in parentheses: `feat(hooks)`, `fix(scanner)`, `docs(plan)`, `test(hooks)`, `ci(pylint)`.
- Then a colon and a subject in plain English. State what changed, not that something was updated.
- Close the task id in trailing parentheses when the commit finishes a planned task.

This is a warning, not a block. Rewrite the subject if the commit belongs to the plan. The repo already has a commit message gate on the roadmap under E6-S8, and that gate replaces this rule.
