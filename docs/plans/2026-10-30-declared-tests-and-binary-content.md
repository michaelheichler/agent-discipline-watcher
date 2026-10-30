# Declared tests and binary content, 2026-10-30

This plan fixes two blocks a TweakCC Fixed update session hit on 2026-10-30, and it makes the test gate and the binary check judge content instead of names. Every rule keeps its strength. The protocol of each changed line sits in `docs/plans/2026-10-30-declared-tests-and-binary-content-protocol.md`.

## Evidence

1. `tar -xzf ~/.local/state/agent-stack-backup/update-20261030/artifacts/tweakcc-fixed-2.9.18.tgz -C ~/.local/state/agent-stack-backup/update-20261030/tweakcc-2.9.18` blocked as `test_write_gate` with "Shell command may change tests it does not name". The same command with ten named members under `package/` blocked the same way. Reports `01a18e46-...-turn-b20bc95e...json` and `...-turn-e6eb3acc...json` in `~/.adw/reports/` show the detail.
2. A probe in `/tmp/adw-probe/scratch/probe.py` reproduced it with a two-file archive. With `~/` the command blocks, and with absolute paths it passes. `_plain` in `hooks/lib/archive_commands.py` returned `None` for any word that holds `~`, because `UNSAFE_CHARS` listed it, so `tar_read` gave up and the segment became unresolved.
3. The Claude executable `~/.local/share/claude/versions/2.1.312` is a Mach-O file. `is_binary_content` in `hooks/lib/scan_input.py` returned `False` for any suffix outside the hard-coded `BINARY_ASSET_EXTS` list, and `.312` is not in it, so the NUL bytes of the executable produced `unscannable_file` with the action "Make the file readable UTF-8 text".
4. While I wrote this plan, the installed 0.31.1 gate blocked the new module `hooks/lib/test_source.py` as a test write, although it holds no test. Its name matched `test_.+\.py`. The module now ships as `hooks/lib/declared_tests.py`.

## Decisions

### Archives and binaries

1. An unquoted leading `~`, `$HOME`, or `${HOME}` and a double-quoted `"$HOME/..."` in a tar, unzip, or patch word become the absolute home folder, the way bash expands them before the command runs. `home_expanded` reads the raw token before `_bare` strips the quotes. A single-quoted `'~/x'`, an inline `--file=~/x` or `-C~/x`, `~user`, other variables, backticks, and globs stay unresolved, because bash leaves them alone too.
2. A file is binary when its first bytes carry a format signature that no source file starts with, or a sized container tag (`RIFF`, `RIFX`, `FORM`, `ftyp`) beside a binary size field. The signatures cover ELF, Mach-O, fat Mach-O and Java class, PE with its `PE\0\0` mark, wasm, PNG, JPEG, zip, gzip, xz, zstd, 7z, rar, SQLite, NumPy, OLE, Matroska, TIFF, ICO, and LZ4. Printable headers such as `%PDF-` count only beside their own suffix, as before.
3. Content without a signature counts as binary only when more than a third of its first 8 KB is strange characters (C0 controls outside whitespace, undecodable bytes). `perldoc -f -X` documents that cut for Perl's `-B` test, so ADW does not invent its own number. An extensionless file needs an executable signature (ELF, Mach-O, or PE) and that share over the whole content, and real executables measure 0.70 (Claude), 0.64 (Codex), 0.93 (bun), and 0.99 (`/bin/ls`) in the first 8 KB. A source, prose, config, data, or script suffix and a file that opens with `#!` never count as binary, as in 0.31.1, because padding can forge any share. A signature also counts in its lossy decoded spelling when a format name such as `PNG` survives in it.
4. `BINARY_ASSET_EXTS` is gone. The text suffixes come from one place, `hooks/lib/markup.py`, which now holds `PROSE_EXTS`, `CONFIG_EXTS`, `DATA_TEXT_EXTS`, `COMMENTABLE_EXTS`, and `SCRIPT_EXTS`.
5. Hard-coded values that were wrong or duplicated go away. `.kotlin` in `COMMENTABLE_EXTS` becomes `.kt` and `.kts`, the inline copy of `MIXED_LANGUAGE_EXTS` in `narration_candidates.py` reads the shared set, and the bare `8192` in `record.py` and `scan_input.py` reads `CONTENT_SAMPLE_BYTES`.

### The test gate

6. A test is what a file declares. `hooks/lib/declared_tests.py` reads test syntax for Python, JavaScript and TypeScript, Go, Rust, Ruby, the JVM languages, C#, PHP, Swift, Elixir, C and C++, Dart, Bats and shunit2, Lua busted, and Jest snapshots. In Python, a framework import, a `Test` class or `TestCase` base, a fixture, a pytest hook, a star import, a pytest setting such as `pytestmark`, or a `test_` function with an assert counts, also inside a module-level `if`, `try`, or `with`. A bare `test_` name proves nothing, so `test_runtime_or_current` in `luna_runtime.py` is no test.
7. `touches_tests` decides in this order. The name and folder rule applies only when the text that lands is unknown, as for a delete, a copy, an archive member, or an unreadable file. A change that leaves the text equal passes. Any file with text under a test folder blocks, code or data, because a helper or fixture there serves tests without declaring one, and `conftest.py` blocks by name, because pytest loads it as a plugin. A file that declares tests on either side blocks any change when its name says test, or when its language has no unit extractor. Python and Rust source with inline tests keeps the unit by unit diff.
8. `testdata`, `__snapshots__`, `__fixtures__`, and `__mocks__` join the test folders, so the gate covers Go golden files, Jest snapshots, and Jest mocks. In these four folders a `.txt` file counts as expected output, not as a document. The fallback name pattern for the JVM now also knows `*IT`, `*Spec`, Kotlin, Groovy, and Scala.
9. In the shell path, a literal text counts as the landing text only when it is the one write to its path in the command, and an append counts as the old text plus the appended text. A second write, an append, a copy, an edit, or any other segment that names the same path, such as `ed` or `ex`, makes the text unknown, so the name and folder rule decides.

## Q&A with the Sonnet agent

A Sonnet agent (`sonnet-qa`) reviewed the first design read-only, ran probes against the real functions, and reported three confirmed bypasses and two semantic errors. Each one changed the code.

1. Bypass. `\x7fELF\0\n` plus prose in `a.md` or `a.py` counted as binary, and one bad byte made any unknown-suffix file binary. Decision 3 now asks for the one-third share.
2. Bypass. For `printf 'x=1' > test_b.py; cat other >> test_b.py` and the same with `cp`, the gate read the stale first literal. Decision 9 closes it.
3. Bypass. `def assert_equal(a, b): pass` in `tests/helpers.py` passed under the first design. Decision 7 keeps the test folder as evidence.
4. Semantics. The first design expanded a quoted `'~/x'` and `--file=~/x`, although bash does not. Decision 1 now reads the raw token.
5. Semantics. `class TestX(Base): pass`, a star import, and `pytestmark` in a test-named file run tests without an assert. Decision 6 counts them, and the detector also reads module-level `if`, `try`, and `with` blocks.

In round two Sonnet confirmed the five fixes with fresh probes and found two more holes, which I closed.

6. Bypass. A forged signature plus junk padding to a third of the file still made a `.md` or `.py` file skippable. A text suffix or a `#!` script now never counts as binary, as in 0.31.1.
7. Bypass. `ed` and `ex` rewrite a file without a redirect, so `printf 'x=1' > test_a.py; ed -s test_a.py` kept the stale literal. Any other segment that names the path now makes the text unknown. `perl -pi`, `awk -i inplace`, and `ruby -pi` already block as in-place editors.

In round three Sonnet confirmed both round-two fixes for text suffixes and found three more spots, which I closed.

8. Bypass. An extensionless `README` with a forged `PK` header and a third of junk counted as binary. An extensionless file now needs an executable signature.
9. Bypass. `printf 'x=1' > sub/test_h.py; cd sub && ed -s test_h.py` resolved `test_h.py` against the session folder. The name count now uses the folders each segment may run in, as `gated_paths` does.
10. Bypass. A glued redirect such as `ex -s f<<<w` hid the name `f`. The name count now splits words at redirect marks.

I declined two proposals. Sonnet listed plain `fixtures/` as a test folder, and I added only the Jest forms `__fixtures__/` and `__mocks__/`, because Django and others keep app data in `fixtures/`. A Python `test_` function without an assert in a source file keeps the old unit diff, so creating one still blocks.

## What changes for a user

1. Extracting a package from a path under `~` no longer blocks unless a member that lands is a test by name or folder.
2. Writing `test_helpers.py` with no test outside a test folder, or an empty `foo.spec.ts`, passes. Writing a test into any of them blocks. A helper in `tests/` still blocks.
3. A file that declares tests under an innocent name, such as `src/checks.ts` with `describe(...)` or `pkg/util.go` with `func TestX(t *testing.T)`, now blocks. Before, it passed.
4. Executables, images, archives, and media pass the post-write scan whatever their name. A text file with a NUL byte still blocks as unscannable.

## Tasks

1. Expand home in archive words (`hooks/lib/archive_commands.py`). Done, and the probe passes with `~/` and with absolute paths.
2. Judge binary by content (`hooks/lib/binary_content.py`, `hooks/lib/scan_input.py`, `hooks/lib/markup.py`, `hooks/lib/scanner.py`, `hooks/lib/narration_candidates.py`, `hooks/record.py`). Done. The Claude executable reads as binary.
3. Judge tests by declaration (`hooks/lib/declared_tests.py`, `hooks/lib/tests_policy.py`, `hooks/pre_bash.py`). Done. Six tests that pinned the name rule with neutral text needed new content.
4. Let `adw-test-writer` update the six pinned tests and add regression tests for tasks 1 to 3. Done. Its probes found two more gaps, a `.txt` golden file in `testdata/` and Jest `it.each`, and I closed both.
5. Run the Q&A with a Sonnet agent on the design and an adversarial review of the diff. Done in three rounds, recorded above.
6. Release 0.32.0 with `CHANGELOG.md` and `README.md`, then run pylint, the shell syntax check, `claude plugin validate . --strict`, and `caliber refresh`, and commit and push.
7. Install on this MacBook and on `tux@10.0.10.107`, then clear the Claude Code and Codex plugin caches on both.

## Checkpoints

1. After task 3, the full hooks suite passes except the six pinned tests, and the probe passes.
2. After task 4, the full suite, the pi suites, and pylint at 10.00 pass.
3. After task 7, `bin/adw-config status` on both machines names 0.32.0, and a replay of the two TweakCC commands passes.

## Remaining limits

1. A copy target (`cp`, `mv`, `git checkout`) and an archive member still fall back to the name and folder rule, because ADW does not read the source text before the run.
2. A Python or Rust file under a test name outside a test folder that declares no test gets the unit by unit diff, so a helper edit in it passes.
3. A file with a suffix no ADW reader treats as text and a forged signature in front of prose counts as binary. Such a file is no source any host runs.
4. A binary whose first 8 KB is valid text without a signature, such as a protocol 0 pickle, still gets scanned as text, as before.
5. A file with a suffix no ADW reader treats as text, such as `x.foo`, counts as binary once a third of it is junk. An agent can hide text that way only in a file no host runs as source.
6. `cd sub && printf 'x=1' > test_g.py` still blocks by name, because a failed `cd` leaves the write in another folder than the literal names. 0.31.1 blocked it the same way.
7. A program that writes a path it never names, such as `make`, leaves a literal in place. The opaque write gates are the layer for that, as before.
