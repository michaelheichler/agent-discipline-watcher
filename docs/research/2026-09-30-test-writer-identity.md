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
| Codex | None. PreToolUse carries no `agent_id`, `agent_type`, or `role` field. `SubagentStart` and `SubagentStop` carry `agent_id` and `agent_type`, but subagent hooks share the parent's `session_id`. Nothing ties a PreToolUse call back to one specific subagent invocation by session id alone. | Not evaluable today. Nothing at PreToolUse exists to spoof, because nothing exists to inspect. | Per-agent TOML file (`~/.codex/agents/*.toml` or `.codex/agents/*.toml`) sets `model` and `model_reasoning_effort`, for example `model = "gpt-6-luna"`, `model_reasoning_effort = "high"` | Do not ship a Codex test-write allowlist that trusts an identity field, none exists at PreToolUse today. Deny every test write on Codex until OpenAI adds an identity field to PreToolUse. As an alternative, correlate `SubagentStart`'s `agent_id` with the immediately following `PreToolUse` call inside the same hook process run. If you build it, mark that correlation fragile and unconfirmed in the gate's own error text. |
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
