# Host repair validation

## Baseline

Python passed 2118 tests with 18 skips. Bun passed 64 tests.
The initial OMP Luna test reproduced the external-target rejection.
Codex Luna completed read and write smoke tests but rejected a read-only
Path.read_text command. Claude initially returned HTTP 407 before inference.

## External targets

The new regressions failed before the implementation, with two Bun failures
and four Python failures. After the fix, Bun passed all 64 tests. The focused
Python run passed 28 tests with one opt-in live test skipped. Pylint rated the
four changed Python files 10.00/10.

OMP Luna then edited an explicitly authorized external file successfully.
The existing inode-swap regression still blocks a replacement file.

## Machine preflight

SSH to tux@10.0.10.106 works. Remote Claude is 2.1.263, Codex is 0.153.4,
and OMP is 18.1.12. The remote noninteractive shell needs ~/.bun/bin and
~/.local/bin on PATH. Both machines have Claude subscription sessions.

Claude Haiku completed a no-tool probe on both machines. On the Mac, removing
the inherited ANTHROPIC_BASE_URL and ANTHROPIC_TARGET_API_URL for that process
avoided the failing proxy. No persistent proxy setting changed.

## Existing size observations

- [x] watcher.ts line 1, file_length_warning. The path fix shrank the file.
- [x] index.test.ts line 1, file_length_warning. Keep new suites in separate files.

The hook also reported existing narration comments in the two touched Python
modules. Those comments no longer remain, and the focused checks pass.
