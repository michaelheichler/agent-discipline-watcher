# Task 3 report: Claude native presets and role batching

## Implementation

- Carried the Task 2 breaker ruling first. Successful Luna worker responses now pass strict parent-side validation before a `JudgeResult` is returned or cached. Validation requires exact provider, model, effort, rubric identity, exact scalar types, `cached is False`, dict payload and usage values, the review-kind output schema, and valid candidate indexes. Malformed results become bounded `worker_protocol` failures and are never cached.
- Replaced the registered Claude subprocess review route with a generated, clearly marked native settings block. The block contains only `type: "agent"` handlers at `PostToolUse` and `Stop`; no native model handler is installed on `PreToolUse`.
- Added `mixed`, `luna`, `haiku`, and `sonnet` presets. `mixed` uses Haiku for post-write comments and Sonnet for one batched Stop review of prose/documents. The single-model presets use their literal model for both roles. Luna success uses the Task 2 provider without a parallel Claude spend; an unavailable Luna review emits bounded feedback and switches subsequent comment events to Haiku or prose/document events to Sonnet.
- Added `bin/adw-judge` and the namespaced plugin skill. The command accepts only the four presets or `status`, writes the selected preset and settings atomically, removes only ADW-marked generated agent hooks, preserves unrelated settings and deterministic plugin hooks, and is idempotent.
- Added exact remote-default selection (`CLAUDE_CODE_REMOTE == "true"` -> Haiku), plus explicit `ADW_CLAUDE_HAIKU_ONLY=1` support for Desktop/Cowork. Local default remains mixed.
- Added a bounded session candidate journal. It records only comment candidates and bounded prose/document context, deduplicates by final content hash, removes stale rows when content changes, and lets Stop inspect only the current session's candidates.
- Prompts require read-only inspection, bounded structured `ok` decisions, fail-open empty/malformed input, `stop_hook_active` loop protection, and post-write/Stop remediation semantics. Deterministic command hooks and hard gates remain unchanged.
- Removed production `claude -p` execution from the legacy judge helpers and removed the obsolete asynchronous `JudgeReview` registration and dispatch. No `codex exec`, API-key client, MCP judge, or Task 4 lifecycle work was added.

## Files

- `bin/adw-judge`
- `skills/adw-judge/SKILL.md`
- `hooks/lib/claude_native.py`
- `hooks/lib/claude_journal.py`
- `hooks/lib/test_claude_native.py`
- `hooks/lib/luna_provider.py`
- `hooks/lib/test_luna_provider.py`
- `hooks/lib/judge.py`, `hooks/lib/pattern_judge.py`, `hooks/lib/document_review.py`
- `hooks/record.py`, `hooks/hooks.json`, `hooks/run.sh`, `install.sh`
- `hooks/test_merge_configs.py`, `hooks/test_run_dispatch.py`

## TDD evidence

### Carried breaker

- RED: the adversarial worker-result tests failed with `AttributeError` because parent validation did not exist (13 failures).
- GREEN: after strict validation was added, the carried Luna provider tests passed (`43 passed`). The additional truthy non-boolean cache entry test first failed because the corrupted cache was accepted, then passed after cache reads reused the strict validator (`44 passed` for the provider suite).

### Native Claude behavior

- RED: new native tests initially failed at collection because `lib.claude_native` and the executable were absent.
- RED: journal stale-content, strict decision parsing, CLI argument validation, and Luna success/fallback tests each failed before their implementation paths existed.
- GREEN: the focused Task 3 command passed after each scoped implementation increment:

  `.venv/bin/python -m pytest hooks/lib/test_luna_provider.py hooks/lib/test_claude_native.py hooks/lib/test_judge.py hooks/lib/test_pattern_judge.py hooks/lib/test_document_review.py hooks/test_edit_journal.py hooks/test_plugin_wiring.py hooks/test_merge_configs.py hooks/test_run_dispatch.py -q`

  Result: `181 passed, 1 skipped, 54 subtests passed in 5.85s`.

## Full required suites

- `.venv/bin/python -m pytest hooks/lib -q` -> `695 passed, 17 skipped, 50 subtests passed in 19.42s`.
- `.venv/bin/python -m pytest hooks/test_*.py -q` -> `963 passed, 1 skipped, 218 subtests passed in 22.78s`.
- `.venv/bin/python -m pytest pi/test_merge_settings.py -q` -> `11 passed in 0.65s`.
- `bash -n install.sh hooks/run.sh pi/install.sh`, Python compile checks for the changed modules, and `git diff --check` all exited 0.

Combined full evidence: `1,669 passed, 18 skipped, 268 subtests passed`.

## Self-review

- Confirmed the deterministic `PreToolUse` hard gate and command hooks remain in the plugin manifest; native agents are confined to post-write and Stop lifecycles.
- Confirmed generated settings preserve unrelated values and hooks, remove only marked ADW agent entries, and switch idempotently through atomic replacement. Prompts use literal static model fields and do not use undocumented async, allowlist, or dynamic-model fields.
- Confirmed candidate journal bounds, final-content deduplication, stale-row cleanup, role batching, session scoping, and unrelated-file exclusion are covered by tests.
- Confirmed remote selection is exact, Desktop/Cowork Haiku selection is explicit, Luna success does not invoke a fallback, and Luna failure transitions once for subsequent events.
- Confirmed production search finds no `claude -p`, `codex exec`, API-key judge, or MCP judge path. Credential-like strings remain only in existing negative tests.
- Confirmed the worktree is clean after the focused commits and final verification.

## Concern

Claude native agent settings cannot directly execute the Python Luna provider themselves. The generated `luna` profile therefore carries the static literal `model: "luna"` and explicit route prompt, while `luna_review()` is the provider-facing integration helper and owns the no-double-spend fallback transition. A future host adapter may need to connect Claude's native Luna route to that helper without adding a sibling fallback.

## Commits

- `f827e4d fix: validate successful Luna worker results`
- `4499399 feat: add native Claude judging presets`
- `dddb1bc fix: route native Claude failures safely`

## Fix round 1

### Changes

- Corrected the Luna preset to generate marked command handlers on `PostToolUse` and `Stop`. The handlers run the Task 2 `LunaJudge` through `claude_luna.sh`; no generated Luna entry has `type: "agent"` or `model: "luna"`.
- Added live Luna routing. PostToolUse extracts candidates directly from the raw host event and the just-edited eligible Python file, without waiting for the parallel deterministic journal hook or copying raw tool content into the judge request. Stop reads only the bounded current-session document rows through `read_claude_journal.sh` and batches them into one document `JudgeRequest`.
- Added bounded result-to-feedback conversion. Comment findings become PostToolUse continuation context; document findings become bounded Stop feedback. Provider and malformed-result failures produce one bounded actionable message and use the existing atomic role fallback transition. A later failure reports the already-configured fallback instead of switching again.
- Added `read_claude_journal.py` and its exact resolver-backed shell entrypoint. It accepts exactly one validated session id and returns only bounded document rows.
- Updated native prompts for parallel-hook ordering. PostToolUse uses only the raw host event and scopes to the just-written file. Native Stop prompts name the exact journal reader helper and forbid direct state or unrelated-file scans.
- Replaced the `env python3` `bin/adw-judge` shebang with a resolver-backed shell launcher. It validates exactly one allowed argument before selecting the newest compatible Python, then invokes the Python module without unsafe argument interpolation.
- Managed settings regeneration now removes both marked/native agent entries and Luna command entries while preserving unrelated hooks. Existing exact remote default and explicit Desktop/Cowork Haiku behavior remains unchanged.

### TDD evidence

RED commands and observed output:

- `.venv/bin/python -m pytest hooks/lib/test_claude_native.py hooks/lib/test_claude_luna.py -q` -> collection failed with `ImportError: cannot import name 'claude_luna'`; the live handler did not exist.
- After the first implementation, the managed-entry, launcher, and old Luna profile assumptions failed (`3 failed`), exposing stale command cleanup, CLI module execution, and updated preservation assertions.
- `.venv/bin/python -m pytest hooks/lib/test_claude_native.py::test_managed_luna_command_and_agent_entries_are_replaced_without_touching_unrelated_hooks -q` -> failed because an unmarked stale `claude_luna.sh` command was retained.

GREEN commands and observed output:

- `.venv/bin/python -m pytest hooks/lib/test_claude_native.py hooks/lib/test_claude_luna.py -q` -> `35 passed in 0.68s`.
- `.venv/bin/python -m pytest hooks/lib/test_claude_native.py hooks/lib/test_claude_luna.py hooks/lib/test_luna_provider.py hooks/lib/test_judge.py hooks/lib/test_pattern_judge.py hooks/lib/test_document_review.py hooks/test_plugin_wiring.py hooks/test_merge_configs.py hooks/test_run_dispatch.py -q` -> `174 passed, 1 skipped, 54 subtests passed in 7.12s`.
- `bash -n install.sh hooks/run.sh pi/install.sh hooks/claude_luna.sh hooks/read_claude_journal.sh bin/adw-judge`, Python compile checks for changed modules, and `git diff --check` exited 0.

### Full required suites

- `.venv/bin/python -m pytest hooks/lib -q` -> `707 passed, 17 skipped, 50 subtests passed in 20.26s`.
- `.venv/bin/python -m pytest hooks/test_*.py -q` -> `963 passed, 1 skipped, 218 subtests passed in 22.88s`.
- `.venv/bin/python -m pytest pi/test_merge_settings.py -q` -> `11 passed in 0.63s`.

Combined fix-round evidence: `1,681 passed, 18 skipped, 268 subtests passed`.

### Self-review

- Confirmed only non-Luna presets generate native agent handlers, and only on `PostToolUse` and `Stop`. Luna generates command handlers on both lifecycles and never spends a sibling Claude fallback on a successful Luna result.
- Confirmed PostToolUse Luna requests are built from the event's own eligible paths and current file candidates, while Stop requests use only `read_for_stop()` rows for the exact session. Missing, malformed, irrelevant, already-active Stop, and empty-journal inputs fail open without a provider call.
- Confirmed feedback is bounded and role-specific, provider failures transition atomically only while Luna remains active, and a repeated failure does not claim a second transition.
- Confirmed the journal reader's one-argument shell path uses the shared newest-compatible Python resolver and rejects unsafe session ids through the Python boundary. The preset launcher validates exact argv before resolution.
- Confirmed settings cleanup recognizes both native agent markers and Luna command paths, preserves unrelated hook groups, and keeps exact remote/Cowork selection semantics.
- Confirmed no Task 4 files or lifecycle work were changed, and production search still finds no `claude -p`, `codex exec`, API-key judge, or MCP judge path.

### Concern

The native Stop agent invokes the exact journal reader through its available inspection tools, so the prompt remains an instruction rather than a hard tool-security boundary, consistent with the Claude hook contract. The helper itself is deterministic, session-scoped, bounded, and read-only; generated command handlers bypass that agent-tool limitation for Luna reviews.
