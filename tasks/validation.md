# Host repair validation

## Release and deployment

PR 4 merged after Cubic reported zero new issues and every CI job passed.
CI passed 2413 Python tests on each tested version and 156 Bun tests.
The published v0.20.14 tag points to e54a2d7. README and CHANGELOG agree.

- [ ] install.sh line 1, self_protection/install_without_sandbox_home. Automatic review rejected the official local installer before execution. Installation requires an execution context that permits live-home maintenance.

The designated remote host still returns Network is unreachable over SSH.
Both machines have verified report and ledger backups. Fresh installations,
old-report cleanup, and post-install harness checks remain incomplete.

## Baseline

Python passed 2118 tests with 18 skips. Bun passed 64 tests.
The initial OMP Luna test reproduced the external-target rejection.
Codex Luna completed read and write smoke tests but rejected a read-only
Path.read_text command. Claude initially returned HTTP 407 before inference.

## External targets

Six regressions reproduced the bug. After the fix, all 64 Bun tests and 28
focused Python tests passed, with one opt-in live test skipped.
The four changed Python files scored 10.00/10 in pylint.

OMP Luna then edited an explicitly authorized external file successfully.
The existing inode-swap regression still blocks a replacement file.

## Machine preflight

The initial SSH preflight succeeded. Remote Claude is 2.1.263, Codex is 0.153.4,
and OMP is 18.1.12. The remote noninteractive shell needs ~/.bun/bin and
~/.local/bin on PATH. Both machines have Claude subscription sessions.

Claude Haiku completed a no-tool probe on both machines. On the Mac, removing
the inherited ANTHROPIC_BASE_URL and ANTHROPIC_TARGET_API_URL for that process
avoided the failing proxy. No persistent proxy setting changed.

A later pre-release SSH check returned Network is unreachable. Deployment
needs another connectivity check after publication.

## Complete review batches

The mixed-review and provider suites passed 119 tests. Pylint rated the changed
review modules and their tests 10.00/10. Regression tests now preserve multiple
comments from one file and include TypeScript comments in the journal.

Document and comment requests share a bounded turn deadline. Failed requests
release their reservation, and oversized batches report the coverage limit.

## Python verification

The read-only Python suite passed 207 tests. Exact Path imports and local
read bindings pass. Mutation, rebinding, and indirect execution still block.
The full Python suite passed 2186 tests with 18 existing skips and 274 subtests
on both the local interpreter and the supported Python 3.11 floor.
Pylint rated all tracked Python files and new OMP bridge modules 10.00/10.
Shell syntax and git diff whitespace checks passed.

## Native OMP review

The native provider returned a grounded finding. The first Luna probe reached
its deadline because the agent kept the flagged wording, but a second probe
repaired the document and finished without an ADW block. Every harness model
role used Luna.

The final lifecycle suite passed all 112 Bun tests. Coverage includes partial
writes and notebook aliases, along with deletion recovery and provider errors.
The extension also bundled successfully.

## Retention startup cost

Retention treated ordinary ledger strings as filesystem paths. A read-only
profile took 0.474 seconds for only 1000 rows before the fix, then 0.778 seconds
for 125074 rows afterward. The fix filters report references and resolves the
reports directory once per compaction. Ten focused tests passed.
A fresh OMP Luna session then read the fixture and finished successfully.
Its session trace contained no startup timeout.

## Journal coverage limits

The independent review found silent row truncation at the journal limit.
Overflow markers now block Codex before reservation, and correcting a file
can restore complete coverage. Document storage retains the full bounded
source while the Claude Stop payload keeps its smaller display limit.
Truncated comments fail explicitly. The focused journal suites passed 59 tests.
Pylint rated the changed journal modules and their regression tests 10.00/10.

The full Python run with the first overflow regressions passed 2191 tests,
18 existing skips, and 274 subtests.

## Existing size observations

- [x] hooks/lib/codex_luna.py line 1, file_length_warning. Keep this repair focused. Extract request construction before the module reaches 750 lines.
- [x] omp-review.ts line 69, provider error exposure. Replaced raw SDK errors with safe category messages and passed the secret disclosure regression.
- [x] hooks/lib/omp_review_findings.py line 42, repeated quote attribution. Cubic prompted a stricter check. Ambiguous quotes now require distinguishing source context.
- [x] watcher.ts line 1, file_length_warning. The path fix shrank the file.
- [x] index.test.ts line 1, file_length_warning. Keep new suites in separate files.

## Writing observations

- [x] tasks/validation.md line 11, low_sentence_variance. Shortened the result and combined its supporting evidence.
- [x] tasks/validation.md line 49, low_sentence_variance. Varied the sentence lengths in the live probe record.
- [x] tasks/validation.md line 12, long_sentence. Put the pylint result in its own sentence.
- [x] tasks/validation.md line 55, three_item_list. Reworded the coverage record as two paired examples.
- [x] tasks/validation.md line 81, oversized_list. Separated writing observations from code observations.

The hook also reported existing narration comments in the two touched Python
modules. Those comments no longer remain, and the focused checks pass.

## Installation preflight

The active hook rejected the installer preview command with
install_without_sandbox_home. No installer ran. The command used --dry-run,
but the guard still required a sandbox HOME. Deployment must respect that
active guard rather than disable it or override its authorization setting.
