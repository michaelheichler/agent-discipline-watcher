---
name: agent-discipline-watcher
description: >-
  Use when an agent writes or edits files or commit text and must
  enforce the combined discipline contract. punctuation-discipline bans em dash
  and en dash characters. It also bans double-hyphen clause breaks and
  spaced-hyphen dash substitutes. Other violations include semicolon splices,
  bad possessive-pronoun apostrophes, and possessive decades. The
  english-for-agents rules remove filler, dead metaphor, AI tells, and inflated
  diction. They also remove wordiness, buried subjects, and empty intensifiers
  from reader-facing English. The clean-coder-discipline rules reject
  narration comments, dead/commented-out code, and deferred-work markers. They also reject
  hollow tests and long functions/files.
---

# Agent Discipline Watcher

Apply this skill whenever you produce or revise agent output that may land in a
file or a commit. The hooks scan files and commit text. No host scans the chat
reply. It supports Claude Code, Codex, and Oh My Pi.

In Oh My Pi, use `/adw configure` or `/agent-discipline configure` for project
policy changes. These commands edit `.agent-discipline.json`. OMP's
`/advisor configure` edits `WATCHDOG.yml` and is a separate reviewer harness.

## Enforce These Rules

- Do not use em dash or en dash characters. Do not use a double
  hyphen as a clause break, a spaced hyphen as a dash, a semicolon to join two
  clauses, an apostrophe on possessive pronouns, or a possessive apostrophe on
  decades. Prefer a comma, period, parentheses, or a real ASCII hyphen when the
  word form requires it.
- Write plain reader-facing English. Cut filler, throat-clearing, dead
  metaphor, AI tell phrases, inflated diction, wordiness, empty intensifiers, and
  buried subjects. State the fact, evidence, consequence, and next action.
- Let prose sentences flow and vary their length. Join related thoughts with a
  subordinate clause or with and, instead of writing a row of short
  telegram-style main clauses. The dash and semicolon bans still hold.
  Code comments stay crisp, one terse WHY line each.
- Make code intent live in names, structure, and tests. Delete comments that
  narrate what the code does, label bug cases, apologize for the code, record
  change history, or hide deferred work. Do not ship commented-out code,
  narrating docstrings, hollow tests, long functions, or oversized files.
- Be skeptical and direct. Verify changeable facts before
  claiming them. Challenge weak assumptions and overbuilt solutions. Do not open
  with empty validators such as agreement, praise, or filler.

## Responding To Hook Findings

A finding that resolves to `block` stops the operation. Fix the named file,
then rerun the relevant check. Rules below their measured precision threshold
stay at `observe`, so their findings report evidence without blocking.

Keep fixes narrow. Rewrite the offending sentence, comment, test, or function
instead of disabling checks. If a finding looks wrong, inspect the scanner rule
and the exact snippet before assuming the hook failed.

## Bash Write Guard

The watcher applies the same rules to Bash file writes and Write or Edit
tool calls. It scans literal write bodies it can read, such as a clean
`echo`, `printf`, or heredoc. When it cannot read a write body, one of seven
rules blocks the call.
`inline_interpreter_write`, `shell_payload_block`, `interpreter_heredoc_write`,
`dynamic_heredoc_write`, `decode_pipe_write`, `inplace_edit_write`, and
`opaque_source_write`. These cover inline interpreter code such as `python3 -c`,
a heredoc or pipe feeding an interpreter's stdin, and a dynamic or unterminated
heredoc aimed at a file. They also cover a decode pipe such as `base64 -d`
ending in a write, an in-place editor such as `sed -i` or `perl -pi`, and an
opaque source such as `dd` or process substitution. Use the Write or Edit tool
for file content instead of routing it through Bash.

## Do Not

- Do not end a turn while a finding remains in your own changes.
- Do not silence a hook, delete hook state, or edit configuration to get past
  a finding. Configuration changes go through `agent-discipline configure`,
  not direct edits.
- Do not add a Craftsman suppression marker. It is an unconditional blocker.
  Fix the reported issue.
- Do not add prose comments to explain code that should be clearer through names
  or structure.
- Do not broaden the task into style cleanup outside the touched or requested
  scope.
