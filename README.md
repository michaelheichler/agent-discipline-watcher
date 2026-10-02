# Agent Discipline Watcher

Discipline gates for agent output across **Claude Code**, **Codex**, **OMP** (`oh-my-pi`), and **Cowork**. Current release: **0.25.0**.

The watcher reads what an agent writes and names what is wrong with it. Every finding cites one rule and one line, so you can open the file and disagree. It never returns a verdict on a document, and it never answers whether a model wrote something.

## Three layers

**Regex.** 98 patterns run on every write. Because this layer is deterministic and asks no model to release a finding, it is the one that decides the gate.

**Meaning.** Off by default. After each prose write, the watcher embeds every sentence and votes it against one pattern's own violating and clean neighbours. That vote calls no model. Each sentence that survives lands in the session journal as a `pattern` row with its rule, line, and text. A model reviewer judges those rows later. It compares each row with four violating and four clean examples of its rule. This layer catches what the regex misses, because a paraphrase has no literal to match.

**Document.** Opt in on Claude Code through the `mixed` preset. When an agent finishes a prose file, the document reader takes the whole file and names what a line rule cannot see. It names an order that hides the argument and a missing bridge between paragraphs. It also names a referent that the document uses before its introduction, and a paragraph shape repeated until it reads as a tic. Each note quotes the sentence it means and cites its line. The note blocks the Stop, so the agent goes back to work rather than handing you an unread draft. The Stop reviewer reads what the current turn wrote. It reads a file from an earlier turn again only after its content changes. Each path gets two review rounds at most, so a third rewrite goes back to you unread. Codex and OMP review every changed prose file without a preset.

Every rule belongs to one of three families, `prose`, `comment`, and `code`. `prose` splits further into the `punctuation` and `english` subfamilies. The legacy name `clean_code` still works, and it turns both `comment` and `code` on or off together.

A rule speaks only where a measurement covers it, and blocks only where that measurement earned the block.

| rule | precision after the judge | gate |
| --- | --- | --- |
| `ai_closer` | 1.0000 | block |
| `utilize` | 1.0000 | block |
| `inflated_diction` | 0.9595 | block |
| `vague_quantity` | 0.9406 | block |
| `business_jargon` | 0.8507 | block |

22 more rules carry exemplars and no measurement. They stay silent until measured. The precision threshold is 0.85, held in `pattern_semantic.ENFORCE_PRECISION`.

The default Claude CLI judge pins Haiku, because a nested top-tier model bills the account for work that only drives a gate. The `mixed` preset runs the Stop review on Sonnet, and it is the one agent preset that adds the whole-document review. The `luna-native` preset uses Luna through a native agent handler. The `luna` preset sits outside the Claude CLI path, because it routes through a command handler on the subscription-backed GPT-5.6 Luna provider. The five precision numbers above came from a Sonnet reader, so they need re-measuring against Haiku before anyone treats them as current. One earlier run showed Haiku blocking two ordinary sentences as `ai_closer`. Sonnet cleared the same document four times out of four.

## What the rules were measured against

The rules used to have no false-positive denominator. They have one now.

**60000 human sentences** from news, encyclopedia articles, and books published mostly before 1930. No model wrote any of it. A rule that fires there is either doing its job or costing you an edit, and `evals/human_hit_rate.json` records the hit rate per genre.

Among the AI-tell rules, the raw regex candidate rate is at most 1 in 20000 human sentences. Structural rules such as `three_item_list` are outside that rate. Its raw regex fires on 278 of 60000 human sentences before the judge decides which candidates count. `passive_voice` is not an AI tell and carries no such budget. It fires on 1 sentence in 4, and every hit read as a genuine passive.

**88148 assistant sentences** from `allenai/WildChat-4.8M` and `lmarena-ai/arena-human-preference-100k`, across 69 models including GPT-4o, o1, Claude 3.5 Sonnet, Gemini 1.5 Pro and Llama 3.1. Rules that name an AI tell fire zero times on human prose. Without this side, they have no violating class and no measurement can reach them.

**9256 documents that still carry their paragraph breaks**, 5000 human from `wikimedia/wikipedia` and `sedthh/gutenberg_english`, 4256 assistant from the same two chat sets. Both sentence corpora flatten a document to one line, so no paragraph-shaped rule had anything to stand on until this one existed. It is what `uniform_paragraph_endings` measures against, and it is also why that rule stays at observe. The shape it names runs commoner in human literature than in model prose.

All three corpora rebuild byte for byte. See `evals/README.md`.

## How it works

Known mutations go through `hooks/pre_tool.py`, which dispatches to the write, Bash, commit, or MCP gate. One process owns the permission result.

Claude Code calls a hook twice around a tool, PreToolUse before the call runs and PostToolUse after it returns. The gate scans a pending write on PreToolUse, before execution. On PostToolUse it rescans the file on disk and can block continuation, and it never mutates the file. The commit gate scans a message in place and never rewrites it.

Text rules do not apply to binary assets such as screenshots, PDFs, fonts, archives, and audio or video files. The scanner requires both a recognized asset extension and content evidence before skipping one. An image filename alone does not exempt code or text stored under it. Commit checks classify the staged bytes, not the working copy, and PostToolUse and Stop apply the same policy before counting lines. Missing files, unreadable source, unknown file types, SVG markup, prose, and commit messages retain their existing checks.

The scanner uses one region extractor for mixed-language files. Markup, attributes, embedded style, embedded script, fenced code, and visible prose keep their original host line numbers.

The meaning layer runs on the `JudgeReview` route in `hooks/judge_review.py`. The route reads each edited prose file, runs the embedding vote, and writes the surviving sentences to the journal. It prints nothing and returns no decision.

1. Claude Code runs the route as an async PostToolUse hook after each file edit tool. The hook has a 180 second timeout. The write never waits for it.
2. Codex 0.156.1 accepts the `async` field but runs such a hook synchronously. Codex therefore runs the route inline, with a 10 second hook timeout and a 9 second budget inside the route. A cold model takes longer than 9 seconds to load. If the model is already on disk, Codex SessionStart and each Codex prompt start the worker in the background. Neither hook waits for the load or downloads anything. Stop releases the model at the end of each turn, and the next prompt starts it again. The vote then runs inline on a warm worker. A write that lands before the load finishes gets no vote.
3. OMP has no async route. Its `OmpReview` prepare step runs the same vote inline and waits at most 10 seconds for the model.

On Claude Code and Codex, the Stop reviewer judges the rows of the turn. OMP judges them per write in its own review.

Temp files are not project output. The temp roots are `/tmp`, `/private/tmp`, `$TMPDIR`, the Python temp directory, and `/var/folders`. For a file outside the project root, a temp root means no prose, comment, or code findings. The candidate journal, the document reviewers, and the `JudgeReview` route skip it too. A project that lives under a temp root keeps the full scan for its own files. Self-protection checks run on every path. A `cp`, `mv`, `install`, `rsync`, or redirect from a temp file into the project gets the full scan of the destination.

The scanner reads every prose extension it knows, not markdown alone. Before 0.18.7 it accepted `.md` and nothing else, so an HTML or text document never reached the meaning layer. It also masks markup before splitting sentences. The meaning layer used to embed style attributes as prose.

## Comment policy

Comments run through the same scan, and they are the one surface where the watcher is stricter than it is on prose.

Code comments and docstrings can contain one strict WHY line of at most 60 characters. WHAT narration, weak reasons, consecutive prose comments, and multi-line docstrings block. Configuration, exemptions, and model output cannot release these rules.

The Luna comment reviewer covers Python and supported comment-bearing source files. These include TypeScript, JavaScript, Go, Rust, Java, C-family languages, PHP, Ruby, Swift, shell, Vue, and Svelte. The Claude Luna handler and the Codex Stop review read the same set. The reviewer masks strings before extracting comments, so text inside source strings does not become a review candidate. Literal Bash writes use the same edited-path extractor as the deterministic route.

The opening clause decides it. When a comment opens on the code and its behaviour, it fails even with a `because` clause after it. This applies to the verb-first form and the subject-first form alike. Both `Returns the cached row because callers need stable identity` and `The reader returns the cached row because callers need stable identity` block. `Callers need stable identity, because a fresh read renumbers every row` passes. Lead with the decision, the constraint, or the measurement, and put anything longer on a wiki page.

These rules carry no measurement yet. The prose rules have 60000 human sentences behind them, and the comment rules have nothing equivalent. The 60-character cap and the opening-clause test are therefore a judgement rather than a number.

## Code Check and the test writer

The `code` family also runs one static test-quality scan, taken from Vladimir Khorikov's book on unit testing. The scan reads every Python and Rust test function under `hooks/lib/test_rules/`. `assert_in_loop` blocks a test that asserts inside a loop, because the first failing case then hides the rest. Eight sibling rules, such as `hardcoded_name_presence` and `exposing_private_methods_for_testing`, report and do not yet block. `evals/code_check_precision.json` holds the hand-labeled hit count and precision behind each of these rules.

A Code Check finding carries one plain-text explanation of the principle it breaks, pulled from a local DevIQ or programming-principles knowledge base. The text shows once per rule per session, stays under 80 words, and carries no link. A missing database or a missing entry leaves the finding unchanged.

A project can deny test writes outright. With `tests: deny` set through `adw-config`, only the `adw-test-writer` subagent adds or changes a test function. Claude Code and Codex 0.159 identify that subagent through its `agent_type` field on the tool call. OMP names no agent on tool calls, so `adw-config tests allow --for 30m` opens a timed window there instead. A write to any `adw-test-writer` definition file gets a block, in both project and user scope.

`adw-test-writer` ships on three hosts. Claude Code runs it on Opus 5.5 at high effort. Codex runs it on `gpt-6-luna` at high effort. OMP runs it with a model the user picks, through a limited tool set. Each host loads the `unit-testing-principles` skill first. That skill holds a full-depth summary of the Khorikov book in the project's own words, one chapter file per book chapter.

## German prose

German prose gets its own rule set. Prose files and commit messages get the German rules. Code comments keep the English rules.

**Language per paragraph.** `hooks/lib/prose_language.py` sorts each paragraph into German or English by stop words, with umlauts as a tiebreak. A paragraph decides on its own once it has 4 countable words. Code, URLs, and paths do not count. A shorter paragraph takes the document language and carries a weak mark. With `data_boundary` enabled, Luna classifies each weak paragraph after the write, never in the Stop review. Claude Code makes that call on the async `JudgeReview` route. Codex queues the paragraph and classifies it in the background at the next prompt. ADW caches each verdict under the paragraph hash, so a paragraph costs at most one Luna call. With `data_boundary` off, no paragraph goes to Luna, and a weak paragraph keeps the document language.

`adw-config prose-languages en|de|en,de` sets the languages per project. The default is `en,de`. With one language set, every paragraph takes that language and no detection runs.

**Typography after Duden.** A German paragraph drops the English semicolon and colon bans, because German uses both marks as ordinary connectors. These dash and quote forms pass in German.

1. The Gedankenstrich, an en dash (U+2013) with a space on each side.
2. The Bis-Strich and Streckenstrich, an en dash with no spaces between two numbers or two names, as in a year range or a ferry route.
3. The Ergänzungsstrich, a word that ends in a hyphen before `und`, `oder`, or `bis`.
4. German quotation marks, the low-high double pair and the low-high single pair.

The em dash (U+2014) stays banned in German. A spaced ASCII hyphen still reports as `spaced_hyphen`. `dash_cluster` limits Gedankenstrich density. It reports at 5 or more spaced dashes and more than 15 per 1000 German words. It ships off, because its measured precision is 0.15.

**German findings speak German.** A finding on a German line carries a German message and a German action. The rule id stays English, such as `de_meta_commentary` or `spaced_hyphen`, so configuration and reports keep one set of names. The message language also shows which language ADW detected.

**LIX and WSTF.** `hooks/lib/german_readability.py` computes LIX after Björnsson and the first Wiener Sachtextformel after Bamberger and Vanecek, with their published weights. WSTF needs a syllable count. `hooks/lib/german_syllables.py` counts vowel groups and treats `ei`, `ie`, `au`, `eu`, and `äu` as one nucleus. It miscounts 6 of 80 German Wiktionary words, an error rate of 0.075, recorded in `evals/syllable_counter.json`. No rule gates on either score yet.

**German corpora.** The human side holds 28000 sentences, 20000 from a 2018 German Wikipedia dump and 8000 from German Gutenberg books. The AI side holds 21000 sentences, 15000 from the COLING 2025 GenAI detection data and 6000 German WildChat replies. A paragraph corpus keeps 5414 documents with their paragraph breaks. Git ignores all three, and they rebuild byte for byte.

```bash
uvx --python 3.11 --with duckdb --with pyarrow python evals/build_german_corpora.py
```

**Gate policy.** Three bands decide what a German rule does. A Wilson lower bound of 0.85 or more blocks (decision Q23). A point precision above 0.70 reports. A point precision of 0.70 or less turns the rule off (N-009). An unmeasured rule stays at observe. `evals/german_static_precision.json` and `evals/judge_stage_de.json` hold the numbers, and `hooks/lib/test_german_rule_registry.py` checks every measured rule against the 0.70 bar.

Two measured rules block German lines today.

1. `de_meta_commentary` holds 40 of 40, lower bound 0.9124.
2. `spaced_hyphen` holds 39 of 40, lower bound 0.8712.

The punctuation family also applies its family default to German lines. `banned_dash`, `dash_break`, `pronoun_apostrophe`, and `decade_apostrophe` therefore block there as well. `banned_dash` measured 0.15 on German text and still blocks. N-009 keeps the em dash ban and leaves `banned_dash` and `spaced_hyphen` at their family default. The German SEMANTIC rules send trigger matches to Luna. Their best lower bound on `gpt-6-luna` is 0.64, so none of them blocks.

## Install

### Claude Code

```text
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

### Codex

`install.sh` wires Codex from this checkout, copies the watcher into
`~/.adw/install/agent-discipline-watcher`, and provisions an ADW-owned virtual
environment with the pinned `openai-codex==0.160.0` runtime. Client hooks point
to the installed copy, not the development checkout. Luna reviews use the
Codex ChatGPT subscription only. Log in through Codex's browser or device-code
flow before using model review. There is no API-key fallback.

Claude Code defines the deterministic hook coverage. Codex uses the same
shared handlers for SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,
SubagentStart, SubagentStop, Stop, and SessionEnd. The pre-tool handler sees
every tool, and the post-tool handler includes Bash writes. Codex does not
provide Claude's PostToolBatch or PostToolUseFailure events.

```bash
./install.sh
./install.sh -y
./install.sh --codex -y
```

### OMP (`oh-my-pi`)
`pi/install.sh` copies the checkout into
`~/.adw/install/agent-discipline-watcher`, symlinks the extension into
`~/.omp/agent/extensions/agent-discipline-watcher`, and registers the
installed `index.ts` in `~/.omp/agent/settings.json`. The extension resolves
its runner from the installed copy under `~/.adw`, so it needs no link outside
the state directory. An earlier install put one under `~/.agents/skills`.
If that link still points at an ADW copy, the installer removes it. Nothing in
the installed client configuration points into the development checkout.

```text
~/.adw/install/agent-discipline-watcher  installed code
~/.adw/state                             session state
~/.adw/ledger                            finding ledger
~/.adw/reports                           finding reports
~/.adw/cache                             judge and embedding caches
~/.adw/runtime                           provider runtimes
<project>/.agent-discipline.json         project policy
```

```bash
./install.sh                      # Choose hosts interactively
./install.sh --claude --codex --omp
./install.sh --omp -y             # OMP only
./pi/install.sh -y                # OMP only (direct)
./pi/install.sh --remove -y       # uninstall OMP extension
```

Set `PI_CODING_AGENT_DIR` to target a non-default OMP agent directory. Set
`ADW_INSTALL_DIR` to choose a different isolated install root. Restart OMP
after install, or pass `--extension` to load it immediately.

The installer puts `~/.adw/bin` on your PATH. It picks the startup file from
`$SHELL`: zsh gets `~/.zshrc` and bash gets `~/.bashrc`. The line sits in a
fenced `# >>> agent-discipline-watcher >>>` block, and the installer prints
the file it changed. A second install leaves the file as it is. `adw-nuke`
removes the block. For any other shell, the installer prints the line for you
to add.

The installer also builds `~/.adw/cache/principles.sqlite`, the principle text
that Code Check findings quote. It downloads about 60 MB. If the download
fails, the install still succeeds and `adw update` retries. Set
`ADW_OFFLINE=1` to skip the download on an air-gapped machine.

OMP JavaScript execution has no ADW syntax allowlist. JavaScript eval and tools
without a known adapter use workspace observation, so computed calls and `hub`
operations can run. Native Write, Edit, and Bash calls keep their existing checks.

The observer compares regular-file metadata before execution, after success or
failure, and at Stop. It scans concrete changed files through the post-write
pipeline. Actual content findings still receive the normal review. An unknown
tool name or incomplete snapshot does not create an unresolved Stop blocker.

Observation covers the current workspace. It skips symlinks and the `.git`,
`node_modules`, and `.adw` directories, and each snapshot stops after 20,000
entries or 250 ms. An incomplete snapshot produces a notice without rejecting
execution. External paths and transient changes have no coverage guarantee.
Background writes after Stop escape observation, while concurrent edits can
appear in the workspace diff without reliable attribution to the agent.

### Controlled release updates

The top-level installer registers `~/.adw/bin/adw`. Its `update` command
installs the latest published release from the official ADW repository for
the hosts you select. It accepts no alternate repository, checkout, or
installation directory. It uses the account's default directories and
preserves session state and all recorded findings.

```bash
~/.adw/bin/adw update --claude --codex --omp --dry-run
~/.adw/bin/adw update --claude --codex --omp
```

Use an absolute path in agent tool calls. For example,
`/Users/yourname/.adw/bin/adw update --omp` lets the guard check the
installed executable and host flags before permitting the update.
Arbitrary installer scripts still require a Terminal install.
The updater requires the default installation directory.

The updater selects an existing Claude profile under `~/.claude` or
`~/.config/claude-code`. If both exist, run the installer from Terminal with
`CLAUDE_CONFIG_DIR` set to the selected profile.
It requires a supported Python in the system executable directories and
ignores `ADW_PYTHON`. Custom interpreters remain an installer option.

Install the first release containing the updater from Terminal. An older
installed guard cannot authorize the new command. Restart the selected agent
hosts after updating so they load the new hooks and extension.

### Full removal

The Claude installer also links `~/.adw/bin/adw-nuke`. It removes every ADW
trace so a fresh `./install.sh` starts clean. In a Claude session,
`/agent-discipline-watcher:adw-nuke --yes` removes ADW and installs it again from a
checkout. `--uninstall` removes it only, and `--dry-run` lists the paths.

```bash
~/.adw/bin/adw-nuke --dry-run
~/.adw/bin/adw-nuke --yes
```

The dry run prints each path that a real run removes or edits, and writes nothing.
Without `--yes` the command prints the same list and refuses.

`--yes` removes these, in this order.

1. The Claude plugin and marketplace records, through `claude plugin
   uninstall` and `claude plugin marketplace remove`. If the `claude` binary
   is absent or the call fails, it edits the two JSON files directly.
2. The ADW entries in Claude `settings.json`, `~/.codex/hooks.json`,
   `~/.codex/config.toml`, `~/.omp/agent/settings.json`, `~/.zshrc`, and
   `~/.bashrc`. Every other entry stays as it was.
3. The Claude plugin cache, marketplace, `commands/adw`, and skill link, the
   Codex skill and ADW backup files, the OMP extension and `~/.agents` skill
   links, and the `~/.local/bin` links.
4. The whole `~/.adw` tree, including state, the ledger, reports, caches, the
   embedding model, and runtimes. No flag keeps them.

If a path leaves the home directory, the command stops before any write. The
same stop applies to a symlinked Claude profile and to a foreign link target.
Restart Claude Code, Codex, and OMP afterwards.

In OMP, `/adw configure` and `/agent-discipline configure` open the ADW policy
screen. They edit the project `.agent-discipline.json` policy used by the same
Python hook engine as Claude Code and Codex. OMP's `/advisor configure` is
separate. It edits `WATCHDOG.yml` and controls OMP's reviewer agents.

Cursor `.mdc` rules use the same Markdown scanner and frontmatter handling
as `.md` files. YAML glob patterns do not become code comments. When an agent
edits a rule or finishes a turn, the watcher still checks the Markdown body.

OMP's exact `xd://report_issue` write destination uses the native report
handler and its consent prompt. ADW does not treat that report as a project
file or create a pending file scan for it. Other virtual write paths remain
subject to target validation.

## Requirements

A Unix shell and the Python named in `.python-version`, the one place this project declares the floor. `hooks/run.sh` probes each `python` on PATH and runs the first that meets that floor. It skips a system `python3` too old to import this codebase rather than trusting it. When nothing on PATH qualifies, every hook exits 2 and names the required version. This prevents silent loss of enforcement.

The plugin manifest ships command hooks only. The reviewer lives in
`~/.claude/settings.json` as the managed block, the hook entries whose first
line or command carries the `adw-managed-hook-v1` marker. When a Claude Code
session starts and `settings.json` holds no managed block, the SessionStart hook
writes the `haiku` preset. A plain install needs no preset step. Claude Code
picks up the configuration change without a restart. SessionStart leaves an
existing managed block alone, so a preset you chose or edited stays. When
SessionStart cannot read `settings.json`, it prints one line to stderr and
the session goes on without a reviewer. Select a different preset with
`/agent-discipline-watcher:adw-judge haiku|mixed|luna|luna-native|status`.
Each selection replaces the managed block, so `settings.json` never holds two
reviewer sets.

Each agent preset registers one reviewer, on Stop. No agent runs per write.
The PostToolUse command hook records comment candidates in the journal, and the
async `JudgeReview` route adds pattern candidates. The Stop agent judges both
from those rows. The journal helper prints the rows, and beside them one rule
entry per rule with four violating and four clean examples. The agent judges
every row in one batch against `PATTERN_RUBRIC` and opens no file.

`haiku` runs the Stop review on Haiku. `mixed` runs it on Sonnet.

Among the agent presets, only `mixed` adds the whole-document review. Its Stop
agent passes `--documents` to the helper, which then prints document rows too.

`luna-native` names the Luna model directly. It works where a tool such as LeverFrame injects
Luna into the Claude model list. `luna` emits no native agent at all. It uses a
command handler on the subscription-backed Codex runtime and switches to
`mixed` only after Luna is unavailable. Its Stop handler judges the same
journal rows as the agent presets. It sends one request per pattern rule, with
four violating and four clean examples, beside the document rows. Each upheld
pattern row prints its path, line, rule title, matched text, and action.
Pattern and document rows share one 48,000 character Stop budget.

The Luna routes send source text off the machine. The Claude Luna handler and
the Codex Stop review run only with `data_boundary.enabled` set to `true` in
`.agent-discipline.json`. The OMP review uses the same gate.

`status` counts the reviewers in the managed block rather than echoing the
stored preset, so an unwired gate says so. An agent preset counts one. `luna`
counts two, one command handler on PostToolUse and one on Stop. If an install needs
the explicit Haiku-only environment, set `ADW_CLAUDE_HAIKU_ONLY=1`.

Codex always selects GPT-5.6 Luna at high effort and has no model fallback.
Missing runtime, subscription login, model availability, or provider
transport emits a bounded user notice and pauses provider retries for five
minutes in that session. Deterministic checks remain active. A Luna timeout
or an unusable reply blocks the Stop instead, and each retry reviews again
until one succeeds. ADW records completion only after a successful review. Run `./install.sh --codex -y`
to repair the runtime, then complete Codex ChatGPT login.

After a review upholds a finding, ADW keeps it active until the affected source changes.
An unrelated edit cannot release them during a provider outage.

## Environment variables

Set these in the `env` block of `~/.claude/settings.json`, because that block is what reaches the hooks. If you use a shell export instead, you must always launch the client from that shell.

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

With none of the URL variables set, the watcher runs its own server on a free port. The platform picks the build, mapping an ARM Mac to MLX and x86 to GGUF. It checks every file against a pinned sha256 before anything runs.

Every project shares the managed worker, and it stays loaded while a live turn holds a lease. The `JudgeReview` route takes the lease on the first prose write of a turn. It waits up to 120 seconds for a cold model. Every PostToolUse renews the lease, so a long turn keeps the model. Stop and SessionEnd release that lease. If the user turned embeddings off after loading, they still release it. Shutdown checks that the process exited before removing its record. A single supervisor checks every five seconds for dead owners and leases older than the existing 900-second lifetime. A missed Stop therefore no longer leaves the model resident indefinitely. Cold-start provisioning retains its pending lease and rechecks demand before launching the worker. These lifecycle checks do not change the model or the opt-in requirement.

### Thresholds

| variable | default | effect |
| --- | --- | --- |
| `ADW_SENTENCE_WORD_CAP` | 40 | Fallback sentence cap. Normally the cap is a Tukey upper fence computed from the document's own sentences, so dense prose gets a higher cap than terse prose. Only a document with too few sentences to measure uses this value. |
| `ADW_LIST_ITEM_CAP` | 8 | Items before a list is oversized. |
| `ADW_FUNC_BLOCK_LINES` | 80 | Function length that blocks. |
| `ADW_MAX_SCAN_BYTES` | 1000000 | Full-text scan limit. Larger files retain fallback length checks. |

Each also has a project configuration key in `.agent-discipline.json`. The configuration key wins where you set both, and the environment variable is the fallback.

Code files warn at 500 lines and turn critical at 750.
At 1000, ADW blocks the write.

ADW measures the resulting file after appends or patch moves, regardless of
the size of the diff. The legacy `ADW_FILE_BLOCK_LINES` and `file_block_lines`
keys do not change these thresholds.

### Escape hatches and internals

| variable | effect |
| --- | --- |
| `ADW_OFFLINE` | Set to 1 to skip the network steps of `./install.sh`. Today that is the principle KB download. The install still exits 0, and Code Check findings carry no principle line until an online `adw update`. |
| `ADW_PYTHON` | Interpreter to run the hooks with, skipping the PATH search. It is still probed against `.python-version`, and a build below the floor fails rather than falling back. If the qualifying Python is not on the PATH your client starts with, set it. |
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
~/.adw/cache              exemplar vectors, keyed by exemplar digest, and principles.sqlite
~/.adw/runtime/codex      pinned openai-codex runtime (retained, not pruned)
```

Session state, reports, ledger rows, judge cache entries, and logs older than
30 days are swept at SessionStart. The current session and live lease are
preserved. The persistent Codex runtime and embedding models are outside that
retention sweep.

The watcher migrates an existing `~/.agent-discipline` once, on first run.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root. The hook code searches upward from the working directory. See `hooks/lib/config.py` for supported keys.

`bin/adw-config` reads and writes that file from a terminal. `adw-config status` prints the effective policy.

`adw-config tests allow` or `adw-config tests deny` sets the test write policy. `adw-config tests allow --for 30m` opens a timed window instead of a permanent change.

`adw-config prose-languages en,de` sets the prose languages ADW detects per paragraph. The default is both. `adw-config prose-languages en` switches German off, so every paragraph runs the English rules.

`adw-config family NAME on|off` toggles one family. An agent that calls a mutating subcommand through a tool call gets a block. Only the user sets policy from a terminal.

Each rule has a gate: `off`, `observe`, `enforce`, or `judged`. Enforce is what the tables above call a block. A rule at observe names the finding without blocking. A rule at judged never reaches the write path at all. Its regex finds candidates and a judge checks them before the watcher reports anything. Today only the OMP review route runs that judge. Rules demoted to observe carry the measurement that demoted them, written next to them in `config.py`.
The same gate covers reviewed pattern rows from the embedding vote on every host. A rule at off gets no pattern rows. A rule at observe never blocks on an upheld row. OMP and Codex report the row. The Claude Stop reviewer can only pass or block, so it never sees the row. The shipped default sets `ai_closer` to observe, so an upheld `ai_closer` row reports unless the project sets that rule to enforce.
In OMP, `/adw configure` and `/agent-discipline configure` edit this project policy through the same Python configuration engine. The screen covers family gates, per-rule gates, thresholds, exemptions, baseline mode, kill switches, and the data boundary. Always-blocking rules stay locked. Unknown keys and environment values are not rendered.

`three_item_list` is the one rule at the judged gate today. Its regex hits 278 of 60000 human sentences, all of them ordinary writing, so the regex alone cannot speak. Its precision behind the judge has no measurement yet. `pattern_exemplars.json` records no judge precision for it, so no number here backs a block. The regex also stopped matching the tail of a four-item list, which cut its raw hits on human prose from 483 to 278.

## Self protection

The `self_protection` family blocks routes around the gates. It covers the watcher's own install directories and a write that strips the watcher's hook entries from a client configuration file. It also covers installer commands without a sandboxed `HOME`, `--no-verify` commits, cap overrides, state deletion, and protected configuration edits. No project configuration can disable these rules.

It does not police file access in general. The host's own permission configuration owns everything else under `~/.claude`, `~/.codex`, `~/.pi`, and `~/.omp`. The watcher judges how an agent writes, not where.

The Python read checker accepts loops, generators, path joins, and text
processing. If the checker trusts the import paths, it permits ordinary
Python startup. Writes and executable startup overrides retain their
checks. Unknown calls must pass the read checker.

`config_seal` reads the pending content of `.agent-discipline.json` and blocks only a write that weakens the gates. That means a self-authorization key, a downgraded always-blocking rule, or a redirected state or ledger root. It also means anything silencing every family through `gates`, `kill_switches`, or a tree-wide exemption glob. Narrowing one family or exempting one path stays yours to change. A write whose body the gate cannot read fails closed, and so does deleting or truncating the file.

Seven rules close the Bash write path: `inline_interpreter_write`, `shell_payload_block`, `interpreter_heredoc_write`, `dynamic_heredoc_write`, `decode_pipe_write`, `inplace_edit_write`, and `opaque_source_write`. Each blocks a Bash-mediated write the scanner cannot read through. Examples are `python3 -c` writing a file, a heredoc piped into an interpreter, a decode pipe ending in a write, `sed -i`, and `dd`. The scanner reads a literal write body such as a clean `echo` or heredoc. It treats that write like a Write or Edit call rather than blocking it.

For read-only Python snippets in Bash, use isolated startup with `python3 -I -S`.
For example, `python3 -I -S -c 'from pathlib import Path; print(Path("notes.md").read_text())'`
reads a file without loading project startup modules. ADW rejects redirects that
write opaque Python output to a file. Use Write or Edit for content changes.

## Active integrations

Claude Code is the primary plugin surface. Codex support uses the checked-in `hooks/codex-hooks.json` routes for `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`, and `SessionEnd`. The installer removes the old watcher entries from `~/.codex/config.toml`, then merges them into `~/.codex/hooks.json` without replacing unrelated configuration or hooks. Codex journals completed writes and runs one Luna review at each completed interaction, with SessionEnd releasing the lease.

OMP loads `pi/extensions/agent-discipline-watcher/index.ts`. The extension calls the same `hooks/run.sh` engine. Pre-tool checks cover every OMP mutating file tool and Bash, then return `{ block: true, reason }`. Unresolved findings block on `session_stop`.

`archive/integrations/` keeps the OpenCode adapters as historical references. The installer, CI, and release verification do not test them.

## Verification

```bash
cd hooks && uvx --python 3.11 --with pytest pytest . lib -q
python3 -m pytest pi/test_merge_settings.py -q
for script in $(git ls-files '*.sh') bin/adw bin/adw-judge bin/adw-nuke bin/adw-config; do bash -n "$script"; done
bun test pi/extensions/agent-discipline-watcher/index.test.ts
claude plugin validate . --strict
```

`evals/README.md` documents how to rebuild the measurements. The corpora stay gitignored and rebuild byte for byte from their sources. If a Luna review reports a missing package or login, repair the pinned runtime and Codex subscription session instead of setting an API key.
