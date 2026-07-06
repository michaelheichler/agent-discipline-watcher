# Combined Watcher Requirements

## As Is

The current setup runs three separate skills for one policy family.

1. `punctuation-discipline` scans punctuation.
2. `english-for-agents` scans prose.
3. `clean-coder-discipline` scans code and also ships a punctuation sibling path.

Claude, Codex, and Pi each load these as separate hooks or extensions. A single edited line can appear in several gate reports. Stop output includes full offending lines and per-line explanation. Two or three blocked turns can put too much repeated text into context.

## To Be

Create `agent-discipline-watcher` as one combined skill. It owns one detector runner, one ledger, one Stop report, one Pi extension, and one installer.

The watcher supports three feature switches per project.

1. Punctuation.
2. English.
3. Clean code.

The watcher keeps full finding detail in a local report file. Hook output to the model is compact and ranked. The default report does not print full offending lines.

The watcher keeps fast regex checks for write-time blocking. At Stop it also judges touched prose and code files with the old English and Clean Coder model paths when the relevant family is enabled and model load gates allow it. Model errors fail soft. Model unload and host release are attempted after Stop.

## Requirements

1. The new skill is separate from `professional-agent-helper`.
2. The new skill can scan punctuation, prose, and clean-code findings through one Python API.
3. The new skill stores findings for a session in one ledger.
4. The Stop hook emits one compact report across all enabled checks.
5. The report includes file, line, rule, policy family, and short action.
6. The report caps model-facing rows and points to a local full report path.
7. The PreToolUse hook denies force-level pending writes through one hook.
8. The PostToolUse hook records edited files through one hook.
9. The SessionStart hook injects one compact policy prompt.
10. The CLI can configure a project with selected checks.
11. The CLI can show effective project config.
12. The installer can install Claude, Codex, and Pi support.
13. The installer removes legacy `punctuation-discipline`, `english-for-agents`, and `clean-coder-discipline` hook or extension entries for selected clients.
14. Pi uses one extension path for this watcher.
15. The Stop hook runs model-backed English and Clean Coder judging over touched files without re-enabling old hook surfaces.
16. Model-backed English findings are advisory and use the normalized English finding shape.
17. Model-backed Clean Coder findings use the normalized clean-code finding shape and preserve force decisions from the deep judge.
18. Clean touched files stay in the ledger even when regex findings are empty, so Stop-time judging still has work.
19. Model load gates, unload, and host turn release are fail-soft.

## Acceptance Criteria

1. No file in `agent-discipline-watcher` imports or shells into `professional-agent-helper`.
2. `scan_all(path, text, config)` returns normalized findings with a `family` field.
3. Ledger files are named for `agent-discipline-watcher`, not the old skills.
4. One Stop hook response includes findings from all enabled families.
5. Default Stop output has no full source line dump.
6. Full details are written under a temp report path with `0600` permissions.
7. A pending write with an em dash is denied by the combined PreToolUse hook.
8. A pending prose write with `utilize` is denied when English is enabled.
9. A pending code write with a deferred-work marker is denied when clean code is enabled.
10. `agent-discipline configure` writes project config.
11. `agent-discipline status` prints project config.
12. Local Claude settings contain one watcher entry per lifecycle after install.
13. Local Codex config contains one watcher entry per lifecycle after install.
14. Local Pi settings contain one watcher extension after install.
15. Legacy entries for the three old skills are absent after replacement.
16. A touched prose file can produce an advisory English model finding at Stop.
17. A touched code file can produce a Clean Coder model finding at Stop.
18. A touched code file with no regex findings is still sent to the Stop jury.
19. Stub tests prove unload runs even when a model call fails.

## Testing Plan

1. Unit test normalized scanning.
2. Unit test compact formatting and full report writing.
3. Unit test ledger record, read, and clear behavior.
4. Unit test PreToolUse pending extraction and denial.
5. Unit test config discovery and CLI writes.
6. Unit test Claude, Codex, and Pi config merge cleanup.
7. Syntax check Python and TypeScript files.
8. Run local install in dry-run or temp-home mode before touching live configs.
9. Stub model tests verify Stop-time jury calls and unload without MLX, GGUF, or real model downloads.

## Implementation Plan

1. Worker A creates the Python scanner, ledger, formatter, and hook entry points.
2. Worker B creates the CLI and config merge or installer code.
3. Worker C creates the Pi extension and tests for the extension contract.
4. Main agent reviews and integrates the worker diffs.
5. Main agent runs verification.
6. Main agent updates docs to describe the hybrid regex and model-backed runtime.
7. Controller handles install and any `x86-host` sync outside this implementation task.
