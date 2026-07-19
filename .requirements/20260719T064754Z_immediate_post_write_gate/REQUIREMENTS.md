# Immediate Post Write Gate

## As Is

Claude Code and Codex register Agent Discipline Watcher for PreToolUse, PostToolUse, and Stop. PreToolUse blocks forced findings before direct write tools run. PostToolUse rescans the resulting file but only records findings for Stop. Pi rescans write results but reports remaining forced findings only at agent end.

## To Be

Direct write tools remain blocked before execution when their pending content contains forced findings. If a finding is visible only after execution, Claude Code and Codex receive an immediate blocking hook error, and Pi receives an immediate error tool result that requires correction before normal work continues.

## Requirements

1. PostToolUse must rescan each edited file and immediately block on forced punctuation, English, clean code, or suppression findings.
2. Clean or advisory only post write results must remain nonblocking.
3. Pi write, edit, and multiedit results with forced findings must immediately become error results containing the repair report.
4. Existing Stop rescans and pre write prevention must remain as fallback enforcement.
5. Installer hook registration must remain idempotent with one watcher hook per lifecycle and client.

## Acceptance Criteria

1. A PostToolUse fixture containing a banned dash exits the shell hook with status 2 and reports `punctuation/banned_dash`.
2. A clean PostToolUse fixture exits with status 0, while advisory only findings do not produce a blocking result.
3. The Pi extension returns `isError: true` and a compact repair message immediately from `tool_result` when forced findings exist.
4. Existing PreToolUse and Stop tests remain green.
5. Reinstalling twice leaves no duplicate Claude, Codex, or Pi watcher registrations.

## Testing Plan

- Add Python unit tests for forced and clean PostToolUse results.
- Add a shell routing test that proves PostToolUse exits 2 with the forced rule on stderr.
- Extend the Pi contract test to require immediate error result behavior.
- Run the full Python test suite, shell syntax checks, installer idempotence tests, and live configuration audit.

## Implementation Plan

1. Add the failing PostToolUse tests and Pi contract assertion, then run only those tests to prove red.
2. Return a compact blocking result from the post write recorder and translate it to exit status 2 in command mode, then rerun the focused Python tests.
3. Return an immediate Pi error result for forced findings, then rerun the Pi contract test.
4. Update lifecycle documentation, run the full suite, install twice, and audit live hooks on Mac and x86-host.
