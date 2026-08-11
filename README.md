# Agent Discipline Watcher

Agent Discipline Watcher is a Claude Code plugin that keeps agent output disciplined. It auto-rewrites safe style issues in a pending write; remaining enforced style findings resolve to `must_fix` and produce forceful advisories, while only the security/self-protection rules in `ALWAYS_BLOCKING_RULES` block. The main session model never changes, whatever gate runs.

## How it works

Every tool call goes through `hooks/pre_tool.py`, a single coordinator that reads the tool name and dispatches to the right check: `pre_write.py` for `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, and `apply_patch`, `pre_bash.py` and `pre_commit.py` for `Bash`, and `pre_mcp.py` for `mcp__*` calls. One process owns this because parallel hooks racing to rewrite the same tool input would produce nondeterministic results.

For a pending write, `pre_write.py` scans the proposed content, then calls `hooks/lib/rewrite.py` to auto-fix safe style findings in prose, code comments, multi-line comment runs, and Python docstrings. It returns the rewritten `updatedInput`; changed or still-flagged lines use a forceful itemized notice led by "agent-discipline-watcher changed or flagged the following. This is not a suggestion: re-check every line below before you consider this edit done." Each row uses `[status] path:line family/rule: action`, where `status` is `removed`, `rewritten`, or `flagged`; a cleanup with no line-level findings may use a compact summary. Findings in the always-blocking security and self-protection families still deny the call outright. Writes to live client config, or routes around the gates, fall in that set. Enforced style findings that cannot be safely rewritten, such as hollow tests, over-long functions or files, and content-dependent English rules, remain as itemized `must_fix` advisories rather than blocking.

After the write lands, `hooks/record.py` rescans the written file deterministically. If an enforced `must_fix` finding remains, it reruns the same rewriter against the file on disk, applies a Python syntax check where applicable, and writes the correction back when safe. Its forceful itemized advisory says that this correction was not part of the tool call and tells the agent to re-check every listed line; style findings never block continuation, and only `ALWAYS_BLOCKING_RULES` findings deny. Separately, `hooks/hooks.json` registers a second `PostToolUse` hook of `"type": "agent"` running on `model: haiku` with `continueOnBlock: true`. That Haiku agent reads a bounded per-tool-use report (never the whole transcript), ignores anything the deterministic cleaner already fixed, and judges only what is left unresolved. It returns `{"ok": true}` or `{"ok": false, "issue": ..., "evidence": ..., "repair": ...}`, and that feedback folds into the same turn. It is a separate model call. It never changes the main session model, and no rewrite, permission, or file-mutation decision depends on it.

**Experimental: Haiku pre-write correction.** A second, independent `PreToolUse` hook of `type: agent` on `model: haiku` runs alongside the deterministic rewrite in `pre_tool.py`. Claude Code documents this hook type as experimental. Its scope is narrow: prose and comment phrasing that needs real content knowledge to fix correctly (a dead metaphor, inflated diction, a vague quantity, awkward but recoverable docstring phrasing) which the deterministic regex rewriter declines to touch. It never attempts a hollow test, an over-long function, or an over-long file. On any failure, timeout, or low confidence, it returns nothing and the write proceeds exactly as if this tier did not exist, it is strictly additive and never a new blocking dependency. Claude Code does not precisely document how multiple `PreToolUse` hooks for the same event are merged or ordered, so this hook is designed to be safe regardless of ordering: it never overwrites another hook's output, it only offers an independent correction attempt.

## Comment policy

Ordinary code comments are not blocked. A comment carrying a concrete WHY (a constraint, a tradeoff, a reason a simpler approach was rejected) is preserved, as is a genuine first-line summary in a public Python scope. A single comment line that only narrates what the code already says (case labels, "increment the counter", restated code) is flagged as `narration_comment` or `what_comment` and removed by the rewriter. A multi-line Python docstring that narrates WHAT is removed when it is pure narration, or has only those lines stripped when a WHY line survives; a multi-line comment run with no WHY marker anywhere is flagged as `prose_comment_block` and removed as a run. A WHY comment that gestures at a reason without naming a concrete constraint or consequence gets a `weak_why_comment` advisory note instead of being deleted, since the rewriter cannot safely guess the missing specifics.

## Optional embedding helper

Set `ADW_EMBEDDING_HELPER` to an absolute path to an executable to let the watcher compare pending text against known-bad prototypes by embedding similarity. `hooks/lib/embeddings.py` invokes it one-shot: load the model, embed one batch, exit, with `shell=False`, a bounded timeout, and a capped payload size. The plugin never depends on this helper. Any failure, missing path, non-executable file, or malformed output falls back to the deterministic scanner with no loss of function. The watcher never starts or talks to a persistent server.

## Install

### Claude Code

```
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

The marketplace entry and the plugin manifest both currently read version 0.13.0. Both must match, and `hooks/test_plugin_wiring.py` fails the suite if they drift, so a fresh checkout is the source of truth over this text.

### Other clients

`install.sh` wires Codex, OpenCode, and Pi from this checkout:

```bash
./install.sh          # interactive
./install.sh -y       # non-interactive
./install.sh --no-claude --codex --no-pi -y
```

For Claude Code, `install.sh` does not write settings itself. A shell script cannot type a slash command, so it prints the three commands above and removes any legacy path-based wiring first.

### Requirements

Python 3, a Unix shell, and recent Claude Code with `PostToolUse` agent-hook support. The `"type": "agent"` hook entry in `hooks/hooks.json` needs it. No minimum version is pinned in this repository. If a hook fails to register, update Claude Code and retry.

## Reminder timing

A one-line clean-code reminder reaches the model twice: once at `SessionStart` (`hooks/session_start.py`, sent as `additionalContext` so the model reads it, plus a short `systemMessage` copy for the transcript), and again on every `PreToolUse` call (`hooks/pre_tool.py`'s `WRITE_REMINDER`). The `PreToolUse` copy matters because that context reaches the next model request, right before the write it is meant to steer, not only at the start of the session.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root. The hook code searches upward from the current working directory for it. If none is found, the default checks apply. See `hooks/lib/config.py` for the full set of keys (`checks`, `baseline`, `exempt_paths`, `exempt_families`, `gates`, `rule_gates`, and the length-cap overrides).

## Self protection

The `self_protection` family blocks routes around the gates. It covers writing a live client install path, and editing `.agent-discipline.json` in a way that would release a protection rule. It also covers running `install.sh` without a sandboxed `HOME`, a no-verify commit that skips the hooks, overriding length-cap environment variables from a command line, and deleting watcher state. These rules are built into `hooks/lib/protected.py` and `hooks/pre_bash.py`. They are never loaded from project configuration, and no check switch or gate state can disable them. The only escape is a human exporting `ADW_ALLOW_PROTECTED_EDIT=1` in the shell that starts the client.

## Cross-Client Event Parity

Claude Code is the primary surface. Codex, OpenCode, and Pi get one Pi extension and matching Codex and OpenCode adapters, each covering what its host client actually fires. Status vocabulary:

| Status | Meaning |
| --- | --- |
| `wired` | The client fires the event and ADW registers it today. |
| `degraded` | ADW wires a reduced path, or only a reduced equivalent exists. The note names the limit. |
| `not-available` | ADW wires no path for this event on this client. The note says whether the client documents an equivalent. |
| `unknown` | Docs too thin to decide. Treated as not-available for gating. |

Cells use the state word alone or as `state: note`. The note carries any unwired nuance.

| Event | Claude | Codex | OpenCode | Pi | Fallback when the event never fires | Min client version |
| --- | --- | --- | --- | --- | --- | --- |
| `SessionStart` | wired | wired | wired: `session.created` injects the returned context through `promptAsync` only when `parentID` is absent | degraded: `before_agent_start` injects the policy and readable output prompts but exposes no parent-session or agent-kind discriminator, so Pi cannot enforce main-agent-only injection | No injection that session. Edit-time gates still fire. | unknown |
| `SubagentStart` | wired: `subagent_start.py` injects the contract, no matcher, so every agent type is covered | not-available: ADW wires no path, no documented equivalent established | not-available: ADW wires no path, no documented equivalent established | not-available: ADW wires no path, no documented equivalent established | The subagent runs without the contract. Its edits still hit the per-edit PreToolUse and PostToolUse gates. | unknown |
| `PreToolUse` | wired: `pre_tool.py` coordinates the rewrite and security gate | wired | wired: `tool.execute.before`, write and edit tools only | degraded: blocking `tool_call` documented in current Pi, ADW adapter unwired, post-hoc today | PostToolUse rescan writes back safe `must_fix` corrections and advises; only security/self-protection findings block. | unknown |
| `PostToolUse` | wired: `record.py` rescans, writes back safe `must_fix` corrections, and advises; plus the agent-type Haiku review hook | wired | wired: `tool.execute.after` | wired: `tool_result`, findings return as an error result | PreCommit scans staged files at commit time. | unknown |
| `Stop` | not-available: no Stop module ships, chat replies are not scanned | not-available: Codex documents Stop with continuation, ADW unwired | degraded: pseudo-Stop on `session.idle` is injection-only through `promptAsync`, it cannot block | not-available: `turn_end` is observation-only | Per-edit `record.py` (PostToolUse) scanning already covers every write, so no turn-level pass is needed. | unknown |
| `SubagentStop` | not-available: no SubagentStop module ships, chat replies are not scanned | not-available: Codex documents SubagentStop, ADW unwired | not-available | not-available | Subagent edits still hit the per-edit PostToolUse scans. | unknown |
| `TaskCompleted` | not-available: Claude documents TaskCompleted, ADW has no module yet | not-available | not-available | not-available | The full suite runs at commit time instead. | unknown |
| `PostToolBatch` | wired: `batch.py` runs the additive cross-file scan | not-available | not-available | not-available | Per-call `record.py` scanning is canonical. Nothing is buffered, so nothing is lost. | unknown |
| `PostToolUseFailure` | wired: `failure.py` tracks failure streaks and MCP backoff | degraded: no dedicated failure event, PostToolUse fires after failed Bash calls, ADW matcher covers edit tools only | unknown: docs list no failure event and do not say whether `tool.execute.after` fires on tool error | degraded: `tool_result` exposes `isError` and ADW subscribes to it, MCP-health handling unwired | MCP health substate stays empty and the PreToolUse consult allows every call. Degraded but harmless. | unknown |
| `UserPromptSubmit` | wired: `prompt_submit.py` runs the prompt firewall | not-available: Codex documents UserPromptSubmit, matcher ignored by client, ADW unwired | not-available: `tui.prompt.append` is TUI-only | not-available: the `input` event can transform or handle user input, ADW unwired | SessionStart contract injection. | unknown |
| `PreCompact` | not-available: Claude documents PreCompact, ADW unwired | not-available: Codex documents PreCompact, ADW unwired | not-available: `experimental.session.compacting` injects context only, no veto, ADW unwired | not-available: `session_before_compact` documented, ADW unwired | SessionStart(compact) contract re-injection after compaction. | unknown |
| `SessionEnd` | not-available: Claude documents SessionEnd, ADW unwired | not-available: Codex documents SessionEnd, advisory only, 1 second default timeout, 3 second cap, ADW unwired | not-available: `session.deleted` and `session.idle` are observation-only, no SessionEnd equivalent wired | not-available: `session_shutdown` documented, ADW unwired | Startup janitor sweep removes stale session state directories. | unknown |
| `InstructionsLoaded` | not-available: Claude documents InstructionsLoaded, ADW unwired | not-available | not-available | not-available | None needed. Audit telemetry only, no gate depends on it. | unknown |
| `ConfigChange` | not-available: Claude documents ConfigChange, ADW unwired | not-available | not-available | not-available | None. The self-tampering defense ships Claude-only. | unknown |

`PreCommit`, `PreBash`, and `PreMcp` are ADW-internal routes that `pre_tool.py` dispatches on `PreToolUse`, not client events, so they have no matrix rows. `PreMcp` consults the backoff windows that `PostToolUseFailure` opens, so the two are wired together or not at all.

No client publishes per-event minimum versions in its primary docs, so every version cell reads unknown. The `hooks/test_plugin_wiring.py` test enforces this table statically: every event key in `hooks/hooks.json` must appear in the documented event list.

Primary sources are the [Claude Code hooks reference](https://docs.anthropic.com/en/docs/claude-code/hooks) and [Codex hooks](https://learn.chatgpt.com/docs/hooks). The other client sources are [OpenCode plugins](https://opencode.ai/docs/plugins/) and [Pi extension docs](https://github.com/badlogic/pi-mono/blob/HEAD/packages/coding-agent/docs/extensions.md).

Repository evidence for current wiring lives in `hooks/claude-settings.snippet.json` and `hooks/codex-config.snippet.toml`. The client adapters are `opencode/agent-discipline-watcher.ts` and `pi/extensions/agent-discipline-watcher/index.ts`.

## Pi Behavior

The Pi extension:

1. Adds the short policy and readable output rules before an agent loop starts. Pi exposes no parent-session or agent-kind discriminator on that event.
2. Scans write, edit, and multiedit tool results through the Python scanner, honoring the project's own `.agent-discipline.json`.
3. Turns any finding into an immediate error result that requires correction.

## Verification

```bash
cd hooks && python3 -m pytest . lib -q
bash -n install.sh hooks/run.sh
claude plugin validate . --strict
```
