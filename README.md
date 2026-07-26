# Agent Discipline Watcher

Agent Discipline Watcher is one hook package for keeping agent output and edits direct, plain, and reviewable. It replaces the older punctuation-discipline, english-for-agents, and clean-coder-discipline packages with one scanner, one compact report path, and one Pi extension.

It exists to catch deterministic low-level drift before it lands in files: banned punctuation, inflated prose, deferred-work comments, noisy code comments, hollow tests, and oversized code shapes.

Every emitted finding blocks. The scanner does not report uncertain or advisory results.

## What It Installs

`install.sh` can install three live surfaces:

| Surface | Live files |
| --- | --- |
| Claude | `~/.claude/settings.json`, `~/.claude/skills/agent-discipline-watcher` |
| Codex | `~/.codex/config.toml`, `~/.codex/skills/agent-discipline-watcher` |
| Pi | `~/.pi/agent/settings.json` |

The Pi surface loads `pi/extensions/agent-discipline-watcher/index.ts`.

The installer creates timestamped backups before changing existing Claude, Codex, or Pi settings. It also links `bin/agent-discipline` into `~/.local/bin/agent-discipline`.

## Installation

From this directory:

```bash
./install.sh
```

Non-interactive install:

```bash
./install.sh -y
```

Install only selected surfaces:

```bash
./install.sh --no-claude --codex --no-pi -y
./install.sh --claude --no-codex --no-pi -y
./install.sh --no-claude --no-codex --pi -y
```

## Codex Activation

After installing or changing Codex hooks, run `/hooks` in Codex and review the new hook commands. Trust the Agent Discipline Watcher hooks there before relying on them.

The Codex hook commands are installed into `~/.codex/config.toml` and call:

```bash
hooks/run.sh SessionStart
hooks/run.sh PreToolUse
hooks/run.sh PreCommit
hooks/run.sh PostToolUse
```

## Usage

The hooks run automatically after installation and client activation.

Use the CLI to view or set per-project checks:

```bash
agent-discipline status
agent-discipline status /path/to/project
agent-discipline configure
agent-discipline configure /path/to/project
agent-discipline configure --checks punctuation,english,clean_code
agent-discipline configure --checks punctuation,clean_code /path/to/project
```

`agent-discipline configure` opens an interactive selector. Choose numbered checks, `all`, `none`, or Enter to keep the current state.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root:

```json
{
  "checks": {
    "clean_code": true,
    "english": true,
    "punctuation": true
  }
}
```

The hook code searches upward from the current working directory for `.agent-discipline.json`. If no file is found, punctuation, English, and clean-code checks are enabled.

The Craftsman suppression marker is always blocked on every scanned file. Project check switches and path exemptions cannot disable this rule. Fix the reported issue instead.

The `what_comment` rule is also unconditional on code files. Neither `clean_code: false` nor `exempt_paths` suppresses it. State a WHY or delete the comment.

Supported checks:

| Check | Purpose |
| --- | --- |
| `punctuation` | Blocks banned dash marks, double hyphen breaks, semicolon splices, incorrect apostrophe forms, and related punctuation tells. HTML `code`, `pre`, `script`, and `style` blocks are exempt, so inline CSS and generated markup never read as prose. |
| `english` | Blocks or reports inflated diction, filler, wordiness, AI tells, and plain-English issues. |
| `clean_code` | Toggles deferred-work comments, explicit narration comments, prose comment blocks, commented-out code, hollow tests, and hard length caps. It does not toggle the always-on `what_comment` rule described above. |

`max_rows` can be set in `.agent-discipline.json` to change how many compact report rows are shown before the full local report path.

`max_scan_bytes` can be set in `.agent-discipline.json`, or through the `ADW_MAX_SCAN_BYTES` environment variable, to cap how large a file the hooks will read. Files over the cap and files that look binary are skipped. The default is 1000000 bytes.

## Hook Lifecycle

| Event | Behavior |
| --- | --- |
| `SessionStart` | Injects the compact watcher reminder. |
| `PreToolUse` | Scans pending write or patch content and blocks forced deterministic findings before the write runs. |
| `PreCommit` | Watches Bash `git commit` commands, scans staged ACM files, and blocks forced deterministic findings before the commit runs. |
| `PostToolUse` | Rescans written files and immediately blocks agent continuation when findings remain. |
| `Stop` | Wired on the Claude surface and inert. The route exits without scanning until the turn-end gate module lands. |

PreCommit parses the shell command heuristically. Commits launched through `sh -c`, `xargs`, shell aliases, or wrapper scripts are not scanned.

PreToolUse prevents a direct write before it runs. PostToolUse cannot undo a completed write, so a forced finding returns a blocking error that requires the agent to repair the file before continuing.

The Claude surface wires the Stop event to `hooks/run.sh Stop`. That route exits without scanning today, so a Stop callback costs one process and changes nothing. The turn-end gate arrives with its own hook module, and the wiring stays inert until then.

## Cross-Client Event Parity

Every event ADW wires or plans to wire, checked against each client's primary docs (sources listed below the table). Status vocabulary:

| Status | Meaning |
| --- | --- |
| `wired` | The client fires the event and ADW registers it today. |
| `degraded` | ADW wires a reduced path, or only a reduced equivalent exists. The note names the limit. |
| `not-available` | ADW wires no path for this event on this client. The note says whether the client documents an equivalent. |
| `unknown` | Docs too thin to decide. Treated as not-available for gating. |

Cells use the state word alone or as `state: note`. The note carries any unwired nuance.

| Event | Claude | Codex | OpenCode | Pi | Fallback when the event never fires | Min client version |
| --- | --- | --- | --- | --- | --- | --- |
| `SessionStart` | wired | wired | wired: `session.created` | degraded: `before_agent_start` injects the policy prompt only, no session payload contract | No injection that session. Edit-time gates still fire. | unknown |
| `PreToolUse` | wired | wired | wired: `tool.execute.before`, write and edit tools only | degraded: blocking `tool_call` documented in current Pi, ADW adapter unwired, post-hoc today | PostToolUse rescan blocks continuation after the write lands. | unknown |
| `PostToolUse` | wired | wired | wired: `tool.execute.after` | wired: `tool_result`, findings return as an error result | PreCommit scans staged files at commit time. | unknown |
| `Stop` | wired: route inert until the turn-end gate lands | not-available: Codex documents Stop with continuation, ADW unwired | degraded: pseudo-Stop on `session.idle` is injection-only through `promptAsync`, it cannot block | not-available: `turn_end` is observation-only | Per-edit `record.py` (PostToolUse) scanning. | unknown |
| `SubagentStop` | not-available: Claude documents SubagentStop, ADW unwired | not-available: Codex documents SubagentStop, ADW unwired | not-available | not-available | Subagent edits still hit the per-edit PostToolUse scans. | unknown |
| `TaskCompleted` | not-available: Claude documents TaskCompleted, ADW unwired | not-available | not-available | not-available | The full suite runs at Stop or commit instead. | unknown |
| `PostToolBatch` | not-available: Claude documents PostToolBatch, ADW unwired | not-available | not-available | not-available | Per-call `record.py` scanning is canonical. Nothing is buffered, so nothing is lost. | unknown |
| `PostToolUseFailure` | not-available: Claude documents PostToolUseFailure, ADW unwired | degraded: no dedicated failure event, PostToolUse fires after failed Bash calls, ADW matcher covers edit tools only | unknown: docs list no failure event and do not say whether `tool.execute.after` fires on tool error | degraded: `tool_result` exposes `isError` and ADW subscribes to it, MCP-health handling unwired | MCP health substate stays empty and the PreToolUse consult allows every call. Degraded but harmless. | unknown |
| `UserPromptSubmit` | not-available: Claude documents UserPromptSubmit, ADW unwired | not-available: Codex documents UserPromptSubmit, matcher ignored by client, ADW unwired | not-available: `tui.prompt.append` is TUI-only | not-available: the `input` event can transform or handle user input, ADW unwired | SessionStart contract injection. | unknown |
| `PreCompact` | not-available: Claude documents PreCompact, ADW unwired | not-available: Codex documents PreCompact, ADW unwired | not-available: `experimental.session.compacting` injects context only, no veto, ADW unwired | not-available: `session_before_compact` documented, ADW unwired | SessionStart(compact) contract re-injection after compaction. | unknown |
| `SessionEnd` | not-available: Claude documents SessionEnd, ADW unwired | not-available: Codex documents SessionEnd, advisory only, 1 second default timeout, 3 second cap, ADW unwired | not-available: `session.deleted` and `session.idle` are observation-only, no SessionEnd equivalent wired | not-available: `session_shutdown` documented, ADW unwired | Startup janitor sweep removes stale session state directories. | unknown |
| `InstructionsLoaded` | not-available: Claude documents InstructionsLoaded, ADW unwired | not-available | not-available | not-available | None needed. Audit telemetry only, no gate depends on it. | unknown |
| `ConfigChange` | not-available: Claude documents ConfigChange, ADW unwired | not-available | not-available | not-available | None. The self-tampering defense ships Claude-only. | unknown |

`PreCommit` is an ADW-internal route on the PreToolUse Bash matcher, not a client event, so it has no matrix row.

No client publishes per-event minimum versions in its primary docs, so every version cell reads unknown. Per the fail-safe registration rule, an unknown event key can break config parsing rather than no-op, so each new wiring proves the merged config in a sandbox HOME before any live install.

Primary sources: [Claude Code hooks reference](https://docs.anthropic.com/en/docs/claude-code/hooks), [Codex hooks](https://learn.chatgpt.com/docs/hooks), [OpenCode plugins](https://opencode.ai/docs/plugins/), [Pi extension docs](https://github.com/badlogic/pi-mono/blob/HEAD/packages/coding-agent/docs/extensions.md). Repo evidence for what ADW wires today: `hooks/claude-settings.snippet.json`, `hooks/codex-config.snippet.toml`, `opencode/agent-discipline-watcher.ts`, `pi/extensions/agent-discipline-watcher/index.ts`.

## Pi Behavior

The Pi extension:

1. Adds a short policy prompt before the agent starts.
2. Scans write, edit, and multiedit tool results through the Python scanner.
3. Turns any finding into an immediate error result that requires correction.

## Verification

Run the full test tree from `hooks/`:

```bash
cd hooks && python3 -m pytest . lib -q
```

Syntax-check the shell entry points from this directory:

```bash
bash -n install.sh hooks/run.sh
```

The hook code holds itself to its own contract: every function stays under the length cap and the scanner reports zero findings on its own files.

Useful manual checks:

```bash
agent-discipline status
agent-discipline configure --checks punctuation,english,clean_code /path/to/project
python3 hooks/merge-codex-config.py --help
python3 hooks/merge-claude-settings.py --help
python3 hooks/merge-pi-settings.py --help
```

## Troubleshooting

If hooks do not run in Codex, run `/hooks` and verify the Agent Discipline Watcher commands are trusted. Codex can require trust review after hook commands are added or changed.

If a project needs fewer checks, run `agent-discipline configure` in that project and disable only the unwanted check families.

If output is too short for diagnosis, open the `Full report:` JSON path printed by the hook. The agent-facing message is intentionally compact.

If Pi does not steer after edits, verify that `~/.pi/agent/settings.json` includes the extension path under `pi/extensions/agent-discipline-watcher/index.ts`.

## License And Contact

This package lives in the local skills workspace. Use the surrounding repository license and maintainer process.
