<!-- love-render src=plan.json sha=b04826fe do not hand-edit -->

# ADW ecosystem hook integration

> You fear everything as mortals but desire to have everything as gods.
> Seneca

**Goal.** Integrate all 51 validated ADW-scoped ecosystem hook ideas into agent-discipline-watcher: 38 built across ten epics, 13 explicitly deferred with reasons. ADW stays a deterministic, blocking-or-injecting discipline layer across its four clients (Claude Code, Codex, OpenCode, Pi).

**Strategy.** TDD per task on the existing 86-test pytest net, staged Lean rollout for every new blocking gate (observe-first per D7, promoted on adjudicated ledger evidence), with DevOps and responsible-engineering gates borrowed where a hook touches install, user prompts, or secrets.. Hook code is logic-heavy and bug-prone, so the delivery strategy is test-first. The real product risk is not code correctness but gate behavior in live sessions: a false-blocking Stop hook is worse than no hook. So the riskiest assumption is tested by the smallest slice (dispatcher plus Stop gate, live-verified) before the wide build-out, and every new gate ships in observe until the adjudicated ledger shows its precision.

## Decisions
- Keep one canonical Python engine (hooks/lib) behind thin per-client adapters. No HTTP service, no MCP server, no daemon. The type:http and mcp_tool hook types are deferred. Tradeoff: Per-client adapters must be extended by hand for each new event, but ADW gains no network dependency, no auth surface, and no daemon lifecycle to babysit. [claims: claim-canonical-engine | sources: book-information-hiding | receipts: verified]
- All event-schema knowledge lives in one payload-normalization module (hooks/lib/payloads.py) with contract tests per documented field. Hooks never read raw payload keys directly. Tradeoff: One extra indirection per hook, but schema drift across Claude Code versions breaks one tested file instead of eleven hooks. [claims: claim-canonical-engine | sources: book-information-hiding | receipts: verified]
- Every hook lands with a test in the hooks/test_*.py pattern plus the full pytest gate. Wiring tasks additionally re-run merge-config tests. A small live end-to-end verification (E10-T1) proves acceptance behavior without replacing focused tests. Tradeoff: More test code to maintain than ad-hoc hook scripts, in exchange for regression evidence on every change. [claims: claim-acceptance-behavior, claim-continuous-evidence | sources: book-acceptance-tests, book-delivery-evidence | receipts: verified]
- Session-scoped state (freeze lease, first-touch acks, failure streaks, dead ends, compaction snapshot) is durable JSON on disk under ~/.agent-discipline/state/<session_id>/, written atomically, cleaned by SessionEnd. Tradeoff: State files need lifecycle management, but gates survive crash, compaction, and hook-process restarts, which in-memory state cannot. [claims: claim-durable-recovery | sources: book-recovery-durability | receipts: verified]
- Work splits by hook event and capability (delivery slices), not by technical layer. Contended files (pre_write.py, stop.py, prompt_submit.py, the snippets) get explicit sequential dependency chains so no two open tasks own the same file. Tradeoff: Some cross-epic dependencies (the verify lib feeds E2), but zero merge collisions between parallel workers. [claims: claim-bounded-ownership | sources: book-team-boundaries | receipts: verified]
- Stdlib-only Python 3.11+, matching the existing codebase. Atomic file replacement and locking follow CPython primary-documented behavior (os.replace, fcntl). Tradeoff: No third-party ergonomics, in exchange for a zero-dependency install on all clients. [claims: claim-current-python-io | sources: primary-cpython-files | receipts: verified]
- Every gate has three states in central config: off, observe, and enforce. New gates ship in observe, where the full check runs and the ledger records a would_block row but nothing blocks. The metric is fully producible: every entry script runs through the shared main wrapper, which emits one observed heartbeat row per invocation and stamps every ledger row with the session's current turn_id from session state, stop.py advances that turn counter on the first Stop of a turn only, never on a stop_hook_active retry after a block (the pseudo-Stop equivalent advances it on clients without Stop per the parity matrix, and a family with no turn producer on its client is reported per-invocation and labeled as such), so the denominator is the count of distinct observed turn_ids, never raw invocations, which a multi-fire hook would inflate. lib/config logs a state-transition row whenever a family's effective state changes (the producer for the override signal), and the observe report renders each family's would_block sample for the weekly review, persists the lead's true-or-false-signal labels as adjudication rows in the ledger (the adjudication that would_block incidence alone cannot supply), and computes the per-family adjudicated false-signal rate per 20 observed turns, the number E10-T2 consumes. Promotion to enforce requires a burn-in window of at least one week and an adjudicated false-signal rate at or under 1 per 20 observed turns for that family, decided at E10-T2. The existing three families keep their current enforce defaults. No exceptions among shipped gates: the TaskCompleted scan, the taint self-protection rule, and the commit-message scan also start in observe. Explicit opt-in features (freeze lease, first-touch gate, at-mention rule, the injection maps, the data_boundary tier) are user-invoked, not silently shipped, so they enforce on enable, and their default-off wording refers to the feature switch, not a gate state. Tradeoff: Slower protection rollout and a weekly adjudication chore for the lead, but the false-block metric has a defined producer for every term before enforcement, and rollback is a config flip. [claims: claim-continuous-evidence | sources: book-delivery-evidence | receipts: verified]
- Defer all non-deterministic hook types (type:prompt, type:agent, the LLM-judge Stop gate, prompt/agent SubagentStop QA): they break ADW's deterministic-blocking contract, and agent hooks are documented as experimental. Tradeoff: Judgment-call rules (hollow test versus trivial test) stay regex-approximate, but every block stays reproducible and explainable. [claims: - | sources: - | receipts: missing]
- The UserPromptSubmit firewall defaults to injecting a warning, not blocking, on matched human prompts. Block-mode is an explicit config opt-in. Tradeoff: A user can still push past the warning, but ADW never silently erases a human's prompt by default, which is the higher harm. [claims: - | sources: - | receipts: missing]
- Blocking parity is capability-bounded per adapter, never assumed. Pi's adapter has no pre-execution hook point, so blocking gates degrade to post-hoc findings on Pi. OpenCode's pseudo-Stop is injection-only. A gate task for a both-scoped idea is complete only when the parity matrix row records per-client status (wired, degraded, or not available), and touching only Claude wiring never marks such an idea done. Tradeoff: Honest degraded parity is documented instead of pretended uniform enforcement, at the cost of a per-gate matrix row to maintain. [claims: claim-canonical-engine | sources: book-information-hiding | receipts: verified]
- One entry script per event-and-matcher pair, never two hooks racing on the same surface. Where several capabilities share a surface they compose inside the entry script in a fixed order: input rewrites first, then structural gates, then content scans, first deny wins, injected contexts concatenate. Concretely: pre_write.py orchestrates the edit-PreToolUse pipeline (redaction rewrite, protected, freeze, first-touch, taint, scan), record.py orchestrates PostToolUse (edit journal, scan, verify recipes, spill, output redaction), and pre_commit.py and pre_mcp.py own their disjoint matchers. Redaction and the formatter therefore land as lib modules called from these orchestrators, not as separate hooks. Tradeoff: The orchestrator files grow and their ownership chains get longer, but handler order and merge semantics are code, not an unspecified property of client hook dispatch. [claims: claim-canonical-engine | sources: book-information-hiding | receipts: verified]
- Command-bearing config is honored only after a user-owned trust grant recorded outside the repo (~/.agent-discipline/trust/<repo-fingerprint>), written by the installed CLI: 'agent-discipline trust' run in the repo, which works from any cwd because install.sh already links bin/agent-discipline into ~/.local/bin. Without the grant, verify, formatter, lint, typecheck, test, coverage, and AST recipes no-op with a visible note. Commands execute as argv lists, never through a shell. An end-to-end test proves the grant flow (trust, revoke, moved repo) from a temporary target repo after a sandbox install. Tradeoff: One extra explicit step per repo before quality gates run, in exchange for a checked-in .agent-discipline.json in an untrusted repo never executing code automatically. [claims: claim-durable-recovery | sources: book-recovery-durability | receipts: verified]
- record.py's per-call scan is canonical and never suppressed. PostToolBatch is additive only: it reads the ledger rows already written for the batch and reports only new cross-file findings, so nothing is buffered and nothing is lost if PostToolBatch never fires. Correlation uses the per-call tool_use_id, carried in the payload contract and stored in every PostToolUse ledger row, matched against the ids in the PostToolBatch tool_calls array. If the live payloads lack the id (the contract test and the E10 smoke check for it), batch.py drops ledger dedupe entirely and restricts itself to intrinsically cross-file rules, its documented degraded mode. Tradeoff: A batch can surface two block messages (per-call plus cross-file) instead of one perfectly merged report, but no finding ever depends on an event that might not exist or a correlation field that might not arrive. [claims: - | sources: - | receipts: missing]
- Fail-safe registration: an unknown event key in a client config is treated as able to break config parsing before any handler runs, never assumed to be a dormant no-op. Therefore events register train by train behind the E10-T0 gate, every wiring task proves the merged config in a sandbox HOME (parse-back plus the client's own config validation where one exists) before the lead installs live, the parity matrix records the minimum client version per event, and the timestamped install backups are the immediate rollback when a client still rejects a key. Tradeoff: Wiring lands in more, smaller steps than one bulk registration, but a client that chokes on a new event key is caught in a throwaway HOME, not in the operator's live config. [claims: claim-continuous-evidence | sources: book-delivery-evidence | receipts: verified]

## Epics
### E1. Foundation: dispatcher, state, payload contracts, ledger  (2/3 stories done)
Every later hook plugs into a data-driven dispatcher, a tested payload layer, durable session state, and a findings ledger. Nothing user-visible changes yet except if-field scoping and async flags on existing wiring.
- **E1-S1 Core libraries: dispatch, payloads, and gate config** (done, sprint 1, gate simplification)
- **E1-S3 Core libraries: durable session state and findings ledger** (done, sprint 1, gate unit-testing)
- **E1-S2 Existing-wiring hardening and parity map** (doing, sprint 1, gate code-review)

### E2. Turn-end and completion enforcement (Stop family)  (0/6 stories done)
ADW can refuse to end a turn, a subagent, a task, or a tool batch while discipline findings or failed verification stand. This is the MVP value epic.
- **E2-S1 Stop gate** (todo, sprint 2, gate code-review)
- **E2-S2 SubagentStop coverage** (todo, sprint 2, gate code-review)
- **E2-S3 TaskCompleted gate** (todo, sprint 2, gate code-review)
- **E2-S4 PostToolBatch single-pass scan** (todo, sprint 2, gate code-review)
- **E2-S5 Failure-event handling** (todo, sprint 2, gate unit-testing)
- **E2-W E2 wiring and parity** (doing, sprint 2, gate code-review)

### E3. Prompt and context boundary (UserPromptSubmit plus JIT injection)  (0/3 stories done)
Discipline applies at the source: human prompts that induce violations get a deterministic warning (or opt-in block), and targeted convention context is injected exactly when relevant.
- **E3-S1 Prompt firewall** (todo, sprint 3, gate code-review)
- **E3-S2 Just-in-time convention injection on edits** (todo, sprint 3, gate code-review)
- **E3-W E3 wiring** (todo, sprint 3, gate code-review)

### E4. Self-protection and scope discipline  (0/6 stories done)
ADW defends its own leash (config tamper seal, ConfigChange defense) and offers structural scope enforcement (freeze lease, first-touch gate, taint sequences).
- **E4-S1 Quality-config tamper seal** (todo, sprint 4, gate unit-testing)
- **E4-S2 ConfigChange self-tampering defense** (todo, sprint 4, gate code-review)
- **E4-S3 Session-scoped edit freeze lease** (todo, sprint 4, gate code-review)
- **E4-S4 First-touch fact-forcing gate (opt-in)** (todo, sprint 4, gate code-review)
- **E4-S5 Cross-call behavioral taint sequences** (todo, sprint 4, gate unit-testing)
- **E4-W E4 wiring** (todo, sprint 4, gate code-review)

### E5. Compaction resilience  (0/3 stories done)
Discipline state survives compaction: PreCompact snapshots session state, and the already-wired SessionStart(compact) path re-injects the full contract plus the snapshot.
- **E5-S1 PreCompact snapshot with a scoped veto** (todo, sprint 5, gate code-review)
- **E5-S2 SessionStart(compact) contract re-injection** (todo, sprint 5, gate code-review)
- **E5-W E5 wiring** (todo, sprint 5, gate code-review)

### E6. Repo verification tier (config-driven quality gates, trust-gated, observe-first)  (0/9 stories done)
One verify runner plus per-category recipes (format, lint delta, typecheck, impacted tests, coverage, AST rules, commit messages) give runtime evidence that text scanning cannot. Entirely config-driven, inert without the D12 trust grant, and observe-first per D7.
- **E6-S1 Verify runner core** (todo, sprint 6, gate unit-testing)
- **E6-S2 Formatter fixed-point** (todo, sprint 6, gate code-review)
- **E6-S3 Baseline-aware lint delta gate** (todo, sprint 6, gate unit-testing)
- **E6-S4 Content-hashed typecheck gate** (todo, sprint 6, gate unit-testing)
- **E6-S5 Impact-selected tests on edits** (todo, sprint 6, gate unit-testing)
- **E6-S6 Differential coverage ratchet** (todo, sprint 6, gate code-review)
- **E6-S7 AST-native forbidden-API and architecture rules** (todo, sprint 6, gate unit-testing)
- **E6-S8 Commit-message gate** (todo, sprint 6, gate code-review)
- **E6-W E6 wiring** (todo, sprint 6, gate code-review)

### E7. Data boundary (secrets and redaction, opt-in)  (0/4 stories done)
A deterministic secret-block tier plus an opt-in pseudonymization boundary with a persistent, lock-guarded mapping, and spilled-output scanning so indirection is part of the payload. No separate hook registrations: per D11 the rewrites ride the pre_write and record.py orchestrators, so E7 needs no wiring task of its own.
- **E7-S1 Secret block tier** (todo, sprint 7, gate unit-testing)
- **E7-S2 Pseudonymization boundary (Claude-only decision fields)** (todo, sprint 7, gate unit-testing)
- **E7-S3 Spilled-output scanning** (todo, sprint 7, gate code-review)
- **E7-H Human policy gate** (todo, sprint 7, gate code-review)

### E8. Negative memory (dead-end registry)  (0/2 stories done)
Failed approaches become deterministic warnings: mined at Stop and SubagentStop, injected at UserPromptSubmit, optionally blocking reintroduction at PreToolUse.
- **E8-S1 Dead-end registry pipeline** (todo, sprint 8, gate unit-testing)
- **E8-W E8 wiring** (todo, sprint 8, gate code-review)

### E9. Telemetry and audit  (0/4 stories done)
ADW measures itself: which prose rules deserve promotion (dead-rules scorecard), which gates fire (the ledger from E1), what loaded when (InstructionsLoaded), and clean shutdown (SessionEnd).
- **E9-S1 Dead-rules compliance telemetry** (todo, sprint 9, gate unit-testing)
- **E9-S2 SessionEnd cleanup and flush** (todo, sprint 9, gate code-review)
- **E9-S3 InstructionsLoaded audit log** (todo, sprint 9, gate code-review)
- **E9-W E9 wiring** (todo, sprint 9, gate code-review)

### E10. Rollout, live verification, docs  (0/1 stories done)
The MVP slice is proven in a live session, gate defaults are a deliberate human decision on ledger evidence, and SKILL.md plus README document the new surface including parity gaps.
- **E10-S1 Prove and decide** (todo, sprint 10, gate code-review)

