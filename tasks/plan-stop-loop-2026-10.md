# Plan for Stop loops and imported content (2026-10-14)

## Incident

A Bash `cp -R` copied a third-party skill (57 files) into `~/.claude/skills/impeccable`. ADW counted every copied file as agent work. The Stop hook blocked 88 times in one session on findings the agent never wrote. Each block sent about 4 KB and wrote a new report file.

## Analysis (Sonnet 5.5 team)

| Report | Scope |
|---|---|
| s1 | Stop-loop root cause and fix design |
| s2 | Code review of v0.25.0..v0.25.4 |
| s3 | Codebase review of the runtime hook path |
| s4 | Leverframe review and host health on Mac and tux |

## Work packages (Opus 5.5)

| Package | Scope | Status |
|---|---|---|
| A | Copy provenance, imported baseline, first-seen snapshot, Stop no-progress breaker, pathless holds, state recovery, data-file length rules, Stop time budget, report and ledger size | merged |
| B | PreToolUse read-only Python, startup prefixes, node require of JSON, temp-only redirects and in-place edits, four security fixes | merged |
| C | UserPromptSubmit gates and wording, Sonnet and Luna review cost and stability, review rounds per turn, merge gate refs | merged |
| L | Leverframe diagnose config_stale, hermetic tests, comments, tagged binding result, read-only credential peek, 0.4.6 | released as v0.4.6, installed on Mac and tux |

## Merged tree checks

| Check | Result |
|---|---|
| Full pytest on main | 4396 passed, 17 skipped |
| pylint | 10.00/10 |
| Incident replay with the real 57-file skill | one advice, four Stops released, no report file |

## Sol review findings

| Finding | Severity | Owner | Status |
|---|---|---|---|
| `functools.reduce` called a stored `open` | major | B | fixed in bf6a92f, merged |
| `authored_temp` evicts after 256 paths, so an old scratch file copies in as imported | major | A | fixed, complete store in cea7fc8 |
| The overflow flag counted genuine external copies as agent-owned | major | A | fixed, refusal at the cap in 34ca999 |
| Three Stop breaker gaps (duplicate hashes, skipped-file stamps, deadline release) | major | A | fixed in 20c75cd |
| `perl -pi` on a scratch file runs arbitrary Perl and writes project files | major | B2 | fixed in 5dce4c5 and 98a9b7e |
| A `.json` require through a symlink runs JavaScript | minor | B2 | fixed in 8f17f4b |
| `patch --diagnose` can refresh OAuth credentials over the network | major | L | fixed in aa1f4cd and bcb0451 |
| A file a saved script writes loses detection after a first-seen snapshot | not blocking | A | documented as a known limit |

Final Sol verdict on 83dcb38 is "no blocking findings".

## Gates before release

1. Every Sol major fixed, then a Sol rerun with no blocker or major finding.
2. Full pytest and pylint 10.00 on the merged tree.
3. Release ADW 0.26.0 and Leverframe 0.4.6 with tags and GitHub releases.
4. Install on the Mac and on tux@10.0.10.107, then check one Stop on each host.

## Later work, agreed scope

1. Split `hooks/lib/claude_native.py` (about 900 lines) and `hooks/lib/reporting.py` by concern.
2. The craftsman DDD verification hook repeats the same layer findings after every edit of one file. It costs tokens like the old ADW loop. That fix belongs in the craftsman plugin.

## Out of scope, noted

The "simple-english reply check" Stop message comes from the simple-english plugin (`src/hooks/lint_hook.py`), not from ADW. The plugin asks for prose replies and conflicts with the user's CLAUDE.md format rules.
