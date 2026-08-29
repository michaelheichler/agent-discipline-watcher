# Task 4 report: Codex synchronization and context budget

## Outcome

Codex now has checked-in `Stop` and `SessionEnd` command routes using only
documented command-hook fields. `Stop` runs the deterministic unresolved-state
gate first, then reviews the bounded current-session candidate journal once per
turn with GPT-5.6 Luna at high effort. A successful review allows completion;
an unavailable runtime, subscription, model, or provider returns one bounded
actionable block and never selects a Claude, API-key, MCP, or `codex exec`
fallback. `SessionEnd` releases the session lease and returns `{}`.

SessionStart and SubagentStart now emit one short contract through one
model-visible `additionalContext` channel. The full readable-output skill and
the duplicate `systemMessage` channel were removed. Codex hook responses cap
each message field before serialization and stay within the 4 KiB response
budget.

Candidate/reporting changes add content hashes, canonical paths, and
session/turn-aware deduplication. Batch correlation reads only a bounded tail
for the current session and turn. The installer provisions the persistent,
ADW-owned `~/.adw/runtime/codex/venv` with pinned
`openai-codex==0.147.0`, uses that interpreter for the production Luna worker,
and leaves unrelated `~/.codex/hooks.json` untouched. Runtime storage is
outside retention cleanup. README guidance now describes Codex subscription
auth, presets, Desktop/Cowork selection, retention, and repair actions;
stale `WATCHDOG.yml` advisor settings were removed.

## Test audit

Removed six `ReadableOutputInjectionTests` that asserted the obsolete full
skill injection and its helper parser. Removed two duplicate SessionStart
tests in `hooks/test_hooks.py`. The focused Task 4 tests retain the observable
single-channel contract, no-readable-skill boundary, Stop once-per-turn
review, bounded failure, lease release, ledger bound, dedup key, and message
cap checks. Existing lifecycle and merge tests were updated for the documented
Codex routes and environment marker.

## Verification

- Focused Task 4 and affected suites: `82 passed`.
- Full Python regression: `1714 passed, 18 skipped, 268 subtests passed`.
- Shell syntax: `bash -n install.sh hooks/run.sh hooks/resolve-python.sh`.
- Bytecode compilation: `.venv/bin/python -m compileall -q hooks pi`.
- Diff whitespace check: `git diff --check`.
- Plugin validation: `claude plugin validate . --strict` passed.

## Remaining concern

Codex hook configuration remains intentionally command-based. The Luna
provider's existing SDK boundary and typed-item rejection continue to be the
security boundary for subscription judging; this task does not claim that a
model prompt itself can enforce tool policy.

## Correction round 1

SessionEnd now always returns `{}`, including malformed payloads and release
errors, while attempting to release any valid session lease. Luna journal and
reservation failures now produce one bounded actionable Stop block instead of
being treated as an empty journal. Reservations are represented as
turn-scoped in-flight tokens and are promoted to the completed set only after
a successful result. Provider, authentication, runtime, malformed-result, and
commit failures roll back their token so a later eligible Stop can retry.

Failed turns remain blocked during Stop retries, with at most three provider
attempts and a bounded retry-limit message. Successful reviews remain
exactly-once. Correction tests cover teardown fail-open behavior, journal
failure visibility, active retry blocking, and reservation rollback.
