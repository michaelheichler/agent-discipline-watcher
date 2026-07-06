# Professional Agent Helper Integration Requirements

## As Is

Agent Discipline Watcher installs one combined hook runner for SessionStart, PreToolUse, PostToolUse, and Stop. SessionStart clears the watcher ledger and emits a short discipline reminder. Professional Agent Helper exists as a separate source repo with persona sections, a UserPromptSubmit refresher, and a deterministic Stop tell gate.

## To Be

Agent Discipline Watcher remains the single combined watcher repo and hook runner. It contains the Professional Agent Helper persona text, emits the full charter once at SessionStart while preserving the watcher reminder and ledger reset, emits the compact REFLEX on each UserPromptSubmit with NUDGE only for correction or challenge prompts, and blocks empty validator tells in the existing Stop hook.

## Requirements

1. Copy Professional Agent Helper persona sections CHARTER, REFLEX, and NUDGE into the watcher repo with text preserved exactly.
2. Add a minimal section reader for the watcher persona file.
3. Add a UserPromptSubmit hook route that emits `hookSpecificOutput.additionalContext` with REFLEX on every prompt and NUDGE when English or German correction cues match.
4. Update SessionStart so it clears the ledger and emits both the PAH CHARTER and the existing watcher reminder.
5. Add deterministic PAH tell scanning to the existing Stop pipeline.
6. Update hook runner and Claude/Codex snippets so UserPromptSubmit is installed through the watcher runner.
7. Update merge logic so legacy standalone PAH hooks are removed when watcher hooks are installed.
8. Keep existing PreToolUse, PostToolUse, Stop findings, Pi, scanner, and config behavior unchanged.

## Acceptance Criteria

1. Persona sections can be read from the watcher repo and match the source PAH section text.
2. Missing persona fences produce an empty section rather than crashing the hook.
3. A neutral UserPromptSubmit prompt emits REFLEX and does not emit NUDGE.
4. Correction prompts including `But what about cache invalidation?` and German examples emit REFLEX plus NUDGE.
5. SessionStart clears stale ledger entries and emits the PAH charter plus the watcher reminder.
6. Claude merge adds exactly one UserPromptSubmit watcher hook and removes legacy PAH entries.
7. Codex merge adds a UserPromptSubmit watcher hook and removes legacy PAH entries.
8. Stop blocks empty validators and flattery tells from the assistant reply.
9. Existing watcher tests for PreToolUse, PostToolUse, Stop findings, Pi, scanner, and config pass.
10. Python compile checks and shell syntax checks pass.

## Testing Plan

Run focused tests for persona reading, prompt injection, SessionStart, Stop tell scanning, hook routing, and config merge behavior first. Then run every existing watcher test script, Python compile, and shell syntax checks.

## Implementation Plan

1. Add tests for persona sections, UserPromptSubmit, SessionStart output, Stop tell scanning, run.sh routing, and merge behavior. Run them to confirm they fail before implementation.
2. Add `hooks/persona.md`, `hooks/lib/persona.py`, and `hooks/lib/correction.py`. Run the new persona and correction tests.
3. Add `hooks/prompt_inject.py`, update `hooks/lib/hookio.py` if needed, and route UserPromptSubmit in `hooks/run.sh`. Run focused hook tests.
4. Update `hooks/session_start.py` to compose CHARTER and the watcher reminder while preserving ledger reset. Run SessionStart tests.
5. Add deterministic tell scanning inside `gate.py`. Run Stop tests for PAH tells and existing watcher findings.
6. Update Claude and Codex snippets plus merge legacy names. Run merge tests.
7. Update README.md and SKILL.md only for the new integrated PAH behavior. Run full verification.
