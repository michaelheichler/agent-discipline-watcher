# Changelog

## Unreleased

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

- Passed 1,112 tests and 227 subtests.
- Passed pylint at 10.00/10 on all tracked Python files.
- Ran the repository's own review against itself. No blocking findings remain
  that were introduced by this change set.

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

## 0.16.2 - 2026-08-14

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

## 0.16.1 - 2026-08-13

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

## 0.16.0 - 2026-08-13

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

## 0.15.0+shame.2 - 2026-08-13

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

## 0.15.0+shame.1 - 2026-08-13

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
