# Host repair tasks

## 1. OMP external paths

Accept external targets and resolve home-relative paths.

- [x] External targets reach the scanner.
- [x] Invalid paths fail closed.
Verification uses Bun path and edit-gate tests.

Depends on none. Expected scope covers watcher.ts and two tests.

## 2. Shared external scans

Scan readable external files without a false unscannable finding.

- [x] External clean files pass and violations block.
- [x] Regular-file and inode checks remain enforced.
Verification uses record and judge-review tests.

Depends on none. Expected scope covers record.py, judge_review.py, and tests.

## 3. OMP Stop recovery

Replace the session latch with pending targets that verification can clear.

- [x] Repaired scans and failed attempts can finish.
- [x] Unrelated scans cannot clear unresolved files.
Verification uses Bun lifecycle tests.

Depends on 1 and 2. Expected scope covers index.ts and lifecycle tests.

## Checkpoint after task 3

- [x] Run the relevant suites and record results before proceeding.

## 4. OMP mutation adapters

Map installed Python and notebook contracts into ADW checks.

- [x] ADW checks mutations and scans completed writes.
- [x] Read-only calls work and unknown writes fail explicitly.
Verification uses adapter tests with real payload shapes.

Depends on 3. Expected scope covers the adapter and watcher tests.

## 5. Codex mixed review

Review every candidate type before recording a completed turn.

- [x] Document and comment findings both reach the user.
- [x] Provider failures remain retryable.
Verification uses Codex review tests.

Depends on none. Expected scope covers codex_luna.py and tests.

## 6. OMP model provider

Connect ADW review requests to a working provider.

- [x] Enabled review returns model findings.
- [x] Disabled egress makes no calls and failures stay visible.
Verification uses provider tests and one Luna live probe.

Depends on 5 if sharing the review contract. Expected scope covers provider, adapter, extension, and tests.

## Checkpoint after task 6

- [x] Run the relevant suites and record results before proceeding.

## 7. Read-only Python

Distinguish known reads from opaque writes.

- [x] Path.read_text verification passes.
- [x] Dynamic writes and indirect execution still block.
Verification uses Bash opaque-write tests.

Depends on none. Expected scope covers interpreter analysis and tests.

## 8. Pull request

Publish tested changes for Cubic review.

- [x] Python, Bun, shell checks, and pylint pass.
- [x] Resolve each Cubic finding with a fix or evidence.
Verification uses PR checks and review threads.

Depends on 1 through 7. Expected scope covers task records and PR metadata.

## 9. Release

Merge the reviewed changes and publish a patch release.

- [x] Required checks pass on the reviewed head.
- [x] Version metadata agrees with the changelog and tag.
Verification uses main and release tag checks.

Depends on 8. Expected scope covers release metadata and changelog.

## 10. Install on both machines

Refresh all three harnesses locally and on the designated remote host.

- [x] Archive old reports and preserve unrelated settings.
- [x] All three remote installations reference v0.20.17.
- [ ] All three local installations reference the released ADW copy.
- [x] Remote Haiku and Luna probes pass on the installed release.
Verification uses allowed and blocked writes using Haiku or Luna.

Depends on 9. Expected scope covers installed configuration and deployment evidence.

## Checkpoint after task 10

- [x] Run the relevant suites and record results before proceeding.

## 11. Native Claude model identifiers

Remote verification found that native agent hooks send the short model alias
directly to the API, which rejects it with HTTP 404.

- [x] Default and generated Anthropic hooks use supported API model identifiers.
- [x] Live Haiku hook review completes without a model-not-found error.

Verification uses preset and manifest regressions, followed by a remote Haiku
probe. Publish the reviewed fix and refresh the remote installation.

Depends on the remote checks in 10. Expected scope covers the native preset
renderer and plugin manifest, plus their tests.

## 12. Native Claude structured output

The installed v0.20.15 post-write probe exhausted its response attempts
without calling StructuredOutput. The Stop review called that tool and passed.

- [x] Native prompts submit their result through StructuredOutput.
- [x] A fresh installed Haiku probe completes both native hooks.

Verification covers all generated native presets and the static plugin
manifest. Review the patch through Cubic before release and remote refresh.

## 13. OMP JavaScript dispatch

- [x] Reproduce the reported which command from its recorded eval input.
- [x] Recognize literal tool dispatch without allowing arbitrary JavaScript.
- [x] Verify nested mutation gates and the installed OMP read path.
- [x] Merge the reviewed fix and publish the next patch release.

## 14. Controlled maintenance

- [x] Fetch and validate a published release from the fixed official source.
- [x] Install selected hosts with fixed destinations and preserved state.
- [x] Keep configuration exceptions and unrelated protection rules intact.
- [x] Verify failures and successful updates in isolated homes before release.

## 15. Cursor rules in OMP

- [x] Reproduce the false comments on the unchanged `.mdc` file.
- [x] Share Markdown formats between prose detection and frontmatter masking.
- [x] Verify pre-write, post-write, and Stop with real hook entrypoints.
- [x] Verify a fresh scan clears a prior comment denial without changing the file.
- [x] Complete a fresh Haiku or Luna OMP write and Stop probe before pushing.
- [x] Verify native issue-report support and preserve its consent handling.

## 16. Reviewed patch release

- [x] Resolve updater review findings and pass the full regression suite.
- [x] Merge the reviewed updater and publish v0.20.18.
- [x] Refresh all three remote harnesses and verify their installed revision.
- [x] Complete the Mac installation through the permitted maintenance entrypoint.

## 17. Claude plugin migration

- [x] Reproduce the remote upgrade in an isolated home with the native CLI.
- [x] Use HTTPS for the pinned public plugin repository.
- [x] Repair stale native commit metadata while preserving plugin data.
- [x] Verify rollback, review the follow-up, and publish the next 0.20 patch.
- [x] Verify the installed release and plugin commit on both machines.

## 18. Native OMP edit and install migration

- [x] Capture the failing edit and verify native OMP hashline requirements.
- [x] Replace the generic target error with native format guidance.
- [x] Reproduce and repair checkout migration with the real installer.
- [x] Pass independent security review and all CI jobs, then merge PR 11.
- [x] Publish 0.20.20 and update all three harnesses on both machines.
- [x] Verify a fresh OMP code-mode edit through the installed release.
