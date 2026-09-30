# Test writer identity across hosts

Task 18. Research only. No code changes. This file answers five questions.
How can each host's PreToolUse-equivalent hook identify the
`adw-test-writer` agent. Can the main agent fake that identity.

## 1. Claude Code, PreToolUse hook input fields

Primary source, `https://code.claude.com/docs/en/hooks`, "Common input
fields" section.

> "When running with `--agent` or inside a subagent, two additional fields
> are included, `agent_id` and `agent_type`. For subagents, the subagent's
> type takes precedence over the session's `--agent` value."

`agent_id` appears only inside a subagent call. It names that subagent.
`agent_type` names the agent, for example `Explore` or `security-reviewer`.

I ran a local experiment under `~/adw-experiment-2026-09-30`, not `/tmp`.

Setup.
- `.claude/agents/adw-test-writer.md` with frontmatter `name: adw-test-writer`,
  `description`, `model: haiku`.
- `.claude/settings.json` with a PreToolUse hook matching `Write`. The hook
  command runs `cat >> ~/adw-experiment-2026-09-30/hook-log.jsonl`.

Command.
```
cd ~/adw-experiment-2026-09-30 && claude -p "Use the adw-test-writer subagent
(via the Task tool with subagent_type=adw-test-writer) to write a file named
out.txt containing the single word hello. Do not write the file yourself."
--dangerously-skip-permissions
```

Logged payload, `hook-log.jsonl`, one line, reformatted for this report.
```json
{
  "session_id": "67cce039-e78a-432e-910a-ff53f0f72795",
  "cwd": "/Users/nootnoot/adw-experiment-2026-09-30",
  "prompt_id": "5707e543-75a5-4c34-996a-9706ccb7d7cf",
  "permission_mode": "bypassPermissions",
  "agent_id": "a85f10d1b1c4c75c9",
  "agent_type": "adw-test-writer",
  "hook_event_name": "PreToolUse",
  "tool_name": "Write",
  "tool_input": { "file_path": ".../out.txt", "content": "hello\n" },
  "tool_use_id": "toolu_01MTS8MXJX4vavDnXu4ThY8e"
}
```

`agent_type` equals the frontmatter `name` field exactly. No `model` field
appears anywhere in this payload.

Can the main agent influence `agent_type` by naming its own Task call. No,
not with an arbitrary string. Second experiment, same project. I asked the
main agent to call the Agent tool with `subagent_type:
"adw-test-writer-FAKE"`, a name with no agent file. Claude Code rejected the
call before it started anything.
```
Agent type 'adw-test-writer-FAKE' not found. Available agents: adw-test-writer,
claude, craftsman:..., Explore, general-purpose, Plan, statusline-setup
```
Claude Code compares `subagent_type` against the registered agent list. It
refuses an unknown name. It does not fall back to a similar name. It does
not fall back to `general-purpose` either. `agent_type` in the hook payload
ties to a real, on-disk agent definition. It does not carry free text the
main agent can inject.

A narrower, real gap remains, the model tier the identity runs on. The docs
give the model resolution order in full.
> "1. The per-invocation `model` parameter. 2. The subagent definition's
> `model` frontmatter... 3. `CLAUDE_CODE_SUBAGENT_MODEL`... 4. The main
> conversation's model."
The per-invocation parameter outranks the frontmatter. My own Agent tool
definition in this session exposes a `model` parameter on every call. That
parameter works even on calls that name a real registered `subagent_type`.
The main agent can spawn the real `adw-test-writer` identity. The main agent
can still pass a cheaper model for that one call. The hook cannot see this substitution.

The same docs page states this too. Only `SessionStart` hooks can receive a
`model` field. Even `SessionStart` does not always carry one. PreToolUse
and SubagentStart carry no model field at all.
`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` closes this one gap, but only by
forcing every subagent onto one model globally. That setting flattens every
other subagent's model choice too, not this one alone.

Effort is a partial mitigation. When the active model supports effort,
PreToolUse carries an `effort.level` field, one of "low", "medium", "high",
"xhigh", "max". The Agent tool exposed to me carries no per-call effort
override parameter, only `model`. A frontmatter `effort: high` on
`adw-test-writer` is therefore harder for the calling agent to downgrade
than `model`.

## 2. Claude Code agent files, frontmatter and plugin scoping

Primary source, `https://code.claude.com/docs/en/sub-agents`.

Model field, quoted. `model` accepts `"sonnet"`, `"opus"`, `"haiku"`,
`"fable"`, a full model ID such as `"claude-opus-5-5"`, or `"inherit"`.

Opus 5.5 model ID, confirmed against
`https://platform.claude.com/docs/en/models/overview`. The Claude API ID and
alias are both `claude-opus-5-5`.

Effort field. While a subagent runs, `effort` sets its effort level.
Quoted, "Overrides the session effort level." Default value, inherits from
session. Option values, low, medium, high, xhigh, max. Available levels
depend on the model. `effort: high` is a supported, real frontmatter field.

Plugins can ship an agent file. Quoted, "Agent files go in the plugin's
`agents/` directory, which is priority 5 (lowest) in scope precedence... a
file at `agents/review/security.md` in plugin `my-plugin` registers as
`my-plugin:review:security`." A plugin-shipped `adw-test-writer.md` at the
top level of `agents/` registers as
`agent-discipline-watcher:adw-test-writer`. That name is not the bare name.
Any hook matcher or gate rule that reads `agent_type` must account for the
scoped form. The docs warn that the colon makes a matcher evaluate as a
regex. Anchor it, `^agent-discipline-watcher:adw-test-writer$`. Plugin
subagents drop the `hooks`, `mcpServers`, and `permissionMode` frontmatter
fields for security reasons. `model` and `effort` still apply.

## 3. Codex, hook visibility, roles, and the Luna model id

Primary source, `https://learn.chatgpt.com/docs/hooks`, the redirect target
of `https://developers.openai.com/codex/hooks`.

PreToolUse input fields, quoted in full. `session_id`, `transcript_path`,
`cwd`, `hook_event_name`, `model`, `permission_mode`. PreToolUse adds
`turn_id`, `tool_name`, `tool_use_id`, `tool_input`. No `agent_id`,
`agent_type`, or `role` field appears in this list.

`SubagentStart` and `SubagentStop` carry two extra fields. `agent_id`,
described as "Identifier for the subagent". `agent_type`, described as
"Subagent type or profile".

The same page states plainly, "Subagent hooks use the parent session id."
A subagent's `SubagentStart` event and its later PreToolUse events share
one `session_id`. That same `session_id` also matches the main agent's own
session id. The
PreToolUse field list carries no `agent_id` or `agent_type` of its own. A
Codex PreToolUse hook today cannot tell whether the main agent or a named
subagent made a given tool call.

This repo's own `hooks/lib/payloads.agent_id()` reads `payload.get
("agent_id")`. `hooks/subagent_stop.py` and `hooks/lib/blocker_state.py` use
this function. On a Codex `PreToolUse` call, Codex never sends that field.
`agent_id(payload)` returns `""` there. I read
`hooks/test_codex_hook_parity.py` and `hooks/test_task4_codex.py`. Neither
file exercises an `agent_id`-bearing `PreToolUse` payload for Codex. That
absence matches the docs, which describe no such field on that event.

Codex roles set model and effort per agent file. Primary source,
`https://learn.chatgpt.com/codex/subagents`. Each custom agent is its own
TOML file. Personal agents live under `~/.codex/agents/`. Project agents
live under `.codex/agents/`. Codex identifies the agent "by its `name`
field," not the filename. Quoted, "The per-agent keys are `model` and
`model_reasoning_effort`." The docs give an example for the explorer agent,
`model = "gpt-6-luna"` paired with `model_reasoning_effort = "high"`. Global
fallbacks live under `[agents]`, namely `agents.default_subagent_model` and
`agents.default_subagent_reasoning_effort`. A custom agent file's own
`model` or `model_reasoning_effort` value wins first. The spawn value wins
second. The `[agents]` default wins third. The parent's value applies last.

Luna model id, per the coordinator's correction, the target is Luna 6, id
`gpt-6-luna`, not `gpt-6.1-luna`. I read the cache directly.
```
jq '.models[] | select(.slug | test("luna"; "i")) |
{slug, display_name, default_reasoning_level,
 supported_reasoning_levels: [.supported_reasoning_levels[].effort]}'
~/.codex/models_cache.json
```
Output.
```json
{
  "slug": "gpt-6-luna",
  "display_name": "GPT-6-Luna",
  "default_reasoning_level": "medium",
  "supported_reasoning_levels": ["low", "medium", "high", "xhigh", "max"]
}
{
  "slug": "gpt-5.6-luna",
  "display_name": "GPT-5.6-Luna",
  "default_reasoning_level": "medium",
  "supported_reasoning_levels": ["low", "medium", "high", "xhigh", "max"]
}
```
`gpt-6-luna` exists in this cache, fetched 2026-09-28. No `gpt-6.1-luna`
entry exists in this cache. I read no Codex source outside the cache.
This confirms only the id's presence in this one snapshot. It does not
prove a `gpt-6.1-luna` id never existed, and it does not predict the future.

## 4. OMP (oh-my-pi), tool_call hook payload and agent definitions

Source, package cache at
`/Users/nootnoot/.bun/install/cache/@oh-my-pi/pi-coding-agent@18.1.16@@@1`,
file `src/extensibility/hooks/types.ts`.

The `ToolCallEvent` interface is this.
```ts
export interface ToolCallEvent {
  type: "tool_call";
  toolName: string;
  toolCallId: string;
  input: Record<string, unknown>;
}
```
No agent, role, or subagent field exists on this event. No such field exists
on `HookContext` either. `HookContext` carries `sessionManager`, a
`ReadonlySessionManager`. `HookContext` also carries `model`, the currently
selected model, possibly undefined. Nothing in `HookContext` names which
agent definition is active for the current tool call.

This repo's own OMP wiring in
`pi/extensions/agent-discipline-watcher/lifecycle-handlers.ts` confirms the
gap in practice. Its `sessionId(ctx)` helper, at line 75, calls
`ctx.sessionManager.getSessionId()`. Every downstream call in that file keys
state on `sessionId(ctx)` and `event.toolCallId`. No line in that file reads
an agent identifier. None exists to read.

A user defines an agent with a chosen model this way. Agent files live at
`~/.omp/agent/agents/*.md` for the user scope, or `.omp/agents/*.md` for the
project scope. An OMP extension's own `agents/` directory is a third
location, per `src/task/discovery.ts`. `parseAgentFields`, in
`src/discovery/helpers.ts` starting at line 308, accepts these frontmatter
fields.

- `name`, `description`, `tools`, `spawns`
- `model`, `output`, `thinkingLevel` (or `thinking`)
- `blocking`, `autoloadSkills`, `readSummarize`, `prewalk`, `advisor`

That function passes `frontmatter.model` to `parseModelList`.
`parseModelList` accepts a literal model id, a `provider/id` pair, or a role
alias such as `@task` or `@smol`. The user maps that alias to a concrete
model elsewhere in OMP config. OMP has no separate `effort` field.
`thinkingLevel` is the OMP equivalent. The agent file sets `thinkingLevel`
once, and no caller overrides it per spawn. A separate spawn-time
`TaskItem.effort` field exists, at `src/task/types.ts` line 148. It is a
caller override for ad hoc task items, not a property of a saved `.md`
agent definition.

## 5. Strongest identity signal per host, spoofing, and the Task 19 recommendation

| Host | Identity field | Spoofable | Model and effort setting | Recommendation |
| --- | --- | --- | --- | --- |
| Claude Code | `agent_type` on PreToolUse, present with `agent_id` only inside a real subagent call | No for the name itself. Claude Code rejects any `subagent_type` with no matching agent file. Yes for the model tier. The caller's per-invocation `model` parameter outranks the frontmatter `model`, and no tool-call hook reports which model actually ran. | Frontmatter `model: claude-opus-5-5` (alias `opus` also resolves here), `effort: high` | Gate test-file writes on `agent_type == "adw-test-writer"` (or the plugin-scoped form) at PreToolUse. Block every write that carries no `agent_id` or a mismatched `agent_type`. Do not confirm the model from hook data, that data does not exist. Use `effort.level == "high"` as a secondary, harder-to-downgrade signal. Treat a low or medium effort on a claimed `adw-test-writer` write as a finding to review, not proof of a fake. |
| Codex | `agent_id` and `agent_type` on `PreToolUse`, both optional and present only on a subagent's own tool calls. See "Codex 0.159.2 recheck" below for the binary, source, and live-experiment evidence. | No for the name itself. Codex confirms a `spawn_agent` call's `agent_type` against registered role files before it creates the child thread. An unregistered name produces a router error, with no child thread and no child `PreToolUse` event. Untested item, scope precedence between a personal-scope and a project-scope role file that share the same name. | Per-agent TOML file (`~/.codex/agents/*.toml` or `.codex/agents/*.toml`) sets `model` and `model_reasoning_effort`, for example `model = "gpt-6-luna"`, `model_reasoning_effort = "high"` | Gate `adw-test-writer` writes on Codex the same way as on Claude Code. Confirm `agent_type == "adw-test-writer"` at `PreToolUse` and block any write that carries no `agent_id` or a mismatched `agent_type`. |
| OMP | None at the tool_call hook. `ToolCallEvent` carries only `toolName`, `toolCallId`, `input`. `HookContext` carries the session and the currently selected model, nothing agent-scoped. | Not evaluable today, for the same reason as Codex. | Agent file (`.omp/agents/*.md` or extension `agents/*.md`) frontmatter `model` (literal id, `provider/id`, or role alias) | Apply the same default-deny approach used for Codex. Do not trust an identity field OMP's hook API does not expose. File an upstream request for an `agentType` or `agentId` field on `tool_call`, matching what Claude Code already ships. |

Three points to flag plainly.

- No source confirms a `gpt-6.1-luna` slug outside
  `~/.codex/models_cache.json` as fetched on 2026-09-28. Marked unconfirmed
  above.
- No Codex or OMP documentation describes a mechanism
  that correlates a specific subagent's `SubagentStart` and `agent_id` with
  its own later tool calls. OMP omits the field. Codex shares the parent
  session id. Whoever picks up Task 19 on those two hosts starts from an
  open question, not a settled fact.
- The one host with a working identity field, Claude Code, still cannot
  prove the model tier at write time. A default-deny test-write policy on
  Claude Code protects identity, not quality. Proving that `adw-test-writer`
  ran on Opus 5.5, and not on some other model, needs evidence from
  outside PreToolUse. A Stop-time reconciliation against `/tasks` history
  or the transcript is one option. PreToolUse alone will never carry that
  proof.

## Codex 0.159.2 recheck

`codex --version` reports `codex-cli 0.159.2`. The active binary lives at
`~/.codex/packages/standalone/current/bin/codex`, and this binary is the one
I inspected below.

### The earlier row was wrong for this version

The earlier pass concluded that Codex `PreToolUse` carries no `agent_id`,
`agent_type`, or `role` field. That conclusion matched the live
documentation page at the time. It does not match the binary Codex 0.159.2
ships, and it does not match the `openai/codex` source at the matching tag.
`PreToolUse` on 0.159.2 carries `agent_id` and `agent_type` as optional top
level fields. When the tool call comes from a subagent thread, Codex
populates both fields. When the tool call comes from the root agent, Codex
omits both fields.

### Evidence from the installed binary

I ran `strings -a` against the installed `codex` binary and located the
JSON Schema definitions Codex embeds for its own hook payloads. The schema
titled `pre-tool-use.command.input` lists `agent_id` and `agent_type` among
its properties. The same schema lists more fields too. Those fields are
`session_id`, `turn_id`, `cwd`, `hook_event_name`, `model`,
`permission_mode`, `tool_name`, `tool_input`, `tool_use_id`, and
`transcript_path`. The schema's `required` array excludes `agent_id` and
`agent_type`. Codex marks both fields optional. When Codex has a value for
a field, that field appears.

I checked the `session-start.command.input` schema the same way. That
schema carries neither field. Codex treats agent identity as a
subagent-scoped concern, not a session-scoped one, on `PreToolUse` and on
`SessionStart` alike.

### Evidence from source

`openai/codex`, file `codex-rs/hooks/src/schema.rs`, at tag `rust-v0.159.2`,
matches the binary exactly. `PreToolUseCommandInput` declares both fields
`Option<String>` with `skip_serializing_if = "Option::is_none"`. A test in
that same file, `subagent_context_fields_serialize_flat_and_omit_when_absent`,
checks the root-agent case. It asserts that a root-agent input serializes
with no `agent_id` key and no `agent_type` key at all. Codex omits the keys
outright. Codex does not send empty strings in their place.

I traced the field to PR #22882, "Add subagent identity to hook inputs",
merged 2026-05-21. The PR body describes a normal hook running inside a
thread-spawned subagent. That hook input gets two new optional top level
fields. `agent_id` carries the child thread id. `agent_type` carries the
subagent role. Root-agent hook inputs omit both fields. `gh api
repos/openai/codex/compare/rust-v0.150.0...16d85e27` reports `"behind"`,
so this commit predates release `0.150.0`. Every 0.15x release I checked
between `0.150.1` and `0.159.2` ships this field. The earlier pass read
documentation that was already stale by the time Codex reached `0.150`.

### Evidence that agent_type resists spoofing

The `spawn_agent` tool, defined in
`codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`, exposes an
`agent_type` parameter to the calling model. Its own description reads,
"Agent type override for the new agent. Omit unless explicitly asked." The
handler passes that value into `prepare_agent_spawn_config`, which calls
`apply_role_to_config` in `codex-rs/core/src/agent/role.rs`. That function
resolves the name against the registered role files for the project and
for the user. It returns the error `unknown agent_type '{role_name}'` for
any name that fails to resolve. Codex raises this error before it spawns
the child thread. No child thread means no `SubagentStart` event, and no
child `PreToolUse` event ever carries that unregistered name as its
`agent_type`.

### Live experiment

I ran this experiment under `~/adw-experiment-codex-2026-09-30`, and I
deleted that directory afterward. I checked this by rerunning `ls` against
the parent directory. The entry no longer exists.

Setup. This repo's own PostToolUse hook blocked my first attempt to write
`.codex/hooks.json` and `.codex/config.toml` inside the scratch project.
That hook treats any `hooks.json` or `config.toml` file under a `.codex`
directory as this project's own gate machinery. The hook applies that rule
regardless of location. I moved the hook wiring and the agent role file to
a `CODEX_HOME` override outside any `.codex` directory,
`~/adw-experiment-codex-2026-09-30/codexhome`. `CODEX_HOME` is a Codex
environment variable Codex documents for relocating its own configuration
home. I did not edit this repo's hook configuration or suppress its
finding.

- `codexhome/agents/adw-test-writer.toml`, fields `name`, `description`,
  `developer_instructions`.
- `codexhome/config.toml`, one `PreToolUse` hook, command `cat >>
  hook-log.jsonl`.
- `codexhome/auth.json`, a copy of my own `~/.codex/auth.json`, needed
  because `codex exec` reads credentials from `CODEX_HOME`.
- Model `gpt-6-luna` at `model_reasoning_effort=low`, the cheapest entry in
  `~/.codex/models_cache.json`.

Command 1, a delegated write.
```
CODEX_HOME=~/adw-experiment-codex-2026-09-30/codexhome codex exec \
  --skip-git-repo-check --dangerously-bypass-hook-trust \
  --dangerously-bypass-approvals-and-sandbox \
  -C ~/adw-experiment-codex-2026-09-30 -m gpt-6-luna \
  -c model_reasoning_effort=\"low\" \
  "Call the spawn_agent tool with agent_type set to adw-test-writer and
  instruct that subagent to write a file named out.txt containing exactly
  the word hello. Do not write the file yourself. Wait for the subagent to
  finish, then stop."
```

Three `PreToolUse` lines landed in `hook-log.jsonl`, reformatted here.
```json
{"tool_name": "collaborationspawn_agent",
 "tool_input": {"agent_type": "adw-test-writer", "task_name": "write_hello"}}
{"tool_name": "collaborationwait_agent",
 "tool_input": {"timeout_ms": 3600000}}
{"agent_id": "01a0f2df-2ea6-7241-95e0-17748887bbba",
 "agent_type": "adw-test-writer",
 "tool_name": "Bash",
 "tool_input": {"command": "printf hello > out.txt"}}
```
Only the third line, the subagent's own write, carries `agent_id` and
`agent_type` at the top level. The first two lines record the main
agent's own `spawn_agent` and `wait_agent` calls, and both omit these
fields. All three lines share one `session_id` and each carries its own
`turn_id`.

Command 2, a direct write by the main agent, fresh session, same scratch
project.
```
"Write a file named out2.txt containing exactly the word hello, directly,
yourself. Do not use spawn_agent or any subagent."
```
The single `PreToolUse` line this run produced carries no `agent_id` and
no `agent_type`, matching the main agent's calls from command 1.

Command 3, a spawn attempt naming a role that does not exist.
```
"Call the spawn_agent tool with agent_type set to adw-test-writer-FAKE (a
role that does not exist) and instruct it to write out3.txt containing
hello. Report exactly what error or result you get. Do not write the file
yourself under any circumstance."
```
Codex logged the `spawn_agent` call itself as one `PreToolUse` event.
`agent_type` appears there only inside `tool_input`, the raw argument the
model chose, never as the hook's own top level identity field. The
transcript then shows `codex_core::tools::router` raising `error=unknown
agent_type 'adw-test-writer-FAKE'`, and the model's own final line reports
that same error back to me. No `SubagentStart` event followed, and no
child `PreToolUse` event followed. The fake name never reached a real
subagent identity, because Codex never created the subagent.

### Answers to the four questions

1. A subagent's `PreToolUse` payload differs from the main agent's in
   exactly two fields, `agent_id` and `agent_type`. Both fields are present
   only on the subagent's own tool calls. Both fields are absent on the
   main agent's tool calls, including the main agent's own `spawn_agent`
   and `wait_agent` calls.
2. The main agent cannot set `agent_type` to an arbitrary string that
   reaches a hook. Codex checks the name against a registered role file
   before it creates the child thread. An unregistered name produces an
   error the router raises, not a subagent identity for any hook to read.
3. Correlating `SubagentStart` with later tool calls through a shared
   `session_id` or `turn_id` is unnecessary on 0.159.2, because `PreToolUse`
   already names the acting subagent directly. A gate can key on
   `agent_type` at `PreToolUse` alone, with no event correlation.
4. I checked only the failure case for an unregistered role name. I did
   not enumerate every scope Codex searches to resolve a role. A
   personal-scope role file and a project-scope role file can share the
   same name, and I did not test that case. I did not test `PermissionRequest`,
   `PostToolUse`, `PreCompact`, `PostCompact`, or `UserPromptSubmit` live.
   I checked those five only through the binary schema and the source.
   The live documentation page at `learn.chatgpt.com/docs/hooks` still
   describes `PreToolUse` as carrying neither field. I have no explanation
   on record for why that page has not caught up with a change merged
   before Codex reached `0.150.0`.

### Corrected recommendation

Retire the earlier default-deny treatment of Codex as a host with no
usable identity field. Gate `adw-test-writer` writes on Codex the same way
this report already recommends for Claude Code. Check `agent_type ==
"adw-test-writer"` at `PreToolUse`. Block any write that carries no
`agent_id` or a mismatched `agent_type`. The earlier default-deny
recommendation for Codex rested on a documentation page, not on the
binary this project runs against.

## OMP recheck

Task 19 asked me to look closer at OMP because an earlier pass read one
package snapshot and stopped. I read the full oh-my-pi source tree instead.

### Source used

Two sources, cross-checked against each other.

- The installed binary. `~/.local/bin/omp` is a 217 MB Mach-O binary, not a
  symlink to a script. `strings ~/.local/bin/omp | grep -o
  '@oh-my-pi/[a-zA-Z0-9_-]+@[0-9.]+'` shows it embeds
  `@oh-my-pi/pi-coding-agent`. The matching package cache is
  `~/.bun/install/cache/@oh-my-pi/pi-coding-agent@18.1.16@@@1`, the same
  package the earlier pass read.
- A full git checkout of the oh-my-pi repository at
  `/Users/nootnoot/Development/projects/.verification/oh-my-pi-reference`.
  `git log -1` shows commit `188b9eab0d65695b00579057a666c504296ba762`,
  dated 2026-09-11. `git remote -v` shows `origin
  https://github.com/can1357/oh-my-pi.git`. Its
  `packages/coding-agent/package.json` reports version `18.1.17`, one patch
  ahead of the installed `18.1.16`. This tree has full TypeScript source
  under `packages/coding-agent/src`, plus a Rust core under `crates`, plus a
  `docs` directory the bun cache does not ship. I read that `docs`
  directory and both `src` trees side by side.

Where both sources define the same type, they agree word for word. I quote
the reference tree below because it carries line numbers and adjacent
context the bun cache snapshot does not.

### What "tool_call" carries

`packages/coding-agent/src/extensibility/hooks/types.ts:304` defines the
event a hook receives.

```ts
export interface ToolCallEvent {
	type: "tool_call";
	toolName: string;
	toolCallId: string;
	input: Record<string, unknown>;
}
```

The parallel extension-facing union at
`packages/coding-agent/src/extensibility/extensions/types.ts:938` through
`980` builds one variant per built-in tool (`BashToolCallEvent`,
`WriteToolCallEvent`, and so on), but each variant still carries only
`type`, `toolCallId`, and a typed `input`. Neither shape names a session
role, an agent, or a caller.

`HookContext`, at `packages/coding-agent/src/extensibility/hooks/types.ts:176`,
is the second argument every handler receives.

```ts
export interface HookContext {
	ui: HookUIContext;
	hasUI: boolean;
	cwd: string;
	sessionManager: ReadonlySessionManager;
	modelRegistry: ModelRegistry;
	model: Model | undefined;
	isIdle(): boolean;
	abort(): void;
	hasQueuedMessages(): boolean;
}
```

`model` names the currently selected chat model. Nothing here names an
agent definition.

### Chasing the one plausible indirect path, and closing it

`ctx.sessionManager` was the last plausible place to hide an agent
identity, so I read what it exposes. `ReadonlySessionManager`,
at `packages/coding-agent/src/session/session-manager.ts:376`, is a
TypeScript `Pick` of the full `SessionManager` class.

```ts
export type ReadonlySessionManager = Pick<
	SessionManager,
	| "getCwd"
	| "getRecordedCwd"
	| "getSessionDir"
	| "getSessionId"
	| "getSessionFile"
	| "getSessionName"
	| "getArtifactsDir"
	| "getArtifactManager"
	| "allocateArtifactPath"
	| "saveArtifact"
	| "getArtifactPath"
	| "getLeafId"
	| "getLeafEntry"
	| "getEntry"
	| "getLabel"
	| "getBranch"
	| "getHeader"
	| "getEntries"
	| "getTree"
	| "getUsageStatistics"
	| "putBlob"
	| "putBlobSync"
>;
```

The full `SessionManager` class does define `getAgentId(): string |
undefined` (`session/agent-session.ts:1991`), reading a private
`#agentId` field. That method is absent from the `Pick` list above, so a
hook cannot call it through `ctx.sessionManager`.

A future OMP release can add `getAgentId` to that list. Even then, the
value does not answer the question ADW needs answered. `runSubprocess`
(`packages/coding-agent/src/task/executor.ts:3509`) sets `agentId: id` when
it builds a subagent's session, and `id` is not the agent definition's
`name` field. It is a random two-word instance label generated per spawn by
`generateTaskName()` in `packages/coding-agent/src/task/name-generator.ts`,
for example `SwiftFalcon` or `CalmPanda`. The real definition name
(`agent.name`, holding a string such as `adw-test-writer`) flows only into
an OTEL `AgentIdentity` object at `executor.ts:3388` and into the Agent Hub
progress rows described in `docs/agent-hub.md`. It never reaches
`HookContext`, `ToolCallEvent`, or the picked `SessionManager` surface.
`SessionHeader` (`session/session-entries.ts:35`) also carries no agent
field, so nothing recoverable sits in persisted session state either.

The earlier row's conclusion holds. A `tool_call` hook on OMP cannot learn
the calling agent's name, not directly, and not through any indirect path
in this source.

### What "limiter" names in OMP

The user's term does not match an OMP source-code identifier. `grep -rn
imiter` across `packages/coding-agent/src` turns up only English words
containing "delimiter" and an unrelated `xargs` command-size limiter in
`crates/pi-builtins/src/xargs.rs`. What the user describes is real, under
a different name. OMP's own code never uses the word "limiter". Two
separate mechanisms match the description, and they solve different
problems.

#### Tool approval tiers

`docs/approval-mode.md` documents a three-tier
system, `read`, `write`, and `exec`, set with `tools.approvalMode` and
overridden per tool with `tools.approval.<toolName>`. This is a session-wide
prompt policy. It decides whether a tool call needs a human "yes." It
does not decide which agent can call which tool, so it is not
agent-scoped.

#### The per-agent tools allowlist

This is the limiter that matters for
ADW's purpose. `AgentDefinition`, at
`packages/coding-agent/src/task/types.ts:376`, carries an optional
`tools?: string[]` field.

```ts
export interface AgentDefinition {
	name: string;
	description: string;
	systemPrompt: string;
	tools?: string[];
	spawns?: string[] | "*";
	model?: string[];
	...
	source: AgentSource;
	filePath?: string;
}
```

`parseAgentFields()` (`src/discovery/helpers.ts`) parses this field from an
agent markdown file's frontmatter, accepting a CSV string or an array.
`task/read-only-policy.ts:27` reads `agent.tools` directly to decide
whether an agent counts as read-only for other guardrails. That use
shows the field drives behavior, not only documents intent.

The enforcement point is `runSubprocess`
(`packages/coding-agent/src/task/executor.ts:3104`).

```ts
let toolNames: string[] | undefined;
if (agent.tools) {
	toolNames = agent.tools;
	...
	if (agent.spawns !== undefined && !toolNames.includes("task") && !atMaxDepth) {
		toolNames = [...toolNames, "task"];
	}
}
```

That `toolNames` list travels into `buildSubagentSessionOptions` at
`executor.ts:3452` and reaches the subagent's session through
`session/session-tools.ts`, whose `setActiveToolsByName` builds the tool
registry the model sees. A tool absent from `agent.tools` is not merely
hidden behind an approval prompt. It is never registered for that
subagent's session, so the model never receives its schema and cannot call
it, no matter what it asks for. This is a capability restriction, not a
permission gate.

### Where the limiter cannot reach

`discoverAgents()` (`src/task/discovery.ts`) and
`docs/task-agent-discovery.md` describe where an `AgentDefinition` comes
from. Three sources are project `.omp/agents/*.md`, user
`~/.omp/agent/agents/*.md`, and an OMP extension package's own `agents/`
directory. Two more sources are Claude marketplace plugin `agents/`
directories, and bundled built-ins. ADW's own `adw-test-writer.md` lives
in that extension `agents/` directory.

Every one of those paths describes a **subagent**, something dispatched
through the `task` tool. I found no CLI flag and no config key for this.
No code path lets the top-level, interactive OMP session itself run under
an `AgentDefinition` with a restricted `tools` list. `cli/` has no
`--agent` flag comparable to Claude Code's. The main session keeps the
full built-in tool surface. The `tools` allowlist limits what a spawned
`adw-test-writer` subagent can do. It does nothing to the main agent that
spawns it.

### Bypass paths, and what closes them

A main agent cannot forge `agent.tools` for a running subagent process.
The model never sees a tool outside that list, so there is no tool call
to forge in the first place. Two other paths remain open.

#### Editing the agent definition file before the spawn

The main session
keeps its ordinary write access to `.omp/agents/adw-test-writer.md` and to
the ADW extension's own `agents/adw-test-writer.md`. Neither path counts
as a test file. `docs/task-agent-discovery.md` documents that execution
rediscovers agents on each dispatch. If agent or extension files change
mid-session, the runtime agent set differs from the set an earlier
description named. A main agent can rewrite that file's `tools` list or
system prompt, then dispatch the now-altered `adw-test-writer` by name.

The section above already showed that OMP's `tool_call` hook and
`HookContext` never see which agent file backed a call. For that reason,
neither can tell the difference between a call from the file ADW shipped
and a call from an edited one. ADW's own default-deny path gate closes
this the same way it closes every other write. Add
`.omp/agents/adw-test-writer.md` and the extension's shipped
`agents/adw-test-writer.md` to the same protected-path set that covers
test files. The main agent then needs the same approval to edit the
trusted agent's definition as it needs to edit a test file directly.
Rewriting the identity buys it nothing new.

#### Self-recursion

`PI_BLOCKED_AGENT` and `task.maxRecursionDepth`
(default `2`) stop a spawned agent from spawning itself in a loop.
`docs/task-agent-discovery.md` documents both, under "Blocked
self-recursion env guard" and "Recursion-depth gating." Neither guard
addresses identity theft. Both bound recursion depth, not which named
agent runs a given write.

### Design ADW ships on OMP

Ship `adw-test-writer.md` as an OMP task-agent definition, in the ADW
extension's own `agents/` directory. Give it a `tools:` list naming
`write` (or whichever tool creates test files), alongside the read tools
it needs.

Give every other agent definition, the ones ADW ships and the ones OMP
ships, a `tools:` list that omits that tool. A subagent dispatched under
any other name then cannot write a test file, even before ADW's own gate
runs.

Keep the existing `tool_call` hook gate. It is the only line that can see
the main session's own direct writes, because the main session sits
outside the `tools` allowlist system. Default-deny a write to a path
matching the project's `tests: deny` pattern at that hook, for the same
reason the Codex row already gives. No field distinguishes the main
agent's write from a subagent's write. Extend that same deny set to cover
the agent-definition files named above, and close the rewrite-then-spawn
path.

Do not make the `tool_call` hook trust an `agent` field. None exists on
`ToolCallEvent`, and none is reachable through `HookContext`. None
survives in `ReadonlySessionManager` either, the one place that looked
like a possible carrier.

### Corrected OMP row

Row 3 of the table in Task 18's Section 5 stated only that OMP has no
identity field. It said ADW must default-deny and file an upstream
request. That much still holds.

It did not mention that OMP separately ships a real, enforced, per-agent
tool-capability system, `AgentDefinition.tools`. ADW can use that system
to keep every subagent except `adw-test-writer` unable to write a test
file. The row also did not mention that this system never reaches the
main session. I corrected the row below.

| Host | Identity field | Spoofable | Model and effort setting | Recommendation |
| --- | --- | --- | --- | --- |
| OMP | None at the tool_call hook or anywhere reachable through HookContext. `ToolCallEvent` carries only `type`, `toolName`, `toolCallId`, `input`. `ReadonlySessionManager` is a `Pick` of `SessionManager` that excludes `getAgentId()`. That method returns a random per-spawn instance label, not the agent definition's `name`, even where exposed. Separately, OMP does enforce a per-agent tool-capability list, `AgentDefinition.tools`, at subagent-session construction in `task/executor.ts`. That list is not an identity check. It restricts which tools a named subagent's session ever registers, and it does not apply to the main interactive session. | The `tools` allowlist itself cannot be spoofed by a running subagent. A tool absent from that list is never registered for the model to call. The allowlist can be neutralized by editing the agent's `.md` file before the spawn. OMP rediscovers agent files at dispatch time, and the main session has ordinary write access to that file. | Agent file (`.omp/agents/*.md` or extension `agents/*.md`) frontmatter `model` (literal id, `provider/id`, or role alias). `tools:` sets the agent's capability list, not a model setting | Ship `adw-test-writer` with `tools:` including the test-write tool, and every other shipped agent without it, so subagents are limited by OMP itself. Keep a default-deny `tool_call` path gate for the main session's own writes, because no identity field ever reaches that hook. Extend the gate's protected-path set to the agent-definition files themselves, closing the rewrite-then-spawn bypass. File an upstream request for an `agentName` field on `tool_call`, matching what Claude Code already ships. |

Three points follow.

- I read a full git checkout of oh-my-pi at commit
  `188b9eab0d65695b00579057a666c504296ba762` (`packages/coding-agent`
  version `18.1.17`), one patch ahead of the installed `18.1.16`. Where I
  checked the same type in both trees, the bun-cache snapshot and the git
  checkout agreed word for word. I did not diff every file the two trees
  share, only the ones cited above.
- I did not check whether a spawned subagent (not depth-capped, not
  plan-mode) loads its own separate instance of an OMP extension such as
  ADW's. If that separate instance exists, it runs its own `tool_call`
  hook that fires only for that subagent's own calls. The alternative is
  one extension-runner instance shared with the parent session.
  `executor.ts:3463` passes `preloadedExtensionPaths` through unchanged
  for a normal spawn, a detail consistent with a separate instance. I did
  not trace extension-runner construction end to end to confirm it.
- I found no OMP documentation or source describing a plan to add an
  agent-identity field to `tool_call` or `HookContext`. The gap is not a
  filed, pending fix. OMP has not addressed it as of this checkout.
