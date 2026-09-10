# PR 4 review findings

## Priority 1

- [ ] hooks/lib/codex_luna.py line 253, cross-turn overflow. Keep unresolved coverage visible until the affected path recovers.
- [ ] lifecycle-handlers.ts line 338, Bash post-scan coverage. Resolve written targets before completing verification.
- [ ] hooks/lib/python_payload.py line 7, import shadowing. Prove the execution import context before admitting Python reads.
- [ ] tool-adapter.ts line 161, unknown executor. Reject unsupported command-bearing tools.

## Runtime checks

- [ ] hooks/lib/test_luna_process.py line 123, timeout assertion. Verify the instance deadline with elapsed time.
- [ ] hooks/lib/luna_provider.py line 242, invalid timeout. Reject non-finite and unrepresentable values.
- [x] hooks/lib/retention.py line 58, invalid reports root. Guard path resolution and preserve ledger compaction. Four path tests pass.
- [ ] hooks/test_pre_tool.py line 22, Python route coverage. Verify that a mutation reaches the rejecting gate.

## Review output

- [x] hooks/lib/omp_review_findings.py line 42, repeated quote. Reject ambiguous quotes and request distinguishing context.
- [x] hooks/lib/omp_review_findings.py line 54, finding output limit. Save every row in a complete report and bound the notice.
- [ ] hooks/lib/luna_worker_protocol.py line 10, launch typing. Check the claim against the repository lint run.
- [x] hooks/lib/omp_review_requests.py line 49, document note limit. Review each document in one request with one six-note budget.

## Remaining coverage

- [x] hooks/lib/omp_review_requests.py line 49, document boundaries. Send the complete bounded document as one source.
- [ ] lifecycle-handlers.ts line 302, MCP post-scan coverage. Classify admitted file mutations and verify their targets.
- [ ] lifecycle.integration.test.ts line 162, missing fixture. Make absent-file and partial-write cases explicit.
- [ ] hooks/lib/journal.py line 204, legacy truncation. Reject or refresh incomplete pre-upgrade rows.
- [x] hooks/test_judge_review.py line 43, external review route. Exercise the enabled review path and assert its finding.

## Review record

- [x] tasks/cubic-review.md line 3, oversized_list. Split findings into smaller groups.

## Additional execution findings

- [ ] tool-adapter.ts line 161, unknown tool schema. Reject unsupported executors regardless of argument names.
- [ ] hooks/lib/opaque_write.py line 99, redirected Python output. Reject opaque content written through redirection or tee.
- [ ] lifecycle-handlers.ts line 416, Stop denial shape. Honor permissionDecision denial as well as decision block.
- [x] CALIBER_LEARNINGS.md line 5, private authorization. Keep host details and the authorization record outside the shared repository.

## Additional result findings

- [x] hooks/lib/omp_review_findings.py line 43, missing quote. Include the reviewed source text in each document finding.
- [x] watcher.ts line 194, symlink trust boundary. The host grants edit access. ADW verifies explicit targets with stable regular-file reads and inode checks, including external symlinks.
- [ ] lifecycle.ts line 67, lost failure reason. Preserve a specific reason when a later scan has no replacement.
- [ ] lifecycle-handlers.ts line 333, orphan partial write. Verify resolved targets after a failure without a matching call ID.

## Nested edit findings

- [ ] lifecycle-handlers.ts line 257, nested edit path. Check each target before execution or reject the unsupported shape.
- [ ] tool-adapter.ts line 123, nested MultiEdit path. Apply the same per-target protection to MultiEdit entries.

## Overflow recovery limit

- [ ] hooks/lib/journal.py line 300, overflow sentinel. Verify the recovery contract when bounded metadata fills.

## Record repairs

- [x] CALIBER_LEARNINGS.md line 1, unscannable_file. Retained neutral project guidance so the active scanner can verify the file after private authorization removal.
- [x] tasks/plan.md line 24, three_item_list. Separated the test and lint instructions.

The document, retention, and external-review suites passed 31 tests with one
opt-in live test skipped. Their changed Python files scored 10.00/10 in pylint.
The OMP suite passed all 112 tests after the document-review changes.
