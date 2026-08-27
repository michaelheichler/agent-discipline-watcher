# Changelog

## 0.18.0 (2026-08-27)

### Added

- The 98 stop-slop patterns are detected. `hooks/lib/slop_phrase.py` carries the weighted marker and formulaic phrase rules, `hooks/lib/slop_structure.py` carries the ten structural categories, and `prose_structure.py` gained the rhythm statistics. Coverage was 6 of 98 before this release.
- A judgement layer for the comments the deterministic rules cannot decide. `hooks/lib/narration_candidates.py` selects lines that open on a behaviour verb and still carry a why marker, which is exactly the set `_has_strong_why_marker` lets through today. `hooks/lib/judge.py` sends them to Haiku through the Claude Code session login, with `ANTHROPIC_API_KEY` stripped from the subprocess so no key is spent, and `ADW_JUDGE_ACTIVE` set so a nested hook cannot recurse. 22 such lines exist in this repository and the judge calls 21 of them narration.
- `hooks/judge_review.py` on the `JudgeReview` route, registered as a second `PostToolUse` group over `Write|Edit|MultiEdit` with `async` and `asyncRewake`. It returns no permission decision, so it delays no write and weakens no gate. It wakes the session on exit 2 with one line per finding. Every deny-capable route still fails the merge-config async guard.
- `hooks/lib/embedding_client.py` and `hooks/lib/embedding_lease.py`. The client speaks the OpenAI embeddings contract over an ordered host list, so the MLX server on a Mac and the GGUF server on an x86 box answer the same call and the first reachable host wins. An absent server returns None rather than raising, a 5xx is retried, and a 4xx raises because a wrong model or route is a configuration defect. The lease is refcounted per session, so the model loads once per machine rather than once per subagent, and a crashed session frees it through a dead-pid probe and a 900 second sweep.
- Both embedding hosts are verified. The Mac serves `LFM2.5-Embedding-350M-bf16` under MLX on port 8000, and the x86 box serves `LFM2.5-Embedding-350M-Q8_0.gguf` under llama.cpp on port 8014, woken on demand by its router at `/embed/v1/embeddings`. Both return 1024 dimensions, so the two hosts share one vector space and failover between them is sound. The router binds loopback, so the fallback URL is a forwarded port: `ssh -f -N -L 8100:127.0.0.1:8000 x86-host`.
- `hooks/lib/slop_exemplars.jsonl`, 86 phrase exemplars rebuilt deterministically from the stop-slop reference files by `evals/build_slop_exemplars.py`. Single-word entries stay in the regex layer, where an exact literal belongs.

### Changed

- `passive_voice` catches the irregular participles. `be` plus an `ed` or `en` suffix is blind to `was built`, `is set`, `is read` and `was rebuilt`, which carried 10 of 13 real passives in a tracked sample. Detection is now 13 of 13 with no hit on six active-voice controls.
- The sentence length cap is derived per document from Tukey's upper fence rather than fixed, and `SENTENCE_VARIATION_LIMIT` moved from 0.32 to 0.16, the measured p05 of 709 real paragraphs. The old value sat near the median and flagged 33.85 percent of ordinary writing.
- Headings, setext underlines, and list-item labels are masked before the phrase rules run, so a title is no longer scanned as prose.

### Measured and not shipped

- `hooks/lib/slop_semantic.py` stays unwired, and a test fails if it reaches the scanner. Nearest-exemplar cosine caught at most 1 of 273 regex-confirmed pattern sentences at any cutoff whose hit rate on the other 2393 stayed under 1 percent. A general embedding measures topic and these patterns are topic-free structures, so no threshold separates them. `evals/measure_slop_semantic.py` reproduces the numbers.

## 0.17.8 (2026-08-26)

### Changed

- `config_seal` no longer blocks every edit to an existing `.agent-discipline.json`. It reads the pending content and blocks only a write that would weaken the gates, so adding a path exemption or turning one family off is the human's to make again. A write whose body the gate cannot read still fails closed, and so does a delete or a truncate.

### Fixed

- `grants_escape` missed two ways to silence the watcher through its own config. A `kill_switches` entry for every family reaches the gates through a key the gate map never reads, and a tree-wide `exempt_paths` or `exempt_families` glob suppresses every scanned file. Both were caught only by the blanket seal, so both are now detected on their own terms.

## 0.17.7 (2026-08-26)

### Added

- `hooks/lib/findings.py` holds the finding value objects. `Finding` and `Rule` are frozen slotted dataclasses that validate their own invariants and raise on an empty family, a line below one, an empty action, or an unsupported key. `Outcome` and `VerdictKind` are string enums, so ledger rows still serialize and compare as bare strings for consumers outside the process. Serialized output is unchanged, key order included.
- `hooks/lib/shell_syntax.py` carries tokenizing, segmentation, pipeline grouping, and interpreter resolution, split out of `hooks/lib/shell_parse.py` along the dependency direction. Write and heredoc detection stay behind, because heredoc bodies and write targets are mutually dependent and separating them would create an import cycle. `shell_parse.py` re-exports every moved name, so existing imports keep resolving.
- `session_state.read_state_strict` and `session_state.update_state_strict`. `advance_turn` now uses the strict path, so a corrupt state file raises instead of silently returning an empty dict and erasing unresolved blockers.
- Parameter objects for the wide hook signatures: `StorageRoots`, `BlockerScope`, `McpRunContext`, `DecisionRecord`, `HeartbeatRecord`, `LedgerInvocation`, `Adjudication`, `ShapedWrite`, and the per-hook run contexts.

### Changed

- Every comment and docstring in non-test source now states why the code is the way it is, or is gone. That closed 70 `what_docstring`, 2 `what_comment`, and 2 `prose_comment_block` findings in the watcher's own source.
- Deep nesting is gone from non-test source. 18 functions were flattened with guard clauses and named helpers, including the parsers behind the write and opaque-write gates, with behaviour held identical.
- Return types are declared on every non-test library function.
- Prose findings fixed in `README.md`, `CHANGELOG.md`, `tasks/plan.md`, and `tasks/spec-bash-write-guard.md`.

### Removed

- A duplicate command line interface in `hooks/lib/reporting.py`. `_main`, `_observe_report_command`, and `_adjudicate_command` were unreachable, nothing invoked `python3 -m lib.reporting`, and `bin/agent-discipline` already exposes all three commands.

### Known remaining

- 11 functions still take four or more parameters. Two cannot change shape because behavioural tests call them positionally, `pre_commit.run` and `scan_input.int_setting`. The rest are judged not to improve from a parameter object.
- Two `long_sentence` findings in `LICENSE`. The MIT text is verbatim and rewording it would change its legal meaning, so it needs an `exempt_families` entry rather than an edit.
- `hooks/batch.py` and `hooks/lib/scanner.py` carry a file length warning.

## 0.17.6 (2026-08-26)

### Changed

- Self-protection no longer polices file access across a client home. The `live_client_surface` rule, which blocked every path under `~/.claude`, `~/.codex`, `~/.pi`, `~/.omp`, `~/.agents/skills`, and `~/.config/opencode`, is replaced by two narrower rules. `watcher_install_surface` blocks writes to the watcher's own install directories and to `~/.local/bin/agent-discipline*`. `watcher_wiring_removal` blocks a write to a client settings file only when it drops the watcher's hook entries, so unrelated edits to those files now pass. Which files an agent may touch is a host permission setting, not a watcher rule. `~/.claude/CLAUDE.md` and shell rc files are no longer protected.
- The install block message states that `ADW_ALLOW_PROTECTED_EDIT` releases every self-protection rule rather than presenting it as a routine escape.

### Fixed

- A read argument in a shell segment is no longer treated as a write target. `python3 ~/.claude/plugins/x/audit.py doc.md > report.json` blocked because the redirect made every path in the segment count as a write, which stopped agents from running audit scripts that live under a client home. Shell write targets now resolve through the same verb-aware rules the live-path check already used, so a copy source, a grep root, and a script argument stay reads.

## 0.17.5 (2026-08-24)

### Fixed

- `pi/install.sh --remove` no longer deletes a real directory or a symlink owned by another install at `~/.omp/agent/extensions/agent-discipline-watcher`. Removal now matches the Claude legacy-link guard: only unlink when the path is our own symlink target.

## 0.17.4 (2026-08-24)

### Added

- OMP (`oh-my-pi`) support: `pi/extensions/agent-discipline-watcher/` is an `ExtensionAPI` extension that calls the same `hooks/run.sh` engine as Claude Code and Codex. It gates `write`/`bash` on `tool_call`, rescans touched files on `tool_result` (including hashline `[path#TAG]` and `MV` destinations), injects the SessionStart contract on the next turn, and blocks unresolved findings on `session_stop`.
- Dedicated OMP installer at `pi/install.sh`: symlinks the extension into `~/.omp/agent/extensions/agent-discipline-watcher`, registers it in `settings.json` via `pi/merge-settings.py`, supports `--remove`, and honors `PI_CODING_AGENT_DIR`.
- Main `install.sh` gains `--omp` / `--no-omp` flags and delegates OMP wiring to `pi/install.sh`. Selective installs (`--claude`, `--codex`, `--omp`) no longer touch the other harnesses.
- Installer tests for OMP target isolation, idempotent registration, and profile-aware agent directories.

### Fixed

- `hooks/lib/protected.py` now treats `~/.omp` as a protected client home alongside `.codex` and `.pi`, so agents cannot disable the watcher by editing OMP's live config.
- OMP `session_stop` accepts both `stop_hook_active` and `stopHookActive` for retry-pass state.
- OMP `PostToolUse` payloads send only `{ file_path }` for resolved paths, while bash keeps `{ command }` for write-path detection. Raw write content and hashline patch text are no longer forwarded.

## 0.17.3 (2026-08-23)

### Fixed

- A shell script with a `case`/`test` glob pattern like `"$root"/*)` or `== */*` no longer gets its whole tail treated as one unterminated comment. The block-comment scanner opens on any literal slash-star and, finding no matching star-slash closer in the script, used to fall back to end-of-file, turning every remaining line into one giant narrating comment block and flagging ordinary code as prose. Block-comment scanning is now skipped for `.sh`, `.bash`, `.zsh`, and `.ksh` files. `#`-style comment blocks in those files are still caught exactly as before.

## 0.17.2 (2026-08-23)

### Fixed

- `python3 -c`, `node -e`, and similar inline payloads no longer block on a read-only `open()`. The 0.17.1 rule flagged every `open(` call regardless of mode, so `open("x.txt").read()` and `open("x.txt", "r")` were treated the same as a write. The check now reads the mode argument: a missing mode (Python defaults to `'r'`), a literal made only of `r`, `b`, `t`, or `U`, clears the call. A write-capable literal (`w`, `a`, `x`, `+`), a mode built at runtime, or an unterminated call still blocks exactly as before.

## 0.17.1 (2026-08-20)

Agents were sneaking file writes past the watcher by going through Bash instead of the Write and Edit tools. This release closes those routes.

### Added

- Seven new blocking rules that no project config can turn off.

  Code the watcher cannot read before it runs:
  - Inline interpreter code that can write files, like `python -c`, `node -e`, or `php -r` with a write call inside. Harmless one-liners like `python3 -c 'print(1)'` still work.
  - Scripts fed into an interpreter through a heredoc or a pipe, like `python3 <<EOF` or `echo "..." | sh`. Content piped into a shell is checked as if you had run it directly.
  - Nested shells, meaning `sh -c` and quoted commands passed through `env -S`, which are unwrapped and checked all the way down.

  Content that reaches a file without passing a readable stage:
  - Heredocs aimed at a file whose content the watcher cannot read, for example when the body contains variables that only expand at run time.
  - Decode pipes that land bytes in a file, like `base64 -d`, `openssl enc -d -out`, or `uudecode`. Decoding to the screen stays allowed.
  - Opaque copy sources like `dd of=` and process substitution.

  Edits that bypass the Edit tool:
  - In-place editors, meaning `sed -i` in all its spellings, `perl -pi`, and `awk` or `gawk` with the inplace extension. Plain `sed` and `awk` transforms to the screen stay allowed.
- Regular Bash writes now get the same treatment as the Write and Edit tools. Overwriting a committed file reports old debt without blocking you for it. Appending only checks the lines you add, and appends that push a file past the length limit are blocked.
- Every block message names the rule and tells the agent to use the Write or Edit tool instead.

### Fixed

- Many trick spellings that used to slip through are now caught: quoted or versioned interpreter names (`'python3'`, `python3.12`), fused flags (`bash -lc`, `sed -Ei`), wrappers like `sudo` and `env` in front of the command, redirects placed before the command, interpreters in the middle of a pipeline, and write calls split across adjacent quoted strings.
- Fewer false alarms: `sed -fi` (a script file, not in-place), `xxd -r -o 16` (an offset, not an output file), `gawk -i somelib` (a library, not in-place), and appending to a file without a trailing newline no longer miscounts the file length.

### Notes

- Known remaining gaps are written down in the test suite so the next hardening pass starts from an honest list: echoing an expanded variable into a file, `curl` piped into `tee`, `python3 -m module` runs, and stream transforms into a new file.
- The human escape hatch is unchanged: setting `ADW_ALLOW_PROTECTED_EDIT=1` in your own shell releases all of these rules.

## 0.17.0 (2026-08-18)

### Fixed

- Narrowed `config.record_state_transitions` to catch only `(OSError, json.JSONDecodeError)`
  instead of a broad exception handler, and made a ledger write failure block the turn
  as undecidable instead of silently swallowing the error.
- Made `record.run` fail closed (block) instead of returning an empty response when
  `session_state.update_state` or `update_state_strict` raises on a write failure.
- Named the parse error and path on stderr when `.agent-discipline.json` is malformed,
  instead of falling back to defaults without any signal.
- Included the exit code and stderr detail in the `gitnexus` probe's degraded-state
  message instead of a bare "error" string.
- Fixed a non-atomic write in `merge-claude-settings.py` by reusing the same
  write-to-temp-then-rename pattern already used in `merge-codex-config.py`.
- Unified the two divergent trust predicates in `prompt_submit.py` (`prompt_firewall_mode`
  and `data_boundary`) so a dict-subclass config object is treated as untrusted
  consistently by both checks.
- Removed `hooks/claude-settings.snippet.json`. The Claude settings merge now writes
  its merged JSON directly and atomically instead of merging in a separate snippet file.

### Changed

- Split `hooks/lib/scanner.py` into `hooks/lib/comment_rules.py` and
  `hooks/lib/prose_structure.py`, and moved inline-code and hidden-text stripping
  into `hooks/lib/markup.py`, to keep the scanner module cohesive and avoid an
  import cycle across the split.
- Split shell-command parsing out of `hooks/pre_bash.py` into `hooks/lib/shell_parse.py`.
- Extracted `hooks/lib/canonical.py` and `hooks/lib/mcp_paths.py` from `hooks/batch.py`
  and `hooks/pre_mcp.py`, and consolidated duplicate test fixtures
  (`HostileDict`, `HostileString`, `CollidingKey`, batch test setup helpers) into
  shared `hooks/testing.py` and `hooks/conftest.py` modules.
- Extracted `scripts/eval_scoring.py` out of `scripts/run_evals.py`.
- Deleted the unused `_exact_string_dict` alias from `hooks/pre_mcp.py`.
- Reworked `hooks/lib/config.py`: removed `ALWAYS_ON_RULES`, added
  `project_config_path()`, and split gate/rule state resolution into
  `_gate_state_from` and `_rule_state_from`.

### Tests

- Added `hooks/test_batch_canonical.py`, `hooks/test_batch_correlation.py`, and
  `hooks/test_batch_race.py` to cover the batch module split.
- Added coverage for `gitnexus` degradation states, malformed `.agent-discipline.json`
  diagnostics, and ledger write failures.
- Updated `test_success_state_write_failure_preserves_record_response` in
  `hooks/test_failure.py` to assert the new fail-closed block response instead of
  the old empty-response behavior.

### Verification

- Passed 1,157 tests and 227 subtests after review triage.
- Passed pylint at 10.00/10 on all tracked Python files.
- Ran the repository's own review against itself. No blocking findings remain
  that were introduced by this change set.
- Triaged 39 automated PR review findings. 32 were confirmed by reproduction
  and fixed with regression tests, 7 were declined with stated reasons.

## 0.16.3 (2026-08-17)

### Fixed

- Named `ADW_ALLOW_PROTECTED_EDIT` in the `live_client_surface` block message, so a
  blocked `.claude/settings*.json` write no longer reads as unconditionally
  unblockable. The override already existed and stays env-var only.
- Masked Python string content before comment scanning. `.py` files were never
  string-masked the way JS and TS files are. A string literal starting with `//`
  or `/*` after whitespace was misread as a real comment. An unclosed `/*` inside
  a string, such as a glob fixture like `"generated/*"`, made the block comment
  regex swallow the rest of the file, corrupting every line after it.

### Verification

- Passed 1,055 tests and 213 subtests.
- pylint was not available in this environment and was not run.

## 0.16.2 (2026-08-14)

### Fixed

- Updated the Claude `PreToolUse` response to the current documented
  `permissionDecision: "deny"` shape without the deprecated top-level block.
- Enabled `continueOnBlock` for Claude `PostToolUse` hooks in plugin and legacy
  settings, so findings return to the agent for correction instead of ending the turn.
- Kept internal hard-block responses unchanged for tests and non-Claude clients.

### Verification

- Passed 1,026 tests and 212 subtests.
- Passed pylint at 10.00/10 and strict Claude plugin validation.
- Verified with a real Claude Code session: the first Write was denied, Claude
  corrected the comment, retried successfully, and completed without user input.

## 0.16.1 (2026-08-13)

### Fixed

- Restored a non-blocking file-length reminder at 500 lines.
- Added a stronger non-blocking file-length reminder at 750 lines.
- Kept the 1000-line source-file limit as an unconditional hard block.
- Made all three tiers survive clean-code switches, rule gates, kill switches,
  path exemptions, committed baselines, byte-scan caps, and staged-blob scans.

### Verification

- Passed 1,022 tests and 212 subtests.
- Passed pylint at 10.00/10 with `hooks/lib/scanner.py` at exactly 1000 lines.
- Verified live `run.sh PreToolUse` responses at 499, 500, 749, 750, 999,
  1000, and 1001 lines.

## 0.16.0 (2026-08-13)

### Changed

- Restored the complete pre-rewrite hard-block behavior while preserving later
  security, mixed-language, packaging, and pylint fixes.
- Enforced one strict WHY line for code comments and docstrings.
- Made WHAT comments, weak reasons, consecutive prose comments, and multi-line
  docstrings unconditional blockers that config and model output cannot release.
- Restored `Stop` and `SubagentStop` lifecycle routes and turn accounting.

### Fixed

- Removed semantic adjudication and cached release paths from write, post-write,
  and batch enforcement.
- Blocked strict findings in HTML comments, JavaScript block comments, malformed
  Python, tagged leading comments, and vague causal wording.
- Preserved JavaScript strings and structured license headers during comment scans.
- Kept Bash post-write scanning aligned across plugin and legacy Claude installs.

### Verification

- Passed 1,016 tests and 212 subtests.
- Passed pylint at 10.00/10 with the unchanged repository-wide command.
- Passed plugin validation, Python compilation, shell syntax, and black-box
  strict-policy probes.

## 0.15.0+shame.2 (2026-08-13)

### Fixed

- Restored the fixed repository-wide pylint gate to 10.00/10 without disabling
  messages, lowering thresholds, narrowing checked files, or pinning an older
  linter.
- Made `hooks/lib` an explicit package and aligned tests with production imports.
- Split scanner input policy and batch CLI tests into focused modules.
- Preserved exact built-in payload type checks without coercion.

### Verification

- Passed pylint at 10.00/10 with the unchanged CI command.
- Passed 1,007 tests and 202 subtests.

## 0.15.0+shame.1 (2026-08-13)

### Changed

- Restored deterministic hard blocking for enforce-mode findings.
- Limited semantic adjudication to ambiguous comment and docstring findings.
- Added content-addressed verdict reuse across write hook phases.
- Capped adjudication below the Claude hook deadline and bounded hook responses.
- Replaced language-specific mixed-file scanning with canonical source regions.
- Kept the existing Codex `PreToolUse` route and `PreCommit` compatibility alias.

### Fixed

- Rejected malformed hook payloads instead of allowing sensitive writes.
- Preserved unconditional blockers during baseline subtraction.
- Prevented script strings from being scanned as source comments.
- Scanned ANSI-C quoted commit messages containing escaped apostrophes.
- Resolved relative write baselines against the payload working directory.
- Prevented released ambiguous findings from being blocked again after writing.
- Removed automatic source, post-write, and commit-message mutation.

### Archived

- Moved the OpenCode adapter and its tests to `archive/integrations/opencode/`.
- Moved the Pi extension, tests, and settings merger to `archive/integrations/pi/`.
- Removed OpenCode and Pi from active installation, CI, release, and support claims.

### Removed

- Removed the rewrite engine and its tests.
- Removed embedding-based review and tool-report lifecycle code.
- Removed active Pi settings merge and adapter installation paths.

### Verification

- Passed 1,007 tests and 202 subtests in the main worktree.
- Passed the direct release matrix for deterministic blocks, ambiguous verdicts,
  timeout denial, cache invalidation, mutation protection, response limits, and
  sandboxed Codex routing.
