<!-- love-render src=plan.json sha=81e0624b do not hand-edit -->

# ADW ecosystem hook integration agent brief

One task at a time. Execute a story only from its own block.

## Boundary

Work within this project's worktree and its plan. That is your whole sphere for the task, and staying inside it is what keeps the work clean.

Why this frees you rather than fences you:
- State what to build and build it here. A clear target is easier to act on than a list of things to avoid (Boonstra, Google Prompt Engineering, ch.5, Use Instructions over Constraints).
- Self-contained work does not ripple into other projects, so it stays cheap to change, test, and merge (Hunt and Thomas, The Pragmatic Programmer, ch.2, tip 17, orthogonality).
- Tend the work in front of you and make it good, rather than reaching into a neighbour's (Marcus Aurelius, Meditations 4.18).

Honest limit: this worktree is a separate checkout, not an enforced sandbox. It gives each project its own files and branch so they do not collide. It does not stop a process from reaching outside. The boundary holds because you keep it, not because a wall forces it.

## E1-S1 Core libraries: dispatch, payloads, and gate config
- Gate: simplification. Sprint: 1. Status: doing.
- Why: As the ADW maintainer, I want one dispatch table, one payload contract, one state store, and one ledger, so that eleven new hooks share tested plumbing instead of reinventing it.
- Done when:
  - run.sh routes events from a single data-driven table, one entry script per event-and-matcher pair (D11), and unknown events still exit 2 with usage
  - lib/payloads.py exposes typed accessors for every documented field the plan consumes (session_id, cwd, tool_name, last_assistant_message, stop_hook_active, agent_id, agent_type, agent_transcript_path, prompt, source, file_path, error, is_interrupt, duration_ms, tool_calls, task_id, task_subject), each with a contract test
  - lib/config.py carries the central gate-state schema: every gate family resolves to off, observe, or enforce, with observe running the full check and writing would_block rows without blocking (D7)
  - every new hook module follows the existing pattern: an importable module exposing run(payload, config) with I/O only via the hookio helpers, so test files import it directly and call run() the way test_hooks.py already does
- Tasks:
  - [x] E1-S1-T1: Data-driven run.sh dispatcher
  - [x] E1-S1-T3: Payload contract module (lib/payloads.py)
  - [ ] E1-S1-T5: Central gate-state config schema (lib/config.py)

## E1-S3 Core libraries: durable session state and findings ledger
- Gate: unit-testing. Sprint: 1. Status: doing.
- Why: As the ADW maintainer, I want one dispatch table, one payload contract, one state store, and one ledger, so that eleven new hooks share tested plumbing instead of reinventing it.
- Done when:
  - lib/session_state.py survives process restart and concurrent writers (atomic replace), keyed by session_id, and offers a sweep API that removes stale session dirs, the janitor for a missed SessionEnd
  - every gate decision appends one JSONL ledger row with hook, rule, duration_ms, tool_use_id where present, and an outcome from the enum block, inject, would_block, no_edits, and record.py journals every successful edit (path, tool, ts) so completion gates know what changed this session
  - every entry script runs through the shared main wrapper, which emits one observed heartbeat row per invocation, the denominator for the D7 metric and the producer for the E10-T1 heartbeat check
- Tasks:
  - [x] E1-S1-T2: Durable session state store (lib/session_state.py)
  - [ ] E1-S1-T4: Findings ledger, session edit journal, heartbeat wrapper, observe report

## E1-S2 Existing-wiring hardening and parity map
- Gate: code-review. Sprint: 1. Status: todo.
- Why: As the ADW maintainer, I want the existing wiring scoped tighter and a per-client event availability matrix, so that new-event wiring tasks have a factual basis per client.
- Done when:
  - the Claude snippet's Bash pre-commit hook carries the documented if filter for git commit while pre_commit.py's own parser stays as the cross-client backstop
  - an async-flag policy exists: log-only hooks declare async true in the Claude snippet
  - a parity matrix (README section) states, per client and per event used in this plan, wired or degraded or not-available, from each client's primary docs, including the Pi post-hoc-only and OpenCode injection-only-Stop limits
  - HOOK_LIFECYCLES in merge-codex-config.py lists every event ADW wires, with a merge test asserting the list matches the snippet
- Tasks:
  - [ ] E1-S2-T1: if-field scoping plus async flag policy on the Claude snippet
  - [ ] E1-S2-T2: Cross-client event parity matrix plus merge-script generalization

## E2-S1 Stop gate
- Gate: code-review. Sprint: 2. Status: todo.
- Why: As an operator, I want the turn blocked when the final message claims done without evidence or violates prose discipline, so that unproved claims never end a turn silently.
- Done when:
  - stop.py scans last_assistant_message with the existing scanner families plus an unproved-done rule in lib/done_claims.py (done, fixed, complete, or passing language with no verification evidence in the message), keeping scanner.py untouched
  - stop_hook_active is honored with no re-block loops, and the documented cap of eight consecutive blocks is respected by design
  - the optional verify mode runs trusted repo-declared commands, ships in observe per D7, and blocks on failure only once the family is promoted to enforce
  - every decision lands in the ledger
- Tasks:
  - [ ] E2-S1-T1: stop.py discipline plus unproved-done gate
  - [ ] E2-S1-T2: Verify-command Stop gate (deterministic test gate)

## E2-S2 SubagentStop coverage
- Gate: code-review. Sprint: 2. Status: todo.
- Why: As an operator, I want delegated work held to the same turn-end discipline, so that a subagent cannot hand back unproved claims invisibly.
- Done when:
  - subagent_stop.py scans the subagent's last_assistant_message with the same rules as stop.py
  - agent_type matcher support is documented, and ledger rows carry agent_id and agent_type
- Tasks:
  - [ ] E2-S2-T1: subagent_stop.py scan

## E2-S3 TaskCompleted gate
- Gate: code-review. Sprint: 2. Status: todo.
- Why: As an operator, I want a task blocked from completing while its changed files carry findings or its verify matrix fails, so that a bad done lands per task, not at turn end.
- Done when:
  - task_completed.py uses the corrected fields (task_id, task_subject, optional teammate and team) and the corrected control (exit 2 or continue false), not the disproven task_result or decision-block fields
  - scans files recorded as changed this session (ledger) and, when configured, runs the verify matrix scoped by changed-file categories
  - documented as Claude-only until the parity matrix says otherwise
- Tasks:
  - [ ] E2-S3-T1: task_completed.py verification gate

## E2-S4 PostToolBatch single-pass scan
- Gate: code-review. Sprint: 2. Status: todo.
- Why: As an operator, I want one coherent block message per parallel edit batch, so that findings across simultaneous writes are deduplicated and cross-file patterns are visible.
- Done when:
  - record.py's per-call scan stays canonical and is never suppressed or buffered (D13)
  - batch.py correlates via tool_use_id (payload contract and ledger row field) between the tool_calls array and the batch's PostToolUse rows, and reports only new cross-file findings, so its dedupe is of its own output and nothing is lost if PostToolBatch never fires
  - when live payloads lack tool_use_id, batch.py drops ledger dedupe and restricts itself to intrinsically cross-file rules, the degraded mode D13 documents
- Tasks:
  - [ ] E2-S4-T1: batch.py additive cross-file pass (D13)

## E2-S5 Failure-event handling
- Gate: unit-testing. Sprint: 2. Status: todo.
- Why: As an operator, I want repeated tool failures met with deterministic guidance and unhealthy MCP servers short-circuited, so that the agent neither weakens changes to dodge errors nor burns turns on dead providers.
- Done when:
  - failure.py records per-tool and per-target failure streaks (error, is_interrupt, duration_ms) in session state
  - a streak threshold injects a fix-the-root-cause instruction naming the repeated failure
  - MCP substate: a server is marked unhealthy on failure with 30s base exponential backoff capped at 10min, and a PreToolUse consult blocks calls to known-unhealthy servers until backoff expiry
- Tasks:
  - [ ] E2-S5-T1: failure.py plus MCP circuit breaker

## E2-W E2 wiring and parity
- Gate: code-review. Sprint: 2. Status: doing.
- Why: As the ADW maintainer, I want the E2 events registered on every client that supports them, so the gates actually fire on all four clients or the gap is a documented fact.
- Done when:
  - E2-W-T0 wires the Stop event alone and heads the shared-file chain, so E10-T0 can smoke the riskiest bet before anything else goes live
  - the Claude snippet then gains SubagentStop, TaskCompleted, PostToolBatch, PostToolUseFailure, and the mcp__* PreToolUse consult entries, with run.sh routing each event, only after E10-T0 passes
  - the Codex TOML gains the events the parity matrix confirms, and HOOK_LIFECYCLES covers each of them (E1-S2-T2 groundwork)
  - the OpenCode and Pi adapters are extended in their own tasks below for every plan event their APIs support, and every gate's parity row records wired, degraded, or not-available per client (D10)
  - install.sh and merge scripts stay idempotent on re-run, proven by a sandbox install into a temporary HOME with every merged client config parsed back cleanly
- Tasks:
  - [x] E2-W-T0: Wire Stop only (the MVP slice)
  - [ ] E2-W-T1: Wire the remaining E2 events on Claude and Codex (post-smoke)
  - [ ] E2-W-T2: Extend the OpenCode adapter (all plan events its API supports)
  - [ ] E2-W-T3: Extend the Pi adapter (post-hoc surfaces only, with its own tests)

## E3-S1 Prompt firewall
- Gate: code-review. Sprint: 3. Status: todo.
- Why: As an operator, I want prompts like 'just comment it out' or 'skip the tests' met with an injected discipline reminder before the agent complies, so violations stop at the source.
- Done when:
  - prompt_submit.py matches a small reviewed rule list against the prompt field, injects additionalContext by default (D9), and offers block-mode as a config opt-in
  - the at-mention rule (config-gated, default off) blocks literal @filename tokens forcing an explicit Read, for data-boundary mode
  - the keyword-to-context map (config-gated, default off) injects mapped guidance deterministically
  - no prompt text is persisted anywhere
- Tasks:
  - [ ] E3-S1-T1: prompt_submit.py firewall (inject-first)
  - [ ] E3-S1-T2: At-mention bypass rule (config-gated)
  - [ ] E3-S1-T3: Keyword-to-context injection map (config-gated)

## E3-S2 Just-in-time convention injection on edits
- Gate: code-review. Sprint: 3. Status: todo.
- Why: As an operator, I want path-scoped conventions injected at the moment of the edit, so guidance arrives before the model commits to an approach instead of only rejecting after.
- Done when:
  - pre_write.py consults a path-glob-to-snippet map (config) and returns the snippet as context alongside allow
  - injection happens at most once per file per session (session state)
- Tasks:
  - [ ] E3-S2-T1: Path-scoped JIT convention injection in pre_write

## E3-W E3 wiring
- Gate: code-review. Sprint: 3. Status: todo.
- Why: As the ADW maintainer, I want UserPromptSubmit registered where available.
- Done when:
  - Claude snippet plus run.sh route added, other clients per the parity matrix, merge tests updated
- Tasks:
  - [ ] E3-W-T1: Wire UserPromptSubmit (Claude and Codex)

## E4-S1 Quality-config tamper seal
- Gate: unit-testing. Sprint: 4. Status: todo.
- Why: As an operator, I want edits to linter, formatter, typecheck, hook, and ignore configs and to ADW's own wiring blocked unless explicitly authorized, so the agent cannot green-light checks by weakening the checker.
- Done when:
  - a protected-path policy in lib/protected.py blocks edits to existing protected files, allows first-time creation, and fails closed on stat errors (EACCES and EPERM treated as exists)
  - case-insensitive basename matching for case-insensitive filesystems
  - explicit authorization via config or a documented env var, with authorized changes invalidating cached verify results and landing in the ledger
  - new blanket suppressions in source edits (file-level lint disables, blanket type-ignores) are blocked unless policy permits them
- Tasks:
  - [ ] E4-S1-T1: Tamper seal in pre_write (merges the ECC config lock and the tamper seal)

## E4-S2 ConfigChange self-tampering defense
- Gate: code-review. Sprint: 4. Status: todo.
- Why: As an operator, I want mid-session changes to ADW's hook registration blocked, so a prompt-injected instruction cannot silently disable enforcement.
- Done when:
  - config_change.py blocks changes whose source is user_settings, project_settings, local_settings, or skills when the changed file matches ADW wiring or skill files
  - policy_settings changes are logged only, since the docs say blocking is ignored there
- Tasks:
  - [ ] E4-S2-T1: config_change.py hook

## E4-S3 Session-scoped edit freeze lease
- Gate: code-review. Sprint: 4. Status: todo.
- Why: As an operator, I want an opt-in freeze command that denies edits outside a directory boundary until I widen it, so scope creep is structurally impossible during focused work.
- Done when:
  - CLI subcommands freeze, unfreeze, and status write the lease to session state
  - pre_write denies (permissionDecision deny) resolved paths outside the boundary with the lease named in the reason
- Tasks:
  - [ ] E4-S3-T1: Freeze lease (CLI plus pre_write deny)

## E4-S4 First-touch fact-forcing gate (opt-in)
- Gate: code-review. Sprint: 4. Status: todo.
- Why: As an operator, I want the first edit to each file per session to force an explicit impact statement, so change-impact thinking happens before the write, not after.
- Done when:
  - default off. When on, the first Edit or Write per file per session is denied with an instruction to state importers and callers, affected APIs, and the current instruction. The denial marks the file acknowledged in session state so the retry passes
  - destructive Bash (rm -rf and configured patterns) gets the same one-pause gate requiring listed targets and a rollback plan
- Tasks:
  - [ ] E4-S4-T1: First-touch gate in pre_write plus the Bash destructive gate

## E4-S5 Cross-call behavioral taint sequences
- Gate: unit-testing. Sprint: 4. Status: todo.
- Why: As an operator, I want read-secret-then-network and download-then-execute sequences blocked, so multi-step exfiltration patterns are caught that single-payload scans cannot see.
- Done when:
  - record.py (PostToolUse) appends tool events to a session event log, and lib/taint.py evaluates a small named-rule set (sensitive-read-then-network, write-then-build poisoning, sensitive-read-then-MCP) on PreToolUse for Bash, Write, and Edit
  - rules also block Bash commands manipulating ADW's own config or allowlist
  - each rule has a named id in block reasons and ledger rows
- Tasks:
  - [ ] E4-S5-T1: lib/taint.py sequence rules plus the event log feed

## E4-W E4 wiring
- Gate: code-review. Sprint: 4. Status: todo.
- Why: As the ADW maintainer, I want ConfigChange registered and the CLI reachable.
- Done when:
  - ConfigChange snippet plus route. install.sh already links bin/agent-discipline. Merge tests updated
- Tasks:
  - [ ] E4-W-T1: Wire ConfigChange (Claude only per matrix)

## E5-S1 PreCompact snapshot with a scoped veto
- Gate: code-review. Sprint: 5. Status: todo.
- Why: As an operator, I want session discipline state snapshotted before compaction, and compaction vetoed only while a blocking gate is unresolved, so enforcement context cannot be summarized away mid-gate.
- Done when:
  - pre_compact.py writes the snapshot (active leases, ack sets, streaks, pending block state) to session state and handles the manual and auto matchers
  - the veto (block decision) fires only when a blocking gate is mid-flight, and the default is allow
- Tasks:
  - [ ] E5-S1-T1: pre_compact.py snapshot and scoped veto

## E5-S2 SessionStart(compact) contract re-injection
- Gate: code-review. Sprint: 5. Status: todo.
- Why: As an operator, I want the full discipline contract re-injected after compaction, so long sessions do not lose the rules.
- Done when:
  - session_start.py branches on source: compact gets the full contract plus a one-line snapshot summary, startup keeps today's line. Wiring already matches compact on Claude and Codex
- Tasks:
  - [ ] E5-S2-T1: session_start.py compact-path enrichment plus janitor call

## E5-W E5 wiring
- Gate: code-review. Sprint: 5. Status: todo.
- Why: As the ADW maintainer, I want PreCompact registered.
- Done when:
  - PreCompact snippet plus route on clients per the parity matrix
- Tasks:
  - [ ] E5-W-T1: Wire PreCompact

## E6-S1 Verify runner core
- Gate: unit-testing. Sprint: 6. Status: todo.
- Why: As the ADW maintainer, I want one runner for repo-declared checks with changed-file category mapping, so six quality gates share one execution and reporting path.
- Done when:
  - lib/verify.py: a declared matrix in .agent-discipline.json (category to commands), changed-file-to-category mapping, fail-fast, per-command timeout, compact structured failures, ledger rows with elapsed time
  - trust boundary (D12): command-bearing config is inert until a user-owned grant exists at ~/.agent-discipline/trust/<repo-fingerprint>, written by the installed CLI 'agent-discipline trust' run in the repo. Without it every recipe no-ops with a visible note. Commands execute as argv lists, never through a shell
  - an end-to-end test proves the documented command works from a temporary target repo after a sandbox install: trust, revoke, and moved-repo, so the boundary is usable, not just fail-closed
- Tasks:
  - [ ] E6-S1-T1: lib/verify.py runner with the trust boundary

## E6-S2 Formatter fixed-point
- Gate: code-review. Sprint: 6. Status: todo.
- Why: As an operator, I want touched files formatted to a fixed point after each edit with non-convergence blocking, so formatting noise never reaches review.
- Done when:
  - a config map from language to formatter runs on the touched file only, check-mode verifies convergence, changed bytes return the path as context to force a reread, and crashes or non-convergence block
  - opt-in: this is ADW's only mutating hook and the config key says so explicitly
- Tasks:
  - [ ] E6-S2-T1: lib/format_fix.py post-edit formatter recipe

## E6-S3 Baseline-aware lint delta gate
- Gate: unit-testing. Sprint: 6. Status: todo.
- Why: As an operator, I want only newly introduced lint diagnostics blocked, so legacy debt stays visible without freezing work.
- Done when:
  - the baseline is captured lazily once per session on the first post-edit check (keyed by session_id in session state, which keeps all work inside lib and avoids owning session_start.py), post-edit lint runs on the touched file or package and blocks only new diagnostics in structured file, line, and rule form, and the baseline recomputes on base-revision or lint-config change
- Tasks:
  - [ ] E6-S3-T1: lib/lint_delta.py plus lazy baseline capture

## E6-S4 Content-hashed typecheck gate
- Gate: unit-testing. Sprint: 6. Status: todo.
- Why: As an operator, I want fresh type errors blocked cheaply after typed-language edits, so cross-file type breakage is caught before review.
- Done when:
  - locate the owning package, run the no-output typecheck, cache keyed by config-file hashes (the verified prior art) with a full-input hash as stretch, block on fresh errors, and offer an uncached full check at completion
- Tasks:
  - [ ] E6-S4-T1: lib/typecheck.py cached gate

## E6-S5 Impact-selected tests on edits
- Gate: unit-testing. Sprint: 6. Status: todo.
- Why: As an operator, I want the affected tests run immediately after a source edit, so behavioral evidence arrives per edit, not per turn.
- Done when:
  - adapters for jest --findRelatedTests and pytest-testmon, failing assertions returned as blocking feedback, and the full suite reserved for Stop, TaskCompleted, or commit
- Tasks:
  - [ ] E6-S5-T1: lib/impacted.py test selection adapters

## E6-S6 Differential coverage ratchet
- Gate: code-review. Sprint: 6. Status: todo.
- Why: As an operator, I want changed-line coverage below policy blocked at completion or commit, so new debt is stopped while legacy coverage stays visible.
- Done when:
  - diff-cover and coverage.py integration, changed-line and changed-branch thresholds, and rejection of a drop from the base-branch baseline
- Tasks:
  - [ ] E6-S6-T1: lib/coverage_gate.py ratchet

## E6-S7 AST-native forbidden-API and architecture rules
- Gate: unit-testing. Sprint: 6. Status: todo.
- Why: As an operator, I want project-owned ast-grep or Semgrep rules run on changed files with rule ids and precise ranges, so code-pattern policy is structural, not regex-lexical.
- Done when:
  - the adapter runs project rules on changed files at PostToolUse and diff-wide at commit or TaskCompleted, blocks with rule id plus range, and reserves regex for non-code files
- Tasks:
  - [ ] E6-S7-T1: lib/ast_rules.py adapter

## E6-S8 Commit-message gate
- Gate: code-review. Sprint: 6. Status: todo.
- Why: As an operator, I want commit messages extracted from -m payloads and scanned (discipline families plus an optional conventional-commit format) before Bash executes, so commit text meets the same bar as file text.
- Done when:
  - pre_commit.py extracts every -m and message-file payload with its existing shell-aware parser, scans with the scanner families, applies the optional format policy from config, and lets editor-only forms pass unless strict mode is on
- Tasks:
  - [ ] E6-S8-T1: Commit-message extraction and scan in pre_commit

## E6-W E6 wiring
- Gate: code-review. Sprint: 6. Status: todo.
- Why: As the ADW maintainer, I want the verification recipes reachable from record.py, stop.py, and task_completed.py per config.
- Done when:
  - record.py consults configured recipes post-edit, stop and task_completed run the full tier, snippets are updated where a new registration is needed, and every recipe is inert without the trust grant and observe-first per D7
- Tasks:
  - [ ] E6-W-T1: Integrate verify recipes into the hook flow

## E7-S1 Secret block tier
- Gate: unit-testing. Sprint: 7. Status: todo.
- Why: As an operator, I want true secrets (key, token, and credential patterns) blocked at write, commit, and prompt, so secrets never pass a boundary in plain form.
- Done when:
  - a new secrets scanner family, config-gated, with a reviewed pattern set and per-rule ids, available to every scan_all caller: pre_write and pre_commit pick it up with no file edits, and the prompt boundary consumes it through E3-S1-T1's scanner integration
  - blocked values never reach the ledger or reports in plain form (fingerprint only)
- Tasks:
  - [ ] E7-S1-T1: Secrets family in the scanner

## E7-S2 Pseudonymization boundary (Claude-only decision fields)
- Gate: unit-testing. Sprint: 7. Status: todo.
- Why: As an operator, I want lower-risk identifiers consistently pseudonymized via updatedInput and updatedToolOutput with one stable mapping, so scrubbed sessions stay coherent.
- Done when:
  - lib/pseudonym.py holds the persistent mapping under an exclusive flock on a sidecar lockfile, with one synthetic replacement per matched value across concurrent invocations
  - the input rewrite (updatedInput) runs first inside pre_write's orchestration and the output rewrite (updatedToolOutput) inside record.py's (D11), so rewrite-then-scan order is code, not racing hook registrations. Both default off, enabled only by data_boundary config
  - documented Claude-only (the decision fields are unavailable elsewhere), with other clients getting the block tier only
- Tasks:
  - [ ] E7-S2-T1: lib/pseudonym.py mapping store (keyed HMAC)
  - [ ] E7-S2-T2: lib/redact_input.py wired first in pre_write (updatedInput)
  - [ ] E7-S2-T3: lib/redact_output.py wired last in record.py (updatedToolOutput)

## E7-S3 Spilled-output scanning
- Gate: code-review. Sprint: 7. Status: todo.
- Why: As an operator, I want spill stubs (truncated, preview, and output-file indirection) scanned at their source up to 1 MiB, so hidden content is part of the payload.
- Done when:
  - lib/spill.py recognizes the stub heuristics, reads the spilled path capped at 1 MiB, runs block rules against the hidden content, and is wired from record.py
- Tasks:
  - [ ] E7-S3-T1: lib/spill.py plus record.py integration

## E7-H Human policy gate
- Gate: code-review. Sprint: 7. Status: todo.
- Why: As the owner, I decide the redaction policy (identifier classes, retention of the mapping store, custody and rotation of the HMAC key, who may enable data_boundary mode) before the tier can be switched on.
- Done when:
  - a short written policy in the repo docs covering identifier classes, mapping retention, and HMAC key custody plus rotation, and data_boundary mode refuses to enable without it
- Tasks:
  - [ ] E7-H-T1: Redaction policy decision

## E8-S1 Dead-end registry pipeline
- Gate: unit-testing. Sprint: 8. Status: todo.
- Why: As an operator, I want tried-and-reverted approaches remembered outside the repo and surfaced when they are about to be retried, so sessions stop rediscovering the same dead ends.
- Done when:
  - a repo-keyed JSONL store outside the repo with a schema of approach fingerprint, evidence pointer, created, and expiry
  - miners on Stop and SubagentStop detect tried-and-reverted hunks from the session ledger and transcript
  - UserPromptSubmit injects a DEAD END card on match, and the PreToolUse similarity check warns by default and blocks only when configured
- Tasks:
  - [ ] E8-S1-T1: lib/deadends.py store plus similarity fingerprinting
  - [ ] E8-S1-T2: Stop and SubagentStop dead-end miners
  - [ ] E8-S1-T3: UserPromptSubmit dead-end warning card
  - [ ] E8-S1-T4: PreToolUse reintroduction guard (warn-first)

## E8-W E8 wiring
- Gate: code-review. Sprint: 8. Status: todo.
- Why: As the ADW maintainer, I want the registry flush wired into PreCompact and SessionEnd.
- Done when:
  - pre_compact and session_end flush pending mining state, and no new events are needed
- Tasks:
  - [ ] E8-W-T1: Registry lifecycle wiring

## E9-S1 Dead-rules compliance telemetry
- Gate: unit-testing. Sprint: 9. Status: todo.
- Why: As the maintainer, I want CLAUDE.md parsed into atomic rules with per-rule relevance and violation tallies and a worst-first scorecard, so the next prose rule worth converting into a deterministic blocker is a measurement, not a guess.
- Done when:
  - SessionStart parses CLAUDE.md into numbered rules, PostToolUse tallies, and SessionEnd renders the worst-first scorecard to the ledger dir
- Tasks:
  - [ ] E9-S1-T1: lib/dead_rules.py plus its three hook integrations

## E9-S2 SessionEnd cleanup and flush
- Gate: code-review. Sprint: 9. Status: todo.
- Why: As an operator, I want session state cleaned and metrics flushed however the session ends, so state directories do not accrete.
- Done when:
  - session_end.py flushes ledger buffers, renders pending scorecards, removes the session state dir, and stays fast (async where wired)
- Tasks:
  - [ ] E9-S2-T1: session_end.py

## E9-S3 InstructionsLoaded audit log
- Gate: code-review. Sprint: 9. Status: todo.
- Why: As the maintainer, I want a ground-truth log of which rule and skill files loaded and why, so checking whether an orphaned hook still loads is a one-line lookup.
- Done when:
  - instructions_loaded.py appends file, load_reason, and ts to the ledger dir, runs async, and its output is ignored per docs
- Tasks:
  - [ ] E9-S3-T1: instructions_loaded.py async logger

## E9-W E9 wiring
- Gate: code-review. Sprint: 9. Status: todo.
- Why: As the ADW maintainer, I want SessionEnd and InstructionsLoaded registered with async true.
- Done when:
  - snippet entries with async true on both, routes added, merge tests updated. Covers the wiring half of the async-hooks idea
- Tasks:
  - [ ] E9-W-T1: Wire SessionEnd plus InstructionsLoaded (async)

## E10-S1 Prove and decide
- Gate: code-review. Sprint: 10. Status: todo.
- Why: As the owner, I want live proof that the events fire as planned and an evidence-based decision on which gates go default-on, so rollout is a decision, not a hope.
- Done when:
  - E10-T0 first: a live session proves the Stop hook blocks and releases as documented, before any other new event goes live. The lead runs the install. This is the first pivot-or-persevere gate from validation.decision_rule
  - E10-T1 then verifies the full surface: SubagentStop scan, UserPromptSubmit inject, ConfigChange block, PreCompact snapshot plus compact re-inject, with a heartbeat requirement (at least one ledger row per wired event during the session) and the installed client version recorded next to the results
  - the gate promotion decision (observe to enforce) is recorded per family with the report's adjudicated false-signal rate and ledger numbers that justified it
  - SKILL.md and README are updated with new events, config keys, the parity matrix with its fallback column, and kill-switches, and block messages are reviewed for actionability (the block message is ADW's whole UI)
- Tasks:
  - [ ] E10-T0: Live Stop smoke (the MVP experiment)
  - [ ] E10-T1: Full-event live verification
  - [ ] E10-T2: Gate promotion decision (observe to enforce)
  - [ ] E10-T3: SKILL.md plus README documentation pass

