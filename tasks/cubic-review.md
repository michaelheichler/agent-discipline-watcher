# PR 4 review findings

## Priority 1

- [x] hooks/lib/codex_luna.py line 253, cross-turn overflow. Unresolved coverage now persists until the affected path recovers.
- [x] lifecycle-handlers.ts line 338, Bash post-scan coverage. The shared parser resolves written targets, and live review verifies completed Bash writes.
- [x] hooks/lib/python_payload.py line 7, import shadowing. Python reads now require a trusted import context, and subprocess tests reject project and environment shadows.
- [x] tool-adapter.ts line 161, unknown executor. Unsupported command-bearing tools now fail before execution.

## Runtime checks

- [x] hooks/lib/test_luna_process.py line 123, timeout assertion. Verified the instance deadline with elapsed time.
- [x] hooks/lib/luna_provider.py line 242, invalid timeout. Non-finite and unrepresentable values now fail validation.
- [x] hooks/lib/retention.py line 58, invalid reports root. Guard path resolution and preserve ledger compaction. Four path tests pass.
- [x] hooks/test_pre_tool.py line 22, Python route coverage. A mutation now proves the Python route reaches its rejecting gate.

## Review output

- [x] hooks/lib/omp_review_findings.py line 42, repeated quote. Reject ambiguous quotes and request distinguishing context.
- [x] hooks/lib/omp_review_findings.py line 54, finding output limit. Save every row in a complete report and bound the notice.
- [x] hooks/lib/luna_worker_protocol.py line 10, launch typing. The original lint run passed. The annotation now reflects the dynamic launch interface, and pylint still scores 10.00/10.
- [x] hooks/lib/omp_review_requests.py line 49, document note limit. Review each document in one request with one six-note budget.

## Remaining coverage

- [x] hooks/lib/omp_review_requests.py line 49, document boundaries. Send the complete bounded document as one source.
- [x] lifecycle-handlers.ts line 302, MCP post-scan coverage. Admitted file mutations now enter target verification.
- [x] lifecycle.integration.test.ts line 162, missing fixture. Tests distinguish absent files from partially written files.
- [x] hooks/lib/journal.py line 204, legacy truncation. Legacy truncated rows block review and refresh when ADW records the same file again.
- [x] hooks/test_judge_review.py line 43, external review route. Exercise the enabled review path and assert its finding.

## Review record

- [x] tasks/cubic-review.md line 3, oversized_list. Split findings into smaller groups.

## Additional execution findings

- [x] tool-adapter.ts line 161, unknown tool schema. Unknown executors fail closed, and known debug and LSP actions have read-only allowlists.
- [x] hooks/lib/opaque_write.py line 99, redirected Python output. Redirection and tee cannot write opaque Python output, including grouped and nested shell calls.
- [x] lifecycle-handlers.ts line 416, Stop denial shape. Stop now honors both blocking response shapes.
- [x] CALIBER_LEARNINGS.md line 5, private authorization. Keep host details and the authorization record outside the shared repository.

## Additional result findings

- [x] hooks/lib/omp_review_findings.py line 43, missing quote. Include the reviewed source text in each document finding.
- [x] watcher.ts line 194, symlink trust boundary. The host grants edit access. ADW verifies explicit targets with stable regular-file reads and inode checks, including external symlinks.
- [x] lifecycle.ts line 67, lost failure reason. A later empty reason preserves the specific failure.
- [x] lifecycle-handlers.ts line 333, orphan partial write. Existing resolved targets enter recovery even without a matching call ID.

## Nested edit findings

- [x] lifecycle-handlers.ts line 257, nested edit path. Each nested target receives its own pre-gate payload.
- [x] tool-adapter.ts line 123, nested MultiEdit path. MultiEdit entries receive the same per-target protection.

## Overflow recovery limit

- [x] hooks/lib/journal.py line 300, overflow sentinel. A full metadata buffer requires a new session because it no longer identifies every omitted path. Regression tests cover the explicit recovery message and bounded storage.

## Record repairs

- [x] CALIBER_LEARNINGS.md line 1, unscannable_file. Retained neutral project guidance so the active scanner can verify the file after private authorization removal.
- [x] tasks/plan.md line 24, three_item_list. Separated the test and lint instructions.
- [x] tasks/cubic-review.md line 5, passive_voice. Reworded the recovery description with ADW as the actor.
- [x] tasks/cubic-review.md line 64, low_sentence_variance. Separated the validation results by topic.
- [x] lifecycle.integration.test.ts line 1, file_length_warning. Keep this regression set together for review. Split future shell coverage into its own suite before reaching 750 lines.
- [x] tasks/cubic-review.md line 1, oversized_list. The report scanned concatenated replacement lines. The complete file separates findings into groups of at most six rows.

The document and retention checks, including external review routing, passed
31 tests with one opt-in live test skipped. Pylint scored 10.00/10.

The journal and Luna regression suites passed 94 tests with pylint at 10.00/10.

OMP passed 112 tests after the document-review changes. A live Luna probe then
executed isolated Path.read_text through Bash and returned the expected sentence
with isError false. The session finished successfully.

A second Luna probe wrote a fixture through normal Bash redirection. ADW
reported a grounded clarity finding, then accepted the repaired file and let
the session finish. Both live probes used Luna for every model role.

Python execution checks passed 422 focused tests. The launcher and runtime
checks passed 200 tests with 60 subtests, and pylint scored 10.00/10.
The isolated hook process also launched a worker that could import its SDK
from the worker virtual environment.

The completed OMP routing suite passed 125 Bun tests. Its Python checks passed
23 bridge tests and 220 related hook tests with 28 subtests. Pylint scored 10.00/10.

The final full Python run passed 2245 tests with 18 existing skips and 274
subtests. The last shell-grouping fix also passed 423 focused tests.
Pylint scored 10.00/10, and shell syntax checks passed.

Python 3.13 CI exposed a path-resolution difference for looping symlinks.
Strict report-root resolution fixed it. All 11 retention and startup tests then
passed on Python 3.11 and 3.13, with pylint at 10.00/10.
