# ADW Native Judges, Retention, and Context Discipline

## Goal

Reduce ADW context growth and session debris while making model-backed review native to each host. Claude keeps its existing Haiku comment and Sonnet prose/document split under the `mixed` preset. Codex always uses GPT-5.6 Luna at high effort through the official `openai-codex` Python SDK and an existing ChatGPT subscription session.

## Global Constraints

- Keep deterministic scanning and hard-block behavior unchanged.
- Never invoke `claude -p`, `codex exec`, an MCP judge, or the OpenAI API-key client.
- Codex judging must use `openai_codex`, reuse existing Codex authentication, create ephemeral threads, request structured output, and use `gpt-5.6-luna` with `high` effort.
- Run the SDK with an ADW-owned minimal `CODEX_HOME` under `~/.adw/runtime`, an empty judge working directory, and only a link to the existing Codex authentication file when one exists. Do not inherit user plugins, MCP configuration, project instructions, skills, apps, or session history.
- ADW must not expose or persist authentication tokens. Missing Codex subscription authentication produces a concise login action, not an API-key fallback.
- Claude model reviews use native `type: "agent"` hooks. Do not place a native agent hook on a pre-write gate because a malformed agent response must never deny a write.
- Claude `mixed` keeps the current responsibility split: Haiku judges code comments after eligible writes, Sonnet judges prose and documents once at `Stop`.
- Claude presets are `mixed`, `luna`, `haiku`, and `sonnet`. The installed plugin command is `/agent-discipline-watcher:adw-judge`, and `status` reports the effective preset. Exact `CLAUDE_CODE_REMOTE=true` selects the automatic cloud default of `haiku`; Desktop/Cowork installs must also be able to select an explicit Haiku-only environment because Claude exposes no reliable Cowork hook marker. Local Claude Code defaults to `mixed`. Codex always uses Luna and has no fallback.
- The Luna preset in Claude uses generated command review handlers that call the Task 2 provider; it must never emit a native Claude agent with `model: "luna"`. It falls back to matching Claude native agents only after Codex subscription judging is unavailable. Because Claude native agent handlers are static settings entries and sibling hooks run in parallel, ADW must not pre-install an always-running native fallback that spends Claude tokens on successful Luna reviews. An unavailable Luna review emits one bounded actionable result and atomically switches the managed preset to `mixed` for subsequent events, restoring Haiku comments and Sonnet prose/documents deterministically regardless of which role observed the outage first.
- Use the newest compatible Python on PATH. `.python-version` remains the minimum floor, currently 3.11. The development and supported runtime is Python 3.14.7 or newer compatible Python.
- Every SessionStart runs a 30-day cleanup. The current session and any session with a live lease are exempt. Runtime dependencies and embedding models are not session data and are never age-pruned.
- Model results are cached by content hash, review kind, provider, model, effort, and rubric version. Cache entries expire after 30 days. Cache hits must not call a model.
- Keep hook model context concise. Never duplicate the discipline contract across `systemMessage` and `additionalContext`, and never inject the full readable-output skill into each session.

## Task 1: Runtime selection and bounded storage

Write failing tests for the existing installer regression and for retention behavior. Add one shared newest-compatible Python resolver for installer and hook entrypoints, then make all install branches use it instead of macOS system Python.

Add active-session leases and a startup retention sweep for session state, ledger events, findings/reports, judge cache, and ADW logs. Stream ledger compaction through an atomic replacement instead of loading the full ledger. Preserve records and referenced reports for sessions that are newer than 30 days or have a live lease. Remove stale orphan reports and stale cache/log artifacts. Keep `~/.adw/runtime` and `~/.adw/models` outside cleanup scope. SessionEnd releases the lease, while abrupt exits expire by heartbeat age.

Tests must cover Python 3.14 winning over Python 3.9, the configured interpreter override, active-session exemption, stale inactive deletion, ledger/report referential consistency, corrupt entries, concurrent sweep safety, and idempotent startup cleanup.

## Task 2: Provider-neutral judge and Luna subscription backend

Introduce typed `JudgeRequest` and `JudgeResult` contracts shared by comment, pattern, and document review. Centralize prompt templates and assign a rubric version. Keep candidate extraction local so only candidate text and required source context reach a model.

Implement a Luna provider with `openai_codex`. Launch it with the isolated ADW `CODEX_HOME`, documented app/web/shell/agent feature disables, and an empty working directory. Start an ephemeral, read-only thread with only ADW base/developer instructions and no configured MCP servers. Validate Luna availability through the SDK model list, run at high effort, use a strict JSON output schema, enforce timeout and bounded retry behavior, and return usage metadata. Reject and do not cache any result whose SDK items show a tool, app, MCP, command, or subagent call. Reuse existing Codex authentication automatically. Report the SDK ChatGPT or device-code login action when no subscription session exists. Do not implement API-key login.

Add a local result cache before the provider boundary. Do not cache transport failures or malformed model output. Tests use a protocol-faithful fake SDK boundary and cover exact model, effort, ephemeral mode, read-only sandbox, structured output, authentication failure, malformed output, retry classification, cache hit, cache miss, and rubric invalidation.

## Task 3: Claude native presets and role batching

Replace Claude subprocess model calls with generated review hook settings. The plugin manifest retains deterministic command hooks. ADW owns a clearly identifiable generated block in Claude settings for model-backed review and rewrites only that block. Claude profiles use native agent handlers; the Luna profile uses command handlers backed by Task 2. The managed block never duplicates deterministic plugin gates.

Add the namespaced plugin skill `/agent-discipline-watcher:adw-judge mixed|luna|haiku|sonnet|status`, backed by a small validated executable rather than interpolated skill shell. The executable validates the preset, writes it atomically, regenerates the managed hook block, and explains that settings-only changes are watched automatically (`/reload-plugins` is reserved for plugin install or source updates). Native Claude profiles use `type: "agent"` on post-write and `Stop` lifecycles. `mixed` runs Haiku for comment judgment after eligible writes and Sonnet once at `Stop` for batched prose/document candidates. `haiku` and `sonnet` use the chosen Claude model for both roles. `luna` routes both roles to Task 2 and applies the subsequent-event fallback specified above only when Luna is unavailable.

Candidate journals prevent a Stop reviewer from rereading unrelated files and deduplicate repeated edits by final content hash. Matching Claude hooks run in parallel, so an immediate native PostToolUse agent scopes itself from the host event and never assumes the deterministic command hook has already journaled the edit. Claude always supplies that raw host event to a native agent; ADW cannot shorten it, but must not duplicate its content into the prompt, journal, or main orchestration context. Stop reviewers consume only the bounded current-session journal through an exact ADW reader path. Native agent responses are continuation decisions: `ok: false` feeds bounded remediation back to Claude after a write or at Stop, while deterministic command hooks remain the only hard pre-write gates. Generated prompts require read-only inspection, avoid unrelated files, check `stop_hook_active`, and return `ok: true` for malformed/empty candidate input. No prompt is treated as a tool-security boundary. Tests execute configuration against temporary settings, validate idempotent switching and unrelated-hook preservation, verify role timing, subsequent-event fallback behavior, exact remote default selection, explicit Desktop/Cowork Haiku selection, and fail-open handling of malformed/empty inputs under ADW's control.

## Task 4: Codex synchronization and context budget

Extend Codex hooks to collect the same post-write candidates, run the Luna judge once per completed interaction, and release session leases on SessionEnd. Codex has no model fallback. A missing SDK, missing subscription session, unavailable Luna model, or provider failure emits one bounded actionable finding and does not silently choose another model.

Reduce SessionStart and SubagentStart context to one short contract in one model-visible channel. Remove full readable-output skill injection. Deduplicate async findings by session, turn, rule, path, and content hash. Cap every hook message before serialization and stop copying the same finding into both model-visible and user-visible channels. Replace full-ledger batch reads with bounded current-session reads.

Update installation to provision an ADW-owned Python runtime environment with compatible pinned `openai-codex` and to keep that runtime outside retention cleanup. Update Claude, Codex, Desktop/Cowork, authentication, preset, retention, and troubleshooting documentation. Repurpose or remove dead `WATCHDOG.yml` advisor configuration so it cannot imply unsupported runtime behavior.

Tests cover Claude and Codex hook manifests, install and update idempotence, subscription-only dependency wiring, Luna/high selection, no Codex fallback, context size ceilings, finding deduplication, bounded ledger reads, remote Haiku default, and full existing regression suites.

## Acceptance

- The full Python 3.14 test suite passes with no new warnings.
- Repeated unchanged content produces a judge cache hit and no model call.
- A startup sweep removes inactive session artifacts older than 30 days and preserves every live session.
- Claude presets switch without damaging unrelated settings. `mixed` retains Haiku comments and Sonnet prose/documents.
- Codex model review uses Luna/high through subscription authentication with ephemeral judge threads and leaves no judge session JSONL.
- Session and subagent context no longer contain duplicate contracts or the readable-output skill body.
