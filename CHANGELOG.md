# Changelog

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
