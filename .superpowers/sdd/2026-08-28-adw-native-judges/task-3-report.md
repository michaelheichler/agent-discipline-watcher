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
