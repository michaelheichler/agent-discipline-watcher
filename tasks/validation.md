# Host repair validation

## OMP code-mode regression

The reported OMP code-mode session called JavaScript eval with
`display(await tool.bash({command:'which -a omp',timeout:30}));`.
ADW rejected eval before the nested Bash command reached its gate. Two new
regressions reproduce the failure, with 70 existing tests still passing.

The live OMP 18.1.17 Luna probe now executes that exact wrapper and returns
the resolved executable paths. Code mode remains enabled. A nested write
probe reaches the normal content gate, which rejects its intentional rule
violation before creating the file. The security review found no remaining
execution escape in the accepted grammar.

PR 7 merged after Cubic reported zero findings. Final CI passed 187 Bun tests
and 2414 Python tests on each tested version. Pylint scored 10.00/10 across
the repository.

Published v0.20.17 at a444313. The Mac's linked OMP extension passed the live
Luna probes. The official remote installer refreshed all three harnesses,
and their source trees match the release. A fresh remote OMP Luna probe also
ran the exact JavaScript-wrapped command successfully. Existing OMP sessions
need a restart to load the extension change.

[x] /tmp/adw-js-dispatch-probe/rejected.md line 1, `english/utilize`. The intentional negative probe returned the expected rejection. Confirmed that the file does not exist.

[x] pi/extensions/agent-discipline-watcher/lifecycle.integration.test.ts line 1, file_length_warning. The focused regression keeps this suite below 750 lines. Split the language-specific lifecycle cases before further growth reaches that limit.

## Release and deployment

PRs 4 through 7 merged after Cubic reported zero remaining findings and CI
passed. The published v0.20.17 tag points to a444313. README and CHANGELOG
agree. All three remote installations match that release's source trees.

The final installed Claude Haiku probe returned structured success from both
native reviewers with no missing-output or API error. Codex and OMP Luna
probes also passed on v0.20.16. The remote fresh installation is complete.

- [ ] install.sh line 1, self_protection/install_without_sandbox_home. Automatic review rejected the official local installer before execution. Installation requires an execution context that permits live-home maintenance.

SSH to the designated remote host recovered. Its official installer refreshed
all three harnesses to v0.20.14. The installed hook and OMP source trees match
the release. Claude's plugin update also refreshed its cache metadata.

Archived 300 old remote reports after confirming no session leases remained.
The ledger and session state stayed in place. Both machines retain verified
report and ledger backups. The local fresh installation remains blocked.

Remote Haiku and Luna probes completed file writes and reads in all three
harnesses. OMP also wrote an external file and ran the compact Python command.
A deterministic negative probe rejected a violating write before execution.

Claude debug output exposed a separate native review failure. The hook sent
model haiku directly to the API, received HTTP 404, and returned no structured
review result. Main-agent success alone did not verify that review path.
Task 11 tracks the correction and a repeat native-hook test.

The selected native IDs follow Anthropic's
[model identifier reference](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).
Haiku uses its dated snapshot. The mixed preset keeps Sonnet for document
review through the supported Sonnet 4.6 identifier. Live checks use Haiku only.

The temporary remote plugin test completed successfully. Both native agent
hooks returned structured ok results, and the debug trace contained no
model-not-found error. Every observed API dispatch used the full Haiku ID.

The focused native-model suite passed 109 tests with 32 subtests. Pylint
scored 10.00/10 on the changed Python files. Bun passed all 156 tests.
The full local Python rerun passed 2416 tests with 18 skips and 274 subtests.
PR 5 merged after Cubic reported no findings. CI passed 2414 Python tests on
each tested version, with repository-wide pylint at 10.00/10.

The remote refresh to v0.20.15 matches release a75b05b. Fresh Luna read probes
passed in Codex and OMP. Claude used the full Haiku ID without HTTP 404.
Its Stop reviewer returned structured success, but the post-write reviewer
made repeated model calls without submitting StructuredOutput. Task 12
tracks the prompt correction and another installed probe.

The structured-response prompt regressions passed 109 focused Python tests
with 34 subtests. Pylint scored 10.00/10 on the changed Python files.

The temporary-plugin Haiku probe submitted structured decisions from both
native reviewers, with no missing-output or API error. The post-write result
flagged vague fixture wording. The Stop result was clean.

[x] structured-final-note.md line 1, native/comment review. Replaced the vague fixture sentence with its test purpose. The final installed probe accepted the descriptive wording in release-verification.md.

PR 6 merged after Cubic reported zero findings. Final CI passed 2414 Python
tests on each tested version and 156 Bun tests. Pylint scored 10.00/10 across
the repository. The merged patch addresses both prompt-order findings.

## Native-model review findings

[x] hooks/lib/test_claude_luna.py line 2, punctuation/prose_colon. Preserve the existing tool directive. Pylint accepts it.

[x] hooks/lib/test_claude_luna.py line 1, what_comment. Automatic review rejected a compact directive proposal before applying it. The original directive remains unchanged.

## Native test size

[x] hooks/lib/test_claude_luna.py line 1, file_length_warning. The model assertions add no lines to this 692-line suite. Split provider-failure coverage before reaching 750 lines.

## Baseline

Python passed 2118 tests with 18 skips. Bun passed 64 tests.
The initial OMP Luna test reproduced the external-target rejection.
Codex Luna completed read and write smoke tests but rejected a read-only
Path.read_text command. Claude initially returned HTTP 407 before inference.

## External targets

Six regressions reproduced the bug. After the fix, all 64 Bun tests and 28
focused Python tests passed, with one opt-in live test skipped.
The four changed Python files scored 10.00/10 in pylint.

OMP Luna then edited an explicitly authorized external file successfully.
The existing inode-swap regression still blocks a replacement file.

## Machine preflight

The initial SSH preflight succeeded. Remote Claude is 2.1.263, Codex is 0.153.4,
and OMP is 18.1.12. The remote noninteractive shell needs ~/.bun/bin and
~/.local/bin on PATH. Both machines have Claude subscription sessions.

Claude Haiku completed a no-tool probe on both machines. On the Mac, removing
the inherited ANTHROPIC_BASE_URL and ANTHROPIC_TARGET_API_URL for that process
avoided the failing proxy. No persistent proxy setting changed.

A later pre-release SSH check returned Network is unreachable. Deployment
needs another connectivity check after publication.

## Complete review batches

The mixed-review and provider suites passed 119 tests. Pylint rated the changed
review modules and their tests 10.00/10. Regression tests now preserve multiple
comments from one file and include TypeScript comments in the journal.

Document and comment requests share a bounded turn deadline. Failed requests
release their reservation, and oversized batches report the coverage limit.

## Python verification

The read-only Python suite passed 207 tests. Exact Path imports and local
read bindings pass. Mutation, rebinding, and indirect execution still block.
The full Python suite passed 2186 tests with 18 existing skips and 274 subtests
on both the local interpreter and the supported Python 3.11 floor.
Pylint rated all tracked Python files and new OMP bridge modules 10.00/10.
Shell syntax and git diff whitespace checks passed.

## Native OMP review

The native provider returned a grounded finding. The first Luna probe reached
its deadline because the agent kept the flagged wording, but a second probe
repaired the document and finished without an ADW block. Every harness model
role used Luna.

The final lifecycle suite passed all 112 Bun tests. Coverage includes partial
writes and notebook aliases, along with deletion recovery and provider errors.
The extension also bundled successfully.

## Retention startup cost

Retention treated ordinary ledger strings as filesystem paths. A read-only
profile took 0.474 seconds for only 1000 rows before the fix, then 0.778 seconds
for 125074 rows afterward. The fix filters report references and resolves the
reports directory once per compaction. Ten focused tests passed.
A fresh OMP Luna session then read the fixture and finished successfully.
Its session trace contained no startup timeout.

## Journal coverage limits

The independent review found silent row truncation at the journal limit.
Overflow markers now block Codex before reservation, and correcting a file
can restore complete coverage. Document storage retains the full bounded
source while the Claude Stop payload keeps its smaller display limit.
Truncated comments fail explicitly. The focused journal suites passed 59 tests.
Pylint rated the changed journal modules and their regression tests 10.00/10.

The full Python run with the first overflow regressions passed 2191 tests,
18 existing skips, and 274 subtests.

## Existing size observations

- [x] hooks/lib/codex_luna.py line 1, file_length_warning. Keep this repair focused. Extract request construction before the module reaches 750 lines.
- [x] omp-review.ts line 69, provider error exposure. Replaced raw SDK errors with safe category messages and passed the secret disclosure regression.
- [x] hooks/lib/omp_review_findings.py line 42, repeated quote attribution. Cubic prompted a stricter check. Ambiguous quotes now require distinguishing source context.
- [x] watcher.ts line 1, file_length_warning. The path fix shrank the file.
- [x] index.test.ts line 1, file_length_warning. Keep new suites in separate files.

## Writing observations

- [x] tasks/validation.md line 11, low_sentence_variance. Shortened the result and combined its supporting evidence.
- [x] tasks/validation.md line 49, low_sentence_variance. Varied the sentence lengths in the live probe record.
- [x] tasks/validation.md line 12, long_sentence. Put the pylint result in its own sentence.
- [x] tasks/validation.md line 55, three_item_list. Reworded the coverage record as two paired examples.
- [x] tasks/validation.md line 81, oversized_list. Separated writing observations from code observations.

The hook also reported existing narration comments in the two touched Python
modules. Those comments no longer remain, and the focused checks pass.

## Installation preflight

The active hook rejected the installer preview command with
install_without_sandbox_home. No installer ran. The command used --dry-run,
but the guard still required a sandbox HOME. Deployment must respect that
active guard rather than disable it or override its authorization setting.

## Cursor rules and native reports

The unchanged `app-marcumar/.cursor/rules/rust-model-parity.mdc` reproduced
ten false comment findings before the fix. The same bytes produced no
findings after `.mdc` joined the shared Markdown format set.

The reported file predates the fix. Its report timestamp is September 10 at
23:08, while the parser changed at 23:11. Mac OMP loads the checkout through
its extension symlink. The later advisor observation saw this new work.

Fresh OMP 18.1.17 session `01a08d33-3cb0-75ad-b51d-ba9739a0d9f8` used
`openai-codex/gpt-5.6-luna` with maximum reasoning. It changed one word in a
temporary copy of the exact rule. The native ledger recorded pre-write,
post-edit, and Stop without findings. The diff contains only the requested
replacement. Haiku could not start because the OMP profile lacks Anthropic
credentials. The probe left the project rule intact and used normal guard checks.

The installed OMP binary implements the exact `xd://report_issue` device.
Its handler owns consent and grievance storage. ADW now leaves that route
to OMP. Tests reject other virtual targets and prevent a report result from
hiding an accepted filesystem write. The tests sent no live report.

The OMP suite passed 214 tests. The broad Python run passed 2,440 tests with
18 existing skips and 276 subtests. Focused shell-entry tests also verified
pre-write, post-write, and Stop for Cursor rules, including an old denial.

- [x] `hooks/lib/scanner.py:300`, `long_comment`. Removed the inherited comment.
- [x] `hooks/lib/scanner.py:1`, `file_length_warning`. Recorded a focused split plan before the 750-line limit.

## Updater review repairs

- [x] `hooks/lib/update_policy.py:16`, shell wrapper. The full gate already rejects the reported PATH override. Added a regression through the hook entrypoint.
- [x] `hooks/lib/update_release.py:466`, cleanup race. Removed the directory sweep and restricted cleanup to an empty directory with the recorded inode.
- [x] `hooks/lib/update_claude.py:110`, profile selection. Resolve the supported profile once and use it for backup, installation, and verification.
- [x] `install.sh:106`, late registration refusal. Check a foreign updater link before any host mutation.
- [x] `hooks/lib/update_claude_state.py:205`, permission preservation. Restore the saved mode, including zero.

- [x] `hooks/lib/update_release.py:75`, repository redirects. Reject redirects and verify the fixed upstream endpoints still work.
- [x] `hooks/lib/update_claude.py:26`, command coverage. Include plugin commands in content and mode verification.
- [x] `hooks/lib/update_claude.py:203`, fallback selection. Read the command verb at the correct index and test install after update failure.
- [x] `hooks/lib/update_runtime.py:234`, judge launcher. Require the published executable and verify its installed link.
- [x] `bin/adw:4`, custom interpreter. Document the intentional system-path requirement. The generic installer still supports custom interpreters.

- [x] `hooks/lib/update_runtime.py:76`, direct entry. Gate direct managed Python calls, including relative and wrapped calls. Require isolated Python startup before importing the runtime.
- [x] `hooks/pre_bash.py:1`, file_length_warning. Move the new working-directory helpers into the update policy module.
- [x] `hooks/lib/update_claude.py:140`, profile guidance. Direct ambiguous profiles to the Terminal installer instead of suggesting an unsupported updater override.

The full local Python suite passed 2,576 tests with 18 existing skips and
276 subtests. Repository-wide pylint scored 10.00/10. The final policy
extraction also passed 125 focused tests. The pinned Claude plugin installed
and verified twice through the real CLI in a temporary home, without model calls.

- [x] `hooks/lib/update_policy.py:98`, home directory changes. Resolve HOME operands and bare cd before classifying a relative managed script.
- [x] `hooks/lib/update_policy.py:126`, Python option parsing. Reuse the shared option matcher for clustered flags and distinguish module or help calls from script execution.

The final independent review reproduced both cases before the fixes. Its
49 focused tests passed afterward, with pylint at 10.00/10 and no discipline
findings. Cubic skipped incremental review because its monthly quota was full.
The final full run passed 2,593 tests with 18 existing skips and 276 subtests.

## Installed release checks

PR 9 merged after CI passed on Python 3.11, 3.12, and 3.13, with Bun green.
Published v0.20.18 at 8702710. Its release CI passed.

The remote fresh installer completed for all three harnesses. Their code
trees match the release. Claude still recorded old plugin metadata, so the
managed updater rejected that mismatch and restored its backup. No success
receipt hid the failed migration.

Fresh remote Claude Haiku and Codex Luna sessions wrote and read the probe
document. Both Claude native reviewers submitted StructuredOutput, and every
observed Claude API dispatch used Haiku. OMP Luna edited the copied Cursor
rule and completed pre-write, post-edit, and Stop without findings in session
`01a08d74-8068-75d0-9705-8939a08c1430`.

## Native plugin migration repair

- [x] `hooks/lib/update_claude.py:170`, SSH transport. Use the documented HTTPS repository source with the exact release SHA.
- [x] `hooks/lib/update_claude.py:220`, stale native metadata. Reinstall the user plugin with data preservation when native update leaves the wrong commit, then verify its content and registration.

The isolated Tux reproduction first failed to clone over SSH. Its fallback
install returned already installed. With HTTPS, native update changed the
cache path but retained the old gitCommitSha. The repaired helper passed the
same migration on Claude 2.1.263 and 2.1.266 with the full pinned commit.

Rollback tests cover both supported Claude profiles. A failed native reinstall
restores the old cache bytes, registry, and enabled setting, removes the
replacement cache, and records no success receipt.
The final full suite passed 2,596 tests with 18 existing skips and 276 subtests.
Independent review found no remaining defect in the migration repair.

## Captured OMP edit and checkout migration

The September 11 OMP trace passed a Codex patch inside a JavaScript tool.edit
call. Native OMP rejects that syntax and expects its current hashline header.
The watcher hid the format error behind a generic unresolved-target message.
The new diagnostic explains the native format without relaxing write checks.
A fresh Luna code-mode session edited and read the fixture successfully, and
its ledger recorded pre-write, post-edit, and Stop without findings.

The Mac installer also copied the runtime before rejecting the existing OMP
checkout link. The router had lost its original source path. A real installer
regression reproduced that failure and passed after forwarding the legacy root.
The updater now recognizes only registered, owned legacy OMP wiring, backs it
up, and passes the validated root to the verified release installer.

The partial Mac install contained a valid managed updater. Its supported
Claude-only update completed and registered the updater command. A read-only
check of the new migration code accepts the Mac's exact existing OMP wiring.

The full Python suite passed 2,604 tests with 18 existing skips and 276 subtests.
All 218 extension tests passed. The captured invalid JavaScript edit now returns
the native hashline guidance in a fresh Luna session. The fixture stayed intact.

## Installed 0.20.20 verification

PR 11 and the release commit passed every CI job. Cubic skipped review after
reaching its monthly quota. Independent security review found no remaining
blocker in the migration changes.

The managed updater completed for Claude Code, Codex, and OMP on both the Mac
and tux at 10.0.10.106. Both receipts and native Claude plugin records name
commit 5caa0655dde50acb1f7d40821c88d51d5015f4dd. OMP registrations and Codex
hooks point to the managed runtime on each machine. The updater verified
runtime contents and preserved existing findings and session state.

Fresh Luna code-mode sessions edited a Markdown rule fixture with YAML glob
frontmatter on both machines. Their ledgers recorded the edit and Stop without
findings. The resulting files have identical SHA-256 hashes. The Mac session
recovered from invalid native edit syntax using the new guidance before its
successful edit. The workstation session completed its edit on the first call.

The Mac probe session was 01a08f2e-f86f-763c-a6e5-53e07e6e8068.
The workstation probe session was 01a08f2f-d6de-70b2-bdb1-85f2fbdcd076.
