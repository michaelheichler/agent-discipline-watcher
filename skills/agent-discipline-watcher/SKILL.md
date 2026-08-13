---
name: agent-discipline-watcher
description: >-
  Use when an agent writes or edits files, commit text, or final prose and must
  enforce the combined discipline contract. punctuation-discipline bans em dash
  and en dash characters, double-hyphen clause breaks, spaced-hyphen dash
  substitutes, semicolon splices, bad possessive-pronoun apostrophes, and
  possessive decades. english-for-agents keeps reader-facing English plain by
  removing filler, dead metaphor, AI tells, inflated diction, wordiness, buried
  subjects, and empty intensifiers. clean-coder-discipline keeps code reviewable
  by rejecting narration comments, dead/commented-out code, deferred-work
  markers, hollow tests, and long functions/files.
---

# Agent Discipline Watcher

Apply this skill whenever you produce or revise agent output that may land in a
file, commit, code review, user-facing prose, or final reply. It supports Claude
Code and Codex.

## Enforce These Rules

- Punctuation: do not use em dash or en dash characters. Do not use a double
  hyphen as a clause break, a spaced hyphen as a dash, a semicolon to join two
  clauses, an apostrophe on possessive pronouns, or a possessive apostrophe on
  decades. Prefer a comma, period, parentheses, or a real ASCII hyphen when the
  word form requires it.
- English: write plain reader-facing prose. Cut filler, throat-clearing, dead
  metaphor, AI tell phrases, inflated diction, wordiness, empty intensifiers, and
  buried subjects. State the fact, evidence, consequence, and next action.
- Code: make intent live in names, structure, and tests. Delete comments that
  narrate what the code does, label bug cases, apologize for the code, record
  change history, or hide deferred work. Do not ship commented-out code,
  narrating docstrings, hollow tests, long functions, or oversized files.
- Response stance: be skeptical and direct. Verify changeable facts before
  claiming them. Challenge weak assumptions and overbuilt solutions. Do not open
  with empty validators such as agreement, praise, or filler.

## Responding To Hook Findings

Every hook finding is a blocker. Fix the named file or reply text, then rerun
the relevant check if the task requires proof. The scanner does not emit fuzzy
or advisory results.

Keep fixes narrow. Rewrite the offending sentence, comment, test, or function
instead of disabling checks. If a finding looks wrong, inspect the scanner rule
and the exact snippet before assuming the hook failed.

## Do Not

- Do not end a turn while a finding remains in your own changes.
- Do not silence a hook, delete hook state, or change config to get past a
  finding unless the user explicitly asked for configuration work.
- Do not add a Craftsman suppression marker. It is an unconditional blocker.
  Fix the reported issue.
- Do not add prose comments to explain code that should be clearer through names
  or structure.
- Do not broaden the task into style cleanup outside the touched or requested
  scope.
