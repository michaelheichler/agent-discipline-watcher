# Host repair tasks

## 1. OMP external paths

Accept absolute, home-relative, sibling, and symlink targets.

- [ ] External targets reach the scanner.
- [ ] Invalid paths fail closed.
- [ ] Verify with Bun path and edit-gate tests.

Depends on none. Expected scope covers watcher.ts and two tests.

## 2. Shared external scans

Scan readable external files without a false unscannable finding.

- [ ] External clean files pass and violations block.
- [ ] Regular-file and inode checks remain enforced.
- [ ] Verify with record and judge-review tests.

Depends on none. Expected scope covers record.py, judge_review.py, and tests.

## 3. OMP Stop recovery

Replace the session latch with pending targets that verification can clear.

- [ ] Repaired scans and failed attempts can finish.
- [ ] Unrelated scans cannot clear unresolved files.
- [ ] Verify with Bun lifecycle tests.

Depends on 1 and 2. Expected scope covers index.ts and lifecycle tests.

## Checkpoint after task 3

- [ ] Run the relevant suites and record results before proceeding.

## 4. OMP mutation adapters

Map installed Python and notebook contracts into ADW checks.

- [ ] ADW checks mutations and scans completed writes.
- [ ] Read-only calls work and unknown writes fail explicitly.
- [ ] Verify with adapter tests with real payload shapes.

Depends on 3. Expected scope covers adapter, watcher, and tests.

## 5. Codex mixed review

Review every candidate type before recording a completed turn.

- [ ] Document and comment findings both reach the user.
- [ ] Provider failures remain retryable.
- [ ] Verify with Codex review tests.

Depends on none. Expected scope covers codex_luna.py and tests.

## 6. OMP model provider

Connect ADW review requests to a working provider.

- [ ] Enabled review returns model findings.
- [ ] Disabled egress makes no calls and failures stay visible.
- [ ] Verify with provider tests and one Luna live probe.

Depends on 5 if sharing the review contract. Expected scope covers provider, adapter, extension, and tests.

## Checkpoint after task 6

- [ ] Run the relevant suites and record results before proceeding.

## 7. Read-only Python

Distinguish known reads from opaque writes.

- [ ] Path.read_text verification passes.
- [ ] Dynamic writes and indirect execution still block.
- [ ] Verify with Bash opaque-write tests.

Depends on none. Expected scope covers interpreter analysis and tests.

## 8. Pull request

Publish tested changes for Cubic review.

- [ ] Python, Bun, shell checks, and pylint pass.
- [ ] Resolve each Cubic finding with a fix or evidence.
- [ ] Verify with PR checks and review threads.

Depends on 1 through 7. Expected scope covers task records and PR metadata.

## 9. Release

Merge the reviewed changes and publish a patch release.

- [ ] Required checks pass on the reviewed head.
- [ ] Version metadata agrees with the changelog and tag.
- [ ] Verify with main and release tag checks.

Depends on 8. Expected scope covers release metadata and changelog.

## 10. Install on both machines

Refresh all three harnesses locally and on tux@10.0.10.106.

- [ ] Archive old reports and preserve unrelated settings.
- [ ] All six installations reference the released ADW copy.
- [ ] Verify with allowed and blocked writes using Haiku or Luna.

Depends on 9. Expected scope covers installed configuration and deployment evidence.

## Checkpoint after task 10

- [ ] Run the relevant suites and record results before proceeding.


