# Spec for the judge restoration and the standing rules

Written on 2026-08-30 from a working session. `spec-host-runtime-split-2026-08.md` covers the
per-host split. This file covers the judge, the banned mechanisms, and the rules the user has
stated more than once.

## Problem Statement

A user installs the ADW plugin and gets no model judge. The deterministic rules fire, so the
gate looks alive, and the semantic layer stays silent.

Judging still happens on one path, through a nested `claude -p` process. That path bills the
user's account per call and spawns a full Claude session for each candidate.

The status command reports a preset nobody selected, so the gap stays invisible.

## Solution

The plugin carries its own judge as a native agent hook. Installing the plugin is the whole
setup. No settings merge, no preset apply step, no nested process.

`claude -p` disappears. Every judge call on Claude runs as an agent hook, and the Luna preset
reaches GPT-5.6 Luna through the SDK instead.

The status command reads the wiring rather than the intent, so an unwired gate says so.

## User Stories

### Getting a working judge

1. As a plugin user, I want the judge to run after a plain install, so that I never discover
   months later that the semantic layer never fired.
2. As a plugin user, I want no nested Claude session per candidate, so that the gate does not
   bill my account for every write.
3. As a plugin user, I want the judge to review the text of a question the agent puts to me,
   so that a cryptic question gets caught like any other reader-facing prose.

### Failing safely

4. As a plugin user, I want the reviewer to stay off PreToolUse, so that a chatty model reply
   never denies a legitimate edit.
5. As a plugin user, I want the reviewer to fail open on a malformed reply, so that the gate
   degrades to silence rather than to a wrongful block.

### Choosing a model

6. As a Claude Code user, I want to pick between a haiku reviewer and a mixed reviewer, so
   that I choose my own cost and strictness.
7. As a Claude Code user running LeverFrame, I want a native Luna preset, so that I use the
   model my harness already injects.
8. As a Codex user, I want Luna judging through the SDK, so that judging costs no Anthropic
   tokens.

### Owning my own machine

9. As a user of any host, I want ADW to write only under its own state directory, so that my
   host configuration stays mine.
10. As a maintainer, I want the status command to read settings and hooks, so that it reports
    the gate rather than a stored preference.

### Keeping the gate honest

11. As a maintainer, I want a test that fails when the plugin loses its reviewer, so that a
    future removal cannot pass review as a cleanup.
12. As a maintainer, I want a test that keeps agent handlers off PreToolUse, so that the
    reproduced deny bug cannot return.
13. As a maintainer, I want the reviewer prompt to enumerate its output space, so that a
    chatty model fails loudly rather than silently.
14. As a maintainer, I want `judge_model.py` to lose its last caller, so that no module pins a
    model behind the user's choice.
15. As a maintainer, I want the rule count stated in one unit, so that 98 and 56 stop reading
    as a contradiction.

### Reading what the agent writes

16. As a person reading a question from the agent, I want concrete options and a named
    recommendation, so that I decide rather than research.
17. As a person with ADHD, I want the shape rules in the global CLAUDE.md honoured, so that an
    answer stays readable.
18. As a maintainer, I want research subagents pinned away from Haiku, so that a hallucinated
    finding does not steer the next several steps.

## Implementation Decisions

### The plugin carries the judge

`hooks/hooks.json` registers a `type: "agent"` reviewer on PostToolUse and on Stop. The
PostToolUse matcher includes the write tools and `AskUserQuestion`.

The plugin default is haiku. A public installer with no Codex login still judges.

### PreToolUse never carries an agent handler

Commit `f9da7d5` reproduced the failure live. A non-conforming agent reply reads as a hook
execution error, and a PreToolUse error denies the tool call. Haiku reasoned correctly, said
so in prose, and the edit died three times.

A test pins this.

### Prompt shape follows the library, not habit

Each reviewer prompt runs in a fixed order. Scope first. Then the ordered steps. Then the
output space written out in full. Then the failure mode to avoid. The input comes last, and
the prompt ends on a priming token.

Two books in the user's library ground that shape.

*Designing Large Language Model Applications* records that models turn chatty when asked for a
bounded answer. It also records that a good prompt describes the output space and primes the
next token.

*Prompt Engineering for Everyone* records that models process a prompt as a chain of
dependencies, so instruction order changes the result.

### Managed hooks carry a marker

The plugin's agent prompts open with the managed marker line. The settings merger recognises
an ADW agent hook by that marker, because an agent hook has a prompt where a command hook has
a command. Without it, a second merge duplicates the entry.

### Presets, four of them

- `haiku` runs the haiku reviewer everywhere.
- `mixed` runs haiku for comments and sonnet for documents.
- `luna` reaches GPT-5.6 Luna through the SDK, and Codex owns that login natively.
- `luna-native` runs an agent hook on the Luna model, for a harness that injects Luna into
  Claude Code.

A sonnet-everywhere preset goes away. The user rejected it.

### OMP stays native

OMP judges in process through `completeSimple` against the model catalogue. No SDK, no CLI, no
direct HTTP. The earlier open question about an upstream inference API closes as answered.

### ADW writes only under its own state directory

The host configuration directories belong to the user. ADW keeps its own files under its state
directory and registers with a host through whatever native mechanism that host offers.

This decision arrived late in the session and conflicts with installers written the same day.
The Further Notes record the conflict rather than hiding it.

## Testing Decisions

A good test here asserts the wiring a user receives or the finding a scan produces. It does
not assert which module produced a finding, because the split moves modules by design.

### Seams

Four seams carry this work, and the tests attach to them rather than to internals.

`hooks/hooks.json` carries the registration contract. `test_plugin_wiring.py` reads it and
asserts the reviewer exists, names its model, enumerates its output space, and stays off
PreToolUse.

`claude_native.generated_hooks(preset)` renders a preset. Its tests assert the shape each
preset emits without writing any file.

`scanner.scan_all` carries deterministic parity. `test_runtime_parity.py` already drives it
across four vendored runtimes.

`configure.run` carries the config bridge. `test_configure.py` already drives it with a
request dict.

### What gets tested

The reviewer registration gets a test that fails when the plugin loses it. Prior art is the
inverted pair in `test_plugin_wiring.py`, which previously asserted the reviewer's absence.

The settings merger gets an idempotency test covering an agent hook, because the marker is the
only thing that makes a re-merge safe.

The judge removal gets a test proving no module spawns a process for a verdict. Prior art is
the existing check that no judge imports `subprocess`.

`pattern_judge` gets a test proving a judged rule reports its unavailability rather than
passing silently, because the current code fails open.

## Out of Scope

Rewriting the shipped release notes in the changelog. Those record what happened.

Splitting rules per host. One ruleset serves every host, permanently.

The `claude_native.py` line count, which `plan-host-runtime-split-2026-08.md` tracks as
Task 14.

Recalibrating any rule threshold. The measurements stand until someone re-measures.

## Further Notes

### Three items the previous session owed, now grounded

**The config-folder conflict is real and unresolved.** The standing rule says ADW writes
nothing into a host configuration directory. Three installers written on 2026-08-30 break it.
The Codex installer merges a fenced block into the Codex config file. The OMP installer
delegates to the extension installer, which writes the agent directory and a skills link. The
Claude installer writes a launcher link, a shell rc block, and a legacy cleanup into the
Claude settings file. That pass has not started.

**The rule count reconciles in two units.** Commit `199525a` states "Coverage was 6 of 98",
so 98 counts source patterns rather than rules. `WEIGHTED_MARKERS` holds 67 of them. Nine
phrase categories hold 65 more. `STRUCTURE_RULES` holds 10 structural categories, and 38
irregular participles feed `passive_voice`. Those patterns surface through the 56 rules the
catalog exposes, which split into 33 configurable and 23 always-blocking. Both numbers are
correct and neither is a contradiction.

**`claude -p` is gone.** Commit `7bf4397` removed it.

The earlier note counted one seam and three call sites. It missed a second, independent copy.
`judge_provider.complete` served `judge.py`, `document_review.py`, and `pattern_judge.py`,
while `evals/measure_judge_stage.py` built its own command. Both are gone now, and a
source-level test fails if either `subprocess` or the literal command returns to the seam.

One correction to the cost claim. The spawn was reachable only through the `JudgeReview` route.
`1ceecb3` registered that route on 2026-08-27 and `4499399` unregistered it on 2026-08-28.
After that only the pi extension called it, and OMP already refused the CLI. So the billing
window ran about one day rather than the whole period. The code still sat one `hooks.json` line
away from billing again, which is why it had to go rather than sit unused.

The fail-open was real, and `confirm_all` now fixes it. That function answered an empty mapping
both when the judge cleared every candidate and when no judge existed, so a judged rule could
stop firing with nothing said. It now returns a `JudgedOutcome` carrying the kept candidates,
the rules nobody read, and the reason. `three_item_list` is the one rule the default config
puts at the judged state.

### How the judge disappeared

`d606abc` on 2026-08-13 removed the last agent hook from the plugin and rewrote the plugin
description to drop the word semantic. Two tests then asserted the absence, which made the
removal look like the intended design.

Judging returned on 2026-08-27 as `claude -p`. The native path returned on 2026-08-28 but only
through a settings write that needs a manual command, and the user's machine had never run it.

### Standing rules the user stated more than once

A question to the user carries concrete options and a named recommendation.

The shape rules in the global CLAUDE.md are hard requirements rather than preferences.

Research subagents run DeepSeek v4 Flash first and Sonnet 5 second, never Haiku. The model
travels on every call, because the default can resolve to Haiku without saying so.

### Measurement still owed for Luna

`evals/measure_judge_stage.py` no longer spawns anything. It stops with a message naming the
missing provider, so nobody burns a measurement run against a judge that cannot answer. Wiring
it to a real provider stays owed, and the corpora it needs are still absent.

### What remains after the removal

`judge_model.py` still screens for haiku, and five modules still call it to pick a model that
never reaches anything. That screen outlived its purpose and should go with the preset rework.

The preset roster still reads `("mixed", "luna", "haiku", "sonnet")` in `claude_native.py`. The
user rejected a sonnet-everywhere preset, and `luna-native` is not there yet.

`adw-judge status` still reports the stored preference rather than the wiring a user received.

The config-folder pass has not started. The installers write a shell rc block, a launcher link,
a Codex config fence, and an OMP agent directory, all outside the state directory.
