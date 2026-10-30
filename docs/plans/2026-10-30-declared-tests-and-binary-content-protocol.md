# Protocol of release 0.32.0, 2026-10-30

This protocol quotes every line that caused the two reported blocks, every hard-coded value I removed, and every production line I changed. The plan and its decisions sit in `docs/plans/2026-10-30-declared-tests-and-binary-content.md`. Line numbers before a change refer to commit `2a5324a`.

## Skills used

1. `debugging-and-error-recovery` from `~/.claude/skills/debugging-and-error-recovery/SKILL.md`. I followed its triage order, which runs from reproduce over localize, reduce, and fix the root cause to a regression guard and an end to end check. The reproduction lives in `/tmp/adw-probe/scratch/probe.py`.
2. `planning-and-task-breakdown` from `~/.claude/skills/planning-and-task-breakdown/SKILL.md`. I used its plan template for the plan document. The plan sits in `docs/plans/` instead of `tasks/plan.md`, because `CLAUDE.md` of this repo puts plans there.
3. `agent-discipline-watcher:unit-testing-principles`, which the `adw-test-writer` agent loads before it writes any test. That agent wrote every test of this release, as the project rule requires.

## Detected lines

### The tar block

`hooks/lib/archive_commands.py:25` listed the tilde as unsafe.

```python
UNSAFE_CHARS = frozenset("$`*?[~{")
```

`hooks/lib/archive_commands.py:48` to `:50` used that set on every archive source and landing folder. A `~/...` word returned `None`, `tar_read` gave up, and the segment became "Shell command may change tests it does not name".

```python
def _plain(word: str) -> str | None:
    bare = word.strip("'\"")
    return bare if bare and not UNSAFE_CHARS.intersection(bare) else None
```

### The test gate by name

`hooks/lib/tests_policy.py:99` to `:102` blocked on the name before it looked at any text.

```python
def touches_tests(change: PendingChange, root: str | None = None) -> bool:
    """Compare both sides, since deleting a test also changes it."""
    if is_test_path(change.path, root):
        return True
```

`hooks/lib/tests_policy.py:39` to `:43` held the name patterns that decided alone.

```python
_TEST_NAME_RE = re.compile(
    r"^(?:test_.+\.py|.+_test\.py|conftest\.py|.+_test\.go|.+_spec\.rb"
    r"|.+\.(?:test|spec)\.[cm]?[jt]sx?)$"
)
_JAVA_TEST_RE = re.compile(r"^.+Tests?\.java$")
```

The same rule blocked my own new module `hooks/lib/test_source.py` during this work, although it held no test. I renamed it to `hooks/lib/declared_tests.py`.

### The binary check by suffix

`hooks/lib/scan_input.py:29` to `:41` was a list of 70 suffixes, and `hooks/lib/scan_input.py:102` returned `False` for every other suffix. The Claude executable `versions/2.1.312` has the suffix `.312`, so its NUL bytes drew `unscannable_file` with "Make the file readable UTF-8 text".

```python
BINARY_ASSET_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".jpe", ".gif", ".webp", ".avif", ".heic", ".heif",
    ...
    ".so", ".dylib", ".dll", ".exe", ".glb", ".pak",
})
```

```python
    if suffix not in BINARY_ASSET_EXTS:
        return False
```

### Wrong and duplicated hard-coded values

1. `hooks/lib/narration_candidates.py:32` named `.kotlin`, a suffix no Kotlin file uses, so Kotlin comments never reached the narration candidates.

```python
    ".jsx", ".kotlin", ".mjs", ".php", ".rb", ".rs", ".sh", ".swift", ".ts",
```

2. `hooks/lib/narration_candidates.py:44` repeated `MIXED_LANGUAGE_EXTS` from `hooks/lib/markup.py:65` inline.

```python
    source = CommentSource(path, text, extract_regions(path, text), PurePath(path.lower()).suffix in {".html", ".htm", ".xml", ".svg", ".vue", ".svelte"})
```

3. `hooks/record.py:175` and `hooks/lib/scan_input.py:235` repeated the sample size `8192` instead of `CONTENT_SAMPLE_BYTES`.

```python
    if len(raw) > limit or b"\0" in raw[:8192]:
```

```python
    if "\0" in text[:8192]:
```

4. `hooks/pre_bash.py:213` used the last literal text of a path as the landing text, even when a later `>>`, `cp`, `ed`, or `ex` in the same command changed the file. The Sonnet agent found this with a probe.

```python
        tests_policy.PendingChange(path, tests_policy.read_before(payloads.resolved_path(path, cwd)), text)
```

5. `hooks/lib/tests_policy.py:35` exempted every `.txt` file as a document, also inside `testdata/`, where a `.txt` holds expected output. The test writer agent found this with a probe.

```python
DOC_EXTS = MARKDOWN_EXTS | {".rst", ".txt", ".adoc"}
```

6. The first version of `JS_TEST_CALL_RE` in the new `hooks/lib/declared_tests.py` missed Jest `it.each(...)` and `test.each` templates, and its `GO_TEST` matched `func Testify()`, which Go does not run as a test. The test writer agent found the `it.each` gap with a probe and noted the `Testify` match in its report.

```python
JS_TEST_CALL_RE = r"^\s*(?:describe|it|test|suite|context|bench)(?:\.\w+)*\s*\(\s*['\"`]"
... |^func\s+(?:Test|Benchmark|Fuzz|Example)\w*\s*\('
```

## Changed lines

### `hooks/lib/archive_commands.py`

```diff
+import os
+import re
+UNQUOTED_HOME_RE = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")
+QUOTED_HOME_RE = re.compile(r'^"(?:\$HOME|\$\{HOME\})(?=/|")')
-            return _plain(args[position + 1])
+            return _plain(home_expanded(args[position + 1]))
-            return _plain(token[1:])
+            return _plain(home_expanded(token[1:]))
+def home_expanded(token: str) -> str:
+    """Raw token only, because bash expands no quoted tilde and no tilde after an equals sign."""
+    for pattern, lead in ((UNQUOTED_HOME_RE, ""), (QUOTED_HOME_RE, '"')):
+        found = pattern.match(token)
+        if found:
+            return lead + os.path.expanduser("~") + token[found.end():]
+    return token
```

### `hooks/lib/write_targets.py`

```diff
-from lib.archive_commands import git_apply_read, patch_plan, stdin_source, tar_read, unzip_read
+from lib.archive_commands import git_apply_read, home_expanded, patch_plan, stdin_source, tar_read, unzip_read
-    plan = patch_plan([_bare(token) for token in _without_redirects(raw)], stdin_source(raw))
+    plan = patch_plan([_bare(home_expanded(token)) for token in _without_redirects(raw)], stdin_source(raw))
-    words = [_bare(token) for token in _without_redirects(raw)]
+    words = [_bare(home_expanded(token)) for token in _without_redirects(raw)]
```

### `hooks/lib/binary_content.py` (new, 126 lines)

The module holds `CONTENT_SAMPLE_BYTES`, the composed `TEXT_SUFFIXES`, `EXECUTABLE_SIGNATURES` and the wider `SIGNATURES`, their lossy `DECODED_SIGNATURES`, the sized containers (`RIFF`, `RIFX`, `FORM`, `ftyp`), the PE check through the pointer at `0x3C`, the printable `TEXTUAL_HEADERS` per suffix, `STRANGE_SHARE = 1 / 3` from `perldoc -f -X`, `strange_share`, and the decision below.

```python
def is_binary_content(path: str | PurePath, content: bytes | str) -> bool:
    """Never for text suffixes, because padding can forge any share a source file is judged by."""
    sample = _sample(content)
    if sample.startswith(TEXT_BOMS):
        return False
    suffix = PurePath(str(path)).suffix.lower()
    if sample.startswith(TEXTUAL_HEADERS.get(suffix, ())):
        return True
    if sample.startswith(SHEBANG) or (suffix and suffix in TEXT_SUFFIXES):
        return False
    dense = strange_share(_encoded(content)) > STRANGE_SHARE
    return _signed(sample) or dense if suffix else _executable(sample) and dense
```

### `hooks/lib/scan_input.py`

```diff
+    from .binary_content import CONTENT_SAMPLE_BYTES, is_binary_content
+    from .markup import DATA_TEXT_EXTS
+    from binary_content import CONTENT_SAMPLE_BYTES, is_binary_content
+    from markup import DATA_TEXT_EXTS
-CONTENT_SAMPLE_BYTES = 8192
-# Content is checked too, because text can hide under these.
-BINARY_ASSET_EXTS = frozenset({ ... 70 suffixes ... })
-DATA_TEXT_EXTS = frozenset({".json", ".jsonl", ".csv", ".tsv", ".lock", ".map", ".svg", ".xml", ".sql"})
-ASSET_TEXT_HEADERS = { ... 9 suffixes ... }
-def is_binary_content(path: str | Path, content: bytes | str) -> bool:
-    suffix = Path(path).suffix.lower()
-    if suffix not in BINARY_ASSET_EXTS:
-        return False
-    ... 20 more lines ...
-    if "\0" in text[:8192]:
+    if "\0" in text[:CONTENT_SAMPLE_BYTES]:
```

### `hooks/lib/markup.py`

```diff
+PROSE_EXTS = MARKDOWN_EXTS | {".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg", ".tex", ".adoc", ".asciidoc", ".org", ".typ"}
+CONFIG_EXTS = frozenset({".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env", ".properties"})
+DATA_TEXT_EXTS = frozenset({".json", ".jsonl", ".csv", ".tsv", ".lock", ".map", ".svg", ".xml", ".sql"})
+COMMENTABLE_EXTS = frozenset({
+    ".c", ".cc", ".cpp", ".cxx", ".cs", ".go", ".h", ".hpp", ".java", ".js",
+    ".jsx", ".kt", ".kts", ".mjs", ".php", ".rb", ".rs", ".sh", ".swift", ".ts",
+    ".tsx", ".vue", ".svelte",
+})
+# Because a host runs these as source, a stray byte must not make them skippable.
+SCRIPT_EXTS = frozenset({".py", ".pyi", ".bash", ".zsh", ".ksh", ".fish", ".pl", ".pm", ".lua", ".ps1", ".css", ".scss"})
```

### `hooks/lib/scanner.py`

```diff
-        MARKDOWN_EXTS,
+        CONFIG_EXTS,
+        PROSE_EXTS,
-PROSE_EXTS = MARKDOWN_EXTS | {".rst", ".txt", ".text", ".html", ".htm", ".xml", ".svg", ".tex", ".adoc", ".asciidoc", ".org", ".typ"}
-CONFIG_EXTS = {".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env", ".properties"}
```

Both import blocks changed the same way. `scanner.PROSE_EXTS` and `scanner.CONFIG_EXTS` still exist for `judge_review.py`, `journal.py`, `omp_review.py`, and `omp_review_requests.py`.

### `hooks/lib/narration_candidates.py`

```diff
-    from .markup import CommentSource, comment_scan_source, extract_regions
+    from .markup import COMMENTABLE_EXTS, MIXED_LANGUAGE_EXTS, CommentSource, comment_scan_source, extract_regions
-COMMENTABLE_EXTS = frozenset({
-    ".c", ".cc", ".cpp", ".cxx", ".cs", ".go", ".h", ".hpp", ".java", ".js",
-    ".jsx", ".kotlin", ".mjs", ".php", ".rb", ".rs", ".sh", ".swift", ".ts",
-    ".tsx", ".vue", ".svelte",
-})
-    """Extract judge candidates from masked non-Python comments without treating strings as comments."""
-    source = CommentSource(path, text, extract_regions(path, text), PurePath(path.lower()).suffix in {".html", ".htm", ".xml", ".svg", ".vue", ".svelte"})
+    """Masked first, because a comment marker inside a string is no comment."""
+    source = CommentSource(path, text, extract_regions(path, text), PurePath(path.lower()).suffix in MIXED_LANGUAGE_EXTS)
```

The docstring change fixed an older `what_docstring` finding that ADW reported when I touched the file.

### `hooks/lib/declared_tests.py` (new, 148 lines)

The module holds one test-syntax pattern per language family, keyed by suffix, an AST reader for Python, and a reader for Rust that drops `#[cfg(test)]` blocks first. Its one public function follows.

```python
def declares_tests(path: str, text: str) -> bool:
    """File level only, because a Rust cfg(test) module beside source is judged unit by unit."""
```

The two patterns from item 6 under "Wrong and duplicated hard-coded values" above, `JS_TEST_CALL_RE` and `GO_TEST`, now read as follows.

```python
JS_TEST_CALL_RE = r"^\s*(?:describe|it|test|suite|context|bench)(?:(?:\.\w+)*\s*\(\s*['\"`]|(?:\.\w+)*\.each\b)"
... |^func\s+(?:Test|Benchmark|Fuzz|Example)(?![a-z])\w*\s*\('
```

### `hooks/lib/tests_policy.py`

```diff
-    from . import agent_types, host, payloads, test_units
+    from . import agent_types, declared_tests, host, payloads, test_units
+    import declared_tests
-TEST_DIRS = frozenset({"tests", "__tests__", "test", "spec"})
+# Because a .txt here is expected output, the document exemption stops at these.
+FIXTURE_DIRS = frozenset({"testdata", "__snapshots__", "__fixtures__", "__mocks__"})
+TEST_DIRS = frozenset({"tests", "__tests__", "test", "spec"}) | FIXTURE_DIRS
+# Kept by name, because pytest loads every conftest.py as a plugin.
+CONFTEST = "conftest.py"
-_JAVA_TEST_RE = re.compile(r"^.+Tests?\.java$")
+_JAVA_TEST_RE = re.compile(r"^.+(?:Tests?|IT|Spec)\.(?:java|kt|kts|groovy|scala)$")
-    """Match by name, because a new empty file has no test yet."""
+    """Name and folder only, so it serves where the landing text is unknown."""
-    in_test_dir = any(part in TEST_DIRS for part in _judged_parts(path, root))
-    if in_test_dir and PurePath(name.lower()).suffix not in DOC_EXTS:
+    if in_test_dir(path, root) and not _document(path, root):
+def in_test_dir(path: str, root: str | None = None) -> bool:
+    return any(part in TEST_DIRS for part in _judged_parts(path, root))
+def _held_by_suite(change: PendingChange, root: str | None) -> bool:
+    """Any text counts, because a helper or fixture in a test folder serves tests without declaring one."""
+    name = PurePath(change.path).name
+    texts = [side for side in (change.before, change.after) if side and side.strip()]
+    suite = in_test_dir(change.path, root) and not _document(change.path, root)
+    return bool(texts) and (suite or name == CONFTEST)
+def _document(path: str, root: str | None) -> bool:
+    fixture = any(part in FIXTURE_DIRS for part in _judged_parts(path, root))
+    return PurePath(path.lower()).suffix in DOC_EXTS and not fixture
-    """Compare both sides, since deleting a test also changes it."""
-    if is_test_path(change.path, root):
+    """Because a declared test is the proof, a name decides only where no text shows what lands."""
+    if change.after is None and is_test_path(change.path, root):
+        return True
+    if change.before == change.after:
+        return False
+    if _held_by_suite(change, root):
+        return True
+    declared = any(declared_tests.declares_tests(change.path, side) for side in (change.before, change.after) if side)
+    if declared and (is_test_path(change.path, root) or test_units.language_of(change.path) is None):
```

### `hooks/pre_bash.py`

```diff
+from collections import Counter
-    heredoc_events, interpreter_invocation, line_segments, write_targets,
+    heredoc_events, interpreter_invocation, line_segments, literal_writes, write_targets,
+# Because a redirect can sit glued to a name, as in f<<<w.
+REDIRECT_SPLIT_RE = re.compile(r"[<>&|]+")
-    payload_start = reachable_directories(command, cwd)
+    targets = _scan_targets(command)
+    texts, unresolved, seen = _gathered(targets, cwd, reachable_directories(command, cwd))
+    appended = {write.path for target in targets for write in literal_writes(target) if write.append}
+    changes = [_landing(path, text, cwd, seen, path in appended) for path, text in texts.items()]
+    return tests_policy.findings(gate, changes, unresolved)
+def _gathered(targets: list[str], cwd: Path, payload_start: Directories) -> tuple[dict[str, str | None], list[str], Counter[Path]]:
+    """Writes and names counted apart, because a literal lands only when neither sees its path twice."""
-    for position, target in enumerate(_scan_targets(command)):
+    writes: Counter[Path] = Counter()
+    named: Counter[Path] = Counter()
+    for position, target in enumerate(targets):
+        writes.update(payloads.resolved_path(path, cwd) for path in paths)
+        named.update(_named_paths(target, scope))
-    changes = [
-        tests_policy.PendingChange(path, tests_policy.read_before(payloads.resolved_path(path, cwd)), text)
-        for path, text in texts.items()
-    ]
-    return tests_policy.findings(gate, changes, unresolved)
+    return texts, unresolved, writes | named
+def _named_paths(command: str, scope: Scope) -> Counter[Path]:
+    """Under every folder a segment may run in, because ed or a generator rewrites a file it only names."""
+    named: Counter[Path] = Counter()
+    segments = line_segments(command)
+    folders = segment_directories(segments, scope.directories, command_expansions(command, scope.cwd).path)
+    for segment, places in zip(segments, folders):
+        words = sorted({part for word in segment for part in REDIRECT_SPLIT_RE.split(_bare(word)) if part})
+        named.update({payloads.resolved_path(path, scope.cwd) for path in joined_paths(words, places or OUTER_START)})
+    return named
+def _landing(path: str, text: str | None, cwd: Path, writes: Counter[Path], append: bool) -> tests_policy.PendingChange:
+    """Text kept for a lone write only, because a later append, copy, or edit lands other bytes than the literal."""
+    resolved = payloads.resolved_path(path, cwd)
+    before = tests_policy.read_before(resolved)
+    if text is None or writes[resolved] > 1:
+        return tests_policy.PendingChange(path, before, None)
+    return tests_policy.PendingChange(path, before, (before or "") + text if append else text)
```

### `hooks/record.py`

```diff
-    if len(raw) > limit or b"\0" in raw[:8192]:
+    if len(raw) > limit or b"\0" in raw[:scan_input.CONTENT_SAMPLE_BYTES]:
```

### Documents

1. `CHANGELOG.md` gained the `## 0.32.0 (2026-10-30)` section with three groups and eight bold-lead bullets.
2. `README.md` line 3 changed from `Current release: **0.31.1**.` to `Current release: **0.32.0**.`. The binary paragraph near line 51 now describes signatures and the one-third share, and the test writer section gained a paragraph on declared tests.
3. `docs/plans/2026-10-30-declared-tests-and-binary-content.md` is new, and so is this protocol.

## Tests

The `adw-test-writer` agent changed four test files and added three. I spawned it first as a named teammate, and the gate rejected its writes, because that hook payload carries no agent type. A plain subagent spawn then carried `adw-test-writer`, and the gate let it write.

### Changed test files

1. `hooks/test_tests_policy_gate.py`. The three empty-file cases of `test_common_test_shapes_count_as_tests` now write a real test to the same path and block. `test_an_empty_file_under_a_test_name_is_no_test` shows that the empty files pass. `test_deny_blocks_a_shell_write_whose_landing_text_may_be_a_test` holds seven shell cases (append, `cp`, `ed`, glued `ex`, `ed` after `cd sub`, a helper in `tests/`, an append that completes a test). `test_deny_passes_a_lone_shell_literal_that_declares_no_test` holds three passing ones.
2. `hooks/test_tests_policy_targets.py`. `pkg/foo_test.go` and `src/BarTests.java` left the name-only list. `test_deny_blocks_a_declared_test_under_a_test_name` blocks a Go test and a JUnit test at those paths, and `test_deny_passes_code_without_a_test_under_a_test_name` passes plain code there and the production module `hooks/lib/test_source.py`.
3. `hooks/test_binary_assets.py`. All format cases carry ids, and `data.bin` holds `bytes(range(256)) * 32`, so density decides it. `test_an_installed_executable_skips_the_post_write_scan` covers the reported bug with an extensionless Mach-O, a Mach-O named `2.1.312`, and an extensionless ELF. `test_binary_bytes_do_not_exempt_text_paths` gained an extensionless `README` with a NUL byte, which stays unscannable.
4. `hooks/test_read_only_shell_routes.py`. `test_deny_passes_a_home_archive_of_plain_members` covers `~/`, `"$HOME/..."`, `${HOME}`, and a named member. `test_deny_blocks_a_home_archive_with_a_test_or_a_kept_tilde` covers a test member, `'~/pkg.tgz'`, and `--file=~/pkg.tgz`.

### New test files

1. `hooks/lib/test_tests_policy.py` checks the decision order of `touches_tests` with 18 cases that touch tests and 9 that do not, including the fixture folders, `testdata/golden.txt`, `conftest.py`, and a Jest file with only `it.each`.
2. `hooks/lib/test_declared_tests.py` holds 53 cases that declare a test and 16 that do not, across every Python form and each language pattern, including `it.each`, `func Test_total`, and the rejected `func Testify`.
3. `hooks/lib/test_binary_content.py` holds 9 binary cases and 13 text cases, including whole-content density in both directions.

### Proof that the tests can fail

1. Against `HEAD` in `/tmp/adw_head/hooks`, 29 of the new tests failed, and both new lib files failed at import.
2. The blocking shell cases pass on `HEAD` too, because the old name rule blocked them. The test writer broke `_landing`, the redirect split, and the folder walk in a scratch copy, and each break failed its cases.
3. With the old `.each` and Go patterns restored in a scratch copy, five of the new cases failed.

### Results

1. `cd hooks && pytest . lib -q -p no:cacheprovider` passed with 6159 tests and 17 skipped in the test writer run.
2. `pytest pi/test_merge_settings.py -q` passed with 11 tests, and `cd pi && bun test` passed with 319 tests and no failure.
3. Pylint rated the code 10.00 out of 10 when I ran `uvx --python 3.13 --with pytest --with pyyaml pylint $(git ls-files '*.py')` with the new files added.
4. `bash -n` passed for every tracked shell script and the four `bin/` commands.
5. `claude plugin validate . --strict` failed on three warnings that this release does not touch, a missing `version` in `.claude-plugin/plugin.json`, `CLAUDE.md` at the plugin root, and a missing icon. ADW versions by commit, as `commands/update.md` says, so I left the manifest alone.
