# Spec for the per-host runtime split

Supersedes `plan-host-runtime-split-2026-08.md`, which states three runtimes and one wrong
fact about OMP inference. Decisions and their evidence live in
`decisions-host-split-2026-08.md`.

## Problem Statement

Installing ADW through one host installs all of them. A Claude Code plugin install drags in
the OMP extension and the Codex bridge, and it points at the development checkout, so moving
the checkout breaks the install.

Three further problems ride along.

The OMP runtime does not match the Claude runtime. It spawns a nested Claude CLI for judge
calls, which bills the account and ignores that OMP already orchestrates many models.

The `/adw configure` screen renders raw identifiers. A reader sees `banned_adverb` and
`max_rows` with no wording, and sees `observe` and `judged` with no consequence attached.

Claude Cowork runs inside a VM that never reads the host home directory, so an install that
assumes `~/.adw` cannot reach it at all.

## Solution

ADW ships one rules core and four host runtimes. A user installs the runtime for the host
they use, and nothing else lands on disk.

The core stays identical everywhere, and a fixture that all four runtimes scan proves it. Each
runtime owns only its adapter, meaning event wiring, payload shape, install surface, and
model provider.

Every judge runs on its host's own models, and no host spawns a nested CLI.

Claude offers four presets. `haiku` runs Haiku alone. `mixed` runs Haiku for comments, and
Sonnet for prose and document reviews. `sonnet` runs Sonnet throughout. `luna` reaches the
subscription-backed GPT-5.6 Luna provider through a command handler. That last one emits no
native agent. The user picks one, and the picker belongs to the Claude runtime.

Codex resolves Luna natively. OMP calls `completeSimple` in process against the model the
user picked, including a local one.

The configuration screen reads in plain language, fed by one catalog beside `config.py`.

The root installer stays and becomes a router, with an interactive picker for humans and a
flag path for agents.

## User Stories

### Claude Code and Claude Desktop

1. As a Claude Code user, I want the plugin install to write no OMP or Codex file, so that my
   machine carries only what I use.
2. As a Claude Code user, I want the plugin to work after I move my checkout, so that a
   directory rename does not silently disable my gate.
3. As a Claude Desktop user, I want the plugin I installed in the terminal to gate my Desktop
   Code tab too, so that I configure the gate once.
4. As a Claude Desktop user, I want no separate Desktop install step, so that I do not
   maintain two copies of one policy.

### Cowork and Codex

5. As a Cowork user, I want ADW to gate writes inside the VM, so that a background agent
   cannot ship prose my terminal sessions would block.
6. As a Cowork user, I want the runtime to need no network at session start, so that the
   default empty egress allowlist does not disable my gate.
7. As a Codex user, I want an installer that touches only `~/.codex` and `~/.adw`, so that
   installing for Codex leaves my Claude configuration alone.

### OMP

8. As an OMP user, I want ADW to block a write with the same verdict Claude Code would give,
   so that switching host does not change what ships.
9. As an OMP user, I want the judge to run on the model I selected in OMP, so that a local
   model keeps my code off the network.
10. As an OMP user, I want to pick any authenticated model for the judge, so that the picker
    reflects that OMP orchestrates many providers.
11. As an OMP user, I want no nested Claude CLI process, so that ADW does not bill an account
    I did not choose for it.
12. As an OMP user, I want the gate to reach a subagent write, so that delegating work does
    not route around the gate.
13. As an OMP user running a restricted-tools subagent, I want to know that path loads no
    extensions, so that I understand where the gate stops.

### Configuring the gate

14. As a person configuring ADW, I want each rule to carry a title and a description, so that
    I can decide without reading the source.
15. As a person configuring ADW, I want each state to say what happens to my write, so that
    `observe` and `judged` mean something.
16. As a person configuring ADW, I want a locked rule to say why it cannot move, so that a
    greyed row does not read as a bug.

### Installing the gate

17. As a person installing ADW, I want an interactive picker that names what each host writes,
    so that I choose without reading the script.
18. As a person installing ADW, I want to click a row rather than type a flag, so that the
    installer suits a human.
19. As an agent or a CI job, I want a flag path that skips the picker, so that an install runs
    without a terminal.

### Maintaining the gate

20. As a maintainer, I want one rules core with no host name in it, so that a rule cannot
    drift between hosts.
21. As a maintainer, I want a parity test across all four runtimes, so that drift fails the
    suite rather than reaching a user.
22. As a maintainer, I want each runtime to pass its own tests after deleting the other three,
    so that isolation holds in fact rather than in theory.
23. As a maintainer, I want the scanner to skip YAML frontmatter, so that ADW stops blocking
    every `SKILL.md` and memory file.
24. As a maintainer, I want no host to downgrade a rule for an easier build, so that the
    discipline holds everywhere.
25. As a writer, I want the commit gate to run structural rules only over a message body, so
    that `banned_adverb` stops blocking my commit.

## Implementation Decisions

### Four runtimes, and why Desktop is not one

The hooks reference states Claude Code fires the same events in the terminal, IDE extensions,
Desktop, and on the web. The Desktop quickstart states both share CLAUDE.md, MCP servers,
hooks, skills, and settings. `codesign -d --entitlements` on the app bundle shows no
`com.apple.security.app-sandbox` key, and no container exists under `~/Library/Containers`.
One plugin cache serves both, at
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>`.

Cowork differs. Its overview states it does not read the CLI `~/.claude` directory. Connected
folders mount under `/sessions/<session-id>/mnt/`, and plugins sync from the claude.ai account
through the Customize panel.

Four runtimes follow, named `claude`, `codex`, `omp`, and `cowork`.

### Cowork runs the real Python core

The VM rootfs carries `python3.10`, `pip`, `uv`, `node`, and `bun`. Plugin files travel into
the VM under `/home/claude/.claude/plugins/`, up to 200 MB and 5000 files. The VM CLI binary
carries the full hook executor set, including `executePreToolHook` and `executeStopHook`.

Cowork therefore needs no regex-only build. It needs a core that arrives with the plugin and
runs without network, because `coworkEgressAllowedHosts` documents no default and PyPI sits
outside it.

`CLAUDE_CODE_IS_COWORK` appears in the VM binary as a detection marker. It carries no
documentation, so the runtime treats a missing `~/.adw` as the reliable signal and uses the
env var only as a hint.

### The core ships vendored, never installed at runtime

Each host directory carries a copy of the core, which a build step writes from one source. No
runtime resolves the core from `~/.adw`, because Cowork cannot, and no runtime installs a
package, because Cowork has no egress.

### OMP reaches parity through its own API

`tool_call` blocks with `{ block, reason }` from `shared-events.ts:310-332`, which replaces
the Claude `permissionDecision` shape.

The gate reaches subagents. An ordinary subagent receives a re-bound extension runner. The
parent forwards `session.preparedExtensions` at `structured-subagent.ts:448`, and `sdk.ts`
rebinds them into a fresh runner. `agent-session.ts:3676-3711` fires `tool_call` there and
honours a block. `registerFileWriteFallback` stays process-global, so a parent handler brokers
subagent writes as well.

Two gaps stay, and both get named rather than papered over. A `restrictToolNames` subagent
loads no extensions, because `structured-subagent.ts:448` forces the list empty. And
`session_stop` never fires for a subagent, because `agent-session.ts:3780` returns early when
`agentKind` is `sub`.

The judge runs in process. `completeSimple` from `@oh-my-pi/pi-ai` needs no separate install,
because the loader rewrites the bare specifier onto the host copy. Credentials come from
`ctx.modelRegistry.getApiKeyForProvider`, and the model list comes from `ctx.models.list()`.
`ollama`, `llama.cpp`, and `lm-studio` register with zero configuration and no key.

### Luna belongs to Codex, and Claude borrows the credential

Codex is OpenAI Codex, so Luna is its native provider. Codex crosses no boundary to reach it.

Claude borrows. `luna_provider.py:236` reads `~/.codex/auth.json` as its auth source, so the
`luna` preset needs the file the Codex login writes. Luna reports unavailable when that file
goes missing, and the runtime falls back to `mixed`.

The borrow reaches no further than that one file. `luna_storage.py:108` builds a scratch
`codex_home` per call under its own directory, chmods it to 0o500, then links `auth.json`
into it. No worker runs against the user's own `~/.codex`.

A credential gates the preset, not a Codex install. A user can install the Claude runtime
alone, log in through Codex, and still reach Luna.

`luna_provider`, `luna_storage`, `luna_worker`, `luna_runtime`, and `luna_feedback` all sit
in the shared core, because both hosts drive them. No Claude module imports a Codex module,
and none goes the other way.

**Decided.** Codex pins the real `~/.codex` rather than copying the credential into a scratch
home. Claude keeps the scratch path for its borrow, so `luna_storage` becomes Claude-owned.

The naive version of this would have removed a security control. `luna_worker.py:127-154`
asserts that `cwd` and `home` both sit inside one confined call directory, and
`luna_provider.py:266-273` refuses to launch without those pinned descriptors. A real
`~/.codex` can never satisfy that containment test.

So Codex gets its own verification rather than a weaker one. `codex_ambient.py` opens
`~/.codex` with `O_NOFOLLOW`, pins its device and inode, and refuses a directory that another
account owns or that carries group or world write. The credential itself must be a regular
file owned by the same account. The swap guard survives in a form that suits an external
home, and `RuntimePaths.home_confined` marks which of the two models applies.

### Parity means deterministic parity

Every regex and structural rule must produce byte-identical findings on a shared fixture
across all four runtimes. Block or allow decisions must match on those rules. Judge verdicts
stay advisory and may vary by model, which is what makes the OMP picker worth building.

### The configuration catalog lives in Python

`lib/catalog.py` carries a title, a description, and per-state wording for 33 configurable
rules, 23 always-blocking rules, 3 families, 3 thresholds, 4 rule states, 3 family states, and
3 baseline modes. The bridge serves it and the TUI renders what arrives. An unknown name falls
back to a derived title rather than crashing the screen, and a test asserts no fallback is
needed today.

### The root installer routes

`install.sh` keeps its place and stops knowing how to install anything. A Python module draws
an interactive multi-select with arrow, space, and SGR mouse support, prints the chosen hosts,
and bash calls each `hosts/<name>/install.sh`. A flag path skips the picker. `hosts/claude`
carries no installer, because the plugin is that path.

### Nothing weakens

A host that cannot enforce a rule gets a harder path, an upstream fix, or a refusal to run.
It never gets an exemption. Policy edits, coverage loss, wiring removal, judge loosening, and
suppression markers all stay out of bounds, per D0 in the decisions file.

## Testing Decisions

A good test here asserts external behaviour, meaning the finding a scan produces or the
decision a gate returns. It does not assert which module produced it, because the split moves
modules around by design.

### Seams

One seam carries the parity guarantee. `scanner.scan_all` is the single point where every
family runs, so the cross-runtime fixture test drives it directly and compares serialized
findings byte for byte. Prior art is `test_slop_integration.py`, which already drives
`scan_all` over a fixture and asserts emitted rules.

The second seam is `configure.run`, which every bridge operation funnels through. Prior art is
`test_configure.py`, which drives `run` with a request dict and asserts the response envelope.

The third seam sits per host at the adapter entry. `pre_tool.run` covers Claude, Codex, and
Cowork, because all three speak the Claude hook payload. The OMP `tool_call` handler in
`index.ts` covers OMP. Prior art is `test_pre_tool.py` and `index.test.ts`.

The fourth seam is the installer router. Host selection and per-folder dispatch get their own
contract rather than riding inside the picker tests, because the router decides what lands on
disk and that decision deserves an assertion of its own. Prior art is
`test_install_runtime.py`, which already drives an install into a temporary HOME and inspects
the resulting tree.

New tests attach to those four seams. No test reaches into a host runtime internal.

### What gets tested

Isolation gets a test that deletes three host directories and runs the fourth runtime's suite.

Parity gets a test that scans one fixture through all four adapters and asserts identical
findings, identical line numbers, and identical block decisions.

The installer router gets a contract test that maps a selection to the exact set of dispatched
host installers. Three cases carry it. A selection dispatches only the chosen hosts. The flag
path dispatches without a terminal. An empty selection dispatches nothing and touches no disk.

The picker itself gets separate tests for arrow movement, space toggling, and mouse click
routing, kept apart from the router contract so a rendering change cannot mask a dispatch bug.

The catalog keeps the coverage in `lib/test_catalog.py`, extended so the bridge carries a
title and a description on every rule and family row.

The frontmatter mask gets a test asserting a leading delimited block produces no punctuation
finding, that a colon in the body still blocks, and that line numbers stay correct.

The OMP judge provider gets a test proving no subprocess spawns, and a test proving a provider
failure reports a named reason rather than passing silently.

The OMP subagent path gets a test proving a re-bound handler blocks a subagent tool call, and
a test pinning the two known gaps so a future OMP change surfaces them.

## Out of Scope

Splitting rules per host stays out of scope permanently. One ruleset serves every host.

The stop-slop calibration work lives in `todo-stop-slop.md`. Its corpora are missing, so it
blocks on a separate decision.

Rebuilding the OMP advisor harness stays out of scope, and `WATCHDOG.yml` now sits deleted,
untracked, and ignored.

Claude Code on the web stays out of scope beyond a documented note, because it reads repo and
server settings rather than any local path.

The `claude_native.py` split stays out of scope here, and Task 14 in the superseded plan
tracks it, though the file sits at 995 lines against a 1000-line hard block.

## Further Notes

### Two weakenings still stand in the working tree

`document_review.py` and `pattern_judge.py` moved the judge from `claude-sonnet-5` to Haiku.
The README previously recorded that Haiku wrongly blocked two ordinary sentences on two of
four runs while Sonnet cleared the same document four times of four. The precision numbers
behind `ENFORCE_PRECISION = 0.85` still cite a Sonnet reader. Either re-measure against Haiku
or restore Sonnet before this spec starts.

Commit `a7ee111` deleted a Luna worker-deadline test as flaky with no replacement and no fix.
That coverage needs restoring.

### Landed already

`lib/catalog.py` and its 11 tests. `configure.py` split into `configure_policy`,
`configure_store`, and `configure_capability`, down from 700 lines to 277, with all eight
oversized functions and every ADW finding cleared. Suite sits at 1780 passing.

### Three memory facts wait on the frontmatter mask

The mask unblocks writing `questions-must-carry-suggestions`,
`global-claude-md-is-binding`, and `research-agents-use-deepseek-or-sonnet`. Their content
sits in the decisions file.
