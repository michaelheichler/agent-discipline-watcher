# Agent Discipline Watcher

Agent Discipline Watcher is one hook package for keeping agent output and edits direct, plain, and reviewable. It replaces the older punctuation-discipline, english-for-agents, and clean-coder-discipline packages with one scanner, one compact report path, and one Pi extension.

It exists to catch deterministic low-level drift before it lands in files: banned punctuation, inflated prose, deferred-work comments, noisy code comments, hollow tests, and oversized code shapes.

A finding blocks or reports according to its gate state. An `enforce` family stops the write, the shell write, or the commit. An `observe` family runs the same check in full, records a `would_block` ledger row, and hands the finding back as non-blocking context the agent still has to answer. The `self_protection` rules block unconditionally, whatever the configuration says.

## What It Installs

Claude Code installs this repo as a plugin. The other clients install through `install.sh`:

| Surface | Mechanism | Live files |
| --- | --- | --- |
| Claude | `/plugin install` | `~/.claude/plugins/cache/agent-discipline-watcher/...` |
| Codex | `install.sh` | `~/.codex/config.toml`, `~/.codex/skills/agent-discipline-watcher` |
| OpenCode | `install.sh` | `~/.config/opencode/plugins/agent-discipline-watcher.ts` |
| Pi | `install.sh` | `~/.pi/agent/settings.json` |

The Pi surface loads `pi/extensions/agent-discipline-watcher/index.ts`.

`install.sh` creates timestamped backups before changing existing settings. It also links `bin/agent-discipline` into `~/.local/bin/agent-discipline`.

## Installation

### Claude Code

Claude wiring ships as a plugin, so no path is written into your settings. Run these inside Claude Code:

```
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

The marketplace and the plugin both resolve from the git remote, so a push is what ships an update. Nothing resolves from a local checkout, which means an install behaves the same on every machine.

A shell script cannot type a slash command, so `install.sh` does not pretend to install the plugin. Running it prints the two commands and removes any legacy path-based wiring first.

### Other clients

From this directory:

```bash
./install.sh          # interactive
./install.sh -y       # non-interactive
```

Install only selected surfaces:

```bash
./install.sh --no-claude --codex --no-pi -y
./install.sh --no-claude --no-codex --pi -y
```

### Local development and testing

Install into a throwaway HOME so the live profile is untouched:

```bash
HOME="$(mktemp -d)" ./install.sh -y
claude plugin validate . --strict
```

The plugin resolves from the git remote, so an unpushed commit is not installable and a plugin install never reads this checkout. While developing the hooks themselves, point Claude at this working tree instead:

```bash
./install.sh --claude-legacy --no-codex --no-opencode --no-pi -y
```

That is the only supported way to run uncommitted hook changes. Undo it with the migration command below once the change is pushed and released.

### Updating

Releasing is two steps. Bump `version` in both `.claude-plugin/plugin.json` and the marketplace entry, then push. The two version fields must match, and `hooks/test_plugin_wiring.py` fails if they drift.

Users then pull the release with:

```
/plugin marketplace update agent-discipline-watcher
/plugin update agent-discipline-watcher@agent-discipline-watcher
```

A push alone does not reach installed clients. Users receive an update only when the version changes, so a bump is part of every release rather than an afterthought.

### Uninstalling

```
/plugin uninstall agent-discipline-watcher@agent-discipline-watcher
/plugin marketplace remove agent-discipline-watcher
```

### Migrating from the legacy path-based install

Earlier versions wrote absolute checkout paths into `~/.claude/settings.json`, so moving the checkout broke every hook. To migrate:

```bash
python3 hooks/merge-claude-settings.py --settings ~/.claude/settings.json --remove-legacy
```

The removal drops watcher hook entries and nothing else. Unrelated hooks, permissions, and model settings survive byte for byte, and a lifecycle key is deleted only when the removal emptied it. Running it twice changes nothing. `./install.sh` performs this step automatically before printing the plugin commands.

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

Three more subcommands read and label the burn-in ledger, which is how an `observe` family earns promotion to `enforce`:

```bash
agent-discipline observe-report clean_code
agent-discipline observe-report clean_code /path/to/project
agent-discipline false-signal-rate clean_code
agent-discipline adjudicate clean_code 2026-07-31T09:12:44Z --justified
agent-discipline adjudicate clean_code 2026-07-31T09:12:44Z --false-signal
```

`observe-report <family>` prints one line per recorded `would_block` row: timestamp, turn id, rule, path. `false-signal-rate <family>` prints the rate per 20 turns, or says the ledger is still below the 20-turn floor. `adjudicate <family> <ref_ts>` labels one recorded row using the timestamp `observe-report` printed, and exactly one of the two verdict flags shown above is required. Each of the three takes an optional project path after its other positionals, plus a `root` flag to read a ledger directory other than the default. A missing or unreadable ledger exits with a message rather than a traceback.

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

### Committed baseline

An agent answers for the edit it made, not for the state of the file it opened. Before reporting, the PostToolUse scan, the batch scan, and the commit gate subtract whatever the same file already carried in `HEAD`.

Editing one line of a legacy file therefore never blocks on inherited debt, while adding a new finding to that same file still blocks. A file with no committed version, an untracked file, or a path outside any repository has no baseline, so it is scanned whole.

Matching runs in two passes. Exact family, rule, and snippet text first, so an edit that shifts a file does not resurface its old debt. Then family and rule alone, so rewording a line that already broke the same rule counts as the debt it always was rather than as something new. Both passes count copies, so an added occurrence still reports even when every earlier one is covered.

```json
{
  "baseline": "report"
}
```

Three modes decide what happens to the subtracted half:

| Mode | Blocking set | Inherited findings |
| --- | --- | --- |
| `report` | The edit's own findings only | Reported back as a separate non-blocking advisory naming the count |
| `git` | The edit's own findings only | Dropped in silence |
| `none` | Every finding in the file | No subtraction happens, so there is no inherited half |

The default is `report`. Working in an old codebase is where this matters most: opening a legacy file to change one line now returns a line reading `this file already carried 2 findings you did not write. Fix them while you are in here.`, followed by the same compact rows the blocking path uses and the full report path. It arrives on `systemMessage` and `additionalContext` with exit 0, so the edit stands and the turn continues. Nothing forces the repair, which is the point: the debt gets named instead of vanishing, and the agent decides whether this is the moment to pay it.

`git` keeps the older behavior for anyone who wants the quiet version, and it is the mode to set when a repository carries so much inherited debt that the advisory would drown the real finding. `none` restores whole-file scanning, which makes every legacy finding blocking again.

### Per-path family exemptions

`exempt_paths` silences every configurable family on a path at once. `exempt_families` is the narrow form: it drops named families on matching paths and leaves the rest enforcing.

```json
{
  "exempt_families": {
    "CHANGELOG.md": ["english"]
  }
}
```

That example stops the plain-English style rules on `CHANGELOG.md` while punctuation keeps blocking em dashes, double hyphens, and spaced hyphens there. Patterns match the same way as `exempt_paths`, so a bare filename also matches it inside any directory.

Chat replies are not in scope for either form: `Stop` and `SubagentStop` no longer scan `last_assistant_message` at all, so there is nothing to exempt there. Every file a `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, or `apply_patch` call touches is still scanned exactly as before.

An unknown family name is ignored rather than rejected, so a typo scans more rather than less. `exempt_families` cannot reach `suppression_escape_hatch` or `what_comment`, which are emitted before the exemption check.

### Per-rule gate states

`gates` sets a family to `off`, `observe`, or `enforce`. `rule_gates` does the same for one rule and wins over its family, so a single rule can burn in while the rest of the family keeps enforcing.

```json
{
  "rule_gates": {
    "what_comment": "enforce"
  }
}
```

`what_comment` ships in `observe`. Its WHY test is a ten-word marker list, not semantic analysis, so it must earn enforcement through the D7 burn-in like every other gate. In `observe` the check still runs in full, the ledger records a `would_block` row, and the finding is reported to the agent as context rather than as a block. It has to be judged and answered, but it does not stop the work.

Every gate resolves the same way: `pre_write.py` before a write, `pre_bash.py` on shell write content, `record.py` after a write, and `pre_commit.py` at commit time all read the state through one resolver, so a rule set to `observe` reports on all four paths and blocks on none of them.

Promote it with the config above once `agent-discipline observe-report clean_code` shows you what the rule actually fired on and `agent-discipline false-signal-rate clean_code` reports a rate you accept.

`rule_gates` cannot release a rule in the always-blocking set.

The Craftsman suppression marker is always blocked on every scanned file. Project check switches, path exemptions, and rule gates cannot disable this rule. Fix the reported issue instead.

The `what_comment` rule still runs on every code file whatever `clean_code` and `exempt_paths` say, because the scanner emits it before the exemption check. What those switches cannot do is silence it. Its outcome now comes from `rule_gates`, which ships it in `observe`.

It skips three things a comment can be without narrating code: a leading banner of two or more comment lines, a line with no letters such as a divider or a bare `#`, and a tag line such as `Args:` or `TRIGGERS:`.

Supported checks:

| Check | Purpose |
| --- | --- |
| `punctuation` | Blocks banned dash marks, double hyphen breaks, semicolon splices, incorrect apostrophe forms, and related punctuation tells. HTML `code`, `pre`, `script`, and `style` blocks are exempt, so inline CSS and generated markup never read as prose. |
| `english` | Blocks or reports inflated diction, filler, wordiness, AI tells, and empty intensifiers. Its rules are literal patterns, not a style model, so coverage is narrower than the rule names suggest. `delve into` matches and `delves into` does not. `it's worth noting` matches and `it is worth noting` does not. Treat a clean scan as the absence of a known pattern rather than as proof the prose is plain. |
| `clean_code` | Toggles deferred-work comments, explicit narration comments, prose comment blocks, commented-out code, hollow tests, and hard length caps. It does not toggle the always-on `what_comment` rule described above. |

Narrow patterns cut both ways, so a rule sometimes fires on prose that is fine as written. The escape for that is `exempt_families` above: name the path and the one family to drop, and the other families keep enforcing there. Reach for `exempt_paths` only when every family is wrong on that path.

## Self Protection

The `self_protection` family blocks routes around the gates. Its rules are built into `hooks/lib/protected.py` and `hooks/pre_bash.py`, never loaded from user-authored configuration, and every one of them sits in `ALWAYS_BLOCKING_RULES`. No check switch, gate state, kill switch, or path exemption suppresses them, because a switch the agent can flip would defeat the protection.

| Rule | Blocks |
| --- | --- |
| `live_client_surface` | Writing a live client install: `~/.claude/settings*.json`, `~/.claude/skills`, `~/.claude/agents`, `~/.claude/CLAUDE.md`, `~/.codex`, `~/.pi`, `~/.agents/skills`, `~/.config/opencode`, and `~/.local/bin/agent-discipline`. Covers both the edit tools and shell mutation through a redirect, `tee`, `sed -i`, `cp`, `mv`, `ln`, `rm`, `dd`, `truncate`, or `chmod`. |
| `config_seal` | Editing an existing `.agent-discipline.json`, and creating or editing one whose content would release a self-protection rule, either through the removed `protected_paths_authorized` key or a `rule_gates` entry that downgrades one. A first creation that releases nothing protected is allowed, and a stat error counts as present so the seal fails closed. |
| `install_without_sandbox_home` | Running `install.sh` or a merge script without setting `HOME`. |
| `commit_gate_bypass` | A `git commit` carrying the no-verify flag, in either the long or the short form. |
| `cap_override` | Setting `ADW_FUNC_BLOCK_LINES`, `ADW_FILE_BLOCK_LINES`, `ADW_MAX_SCAN_BYTES`, or `ADW_ALLOW_PROTECTED_EDIT` in command position, or one of the accepted `CLEANCODER_` aliases. |
| `state_deletion` | Deleting watcher state or the gate config with `rm`, `unlink`, or `shred`. |

Reading is never blocked. `cat`, `grep`, `git diff`, and `python3 -m json.tool` on a live client file all pass, and stderr handling such as `2>/dev/null`, `2>>log`, or `2>&1` is not treated as a write.

A human can grant an explicit escape, which releases every rule in the family:

```bash
ADW_ALLOW_PROTECTED_EDIT=1 <command>
```

The environment variable is the only escape. The `"protected_paths_authorized": true` config key was removed, because a config file is a file the agent can write, and a write route the hooks do not see would have released every self-protection rule silently. Writing that key into `.agent-discipline.json` is still blocked as a `config_seal` finding, and the block message points at the environment variable.

The guarantee is narrow and exact: the agent cannot set the environment of the hook process, and setting the variable inline on a command is itself a `cap_override` block. A human who exports it in the shell that starts the client releases the family for that session.

Scratch and transcript paths under the Claude home are not wiring, so `~/.claude/jobs`, `~/.claude/projects`, `~/.claude/plugins`, `~/.claude/todos`, and `~/.claude/shell-snapshots` stay writable.

`max_rows` can be set in `.agent-discipline.json` to change how many compact report rows are shown before the full local report path.

Length caps come from `.agent-discipline.json` first, then the environment. `function_block_lines` pairs with `ADW_FUNC_BLOCK_LINES` and defaults to 80. `file_block_lines` pairs with `ADW_FILE_BLOCK_LINES` and defaults to 1000. The older `CLEANCODER_FUNC_BLOCK_LINES` and `CLEANCODER_FILE_BLOCK_LINES` names stay accepted as aliases, because clean-coder-discipline was merged into this package and existing shells still export them. The `ADW_` name wins when both are set.

`max_scan_bytes` can be set in `.agent-discipline.json`, or through the `ADW_MAX_SCAN_BYTES` environment variable, to cap how large a file the hooks will read. Files over the cap and files that look binary are skipped. The default is 1000000 bytes.

## Hook Lifecycle

Every Claude route in `hooks/run.sh` is registered in `hooks/hooks.json` and reaches a real module. `hooks/test_plugin_wiring.py` fails if a route is registered without a module or a module is left unregistered.

| Event | Route | Module | Behavior |
| --- | --- | --- | --- |
| `SessionStart` | SessionStart | `session_start.py` | Injects the full discipline contract as `additionalContext`, plus a one-line reminder as `systemMessage`. |
| `SubagentStart` | SubagentStart | `subagent_start.py` | Injects the same contract into every spawned subagent. No matcher, so every agent type is covered. |
| `UserPromptSubmit` | UserPromptSubmit | `prompt_submit.py` | Scans the user's own prompt and reports the matched rule ids back as context. Blocks prompt-level bypass attempts. It injects no contract. |
| `PreToolUse` | PreToolUse | `pre_write.py` | Scans pending write or patch content, and blocks protected-path targets, before the write runs. |
| `PreToolUse` | PreCommit | `pre_commit.py` | Filtered to `Bash(git *)`. Scans staged ACM files and the inline commit message before the commit runs. |
| `PreToolUse` | PreBash | `pre_bash.py` | Sees every Bash call, blocks shell routes around the gates, and scans literal file content a command writes. |
| `PreToolUse` | PreMcp | `pre_mcp.py` | Matched on `mcp__.*`. Blocks an MCP call while its server backoff window is open. |
| `PostToolUse` | PostToolUse | `record.py` | Rescans written files. Blocks agent continuation on an enforced finding, reports an observed one, and reports inherited findings under `baseline: report`. |
| `PostToolBatch` | PostToolBatch | `batch.py` | Additive cross-file scan after the canonical per-call scans. |
| `PostToolUseFailure` | PostToolUseFailure | `failure.py` | Records tool failures and opens session-scoped MCP backoff windows. |
| `SubagentStop` | SubagentStop | `subagent_stop.py` | Records a heartbeat for the delegated turn. Chat replies are not scanned. |
| `Stop` | Stop | `stop.py` | Advances the turn counter and closes out the turn. Chat replies are not scanned. |

PreCommit parses the shell command with a shell-aware parser that resolves `git -c`, `git -C`, `env`, `command`, and compound segments. The `if` filter is deliberately the broad `Bash(git *)` rather than `Bash(git commit *)`, because a narrower literal hides forms such as `git -c user.name=x commit` before the parser ever sees them. Commits launched through `sh -c`, `xargs`, shell aliases, or wrapper scripts are still not scanned.

The commit message is scanned too. `pre_commit.py` reads every inline spelling git accepts, shown here in a fence because the long flags carry a double hyphen:

```
git commit -m "text"
git commit -mtext
git commit --message "text"
git commit --message=text
```

It joins repeated values into paragraphs the way git itself does, then scans the result as `commit_message.md` so the prose rules reach it. A message carrying an em dash blocks the commit exactly as a staged file would. The file-reading forms `-F` and its long spelling, and any message typed into the editor, are deliberately not covered, because that text does not exist in the command line the hook sees.

PreToolUse prevents a direct write before it runs. PostToolUse cannot undo a completed write, so an enforced finding returns a blocking error that requires the agent to repair the file before continuing. An observed finding returns exit 0 with the same rows carried as context, so the gate state means one thing on both sides of the write.

### Contract injection

The contract is one 1,752 character text in `hooks/lib/hookio.py`, and two events deliver it: `SessionStart` and `SubagentStart`. Both send it as `hookSpecificOutput.additionalContext`, which is the channel the model reads. `systemMessage` is transcript chrome and reaches the user rather than the model, so `SessionStart` sends the one-line reminder there and the contract through the other channel.

`SubagentStart` closes a real gap. A subagent gets neither `SessionStart` nor `UserPromptSubmit`, so a subagent spawned by `/coderabbit:code-review`, `/feature-dev:feature-dev`, or `/code-modernization:modernize-assess` used to write into gates it had never been shown. The hook carries no matcher, so every agent type receives the contract, and the text opens by stating that it overrides the agent definition the subagent was given.

### Shell writes

`PostToolUse` never matches a Bash call, so content written through the shell would otherwise land unscanned. `pre_bash.py` extracts the literal text a command is about to write and scans it against the target path, which is what makes the right rule families apply to a `.md` target and a `.py` target.

Three forms are covered. Heredocs in every spelling: `<<EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`, and any other delimiter. `echo` and `printf` redirects, including the appending `>>`. And `tee`, with or without `-a`. Self-protection rules keep precedence and stay unconditionally blocking. Content findings obey gate state like any other finding.

Not covered, and failing open and silent when they appear:

| Form | Why |
| --- | --- |
| `cp`, `mv`, `dd`, `sed -i` | The content lives in another file or in a stream, not in the command text |
| `python3 -c` and other interpreter writes | The write happens inside a program the hook does not run |
| A pipe from a real program | Same reason |
| `$VAR` and `$(...)` in an unquoted heredoc or an `echo` argument | The text is assembled at runtime, so the parser refuses to guess |
| An unterminated heredoc | The body has no end, so no content is claimed |

Do not read the covered list as total coverage of shell writes. Any route in the second table reaches disk unscanned, and `pre_commit.py` is the only gate that sees it, at commit time, once the file is staged.

PostToolBatch reports and never halts. Its findings leave the entry script with exit 0, carried as `systemMessage` and `additionalContext`, because `record.py` is the canonical per-edit gate and has already blocked anything it shares. The batch layer exists for cross-file findings such as duplicated content, and an agent that cannot finish its turn cannot act on one.

Both gate paths write ledger rows. A blocked commit appends one `pre_commit` decision row with `event` set to `PreCommit`, so an empty ledger means the gate never ran rather than the gate finding nothing.

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
| `SubagentStart` | wired: `subagent_start.py` injects the contract, no matcher, so every agent type is covered | not-available: ADW wires no path, no documented equivalent established | not-available: ADW wires no path, no documented equivalent established | not-available: ADW wires no path, no documented equivalent established | The subagent runs without the contract. Its edits still hit the per-edit PreToolUse and PostToolUse gates. | unknown |
| `PreToolUse` | wired | wired | wired: `tool.execute.before`, write and edit tools only | degraded: blocking `tool_call` documented in current Pi, ADW adapter unwired, post-hoc today | PostToolUse rescan blocks continuation after the write lands. | unknown |
| `PostToolUse` | wired | wired | wired: `tool.execute.after` | wired: `tool_result`, findings return as an error result | PreCommit scans staged files at commit time. | unknown |
| `Stop` | wired: `stop.py` advances the turn counter, chat replies are not scanned | not-available: Codex documents Stop with continuation, ADW unwired | degraded: pseudo-Stop on `session.idle` is injection-only through `promptAsync`, it cannot block | not-available: `turn_end` is observation-only | Per-edit `record.py` (PostToolUse) scanning. | unknown |
| `SubagentStop` | wired: `subagent_stop.py` records a heartbeat without ending the parent turn, chat replies are not scanned | not-available: Codex documents SubagentStop, ADW unwired | not-available | not-available | Subagent edits still hit the per-edit PostToolUse scans. | unknown |
| `TaskCompleted` | not-available: Claude documents TaskCompleted, ADW has no module yet (E2-S3) | not-available | not-available | not-available | The full suite runs at Stop or commit instead. | unknown |
| `PostToolBatch` | wired: `batch.py` runs the additive cross-file scan | not-available | not-available | not-available | Per-call `record.py` scanning is canonical. Nothing is buffered, so nothing is lost. | unknown |
| `PostToolUseFailure` | wired: `failure.py` tracks failure streaks and MCP backoff | degraded: no dedicated failure event, PostToolUse fires after failed Bash calls, ADW matcher covers edit tools only | unknown: docs list no failure event and do not say whether `tool.execute.after` fires on tool error | degraded: `tool_result` exposes `isError` and ADW subscribes to it, MCP-health handling unwired | MCP health substate stays empty and the PreToolUse consult allows every call. Degraded but harmless. | unknown |
| `UserPromptSubmit` | wired: `prompt_submit.py` runs the prompt firewall | not-available: Codex documents UserPromptSubmit, matcher ignored by client, ADW unwired | not-available: `tui.prompt.append` is TUI-only | not-available: the `input` event can transform or handle user input, ADW unwired | SessionStart contract injection. | unknown |
| `PreCompact` | not-available: Claude documents PreCompact, ADW unwired | not-available: Codex documents PreCompact, ADW unwired | not-available: `experimental.session.compacting` injects context only, no veto, ADW unwired | not-available: `session_before_compact` documented, ADW unwired | SessionStart(compact) contract re-injection after compaction. | unknown |
| `SessionEnd` | not-available: Claude documents SessionEnd, ADW unwired | not-available: Codex documents SessionEnd, advisory only, 1 second default timeout, 3 second cap, ADW unwired | not-available: `session.deleted` and `session.idle` are observation-only, no SessionEnd equivalent wired | not-available: `session_shutdown` documented, ADW unwired | Startup janitor sweep removes stale session state directories. | unknown |
| `InstructionsLoaded` | not-available: Claude documents InstructionsLoaded, ADW unwired | not-available | not-available | not-available | None needed. Audit telemetry only, no gate depends on it. | unknown |
| `ConfigChange` | not-available: Claude documents ConfigChange, ADW unwired | not-available | not-available | not-available | None. The self-tampering defense ships Claude-only. | unknown |

`PreCommit`, `PreBash`, and `PreMcp` are ADW-internal routes on PreToolUse matchers, not client events, so they have no matrix rows. `PreMcp` consults the backoff windows that `PostToolUseFailure` opens, so the two are wired together or not at all.

No client publishes per-event minimum versions in its primary docs, so every version cell reads unknown. Per the fail-safe registration rule, an unknown event key can break config parsing rather than no-op, so each new wiring proves the merged config in a sandbox HOME before any live install. `hooks/test_plugin_wiring.py` enforces this statically: every event key in `hooks/hooks.json` must appear in the documented event list, and an `if` filter may only sit on an event the docs say evaluates one.

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

Validate the plugin and marketplace manifests with the official validator:

```bash
claude plugin validate . --strict
claude plugin validate .claude-plugin/plugin.json --strict
```

The validator checks schema only. It accepts manifests the loader rejects, so the load itself must be proven separately:

```bash
claude plugin list
```

Any entry reading `Status: failed to load` is a real break that `validate` and `install` both report as success. `hooks/test_plugin_wiring.py::PluginLoaderTests` runs that check against a sandbox profile with a local marketplace, so a manifest that cannot load fails the suite.

The manifest deliberately omits a `hooks` key. `hooks/hooks.json` is the documented default location and loads automatically. The `hooks` field is for additional hook files only, so naming the standard path there loads it twice and the plugin fails.

Prove the plugin install without touching the live profile:

```bash
SANDBOX="$(mktemp -d)"
HOME="$SANDBOX" claude plugin marketplace add "$PWD"
HOME="$SANDBOX" claude plugin install agent-discipline-watcher@agent-discipline-watcher
HOME="$SANDBOX" claude plugin details agent-discipline-watcher@agent-discipline-watcher
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
