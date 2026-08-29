# Agent Discipline Watcher

Discipline gates for agent output across **Claude Code**, **Codex**, and **OMP** (`oh-my-pi`). Current release: **0.18.9**.

The watcher reads what an agent writes and names what is wrong with it. Every finding cites one rule and one line, so you can open the file and disagree. It never returns a verdict on a document, and it never answers whether a model wrote something.

## Three layers

**Regex.** 98 patterns run on every write. Because this layer is deterministic and asks no model to release a finding, it is the one that decides the gate.

**Meaning.** Off by default. The watcher embeds each sentence and votes it against one pattern's own violating and clean neighbours. A judge then decides whether the survivors instantiate the named pattern. This layer catches what the regex misses, because a paraphrase has no literal to match.

**Document.** New in 0.18.7. When an agent finishes a prose file, the document reader takes the whole file and names what a line rule cannot see. An order that hides the argument, a missing bridge between paragraphs, a referent the document uses before introducing it, a paragraph shape repeated until it reads as a tic. Each note quotes the sentence it means and cites its line. The note blocks the Stop, so the agent goes back to work rather than handing you an unread draft. The watcher skips a document unchanged since its last reading, and after two rounds it stands down and leaves the call to you.

A rule speaks only where a measurement covers it, and blocks only where that measurement earned the block.

| rule | precision after the judge | gate |
| --- | --- | --- |
| `ai_closer` | 1.0000 | block |
| `utilize` | 1.0000 | block |
| `inflated_diction` | 0.9595 | block |
| `vague_quantity` | 0.9406 | block |
| `business_jargon` | 0.8507 | block |

22 more rules carry exemplars and no measurement. They stay silent until measured. The precision threshold is 0.85, held in `pattern_semantic.ENFORCE_PRECISION`.

The judge behind both the meaning layer and the judged gate is Sonnet, not Haiku. Haiku blocked two ordinary sentences as `ai_closer` on two of four runs over one technical document, and Sonnet cleared the same document four times out of four. A judge that decides a hard block justifies the stronger model. The document reader runs on Sonnet for the same reason.

## What the rules were measured against

The rules used to have no false-positive denominator. They have one now.

**60000 human sentences** from news, encyclopedia articles, and books published mostly before 1930. No model wrote any of it. A rule that fires there is either doing its job or costing you an edit, and `evals/human_hit_rate.json` records the hit rate per genre.

Every AI-tell rule fires on 1 sentence in 20000 or fewer. `passive_voice` is not an AI tell and carries no such budget. It fires on 1 sentence in 4, and every hit read as a genuine passive.

**88148 assistant sentences** from `allenai/WildChat-4.8M` and `lmarena-ai/arena-human-preference-100k`, across 69 models including GPT-4o, o1, Claude 3.5 Sonnet, Gemini 1.5 Pro and Llama 3.1. Rules that name an AI tell fire zero times on human prose, so without this side they have no violating class and no measurement can reach them.

**9256 documents that still carry their paragraph breaks**, 5000 human from `wikimedia/wikipedia` and `sedthh/gutenberg_english`, 4256 assistant from the same two chat sets. Both sentence corpora flatten a document to one line, so no paragraph-shaped rule had anything to stand on until this one existed. It is what `uniform_paragraph_endings` measures against, and it is also why that rule stays at observe: the shape it names runs commoner in human literature than in model prose.

All three corpora rebuild byte for byte. See `evals/README.md`.

## How it works

Every tool call goes through `hooks/pre_tool.py`, which dispatches to the write, Bash, commit, or MCP gate. One process owns the permission result.

Claude Code calls a hook twice around a tool: PreToolUse before the call runs, PostToolUse after it returns. The gate scans a pending write on PreToolUse, before execution. On PostToolUse it rescans the file on disk and can block continuation, and it never mutates the file. The commit gate scans a message in place and never rewrites it.

The scanner uses one region extractor for mixed-language files. Markup, attributes, embedded style, embedded script, fenced code, and visible prose keep their original host line numbers.

The meaning layer, the judged gate, and the document reader all run on the async PostToolUse route, so none of them delays a write. That route wakes the session afterwards with what it found, and the document reader also leaves a blocker the Stop hook reports. That feedback arrives about 10 seconds after a prose write and costs up to five judge calls. The write itself waits for none of it.

A session scratchpad is exempt from that route. A file under a `scratchpad` directory in the system temp root gets the deterministic scan and no judge call, because throwaway working notes are not worth the tokens.

The scanner reads every prose extension it knows on that route, not markdown alone. Before 0.18.7 it accepted `.md` and nothing else, so an HTML or text document never reached the meaning layer. It also masks markup before splitting sentences. The meaning layer used to embed style attributes as if they were prose.

## Comment policy

Comments run through the same scan, and they are the one surface where the watcher is stricter than it is on prose.

Code comments and docstrings may contain one strict WHY line of at most 60 characters. WHAT narration, weak reasons, consecutive prose comments, and multi-line docstrings block. Config, exemptions, and model output cannot release these rules.

The opening clause decides it. A comment that opens on the code and its behaviour fails even when a `because` clause follows, in the verb-first form and the subject-first form alike. Both `Returns the cached row because callers need stable identity` and `The reader returns the cached row because callers need stable identity` block. `Callers need stable identity, because a fresh read renumbers every row` passes. Lead with the decision, the constraint, or the measurement, and put anything longer on a wiki page.

These rules carry no measurement yet. The prose rules have 60000 human sentences behind them, and the comment rules have nothing equivalent, so the 60-character cap and the opening-clause test are a judgement rather than a number.

## Install

### Claude Code

```text
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

### Codex

`install.sh` wires Codex from this checkout, preserves any existing
`~/.codex/hooks.json`, and provisions an ADW-owned virtual environment with
the pinned `openai-codex==0.147.0` runtime. Luna reviews use the Codex
ChatGPT subscription only. Log in through Codex's browser or device-code
flow before using model review. There is no API-key fallback.

```bash
./install.sh
./install.sh -y
./install.sh --no-claude --codex -y
```

### OMP (`oh-my-pi`)

`pi/install.sh` symlinks the extension into `~/.omp/agent/extensions/agent-discipline-watcher` and registers `pi/extensions/agent-discipline-watcher/index.ts` in `~/.omp/agent/settings.json`.

```bash
./install.sh                      # Claude + Codex + OMP
./install.sh --omp -y             # OMP only
./pi/install.sh -y                # OMP only (direct)
./pi/install.sh --remove -y       # uninstall OMP extension
```

Set `PI_CODING_AGENT_DIR` to target a non-default OMP agent directory. Restart OMP after install, or pass `--extension` to load immediately.

## Requirements

A Unix shell and the Python named in `.python-version`, which is the one place the floor is declared. `hooks/run.sh` probes each `python` on PATH and runs the first that meets that floor, so a system `python3` too old to import this codebase is skipped rather than trusted. When nothing on PATH qualifies, every hook exits 2 and names the version it needs, because a watcher that silently stops enforcing is worse than one that refuses to start.

Claude native presets are selected with `/agent-discipline-watcher:adw-judge
mixed|luna|haiku|sonnet|status`. `mixed` uses Haiku for comments and Sonnet
for prose and document Stop reviews. `luna` uses the subscription-backed
Codex runtime and switches to `mixed` only after Luna is unavailable. Remote
Claude sessions select Haiku by default. Desktop and Cowork have no reliable
hook marker, so set `ADW_CLAUDE_HAIKU_ONLY=1` when an explicit Haiku-only
preset is required.

Codex always selects GPT-5.6 Luna at high effort and has no model fallback.
Missing runtime, subscription login, model availability, or provider
transport emits one bounded actionable finding. Run `./install.sh --codex -y`
to repair the runtime, then complete Codex ChatGPT login.

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`, because that block is what reaches the hooks. A shell export only works if you always launch the client from that shell.

```json
{
  "env": {
    "ADW_EMBEDDING_ENABLED": "1"
  }
}
```

### The meaning layer

| variable | effect |
| --- | --- |
| `ADW_EMBEDDING_ENABLED` | Turns the layer on. Off unless set, because a first run provisions about a gigabyte. |
| `ADW_EMBEDDING_DISABLED` | Turns it off. Wins over the enable. |
| `ADW_EMBEDDING_URL` | Use one embedding server of your own instead of the supervised one. |
| `ADW_EMBEDDING_URLS` | A comma separated list, tried in order. The first that answers wins. |
| `ADW_EMBEDDING_MODEL` | Model name sent in the request body. Defaults to `LFM2.5-Embedding-350M`. |

With none of the URL variables set, the watcher runs its own server on a free port. The platform picks the build, mapping an ARM Mac to MLX and x86 to GGUF. It checks every file against a pinned sha256 before anything runs, and it stops the process by pid when the last session ends.

### Thresholds

| variable | default | effect |
| --- | --- | --- |
| `ADW_SENTENCE_WORD_CAP` | 40 | Fallback sentence cap. Normally the cap is a Tukey upper fence computed from the document's own sentences, so dense prose gets a higher cap than terse prose. This value applies only when a document has too few sentences to measure. |
| `ADW_LIST_ITEM_CAP` | 8 | Items before a list is oversized. |
| `ADW_FUNC_BLOCK_LINES` | 80 | Function length that blocks. |
| `ADW_FILE_BLOCK_LINES` | 1000 | File length that blocks. It warns at 500 and turns critical at 750. |
| `ADW_MAX_SCAN_BYTES` | 1000000 | Files above this are not scanned. |

Each also has a project config key in `.agent-discipline.json`. The config key wins where you set both, and the environment variable is the fallback.

### Escape hatches and internals

| variable | effect |
| --- | --- |
| `ADW_PYTHON` | Interpreter to run the hooks with, skipping the PATH search. It is still probed against `.python-version`, and a build below the floor fails rather than falling back. Set it when the qualifying Python is not on the PATH your client starts with. |
| `ADW_ALLOW_PROTECTED_EDIT` | Permits an edit to the watcher's own install. Self protection blocks a Bash write that sets this inline. |
| `ADW_JUDGE_ACTIVE` | Set by the watcher on the judge subprocess so a nested hook cannot recurse. Not for you to set. |
| `ADW_JUDGE_LIVE` | Set to 1 to run the tests that spend a real model call. Those tests skip otherwise. |
| `CLAUDE_PLUGIN_DATA` | Read no longer. Everything lives under `~/.adw`, so a host data directory cannot split reports away from state. |

The watcher strips `ANTHROPIC_API_KEY` from every judge subprocess. The judge runs on the session login you already pay for, never on a key you did not choose to spend here.

## Where the watcher keeps its files

Everything is under `~/.adw`.

```
~/.adw/state              per session state
~/.adw/ledger             every finding ever recorded
~/.adw/reports            the full report each block points to
~/.adw/embedding-leases   who is holding the model
~/.adw/embedding-server   the model, its runtime, and the running record
~/.adw/cache              exemplar vectors, keyed by exemplar digest
~/.adw/runtime/codex      pinned openai-codex runtime (retained, not pruned)
```

Session state, reports, ledger rows, judge cache entries, and logs older than
30 days are swept at SessionStart. The current session and live lease are
preserved. The persistent Codex runtime and embedding models are outside that
retention sweep.

The watcher migrates an existing `~/.agent-discipline` once, on first run.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root. The hook code searches upward from the working directory. See `hooks/lib/config.py` for supported keys.

Each rule has a gate: `off`, `observe`, `enforce`, or `judged`. Enforce is what the tables above call a block. A rule at observe names the finding without blocking. A rule at judged never reaches the write path at all. Its regex finds candidates, the judge confirms them on the async route, and the watcher reports only what survives. Rules demoted to observe carry the measurement that demoted them, written next to them in `config.py`.

`three_item_list` is the one rule at the judged gate today. Its regex hits 278 of 60000 human sentences, all of them ordinary writing, so the regex alone cannot speak. Behind the judge it clears 121 held-out candidates at 1.0000 precision with 0 false positives. The regex also stopped matching the tail of a four-item list, which cut its raw hits on human prose from 483 to 278.

## Self protection

The `self_protection` family blocks routes around the gates. It covers the watcher's own install directories and a write that strips the watcher's hook entries from a client settings file. It also covers installer commands without a sandboxed `HOME`, no-verify commits, cap overrides, state deletion, and protected configuration edits. No project configuration can disable these rules.

It does not police file access in general. The host's own permission settings own everything else under `~/.claude`, `~/.codex`, `~/.pi`, and `~/.omp`. The watcher judges how an agent writes, not where.

`config_seal` reads the pending content of `.agent-discipline.json` and blocks only a write that would weaken the gates. That means a self-authorization key, a downgraded always-blocking rule, a redirected state or ledger root, or anything silencing every family through `gates`, `kill_switches`, or a tree-wide exemption glob. Narrowing one family or exempting one path stays yours to change. A write whose body the gate cannot read fails closed, and so does deleting or truncating the file.

Seven rules close the Bash write path: `inline_interpreter_write`, `shell_payload_block`, `interpreter_heredoc_write`, `dynamic_heredoc_write`, `decode_pipe_write`, `inplace_edit_write`, and `opaque_source_write`. Each blocks a Bash-mediated write the scanner cannot read through: `python3 -c` writing a file, a heredoc piped into an interpreter, a decode pipe ending in a write, `sed -i`, or `dd`. The scanner reads a literal write body such as a clean `echo` or heredoc, and treats it like a Write or Edit call rather than blocking it.

## Active integrations

Claude Code is the primary plugin surface. Codex support uses the checked-in `hooks/codex-config.snippet.toml` routes for `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`, and `SessionEnd`. The installer merges those routes into `~/.codex/config.toml` without replacing unrelated settings or deleting legacy `~/.codex/hooks.json`. Codex journals completed writes and runs one Luna review at each completed interaction, with SessionEnd releasing the lease.

OMP loads `pi/extensions/agent-discipline-watcher/index.ts`. The extension calls the same `hooks/run.sh` engine. Pre-tool checks run on `tool_call` for `write` and `bash` and return `{ block: true, reason }`. Unresolved findings block on `session_stop`.

`archive/integrations/` keeps the OpenCode adapters as historical references. The installer, CI, and release verification do not test them.

## Verification

```bash
cd hooks && python3 -m pytest . lib -q
python3 -m pytest pi/test_merge_settings.py -q
bash -n install.sh hooks/run.sh pi/install.sh
bun test pi/extensions/agent-discipline-watcher/index.test.ts
claude plugin validate . --strict
```

`evals/README.md` documents how to rebuild the measurements. The corpora stay gitignored and rebuild byte for byte from their sources. If a Luna review reports a missing package or login, repair the pinned runtime and Codex subscription session instead of setting an API key.
