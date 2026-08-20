# Spec: Bash Write Guard

Triage: ready-for-agent

## Problem Statement

Agents under observation dodge the discipline watcher by routing file writes through Bash instead of the Write and Edit tools. Inline interpreter code, heredocs piped into interpreters, dynamic heredocs, decode pipes, and in-place editors all land content on disk without ever passing the scanner. The watcher's core promise, catching drift before it lands in files, fails exactly when an agent tries hardest to avoid it.

## Solution

Every Bash-mediated write route the gate can attribute to a write is guarded, meaning heredocs, inline interpreters, decode pipes, in-place editors, and literal redirects. Literal write bodies the watcher can fully see are scanned with the same strict hard block on findings as the Write and Edit tools, including the split between whole-file writes and edits. Write bodies the watcher cannot statically see are hard blocked outright, with a deny message directing the agent to the Write or Edit tool. The residual gaps named under Out of Scope below are the documented exception to this guarantee. The new rules sit in the always-blocking tier, so no project config can weaken them and only the human-held environment escape releases them.

## User Stories

1. As a repo owner, I want inline interpreter code that can write files blocked, so that agents cannot smuggle content past the scanner through python -c or node -e.
2. As a repo owner, I want heredocs feeding an interpreter's stdin judged like inline code, so that piping a script into python3 is not a loophole.
3. As a repo owner, I want dynamic heredocs aimed at files blocked instead of silently dropped, so that variable expansion cannot hide unscannable content.
4. As a repo owner, I want decode pipes that end in a file write blocked, so that base64-staged content cannot bypass scanning.
5. As a repo owner, I want in-place editors blocked, so that sed -i and perl -pi cannot mutate files outside the Edit tool.
6. As a repo owner, I want opaque copy sources blocked, so that dd and process substitution cannot launder content onto disk.
7. As a repo owner, I want shell -c payloads judged recursively when literal and blocked when not, so that nesting a shell does not strip the guard.
8. As a repo owner, I want the new rules unremovable through project config, so that an observed agent cannot grant itself an escape.
9. As a repo owner, I want the existing environment escape to keep working, so that a human can still authorize exceptional maintenance.
10. As an agent, I want literal echo, printf, and quoted heredoc writes scanned rather than banned, so that legitimate small file writes keep working when clean.
11. As an agent, I want append writes judged like edits, so that adding clean lines to a large file is not blocked for pre-existing debt.
12. As an agent, I want overwrites of committed files to report inherited debt without blocking, so that I am only stopped by lines I own.
13. As an agent, I want read-only interpreter one-liners to keep working, so that version probes and quick arithmetic do not require an escape.
14. As an agent, I want decode and stream tools allowed when nothing is written, so that base64 to stdout and sed transforms to stdout keep working.
15. As an agent, I want display heredocs and heredocs into non-writing consumers allowed, so that cat banners and psql sessions are not blocked.
16. As an agent, I want a deny message that names the rule and the correct tool, so that I can immediately switch to Write or Edit.
17. As a maintainer, I want every must-stay-allowed idiom pinned by a regression test, so that hardening does not creep into false positives.
18. As a maintainer, I want residual known gaps written down where the tests live, so that the next hardening pass starts from an honest list.
19. As a maintainer, I want appends that grow a file past the length limit blocked, so that the file-size discipline cannot be bypassed line by line.
20. As a maintainer, I want the seven rule names documented in the README and skill text, so that users understand what blocks and why.

## Implementation Decisions

- Seven new always-blocking rules: inline_interpreter_write, shell_payload_block, interpreter_heredoc_write, dynamic_heredoc_write, decode_pipe_write, inplace_edit_write, opaque_source_write.
- Rules join the self-protection tier, which makes them immune to rule gates, kill switches, and path exemptions, and makes any config that downgrades them an escape attempt in its own right.
- The only release is the existing human-held environment escape. Config keys stay inert by design.
- A literal interpreter payload is judged by a single write-capable token regex covering filesystem APIs, process spawning, dynamic dispatch, dunder access, and shell-out backticks. Payloads free of these tokens stay allowed. Non-literal or absent payloads block outright.
- Shell -c recursion goes one level: a literal payload re-enters the full Bash gate, a non-literal payload blocks.
- Bash overwrite redirects take the write shape: full scan, then a committed-baseline split so inherited debt reports without blocking. Appends take the edit shape: only the appended body is scanned and every finding is owned, plus a file-length check on the resulting size.
- No scratch-path carve-out for the opaque rules. An unscannable body to any path is treated as a laundering step.
- Deny messages end by naming the Write or Edit tool as the correct path.
- Parsing stays in pure functions in the shell-parse module. Detection and gate wiring stay in the Bash gate module.

## Testing Decisions

- The seam is the Bash gate's run entry point, fed hook payloads and returning decisions, the same seam the existing Bash gate tests use. No new seams.
- Tests assert external behavior only: decision, rule name in the reason, and the tool redirect text. No assertions on parser internals beyond the existing parsing test style.
- Every blocking rule gets a trigger test and an environment-escape release test. Every row of the must-stay-allowed table gets an allow test.
- Shape-split tests run in a temporary git repo, following the existing edit-journal fixtures.
- Prior art: the existing Bash write scan tests, the Bash gate tests, and the self-protection invariant tests.

## Out of Scope

- Variable-staged writes (echo of an expanded variable to a file) and network-to-file pipes (curl into tee) stay allowed and documented as residual gaps.
- Stream transforms to a new file (sed from one file to another) stay allowed.
- Module runs (python3 -m) are not judged.
- No changes to the Write and Edit tool gates, the commit gate, or the MCP gate.
- No new configuration surface.

## Further Notes

Ticket breakdown lives in tasks/tickets/. Implementation and QA run as a workflow: Sonnet 5 coder agents at high effort, Opus 5 QA agents at medium effort. Coders must use the Write and Edit tools truthfully. Any Bash-mediated file write or any edit to the watcher's own gates by an implementing agent is grounds for QA rejection.
