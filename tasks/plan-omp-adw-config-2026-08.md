# Implementation Plan: OMP ADW Configuration and Harness Separation

## Overview

Add an interactive ADW configuration screen to the Oh My Pi extension. The screen edits the same project policy that Claude Code and Codex use in `.agent-discipline.json`. It must not reuse or modify OMP's separate `WATCHDOG.yml` advisor harness. The Python hook engine remains the policy authority. OMP provides the UI and calls that engine.

The prerequisite host changes and OMP configuration work are implemented. The current `WATCHDOG.yml` edit remains a separate OMP advisor decision and is preserved outside ADW policy. Pylint is available and reports two pre-existing import-order warnings outside this change.
## Current Status

- [x] ADW OMP policy screen and bridge implemented.
- [x] `/adw configure` and `/agent-discipline configure` remain separate from `/advisor configure`.
- [x] Colon blocking excludes structured code comments and metadata directives.
- [x] OMP model selection reaches the guarded bridge Save request.
- [x] Full verification passes with 1614 Python tests, 18 skips, 270 subtests, 42 Bun tests, and shell syntax checks.
- [x] Unresolved mutating OMP results remain blocking after later valid results.
- [x] SessionStart block reasons reach the user-visible OMP diagnostic path.
- [x] The bridge exposes and validates `describe`, `read`, `validate`, and `write`.
- [x] Pylint is available, but two pre-existing import-order warnings remain.


## Architecture Decisions

- Keep ADW policy in `.agent-discipline.json`. Preserve the existing upward path search from `hooks/lib/config.py`.
- Add a narrow configuration bridge that uses the Python configuration code for path resolution, defaults, validation, protected rules, and atomic writes. The Configure route exposes describe, read, validate, and guarded write operations. Write is accepted only from the trusted OMP process boundary with an owner-only one-shot capability file and exact parent executable attestation. Same-user process impersonation remains an accepted host-trust limitation.
- Register `/adw configure` and `/agent-discipline configure` as OMP commands. Both open the ADW screen. `/advisor configure` remains the OMP advisor editor for `WATCHDOG.yml`.
- Keep `WATCHDOG.yml` and the OMP advisor runtime completely outside the ADW configuration flow. The ADW screen must never create, update, enable, or disable OMP advisors.
- Edit project policy only. Environment-only controls such as embedding URLs and `ADW_PYTHON` remain runtime settings. Show their current state and setup guidance without pretending that a project file can persist them.
- Lock always-blocking rules in the UI. Permit ordinary family gates, per-rule gates, thresholds, exemptions, baseline mode, kill switches, and data-boundary settings through the same semantics already used by Claude Code and Codex.
- The configuration bridge must not reuse `protected.authorized()` or `ADW_ALLOW_PROTECTED_EDIT`. That escape is for protected hook edits, not policy weakening through the OMP editor.
- Preserve unknown configuration keys when saving through a locked compare-and-swap. Write atomically and apply the new policy to the next hook call without requiring an OMP restart.
- OMP exposes an `adw_model` chooser from its authenticated Anthropic model registry. The selected CLI-compatible model propagates to the comment judge, pattern judge, and document reviewer. The embedding model remains a separate local or explicitly approved runtime setting.

## Dependency Graph

```text
hooks/lib/config.py policy authority
    |
    +-- configuration bridge and validation
            |
            +-- OMP config data model
                    |
                    +-- interactive ADW overlay
                            |
                            +-- OMP command registration and live reload
                                    |
                                    +-- parity, separation, and regression tests
```

## Task List

### Phase 0  Worktree reconciliation

- [x] Task 1  Reconcile the current uncommitted host changes

### Checkpoint 0

- [x] The dirty patch has one clear purpose per file.
- [x] Startup tests match implemented behavior.
- [x] ADW contract text reaches OMP without premature truncation.

### Phase 1  Shared ADW configuration contract

- [x] Task 2  Add the policy descriptor and configuration bridge

### Checkpoint 1

- [x] The bridge reads the same project file and effective defaults as hook execution.
- [x] Bridge writes reject protected weakening and preserve unrelated keys.
- [x] Bridge tests cover absent, malformed, legacy, and populated project files.

### Phase 2  OMP configuration screen

- [x] Task 3  Implement the ADW policy editor overlay
- [x] Task 4  Register ADW configuration commands and live apply

### Checkpoint 2

- [x] `/adw configure` opens the ADW editor in an interactive OMP session.
- [x] Saving changes `.agent-discipline.json` and affects the next watcher call.
- [x] `/advisor configure` and `WATCHDOG.yml` behavior is unchanged.

### Phase 3  Host parity and hardening

- [x] Task 5  Close OMP lifecycle and payload parity gaps
- [x] Task 6  Add separation, parity, and user-flow coverage
- [x] Task 7  Update integration documentation and verification commands

### Checkpoint 3

- [x] OMP reaches every equivalent ADW gate without weakening block behavior.
- [x] The ADW screen and the OMP advisor screen edit different files and runtimes.
- [x] Focused tests, the full suite, focused lint, shell checks, and Bun tests pass. Full lint reports two pre-existing import-order warnings.

## Tasks

## Task 1  Reconcile the current uncommitted host changes

**Description:** Review the existing changes in `hooks/lib/hookio.py`, `hooks/merge-codex-config.py`, `hooks/test_hooks.py`, `hooks/test_session_start.py`, and `hooks/codex-runtime.requirements.txt` as one patch. Keep only behavior supported by the current source. Repair or remove speculative tests and decide whether the requirements file belongs to the current Codex installer. Preserve the current `WATCHDOG.yml` advisor edit and do not fold it into this cleanup. Do not mix the OMP screen into this cleanup.

**Acceptance criteria:**

- [x] `test_session_start.py` uses the repository test framework and asserts behavior implemented by `session_start.py` and `subagent_start.py`.
- [x] `_bounded_payload` preserves any response that already fits `MAX_RESPONSE_BYTES`, including the complete `CONTRACT` and hook-specific context.
- [x] `read_payload()` rejects oversized or excessively nested stdin before unbounded parsing, and tests cover oversized input plus oversized unknown tool fields.
- [x] Codex lifecycle pruning uses the authoritative current event set `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, and `Stop`. `Interrupt` is not retained unless a later official Codex reference adds it.
- [x] Tests cover each added Codex lifecycle name, and the requirements file is either wired into the installer or absent.

**Verification:**

- [x] Run `cd hooks && python3 -m pytest test_session_start.py lib/test_hookio.py test_merge_configs.py -q`.
- [x] Run `python3 -m py_compile` for changed Python files.
- [x] Run `bun test pi/extensions/agent-discipline-watcher/index.test.ts`.

**Dependencies:** None

**Files likely touched:**

- `hooks/lib/hookio.py`
- `hooks/merge-codex-config.py`
- `hooks/test_hooks.py`
- `hooks/test_session_start.py`
- `hooks/lib/test_hookio.py`
- `hooks/codex-runtime.requirements.txt`

**Estimated scope:** M

## Task 2  Add the policy descriptor and configuration bridge

**Description:** Expose a narrow configuration bridge for the OMP screen to inspect and update ADW policy. The bridge must use `config.effective_config`, `project_config_path`, `GATE_FAMILIES`, `DEFAULTS`, and `ALWAYS_BLOCKING_RULES` instead of reimplementing policy in TypeScript. Define describe, read, validate, and guarded write operations with bounded bridge input and bounded project-file reads, explicit type checks, protected-rule enforcement, unknown-key preservation, compare-and-swap under a lock, and atomic file replacement. The write operation requires a verifiable one-time capability bound to the explicit OMP Save action. Direct shell invocation and caller-supplied nonempty environment strings must not authorize writes. Keep `state_root` and `ledger_root` outside the editable project policy. Never call `protected.authorized()` and never treat `ADW_ALLOW_PROTECTED_EDIT` as authorization for this bridge.

**Acceptance criteria:**

- [x] Read returns the project path, known editable values, effective values, supported family and rule metadata, and redacted environment-only setting status. Unknown keys stay inside the bridge read-modify-write boundary and never cross into OMP rendering or command messages.
- [x] The shared project-config loader rejects oversized or excessively nested `.agent-discipline.json` input before expensive parsing, rejects non-boolean legacy family values such as `[]`, `0`, `""`, `null`, and `"false"`, and returns safe failure without crashing any hook.
- [x] Write preserves unknown keys, rejects malformed values including non-boolean legacy family gates such as `[]`, `0`, `""`, `null`, and `"false"`, rejects attempts to weaken always-blocking rules regardless of `ADW_ALLOW_PROTECTED_EDIT`, and never writes state or ledger roots.
- [x] A missing file can be created at the same path the hook resolver would use, while malformed input fails without replacing the existing file.
- [x] Remote semantic or document review egress is disabled unless an explicit local-only or approved-provider policy allows it. Tests prove private source text is not sent to an unapproved embedding or review endpoint.

**Verification:**

- [x] Run bridge unit tests for defaults, upward path resolution, legacy `checks` flattening, malformed family gates, protected rules, malformed input, direct shell invocation refusal, concurrent saves, and atomic failure.
- [x] Run `cd hooks && python3 -m pytest lib/test_config_schema.py -q`.
- [x] Exercise the bridge against a temporary project and compare its effective policy with `config.effective_config`.

**Dependencies:** Task 1

**Files likely touched:**

- `hooks/lib/config.py`
- `hooks/configure.py`
- `hooks/run.sh`
- `hooks/lib/test_config_schema.py`
- `hooks/test_configure.py`

**Estimated scope:** M

## Task 3  Implement the ADW policy editor overlay

**Description:** Build an OMP TUI overlay using the existing advisor configuration overlay patterns. Provide sections for family gates, per-rule gates, the OMP-backed ADW model chooser, thresholds, baseline mode, exemptions, kill switches, data boundary, and redacted runtime status. Display always-blocking rules as locked. Keep edits in memory until save. Preserve unknown keys through a bridge-side read-modify-write guarded by a file digest. Treat every policy value and path as untrusted display data. Sanitize ANSI and control characters, normalize line breaks, and encode or truncate markup before it reaches the TUI.

**Acceptance criteria:**

- [x] The overlay exposes every supported project policy field without editing `WATCHDOG.yml`.
- [x] Gate and rule controls show effective state and distinguish off, observe, enforce, and judged where valid.
- [x] Save and cancel paths are explicit, keyboard and mouse navigation work, and long values remain readable without corrupting the terminal frame.
- [x] Policy values and paths containing ESC, control characters, newlines, and markup render as inert text in every screen and status row. Runtime status redacts URL userinfo and query strings, reports only configured or unset, shows only the executable basename, and never presents `ADW_ALLOW_PROTECTED_EDIT` as a save control.

**Verification:**

- [x] Add deterministic component tests for initial values, nested edits, locked rules, cancel, save, and unknown-key preservation.
- [x] Run `bun test pi/extensions/agent-discipline-watcher/index.test.ts`.
- [x] Manually open `/adw configure` in OMP and verify each section renders at the current terminal width.

**Dependencies:** Task 2

**Files likely touched:**

- `pi/extensions/agent-discipline-watcher/adw-config.ts`
- `pi/extensions/agent-discipline-watcher/index.test.ts`

**Estimated scope:** M

## Task 4  Register ADW configuration commands and live apply

**Description:** Add `/adw configure` and `/agent-discipline configure` command handlers to the extension. Resolve the current OMP project directory, load policy through the bridge, open the overlay, save through the bridge, and report the result. Refresh the watcher process environment or cached configuration only where the existing runner requires it. Sanitize every watcher-derived message before `sendMessage`, `session_stop`, and `appendNotice`. Do not call OMP's advisor enablement or mutate advisor state.

**Acceptance criteria:**

- [x] Both command names open the same ADW editor in interactive OMP sessions and return a clear non-interactive message otherwise.
- [x] Only an explicit user-triggered Save action writes. The bridge uses an expected file digest, rereads the canonical target, preserves opaque unknown keys, and refuses concurrent changes without overwriting them.
- [x] Saving creates or updates the resolved `.agent-discipline.json`, and the next watcher call observes the new policy without restart.
- [x] The command never reads or writes `WATCHDOG.yml`, never toggles `--advisor`, and reports bridge errors without losing the current editor state.

**Verification:**

- [x] Test command registration, project path forwarding, save failure handling, and next-call policy reload with a fake runner.
- [x] Run `bun test pi/extensions/agent-discipline-watcher/index.test.ts`.
- [x] Manually change one family gate and confirm a matching OMP write changes from block to observe or release according to the selected state.

**Dependencies:** Task 2, Task 3

**Files likely touched:**

- `pi/extensions/agent-discipline-watcher/index.ts`
- `pi/extensions/agent-discipline-watcher/watcher.ts`
- `pi/extensions/agent-discipline-watcher/index.test.ts`

**Estimated scope:** M

## Task 5  Close OMP lifecycle and payload parity gaps
**Description:** Compare the OMP extension event map with the Claude and Codex routes. Pre-gate every equivalent direct writer, not only `write` and `bash`. Reject conflicting `path`, `file_path`, and equivalent aliases before either pre or post processing, then use one canonical validated target. Route failed tool results to `PostToolUseFailure` where OMP exposes `tool_result.isError`. Forward user prompts and subagent lifecycle events where OMP has a safe equivalent. Before PostToolUse scanning, project tool-result content through bounded chunk and byte limits, cap extracted target count, canonicalize and validate every candidate path against an explicit trusted-root policy and the original tool input. Reject forged result-text paths, `../` escapes, outside-cwd absolute paths, and symlink escapes. Pin the canonical target or verify its inode immediately before reading to reduce swap races. Validate runner JSON against a strict result shape, cap serialized input, bound runner time, and use the per-event fallbacks below. Preserve the current Stop continuation behavior and pass the exact session and tool identifiers needed by the Python hooks.


**Acceptance criteria:**

- [x] OMP pre-gates Write, Edit, MultiEdit, NotebookEdit, apply_patch, and Bash through the same `PreToolUse` dispatcher. Conflicting path aliases block before the runner is called.
- [x] Post-tool success and failure routes bound result chunks and bytes, cap result-derived targets, validate scan targets before reading, and open each approved file with no-follow semantics. Verify `fstat` against the validated inode and scan the opened bytes while holding the descriptor. Post-tool errors record and advise without pretending to roll back a completed tool. Failure text and targets are quoted and sanitized as data. Malformed post responses fail safely without exposing raw fields.
- [x] Stop errors block continuation. Session-start errors remain user-visible diagnostics without being treated as tool approval. Prompt and subagent routes preserve the matching Python hook semantics.
- [x] Every mutating OMP tool result must resolve at least one trusted target. An unresolved or obfuscated target persists a blocker for Stop instead of returning an advisory-only notice.
- [x] Block, observe, judged, inherited-advice, and Stop continuation semantics match the existing Python hook results.

**Verification:**

- [x] Add event-map tests for every supported OMP event and tool type.
- [x] Add path-security tests for fabricated hashline paths, result `resolvedPath`, conflicting aliases, `../` traversal, outside-cwd absolute paths, symlinks escaping the trusted root, control characters, and a path swap between validation and read.
- [x] Add fallback tests for pre-tool block, post-tool advise, post-tool failure, unresolved mutating-tool paths, Stop continuation block, malformed runner JSON, oversized input, oversized tool-result content, and runner timeout.
- [x] Run the focused Python hook tests and the Bun extension suite.
- [x] Exercise one blocked write, one observed finding, one post-write advisory, one forged outside-cwd path, and one Stop continuation in a real OMP session.

**Dependencies:** Task 1, Task 4

**Files likely touched:**

- `pi/extensions/agent-discipline-watcher/index.ts`
- `pi/extensions/agent-discipline-watcher/watcher.ts`
- `pi/extensions/agent-discipline-watcher/index.test.ts`
- `hooks/record.py`
- `hooks/test_hooks.py`

**Estimated scope:** M

## Task 6  Add separation, parity, and user-flow coverage

**Description:** Pin the boundary between ADW policy and the OMP advisor harness. Add tests that prove the two commands edit different files, that OMP advisor configuration remains independent, and that every ADW setting exposed by the screen survives a read and write round trip. Add regression coverage for the current advisory response shape, the complete SessionStart contract, malformed hook payload sentinels, partial tool failures, hostile model or finding text, and unapproved semantic or document-review egress.

**Acceptance criteria:**

- [x] ADW configuration tests use `.agent-discipline.json`, while advisor tests use `WATCHDOG.yml` and never cross the boundary.
- [x] Every screen field round-trips through the bridge without changing unrelated keys or protected invariants.
- [x] The test suite catches premature contract truncation, missing OMP pre-gates, and source text sent to an unapproved provider.

**Verification:**

- [x] Run `cd hooks && python3 -m pytest . lib -q`.
- [x] Run `bun test pi/extensions/agent-discipline-watcher/index.test.ts`.
- [x] Run `bash -n install.sh hooks/run.sh pi/install.sh`.

**Dependencies:** Task 2, Task 4, Task 5

**Files likely touched:**

- `hooks/test_configure.py`
- `hooks/lib/test_hookio.py`
- `pi/extensions/agent-discipline-watcher/index.test.ts`
- `pi/test_merge_settings.py`
- `hooks/lib/test_pattern_semantic.py`
- `hooks/lib/test_document_review.py`

**Estimated scope:** M

## Task 7  Update integration documentation and verification commands

**Description:** Document the OMP ADW command, supported policy fields, project-only scope, runtime environment limits, and the separation from OMP's `/advisor configure`. Update the OMP installation and verification sections so users can discover and test the new screen without confusing it with the OMP advisor harness.

**Acceptance criteria:**

- [x] README names both ADW commands and points to `.agent-discipline.json` as their target.
- [x] README states that `/advisor configure` edits `WATCHDOG.yml` and is a separate OMP feature.
- [x] Verification commands cover the bridge, overlay, lifecycle parity, and the existing Claude and Codex integrations.

**Verification:**

- [x] Run the full repository test commands listed in README.
- [x] Run `pylint $(git ls-files '*.py')` when pylint is installed.
- [x] Review the documentation against the final command names and screen fields.

**Dependencies:** Task 6

**Files likely touched:**

- `README.md`
- `skills/agent-discipline-watcher/SKILL.md`
- `CHANGELOG.md`

**Estimated scope:** S

## Trust Boundary

The OMP path currently crosses several trust boundaries.

1. `sessionId(ctx)` copies `ctx.sessionManager.getSessionId()`. `watcherPayload()` adds that value, `ctx.cwd`, the mapped tool name, normalized tool input, and the tool call id. `normalizeArgs()` copies unknown input fields, so tool values remain untrusted data. Command handlers must use the canonical OMP cwd and must not accept a user-supplied cwd for bridge reads or writes. Subagent and scope identifiers must come from immutable host event fields, never command arguments.
2. `runWatcher()` serializes the payload and sends it to `run.sh` with `execFileSync`. The runner path is selected from `AGENT_DISCIPLINE_WATCHER_HOME` or the user home. `run.sh` selects a fixed Python dispatch route and probes the configured Python version. Input size and runner time must be bounded. `PATH` and `ADW_PYTHON` remain ambient process trust, so runner output is not authenticated. Inherited environment authorization must not silently turn a configuration save into a hook escape.
3. `pre_tool.py`, `pre_bash.py`, and `pre_write.py` resolve `effective_hook_config()` from the payload cwd. They run protected-path checks, scanner gates, and `resolve_outcome()`. Relative protection targets must resolve against that same trusted cwd before checks, not the hook process cwd. `protected.authorized()` reads the human environment escape for protected hook paths and opaque Bash rules. It must not authorize configuration-screen writes.
4. Findings and decisions flow through `run_with_ledger()`. Ledger rows use `record_findings()` and `append_row()`. Session and blocker state use `session_state.write_state()` and `blocker_state` updates. Validate and bound finding paths and blocker reasons at the state-write boundary, then sanitize again for every renderer. Reports must not become an uncontrolled copy of source text.
5. `record._scan_paths()` resolves each candidate with `payloads.resolved_path()` and passes it to `read_scannable()`. It currently has no project-root containment check. A forged `details.resolvedPath`, hashline header, or result-text path can make PostToolUse read an arbitrary local file before message rendering. Canonicalize candidates, reject traversal, outside-cwd absolute paths, symlink escapes, control characters, and result-text paths that are not correlated with the original tool input or a verified host result. The final read must use no-follow open semantics, verify `fstat` against the approved inode, and scan bytes from the held descriptor so a path swap cannot redirect the read.
6. `runWatcher()` currently casts any parsed JSON to `WatcherResult`. `blockReason()` and `feedbackMessage()` can therefore receive non-string fields. Validate the result shape before use, wrap every OMP lifecycle handler with safe fail-closed handling, and fail closed on malformed blocking results.
7. `feedbackMessage()` returns raw `hookSpecificOutput.additionalContext` before raw `systemMessage`. `appendNotice()` concatenates that text into OMP tool-result content. `session_stop` also returns watcher-derived text directly as `reason` or `additionalContext`. Sanitize terminal controls, normalize line breaks, and encode markup-like text at every delivery sink.
8. `hookio._bounded_payload()` limits JSON byte size and serializes non-ASCII characters, but it does not strip terminal controls, normalize hostile line breaks, or encode markup. A fitting response must still preserve the complete contract.
9. Runtime status must not echo raw `ADW_EMBEDDING_URL`, `ADW_EMBEDDING_URLS`, or other environment values. Redact URL userinfo and query strings, report configured or unset, and show only the `ADW_PYTHON` executable basename. `ADW_ALLOW_PROTECTED_EDIT` is never an actionable control.

Task 2 must enforce bridge authorization independently of the UI. Task 3 and Task 4 must close the scan and display gaps. The bridge must handle strict JSON, size and depth caps, symlink target resolution, and read/write races. Its write path must preserve unrelated keys while excluding `state_root` and `ledger_root`. Tests must include forged hashline paths, `resolvedPath`, `../` traversal, outside-cwd paths such as `/etc/hosts`, symlink escapes, control characters, malformed runner JSON, and inherited `ADW_ALLOW_PROTECTED_EDIT`.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| TypeScript duplicates Python policy rules | High | Route describe, read, and write operations through the Python bridge and test metadata against `config.py`. |
| ADW screen is mistaken for the OMP advisor | High | Use separate commands, files, labels, tests, and documentation. Never call advisor runtime APIs from ADW handlers. |
| OMP event mapping misses a writer or failure path | High | Build an explicit event matrix from `pre_tool.py`, `hooks.json`, `codex-config.snippet.toml`, and OMP extension events. Test every supported row. |
| UI writes weaken self-protection | High | Lock always-blocking fields and revalidate every write in Python before atomic replacement. |
| Existing dirty changes hide regressions | Medium | Reconcile them before adding the screen. Keep the first checkpoint green. |
| Runtime-only environment controls appear configurable but do not persist | Medium | Mark them read-only in the screen and show the exact shell or OMP startup configuration location. |
| Same-user process impersonation | Medium | Accepted for this release as a host-trust limitation. Keep the capability file owner-only and one-shot. Replace it with an authenticated OMP channel if the host exposes one. |

## Deferred Follow-ups

- Harden protected-file identity checks against hardlink aliases and include `mv` source paths when checking protected install surfaces.
- Audit cap-override and protected-hook detection through `env` and other shell wrappers, including `env ADW_ALLOW_PROTECTED_EDIT=1 hooks/run.sh ...`.
- Decide whether opaque Bash writes such as `python3 -m module`, `curl | tee`, and `xargs tee` must become fail-closed for every host or remain documented residual gaps.
- Audit ledger file permissions and add owner-only mode checks for rows containing session ids, tool ids, paths, and decisions.
- Audit installer and settings-target protection for sandbox bypasses through `HOME`, `PI_CODING_AGENT_DIR`, `--agent-dir`, and direct `merge-settings.py` invocation.
- Align relative protection checks with the event cwd and test a session cwd that differs from the hook process cwd.
- Protect or hash the active development checkout used by `SessionStart` and the OMP extension, or document the symlinked-checkout source-integrity risk.
- Redact provider and tool error secrets before persisting failure state or rendering repeated failure guidance.
- Harden the trusted-process boundary around direct `run.sh` and lifecycle-scope calls. The current implementation treats OMP parent attestation as host trust, not cryptographic authentication.
- Add an explicit follow-up for `PATH` and `ADW_PYTHON` interpreter substitution. Pin or verify the runner identity before treating hook output as policy evidence.
- Treat full finding reports as a privacy boundary. Bound retention and content, and document what source excerpts may be written under `~/.adw/reports`.
- Bound optional embedding worker body size, batch size, text size, response size, and persisted server records. Keep this outside the OMP screen slice unless the semantic route is changed.
- Replace session-state pathname checks with descriptor-relative no-follow directory operations before treating storage containment as complete.
- Bind persisted embedding server records to a verifiable worker identity before signaling a PID. Positive PID and loopback URL checks alone are not sufficient.

## Open Questions

- [ ] The decision to fail closed on opaque Bash writes is outside this plan. The residual behavior stays documented until a separate host-wide policy decision covers `python3 -m module`, `curl | tee`, and `xargs tee`.

## Source Verification

The current installed OMP runtime is `18.0.11`. The official release page identifies `v18.0.11` as latest at planning time. Its extension API supports `registerCommand`, `pi.on`, `ctx.ui.custom`, `ctx.hasUI`, and `tool_call` plus `tool_result` interception.

The current Claude Code release is `v2.1.251`. Its hook reference includes `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, and `Stop`.

The current Codex release is `0.151.0`. Its hook reference documents `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, and `Stop`, plus additional session and compaction events.
The verified Python runtime is `3.14.7`. The verified Bun runtime is `1.4.0`. Tests use Python 3.14.7 through `uv` and Bun 1.4.0.

Primary references:

- https://github.com/can1357/oh-my-pi/releases/latest
- https://github.com/can1357/oh-my-pi/blob/main/docs/extensions.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/advisor-watchdog.md
- https://code.claude.com/docs/en/hooks
- https://learn.chatgpt.com/docs/hooks

## Execution Handoff

This is a planning-and-task-breakdown plan, not a GitNexus schema-2 execution artifact. After human approval, generate the normalized GitNexus plan from this scope. Then execute it with `gitnexus-work` so every symbol edit receives a fresh impact check and every commit receives a detect-changes gate.
