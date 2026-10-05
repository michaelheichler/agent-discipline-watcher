# Changelog

## 0.25.2 (2026-10-05)

### Fixed

- **The Claude Code model review runs again.** The `haiku`, `mixed`, and `luna-native` presets registered `agent` Stop hooks. Each hook told the agent to run `read_claude_journal.sh`. Agent hooks run in the mode that asks no questions, and no allow rule covered that helper. So the review never ran, and its verdicts disappeared. The `mixed` preset is now a command handler in `hooks/lib/claude_sonnet.py`. It reads the journal itself and makes one `claude -p --model claude-sonnet-5-5` call per Stop. That call has no tools, no MCP servers, and no nested hooks. An empty turn makes no call. If the CLI is missing, times out, or returns no usable verdict, the Stop shows "ADW Sonnet review did not run this turn". The rows then stay queued for the next Stop (T-021).
- **Hash directives match exact tool syntax.** The scanner treated `# eslint-disable` and eight other `#` prefixes as directives. Prose after the prefix escaped every comment rule. `# eslint-disable` had no legitimate use and is gone. The other eight prefixes now pass only in their real tool shapes. The Python ones are `noqa`, `type:`, `pragma`, `ruff:`, and `fmt:`. The Dockerfile ones are `syntax=`, `escape=`, and `check=`. The ADW fence follows the same rule (T-019).

### Removed

- **The `haiku` and `luna-native` presets.** Haiku spent more tokens on wrong verdicts than on usable ones (user decision 2026-10-05). `--model luna` returns HTTP 404 through the Claude CLI, and the `luna` preset already reaches Luna through the Codex runtime. `CLAUDE_HAIKU_MODEL`, `ADW_CLAUDE_HAIKU_ONLY`, and `hooks/read_claude_journal.py` and `.sh` are gone too. A stored retired preset name reads as `mixed` (T-021).

### Changed

- **`mixed` is the default preset.** SessionStart replaces any managed block that registers an agent hook with the `mixed` command. A `luna` block that the user chose stays. `adw-judge` accepts `mixed`, `luna`, and `status` (T-021).
- **The comment corpus covers subject openers.** `hooks/lib/corpus_what_comments.jsonl` grows from 49 to 187 rows. No lexical rule separated narration from a genuine reason better than the current rule on 80 unseen rows, so the rule stays. Three tests pin the subject-opener guard (T-020).

## 0.25.1 (2026-10-05)

### Fixed

- **Tool directives pass the comment rules.** The scanner blocked the required first line `// swift-tools-version`, so an agent failed to write `Package.swift`. `hooks/lib/comment_rules.py` now skips exact directive shapes for Swift, Go, TypeScript, and JavaScript, and a short `// MARK:` heading. Prose after a directive prefix still gets a finding. A `///` doc comment counts from its first word. The JavaScript test case moved from `#` to `//`, because `#` is not a JavaScript comment (T-012).
- **The heredoc action names the next step.** `interpreter_heredoc_write` still blocks. Its action now reads "Save the script with Write or Edit, then run the file." (T-015).

### Changed

- **Comments cap at 80 characters, up from 60.** The 60 cap pushed agents to cut the marker word. The shorter comment then failed as a WHAT comment. The `long_comment` action reads the cap from `COMMENT_CHAR_CAP` (T-013).
- **A consequence clause states WHY.** A comment like "Empty feeders end a batch with a non-zero status, so pages count as success." passes. "so" needs the comma before it. A subject opener that describes the code still blocks. The `what_comment` action lists the accepted markers (T-013).
- **`deferred_work_comment` observes.** A short marker line gives a warning instead of a block (user decision 2026-10-05). The marker line still answers to `long_comment` and `prose_comment_block` (T-013).
- **The contract overrides plugin docstring demands.** The session contract now ranks above plugin and skill guidance. A demand for a docstring on every function does not apply (T-014).

## 0.25.0 (2026-10-02)

### Added

- **German prose gets its own rules.** Prose files and commit messages now run German rules on German paragraphs and English rules on English ones. Code comments keep the English rules. The README section "German prose" describes the behaviour, and `NOTICE` credits the sources.
- **Language per paragraph.** `hooks/lib/prose_language.py` sorts each paragraph into German or English by stop words, with umlauts as a tiebreak. A paragraph under 4 countable words takes the document language and carries a weak mark. `evals/measure_language_detection_short.py` measured accuracy per paragraph length. At the cut of 4, `evals/measure_german_hit_rate.py` counts 122 of 28000 German human sentences that still route to English, against 1989 at the earlier 8. With `data_boundary` enabled, Luna classifies weak paragraphs after the write. ADW caches each verdict under the paragraph hash, so a paragraph costs at most one Luna call. Codex queues the call to the next prompt. The new `prose_languages` policy key defaults to `["en", "de"]`, and `adw-config prose-languages en|de|en,de` sets it.
- **German typography after Duden.** On German lines, the semicolon and colon bans drop. The spaced Gedankenstrich, the Bis-Strich and Streckenstrich, the Ergänzungsstrich, and German quotation marks pass. The em dash stays banned. `dash_cluster` limits Gedankenstrich density per document.
- **German findings speak German.** `hooks/lib/catalog_de.py` gives each rule a German message and action. Rule ids stay English.
- **The German rule catalog.** `hooks/lib/german_rules/` declares the static and SEMANTIC rows of the catalog in `docs/research/2026-09-30-german-style-catalog.md`, minus the rows N-008 leaves out. `hooks/lib/german_document_rules.py` adds the document rules. `hooks/lib/german_readability.py` computes LIX and the first Wiener Sachtextformel, and no rule gates on either yet. The trigger lists follow humanizer-de closely (decision Q13).
- **German SEMANTIC rules go from a trigger to the Luna judge.** The embedding vote admitted about half of all German human sentences, so a German rule now sends every German sentence its trigger matches. A German pattern row reaches Luna with a German rubric under rubric version `adw-rubric-de-v1`. The prompt carries the rule definition and a boundary for stock phrase, foreign word, false agency, and retroactive nuance. Rater agreement rose from kappa 0.52 to 0.67, and a Luna majority settled the rest. `evals/build_pattern_exemplars_de.py` writes the exemplars to `hooks/lib/pattern_exemplars_de.jsonl` and reads the highest Luna run into `hooks/lib/pattern_exemplars_de.json`.
- **German corpora and measurements.** `evals/build_german_corpora.py` rebuilds three gitignored corpora byte for byte. The human side holds 28000 sentences from a 2018 German Wikipedia dump and German Gutenberg books. The AI side holds 21000 sentences from COLING 2025 and German WildChat. The paragraph corpus holds 5414 documents. `evals/german_static_precision.json` holds the labeled precision of every static rule, from Sonnet and Luna labels with Opus deciding splits. `evals/judge_stage_de.json` holds the judged stage of 14 SEMANTIC rules per model id. On `gpt-6-luna` precision rose for 9 of 14 rules over `gpt-5.6-luna`, and the best lower bound rose from 0.55 to 0.64.
- **humanizer-de attribution in each file.** The seven `hooks/lib/german_rules/` modules that adapt humanizer-de trigger lists carry SPDX headers that name Martin Moeller and the license `MIT AND CC-BY-SA-4.0`. `NOTICE` holds the full credit.
- **`de_meta_commentary` blocks.** It holds 40 of 40 under two raters, lower bound 0.9124, so `hooks/lib/german_rules/phrases.py` sets it to enforce.

### Changed

- **German rules report only above 0.70 point precision.** This holds the user's 2026-10-02 decision (N-009). A rule at 0.70 or under goes off. A rule above it observes, and enforce still needs a Wilson lower bound of 0.85. `hooks/lib/german_rules/*.py` sets 31 rules to `state="off"` where `evals/german_static_precision.json` or `evals/judge_stage_de.json` measured 0.70 precision or under. `hooks/lib/config.py` sets 7 more `rule_gates` entries to `off` for the same reason. `banned_dash` and `spaced_hyphen` keep their family default, because the decision covers German rules, not these two English ones. `spaced_hyphen` clears the enforce bar on German text at 39 of 40, lower bound 0.8712. `hooks/lib/reporting.py` now drops an off-gated finding from inherited debt too, so an old hit in an edited file stays silent instead of showing as debt to fix. `hooks/lib/test_german_rule_registry.py` adds a test that reads both eval files and checks every measured rule's state against the 0.70 bar, with no rule name fixed in the test.
- **Luna judges run on `gpt-6-luna`.** The Codex runtime pin moves from `openai-codex==0.147.0` to `0.160.0`. The 0.147.0 model list stopped at `gpt-5.6-luna`, so every judge resolved that model. The 0.160.0 list offers `gpt-6-luna` at high effort. The fallback `LUNA_MODEL` moves to `gpt-6-luna` as well. The installer reinstalls the runtime when the pinned requirements file changes, so `./install.sh --codex` upgrades it. The first judge call that misses the cache replaces the remembered `gpt-5.6-luna`.

## 0.24.1 (2026-09-30)

### Changed

- **`/agent-discipline-watcher:adw-nuke --yes` removes ADW and installs it again.** The skill finds a checkout before the removal. It reinstalls the hosts the dry run named, checks the result, and reports. Before, the agent stopped after the removal and told the user to run `./install.sh`. `--uninstall` keeps the removal-only path.

- **`./install.sh` puts `~/.adw/bin` on PATH again.** This reverses the August
  decision in 0.20.2 that only printed the line. The user asked for the reversal on
  2026-09-30, because `adw`, `adw-config`, `adw-judge`, and `adw-nuke` were not
  reachable by name after an install. The old objection was that the user did
  not see the change. The installer now prints the file it edited. The router,
  not a host installer, writes one fenced `# >>> agent-discipline-watcher >>>`
  block into `~/.zshrc` for zsh or `~/.bashrc` for bash, chosen from `$SHELL`.
  Other shells still get the printed line. A second install leaves the file
  byte-identical, and the installer replaces an older block with other content.
  The Claude host installer no longer strips the block. `adw-nuke` still removes it.

### Added

- `./install.sh` builds `~/.adw/cache/principles.sqlite` after the host
  installers, so Code Check findings carry their principle line right after a
  fresh install. The build is best effort. A failed or offline build prints one
  line and the install still exits 0.
- `ADW_OFFLINE=1` skips the network steps of an install, today the principle
  KB download. The test suite sets it through `hooks/install_sandbox.py`, so no
  test run downloads the 60 MB DevIQ archive.

## 0.24.0 (2026-09-30)

### Added

- A third rule family, Code Check, covers test and code quality. `catalog.FAMILIES` names `prose`, `comment`, and `code`. A configuration that names `punctuation` or `english` still selects a `prose` subfamily, and `clean_code` still enables or disables both `comment` and `code` together.
- Nine Code Check test rules live under `hooks/lib/test_rules/`, each with one violating and one clean fixture from the Khorikov catalog. `assert_in_loop` blocks new loops after Luna and Sonnet called 25 of 26 hits bogus under the user's criterion. The other eight rules stay at observe.
- A Code Check finding carries one plain-text principle line from DevIQ or programming-principles, at most 80 words and no URL. The text shows once per rule per session. The lookup reads `~/.adw/cache/principles.sqlite`, built by the update path from pinned commits at `NimblePros/deviq-hugo` and `webpro/programming-principles`. No source text enters this repository, and a test scans the tracked files for it.
- `evals/code_check_precision.json`, `evals/code_check_labels_luna.jsonl`, and `evals/code_check_labels_sonnet_user.jsonl` hold the self-audit measurement on the ADW suite, 131 hand-labeled rows. Luna and Sonnet agree on 120 of 131 hits, Cohen's kappa 0.833.
- `bin/adw-config` gives a small policy CLI, `status`, `tests allow|deny`, `tests allow --for DURATION`, and `family NAME on|off`. An agent that calls the mutating subcommands through a tool call gets a block, because only the user sets policy from a terminal.
- With `tests: deny`, only the `adw-test-writer` subagent adds or changes a test function on Claude Code and on Codex 0.159, through its `agent_type` field. OMP names no agent on tool calls, so `adw-config tests allow --for 30m` opens a timed window there instead. A write to any `adw-test-writer` definition file gets a block, in project scope and user scope.
- The `adw-test-writer` agent ships on three hosts. Claude Code runs it on Opus 5.5 at high effort. Codex runs it on `gpt-6-luna` at high effort. OMP runs it with a model the user picks, through a limited tool set. Each host loads the new `unit-testing-principles` skill. The skill summarizes Khorikov's book in the project's own words, at full depth, one chapter file per book chapter.

### Changed

- Luna resolves to the newest `gpt-N-luna` that the account lists at high effort, instead of the pinned `gpt-5.6-luna` floor. When nothing newer answers, the resolved id becomes the fallback.
- The Claude judge pins move to current snapshot ids. Sonnet moves to `claude-sonnet-5-5`. The `haiku` preset moves from the dated snapshot to `claude-haiku-4-5`, which the API points at the newest Haiku 4.5 snapshot. A scratch test showed the Claude Code hook `model` field rejects a bare alias such as `sonnet` or `haiku`, with a 404 response. The pins therefore stay on full model ids, not aliases.
- A file under `/tmp`, `/private/tmp`, `$TMPDIR`, or `/var/folders` gets no content findings once it sits outside the project root. A `cp`, `mv`, `install`, or `rsync` that lands such a file inside the project still gets the full scan of the destination. Self-protection checks run on every path either way.
- CI runs `bash -n` on every shell script and every `bin/` launcher in a loop. Before, `bash -n $(git ls-files '*.sh')` read only the first file as the script and the rest as its arguments.

### Removed

- The clock rule, `time_as_ambient_context`. Luna and Sonnet called 0 of 17 hits bogus, because a test cannot see whether the production code under test reads the system clock.
- Five test assertions that pinned a constant, a manifest field, a description word, or CI text, and caught no change in behavior.

## 0.23.1 (2026-09-28)

### Fixed

- If `server.json` no longer names the embedding worker, or no supervisor holds `supervisor.lock`, the worker stops itself within about 10 seconds. Before, a worker that the supervisor lost ran until reboot. One such worker held 12 GB.
- A `ps` call that does not answer in time no longer marks the worker as dead. Before, the supervisor then started a second worker and overwrote the record of the first.
- The embedding worker caps the MLX buffer cache at 256 MB and empties it after each request. On a 32-text batch, the worker now stays at 813 MB. Before, it stayed at 4.66 GB.

## 0.23.0 (2026-09-28)

### Changed

- Every model reviewer honors `rule_gates` for pattern rows. A rule the project sets to `observe` reports and never blocks, on Claude Code, Codex, and OMP. The vote skips a rule set to `off`. The shipped default sets `ai_closer` to `observe`. So an upheld `ai_closer` row now reports instead of blocking, unless a project sets it to `enforce`.
- The Claude `luna` preset judges the pattern rows from the embedding vote at Stop, one request per rule with four examples per side. Before, it read document rows only.
- Codex starts the embedding worker in the background at SessionStart and at each prompt. Once the load finishes, a prose write finds a loaded model. A write in the first seconds of a turn still gets no vote.

## 0.22.1 (2026-09-27)

### Fixed

- `adw-nuke` and `adw update` remove a read-only Luna sandbox directory under `~/.adw/runtime`. Before, the first such directory stopped the run with a permission error.

## 0.22.0 (2026-09-27)

### Added

- `adw-nuke --dry-run|--yes` and `/agent-discipline-watcher:adw-nuke` remove every ADW trace from Claude Code, Codex, OMP, and the shell. The whole `~/.adw` tree goes too, so a fresh `./install.sh` starts clean.

### Changed

- The `max_rows` default is 5, the same as the block cap, and the cap lives in one place.
- The batch and record undecidable messages name the config path, through the shared `hookio` text.
- `luna_worker.main` takes `stdin` and `run` as keyword seams. Tests inject fakes through seams instead of patching private names, 285 patches down to 107.
- `claude_native.py` holds no function over 25 lines. `claude_default` reaches it through one public function, `ensure_managed_block`.
- README sentences follow the Simplified Technical English lint, 30 hits down to 0.

### Removed

- The dead document-review state path in `end_turn.py` and `document_review.py`, which had no writer since 0.21.0. The unused `comment_prompt` alias in `claude_native.py`.

## 0.21.0 (2026-09-27)

### Changed

- Model advisors read candidate rows from the session journal instead of whole files. The embedding vote runs on an async PostToolUse route on Claude Code and inline on Codex, and writes each surviving sentence as a pattern row. The Claude Stop reviewer, the OMP provider, and Codex Luna judge those rows with four examples per side per rule. Whole-document review stays opt-in through the `mixed` preset.
- The plugin ships command hooks only. SessionStart writes one Stop reviewer into Claude settings on first run and repoints it after a plugin update. A preset replaces that block. No preset runs a per-write agent any more, and the stand-down check is gone.
- Finding rows show the catalog title, the matched phrase in quotes, and the action, with the rule id last. Blocks number their rows, cap at five, and keep the report path after clipping. Resume, clear, and compact inject one line instead of the full contract.
- When a consumer registers, the embedding model loads. The lease renews on every PostToolUse, and Stop releases the lease without terminating the worker. The server record carries the process start time and a launch nonce, so a reused pid receives no signal and no prompt text.

### Fixed

- Project configuration merges nested maps over the defaults, so one `rule_gates` entry no longer replaces the whole map.
- A `<record-error>` blocker clears once every touched path rescans clean.
- The pre-tool gate denies a Bash payload without a string command before dispatch. Pre-commit scans renamed and non-ASCII staged paths.
- The Python read-only checker accepts `json.load(...).get`, comprehensions, and `import sys`. Denials name the rejected node.
- `passive_voice` no longer treats `read` as a participle, and the scanner masks quoted text before structure and punctuation rules.
- `function_too_long` measures TypeScript and JavaScript functions by brace span.
- The Stop journal filters by turn and applies one 48,000 character budget. Luna comment review covers every language the extractor supports. Codex keeps a review blocker after a Luna timeout, matching OMP. The `data_boundary` switch gates Claude Luna and Codex Luna as well as OMP.
- Commit message checks preserve Conventional Commit prefixes and trailers.
- OMP derives hashline paths from one parser, drops an ambiguous judge quote without a retry, and reports the runner failure reason.

### Removed

- The orphan review CLI (`review.py`, `bm25.py`, `render.py`), the `ADW_FILE_BLOCK_LINES` mapping, and twelve dead symbols.

## 0.20.24 (2026-09-15)

### Fixed

- Binary screenshots and other recognized binary assets no longer receive source-length or unreadable-text findings during commit, post-write, and Stop checks. Text stored under an asset filename still receives its checks, and code, prose, markup, and commit-message enforcement is unchanged.
- Embedding startup retains pending leases and cancels a late worker launch after demand ends. A single supervisor sweeps expired and dead-owner leases across projects, while Stop and SessionEnd release ownership even after embeddings are disabled. Shutdown waits for process exit and preserves the running record on failure.

## 0.20.23 (2026-09-11)

### Fixed

- Restore the release version marker required by the managed updater. Add a check against the repository README and changelog.

## 0.20.22 (2026-09-11, withdrawn)

### Fixed

- Codex matches Claude's supported command-hook coverage, including Bash post-write scans, prompt submission, and subagent lifecycle checks.
- Patch checks measure resulting file length. Bash length checks account for sequential writes, newlines, and literal printf formatting.
- Read-only Python loops, generators, path joins, and trusted ordinary startup no longer receive write findings.
- Codex keeps host turn IDs in the candidate journal. Provider failures produce a user notice and pause retries for five minutes while deterministic checks remain active.
- Confirmed review findings survive provider outages until their source changes. Unrelated edits cannot release them.
- Successful deletions and moves no longer produce missing-file findings. Missing write targets still block and name their paths.
- Reports retain distinct line findings and remove duplicate Stop findings. Codex installation preserves unrelated handlers that share a group with ADW.
- Tests isolate their default report storage from the live ADW profile.

## 0.20.21 (2026-09-11)

### Changed

- OMP allows arbitrary JavaScript eval syntax and tools without a known adapter, including hub. ADW no longer rejects them because it cannot classify their source or tool name.
- Workspace observation scans actual file changes after execution, including failed calls and changes detected at Stop. Known native mutation checks remain.
- Bounded snapshots report incomplete coverage without an unresolved-target blocker. Regression tests cover partial snapshots and preserve findings outside observer coverage.

## 0.20.20 (2026-09-11)

### Fixed

- OMP edit calls without a valid target explain the required native hashline format. Invalid calls do not latch Stop, and valid edits retain their checks.
- The installer preserves its original checkout path when replacing legacy OMP links.
- The managed updater migrates registered legacy OMP wiring after checking ownership and protected paths. It rejects foreign links and retains update rollback.

## 0.20.19 (2026-09-11)

### Fixed

- Claude release updates use the pinned official repository over HTTPS, avoiding an SSH credential requirement for public source.
- The updater repairs stale native commit metadata through a user plugin reinstall that preserves persistent data. Strict release and content checks remain in place.
- Regression tests verify that a failed native reinstall restores the previous cache, registry, and enabled setting in both supported Claude profile locations.

## 0.20.18 (2026-09-11)

### Fixed

- Cursor `.mdc` files use Markdown and YAML frontmatter handling. Glob patterns no longer produce false code-comment findings during post-edit or Stop checks.
- OMP routes the exact `xd://report_issue` destination to its native report handler and preserves its consent prompt.
- Installer preflight rejects a foreign updater link before changing host installations.

### Added

- The installed `adw update` command refreshes selected hosts from the latest published ADW release, verifies the pinned source and host wiring, and restores the previous installation on failure.
- Claude updates verify the enabled user plugin and its content before removing legacy hooks. The updater preserves findings and session state.

## 0.20.17 (2026-09-10)

### Fixed

- OMP code mode accepts literal JavaScript tool-dispatch calls, restoring ordinary commands such as `which -a omp` while preserving nested write checks.
- Unsupported JavaScript eval calls explain the accepted dispatch format. Direct host access and internal bridge methods remain blocked.

## 0.20.16 (2026-09-10)

### Fixed

- Claude native reviewers submit decisions through StructuredOutput, preventing plain JSON responses from exhausting the hook's response attempts.
- Generated Stop prompts preserve the retry exit and place output instructions after the review steps.

## 0.20.15 (2026-09-10)

### Fixed

- Claude native review hooks use supported API model identifiers, preventing HTTP 404 failures from short aliases.
- The preset skill lists the supported Luna native option and removes the unsupported Sonnet preset.

## 0.20.14 (2026-09-10)

### Fixed

- OMP scans explicit external targets and retries unresolved files at Stop, so successful verification clears the affected target.
- Native OMP review uses the authenticated provider and reports complete findings. Mutation checks cover nested edits and MCP operations.
- Codex reviews document and comment batches together. Journal overflow remains visible until source coverage recovers.
- Python reads require trusted startup. Shell parsing preserves quoted payloads and tracks output through compound commands, combined redirects, and here-strings.
- Retention filters report references before resolving paths, preventing startup timeouts on large ledgers.

## 0.20.13 (2026-09-08)

### Fixed

- Partial apply_patch updates now check the resulting file for watcher wiring. Unrelated edits and trust-entry deletions preserve existing hooks.
- Relative patch paths resolve against the tool's working directory, so wiring removal cannot evade the protected-path check.

## 0.20.12 (2026-09-05)

### Changed

- Codex hooks now install in `~/.codex/hooks.json`. The installer removes ADW's old inline hook block from `config.toml` and preserves unrelated hook entries.
- Codex hook merging is idempotent and removes stale watcher entries before reinstalling the current routes.

## 0.20.2 (2026-08-31)

### Changed

- The plugin carries its own semantic reviewer again. `hooks/hooks.json` registers an agent
  handler on PostToolUse and on Stop, so a plain install judges with no preset step. It stays
  off PreToolUse, because a non-conforming reply there reads as a hook error and denies the
  tool call. Commit `d606abc` had removed the last agent handler on 2026-08-13, and two tests
  then asserted its absence, which made the removal read as design.
- The preset roster is `haiku`, `mixed`, `luna`, and `luna-native`. **The `sonnet` preset is
  gone.** A stored `sonnet` preset now reads as `mixed` rather than as no preset at all.
  `luna-native` names the Luna model on a native agent handler. That suits a harness which
  injects Luna into the Claude model list.
- `adw-judge status` counts the reviewers a session carries instead of echoing the stored
  preference, so an unwired gate says so. It reads the installed plugin rather than the
  checkout, because a checkout answers yes on a machine with no install at all.
- **ADW no longer ships a haiku-only model policy.** This release deletes
  `hooks/lib/judge_model.py`. It existed to stop a nested CLI spending the user's Anthropic
  account, and that CLI no longer exists. The same screen sat in config validation, where it
  rejected every model OMP's own catalogue offers, so the Python and TypeScript sides of
  `adw_model` disagreed. The OMP model picker had the matching filter and lost it too.
- **The Claude launcher moved from `~/.local/bin/adw-judge` to `~/.adw/bin/adw-judge`**, and the
  installer no longer appends a PATH block to `.zshrc` or `.bashrc`. It prints the line instead.
  The OMP extension resolves its runner from its own install rather than `~/.agents/skills`.
  Each installer reclaims what an earlier version of itself left behind, and only when the file
  still points at an ADW copy.

### Added

- Rule gates accept a `{surface: state}` map, and findings carry the surface they came from.
  No shipped default changes, so a commit body with a banned adverb still blocks. An untagged
  finding counts as prose, so a rule turned off for prose is off.
- CI runs the floor from `.python-version` plus 3.12 and 3.13 ahead of it, a job for the Bun
  suite that never ran before, and a pylint score assertion. Pylint exits zero on a warning, so
  the previous job called a 9.98 a pass.

### Fixed

- **`claude -p` is gone.** Two spawn sites existed. `judge_provider.complete` served three
  library callers, and `evals/measure_judge_stage.py` carried its own copy. A source-level test
  now fails if either the import or the literal command returns. The route that reached it ran
  from 2026-08-27 to 2026-08-28, so the billing window was about a day, but the code sat one
  manifest line from billing again.
- `pattern_judge.confirm_all` answered an empty mapping both when the judge cleared every
  candidate and when no judge existed, so a judged rule could stop firing with nothing said. It
  now reports which rules went unread and why.
- Nothing ever wrote the candidate journal. A parameter named `journal` shadowed the module it
  came from, so every append raised into a swallowed `except`. The Stop reviewer reads only that
  journal, so it saw an empty candidate list on every turn.

## 0.20.11 (2026-08-30)

### Added

- ADW now builds four host runtimes from one shared core. Each `hosts/<name>/host.json`
  declares that host's adapters, entry scripts, installer, and write surface. `lib/vendor.py`
  writes a runtime and `hooks/build_runtime.py` runs the build. A runtime passes its own tests
  with the other three deleted, and all four produce byte-identical findings on one fixture.
- `install.sh` became a router. It draws an interactive picker, then calls the installer for
  each chosen host. Arrows move, space toggles, Enter installs, and a mouse click selects a
  row. A flag path skips the picker for agents and CI, and `--dry-run` reports without writing.
  Choosing nothing leaves the disk untouched.
- Each host owns its installer under `hosts/<name>/install.sh`. Claude writes the `adw-judge`
  preset CLI, Codex writes its config fence and pinned runtime, and OMP writes its extension.
  A host you do not pick leaves nothing behind.
- The `commands/update.md` runbook clears the Claude plugin cache and reinstalls from a clean
  one. `hooks/claude_cache_nuke.py` performs the wipe. It refuses a symlinked cache, refuses
  any path outside the config root, and never touches `~/.adw`.
- A Claude install now clears the stale plugin cache and reinstalls by default. Set
  `ADW_SKIP_PLUGIN=1` to opt out.

### Fixed

- YAML frontmatter in Markdown no longer trips the punctuation rules. A leading delimited
  block masks out, a colon in the body still blocks, and line numbers stay exact. This
  unblocks every `SKILL.md`, memory file, and static-site page carrying frontmatter.

### Changed

- The shared core no longer names a host. `stop.py` and `session_end.py` imported `codex_luna`
  directly, which made Codex mandatory for every other host. `lib/turn_retry.py` now holds the
  session-state helpers, and `lib/turn_adapter.py` is the single declared seam. A test parses
  every module and refuses a second one.
- Luna keeps its SDK path on both Claude and Codex. Codex hooks parse an `agent` handler and
  then skip it, so the agent-hook shape the other presets use cannot work there.

### Changed

- Installers now copy ADW into `~/.adw/install/agent-discipline-watcher` and point OMP, Codex, Claude legacy wiring, and command links at that isolated copy instead of the development checkout. Installers preserve foreign install directories and symlinks.
- Every judge that reaches the Claude CLI now pins Haiku. `pattern_judge` and `document_review` previously selected Sonnet, and the Claude native presets emitted Sonnet for Stop reviews. A new `hooks/lib/judge_model.py` screens the name, the configure bridge rejects a stronger model, and the OMP picker offers Haiku only. The `luna` preset sits outside that path, since it routes through a command handler on the subscription-backed GPT-5.6 Luna provider. The five precision numbers recorded for the meaning layer came from a Sonnet reader and need re-measuring.
- OMP no longer spawns the Claude CLI. `hooks/lib/host.py` reads the `OMPCODE` marker, and the judge availability gate refuses the CLI under OMP so judging can move to OMP's own models.

## 0.20.0 (2026-08-30)

### Added

- OMP now has an ADW configuration screen through `/adw configure` and `/agent-discipline configure`. Both commands edit the shared `.agent-discipline.json` policy. OMP's `/advisor configure` remains separate and edits `WATCHDOG.yml`.
- The OMP editor now exposes family gates, per-rule gates, thresholds, exemptions, baseline mode, kill switches, data-boundary settings, runtime status, and the selected ADW model. Always-blocking rules stay locked.
- The configuration bridge now exposes bounded `describe`, `read`, `validate`, and guarded `write` operations. Writes preserve unknown keys, use compare-and-swap digests, reject protected weakening, and replace files atomically.

### Changed

- OMP now pre-gates every supported mutating file tool and Bash, rescans trusted post-tool targets, and runs the configured review path without forwarding raw file content.
- Model-backed reviews read only within the project boundary. They use descriptor-based no-follow reads, inode checks, bounded input, and an explicit enabled data boundary.
- The hooks sanitize and bound response text without truncating a complete contract that already fits. Python support remains 3.11 and newer.

### Fixed

- Unresolved mutating OMP results remain blocking even after a later valid result. A new session clears only its own marker.
- SessionStart block reasons now reach the user-visible OMP diagnostic path.
- Structured code comments such as SPDX headers, coding markers, and linter directives no longer trigger the prose-colon rule.
- OMP model selection now reaches the guarded Save request and the review runner.
- The merged branch now passes the project test suite, Bun tests, shell checks, and full Pylint.

### Since 0.18

- Deterministic punctuation, prose, clean-code, slop, and structural gates now cover the main agent output failure modes.
- Semantic and judged routes add model confirmation only where measured precision supports it. Document review adds bounded whole-document coherence checks.
- Claude Code has native judging presets. Codex has synchronized lifecycle hooks, subscription-backed Luna reviews, active-session leases, retention cleanup, and crash-safe retry state.
- Bash workarounds, protected-file edits, path aliases, symlink escapes, malformed payloads, oversized responses, and untrusted review text now have explicit blocking or bounded failure behavior.
## 0.19.1 (2026-08-29)
### Fixed

- Luna comment reviews now cover supported comment-bearing source files beyond Python, reuse the shared Bash target extractor, report state failures instead of returning a clean-looking empty response, and remain safe when launched with an exported `CDPATH`.
- Added regression coverage for TypeScript comments, literal Bash write targets, Luna state failures, launcher path resolution, and Python 3.11 test compatibility.


## 0.19.0 (2026-08-29)

### Added

- Native Claude Code judging presets: `/agent-discipline-watcher:adw-judge mixed|luna|haiku|sonnet|status`. `mixed` keeps Haiku on comment checks and Sonnet on prose and document reviews. `luna` routes both roles through the subscription-backed Codex Luna judge. Remote Claude sessions default to Haiku, and Desktop or Cowork can opt into the explicit Haiku-only setting.
- Codex synchronization for `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`, and `SessionEnd`. Codex always uses GPT-5.6 Luna at high effort through the official `openai-codex` subscription runtime, with one review per completed interaction and no API-key or model fallback.
- Active-session leases and retention sweeps for state, journals, findings, reports, caches, and logs. The sweeps protect live sessions and runtime/model directories while removing stale orphan JSON and cache artifacts.

### Changed

- The hooks bound and deduplicate response text, model feedback, journals, and review inputs so repeated hooks do not inflate the orchestration context. The cache reuses content-hash entries for 30 days and writes them through crash-safe state transitions.
- Installers provision the ADW-owned Codex runtime and merge only the managed Codex hook block, preserving unrelated user configuration. The Claude Code marketplace and plugin commands handle Claude installation.

### Fixed

- Claude and Codex review retries now preserve the failed turn identity, reclaim expired reservations, and clear retry state after a successful review or session end. Stop and SessionEnd output stays bounded even when a provider or state store fails.
- Luna comment reviews now cover supported comment-bearing source files beyond Python, reuse the shared Bash target extractor, report state failures instead of returning a clean-looking empty response, and remain safe when launched with an exported `CDPATH`.

## 0.18.9 (2026-08-28)

### Fixed

- A parent session could not stop while a subagent held a blocker. The Stop hook aggregated every blocker scope in the session, so it handed the findings of an agent that owned the file to an orchestrator that had edited nothing. That orchestrator could not clear them, and the hook blocked until the nine-block cap overrode the turn. Each turn now gates on its own scope, and a subagent answers for what it wrote at its own SubagentStop, where the owner can fix it.
- Dropping the inherited blockers would have left the parent blind, so it still hears the count. When a subagent ends with findings left, the parent Stop returns one line per agent naming how many and which files, as a user-visible system message that costs the model nothing and fires once before the scope clears.
- The two-round cap on document readings never advanced past one. The reader took its round count before a call that runs for tens of seconds and wrote the increment back after, so every reading a burst of edits started read the same count and none of them saw another's. Nothing limited how often the watcher could read one document, each pass returned a different set of style notes, and the agent that kept fixing them never reached the round where the reader stands down. The reader now spends the round under the lock before the call starts, so an empty reading costs one too. The cap counts readings per changed document rather than readings that produced notes.
- A document note outlived the document it quoted. The reader stores line anchors and quoted sentences from one reading, and nothing voided them when the file changed underneath. An agent that restructured a file kept receiving the original four notes against positions that no longer held that text. The Stop hook now compares the file against the digest the reader saw, and drops the blocker when they differ.

## 0.18.8 (2026-08-28)

### Changed

- A `because` clause no longer rescues a comment that opens on the code. The opening clause decides it, which is the standard the judge prompt has always stated and the deterministic rule never enforced. `Returns the cached row because callers need stable identity` blocks. So does its subject-first twin, `The reader returns the cached row because callers need stable identity`, which is the form that walked past the opener test for a whole release. `Callers need stable identity, because a fresh read renumbers every row` passes.
- Comments cap at 60 characters, down from 150. Anything longer belongs on a wiki page.
- `assumes`, `requires` and `guarantees` stopped counting as reasons. They open a contract, not a justification, and every opener exception went with them.
- On this repository the tightened rules report 239 findings across 69 of 147 files. The character cap accounts for 148 findings. Narrating docstrings account for 75, and narrating comments for 16.

### Added

- A session scratchpad skips every model-backed route. A file under a `scratchpad` directory in the system temp root gets the deterministic scan and no judge call. Both conditions have to hold, since the directory name alone would exempt a real project folder and the temp root alone would exempt every test fixture.

### Fixed

- A document blocker outlived the file it named. Its key never appears in the touched-path list by design, so deleting the file left the Stop hook blocking on a path that no longer existed. The key now dies with the file.
- The 0.18.6 entry claimed a Python 3.11 floor. That release shipped 3.14, and lowering the floor in 0.18.7 is what rewrote the older entry. Released history reads as it shipped again.
- The README counted two layers while describing three, and used one word for both the pattern judge and the document reader.

## 0.18.7 (2026-08-28)

### Added

- A document reader. When an agent finishes a prose file, `hooks/lib/document_review.py` sends the whole document to Sonnet and asks for coherence and style problems a line rule cannot see. An order that hides the argument, a missing bridge between paragraphs, a referent the document uses before introducing it, a paragraph shape repeated until it reads as a tic. Each note quotes its sentence and cites its line. The note lands as a pending blocker, so the Stop hook returns the agent to work instead of handing over an unread draft. The watcher skips a document unchanged since its last reading, and after two rounds it stands down and leaves the call to you.
- `uniform_paragraph_endings`, the one rhythm pattern from the source rules that had no implementation. A paragraph ends punchily when its last sentence runs shorter than 0.7018 of the paragraph's own mean, which is the p25 of 30700 human endings. A document trips the rule above two thirds, the p95 of 4570 human documents. It ships at observe, because the shape runs commoner in human literature (4.92 percent) than in assistant replies (0.55 percent) and says nothing about who wrote a document.
- A paragraph corpus. `evals/build_paragraph_corpus.py` draws 9256 documents that still carry their paragraph breaks, 5000 human from `wikimedia/wikipedia` and `sedthh/gutenberg_english` and 4256 assistant from the two chat sets. Both sentence corpora flatten a document to one line, which is why no paragraph rule had anything to stand on before. `evals/measure_paragraph_endings.py` writes `paragraph_endings.json`.
- The `judged` gate. A rule there never reaches the write path. Its regex finds candidates, a reader confirms them on the async route, and the watcher reports only survivors. `evals/measure_regex_judge.py` scores the pair as one stage into `regex_judge.json`.

### Changed

- `three_item_list` moved from off to the judged gate. It had sat off since a 0.0000 precision reading, which measured the regex alone. Behind the reader it clears 121 held-out candidates at 1.0000 precision with 0 false positives and 0.5422 recall.
- The reader behind the meaning layer and the judged gate is Sonnet, not Haiku. Haiku blocked two ordinary technical sentences as `ai_closer` on two of four runs over one document, where Sonnet cleared the same document four times out of four. Re-measurement after the reader gave `ai_closer` and `utilize` 1.0000. It gave `inflated_diction` 0.9595 with recall up from 0.7067 to 0.9467, `vague_quantity` 0.9406, and `business_jargon` 0.8507. All five stay above the 0.85 floor and keep their block.
- The interpreter floor dropped from 3.14 to 3.11, the oldest release carrying `tomllib` and `dataclass(slots=True)`. A hard 3.14 floor turned every hook into an exit 2 on any machine without that build.

### Fixed

- `three_item_list` matched the tail of a four-item list, so ordinary writing read as slop. Its human hit rate fell from 483 to 278 of 60000 sentences.
- The async review route accepted `.md` and nothing else, so an HTML, text or reStructuredText document never reached the meaning layer at all. It now reads every prose extension the scanner knows.
- The meaning layer split sentences out of raw file text. On an HTML document it embedded doctype lines and style attributes as if they were prose and glued each real sentence to the tag that followed it. It masks markup first now, the same way the regex scan does.
- The self-protection check compared an edit's own fragment against the whole-file wiring signature, so every unrelated edit to a client settings file read as a removal of the watcher's hooks. The check sees the applied result now.
- The meaning layer ran whenever an embedding server happened to answer and ignored `ADW_EMBEDDING_ENABLED`. Only the lease honoured that switch.
- No paragraph rule could see an HTML document, because a rendered block leaves no blank line behind and the splitter looked for one. `low_sentence_variance` and `uniform_paragraph_endings` now treat one block element as one paragraph in markup. A block spanning several source lines still splits, which is the cost of keeping the host line numbers.

## 0.18.6 (2026-08-27)

### Fixed

- Every hook except `SessionStart` crashed on a machine whose only `python3` was the macOS system build. `hooks/run.sh` hardcoded `PYTHON=python3` and checked only that the name resolved, so it accepted a 3.9 interpreter that then died importing `enum.StrEnum`. Claude Code reported "failed with non-blocking status code" on `PreToolUse`, `PostToolUse` and `PostToolBatch` while the contract still loaded. The watcher went on announcing rules it had stopped enforcing. `run.sh` now probes every candidate on PATH and runs the first that meets the floor.
- An exported `CDPATH` corrupted the paths `run.sh` derives from its own location, because `cd` echoes the directory when it resolves one through `CDPATH`. `run.sh` unsets it before resolving anything.

### Changed

- The interpreter floor is Python 3.14, declared once in `.python-version`. `run.sh`, `.pylintrc` and the CI workflow all read that file, and `hooks/test_run_dispatch.py` fails when any of them drifts from it.
- A missing or too-old interpreter now exits 2 and names the version it needs. Failing loudly beats a watcher that loads its contract and enforces nothing.

### Added

- `ADW_PYTHON` names the interpreter to run the hooks with, for a qualifying build that is not on the PATH the client starts with. `run.sh` probes it against the same floor and rejects a build below it without falling back.

## 0.18.5 (2026-08-27)

### Added

- The watcher reads meaning, not only exact words. `hooks/lib/pattern_semantic.py` embeds each prose sentence, votes it against one pattern's own violating and clean neighbours, and sends the survivors to Haiku. Haiku decides whether the sentence instantiates the named pattern. A rule reports only where the pipeline has measurements, and blocks only where the measurement reached 0.85 precision. `ai_closer` and `utilize` measured 1.0000, `vague_quantity` 0.9519, `inflated_diction` 0.9381, `business_jargon` 0.9344.
- `hooks/lib/pattern_judge.py`, a judge for any named pattern. It receives the rule, the fix the rule asks for, and real examples of both sides, and returns one verdict per sentence. An absent judge confirms nothing, a skipped index reads as clean, and no candidates costs no call. Rules run in parallel because one call each in series cost a file scan 228 seconds.
- `hooks/lib/pattern_exemplars.jsonl`, 2099 real sentences over 27 rules with their source recorded, drawn only from the development split so a later measurement stays honest. Caching their vectors under the exemplar digest took a warm scan from 40 seconds to 11.
- A human baseline the rules never had. `evals/build_human_corpus.py` draws 60000 sentences from news, encyclopedia and pre-1930 books, and `evals/measure_human_hit_rate.py` scores every rule against prose no model wrote. The AI tell rules fire on 1 sentence in 20000 or fewer there, and `passive_voice` fires on 1 in 4.
- An assistant corpus. `evals/build_ai_corpus.py` draws 88148 sentences from `allenai/WildChat-4.8M` and `lmarena-ai/arena-human-preference-100k` across 69 models. Rules that name an AI tell fire zero times on human prose, so measurements needed this corpus to supply a violating class.
- `evals/build_pattern_benchmark.py` and `evals/qualify_embeddings.py`. The clean side is drawn half from human prose and half from assistant replies, because a human-only clean side lets provenance stand in for the pattern. 27 rules reach the row count where 15 did before.

### Changed

- The long sentence finding no longer asks for fragments. It said "Split it into shorter sentences", which is the instruction that produced the fragmentation the other rules then punished. It now says to cut a clause or break at one clause boundary.
- Every watcher path lives under `~/.adw`. State, ledger, reports, leases, models and caches share one root. The watcher migrates an existing `~/.agent-discipline` once, and a host-supplied data directory no longer splits reports away from the rest.
- ADW provisions the embedding runtime. `hooks/lib/model_artifacts.py` resolves the platform to its own build, `hooks/lib/model_store.py` downloads and verifies it by pinned sha256, and `hooks/lib/embedding_server.py` starts it on a free port and stops it by pid. The hard-coded host addresses are gone.
- The turn bracket is opt-in behind `ADW_EMBEDDING_ENABLED`.

### Fixed

- `process_alive` treated a killed child as running, because a zombie answers a signal probe. Unload reported success while the process was still there.
- The test suite could provision a model into the user's home and leave servers running. Every test now points at a temporary root and cannot start or stop a real one.

## 0.18.0 (2026-08-27)

### Added

- The scanner detects all 98 stop-slop patterns. `hooks/lib/slop_phrase.py` carries the weighted marker and formulaic phrase rules, `hooks/lib/slop_structure.py` carries the ten structural categories, and `prose_structure.py` gained the rhythm statistics. Coverage was 6 of 98 before this release.
- A judgement layer for the comments the deterministic rules cannot decide. `hooks/lib/narration_candidates.py` selects lines that open on a behaviour verb and still carry a why marker, which is exactly the set `_has_strong_why_marker` lets through today. `hooks/lib/judge.py` sends them to Haiku through the Claude Code session login. It strips `ANTHROPIC_API_KEY` from the subprocess to avoid API-key billing and sets `ADW_JUDGE_ACTIVE` so a nested hook cannot recurse. 22 such lines exist in this repository and the judge calls 21 of them narration.
- `hooks/judge_review.py` on the `JudgeReview` route, registered as a second `PostToolUse` group over `Write|Edit|MultiEdit` with `async` and `asyncRewake`. It returns no permission decision, so it delays no write and weakens no gate. It wakes the session on exit 2 with one line per finding. Every deny-capable route still fails the merge-config async guard.
- `hooks/lib/embedding_client.py` and `hooks/lib/embedding_lease.py`. The client speaks the OpenAI embeddings contract over an ordered host list. The MLX server on a Mac and the GGUF server on an x86 box answer the same call, and the first reachable host wins. An absent server returns None rather than raising. The client retries a 5xx and raises on a 4xx because a wrong model or route is a configuration defect. The lease counts references per session, so the model loads once per machine rather than once per subagent. A dead-pid probe and a 900 second sweep free the lease after a session crashes.
- The hooks load and release the model around each turn. `UserPromptSubmit` takes the session lease and probes the hosts, and `Stop` releases it. The model stays resident while a turn runs, and the last live session unloads it. The probe is one short attempt per host, because a retry ladder inside a prompt hook would stall the turn. The lease records the Claude Code process as its owner rather than the hook's own pid. A hook exits within the second, so the sweeper would mark its lease as dead. `ADW_EMBEDDING_DISABLED` turns the whole bracket off, and an absent server costs the turn nothing.
- Verification covered both embedding hosts. The Mac serves `LFM2.5-Embedding-350M-bf16` under MLX on port 8000, and the x86 box serves `LFM2.5-Embedding-350M-Q8_0.gguf` under llama.cpp on port 8014. Its router wakes it on demand at `/embed/v1/embeddings`. Both return 1024 dimensions, so the two hosts share one vector space and failover between them is sound. Each server binds loopback, so clients reach a remote host through a locally forwarded port, and the release embeds no address.
- `hooks/lib/slop_exemplars.jsonl`, 86 phrase exemplars rebuilt deterministically from the stop-slop reference files by `evals/build_slop_exemplars.py`. Single-word entries stay in the regex layer, where an exact literal belongs.

### Changed

- `passive_voice` catches irregular participles. Matching `be` plus only an `ed` or `en` suffix missed forms such as `built`, `set`, `read`, and `rebuilt`, which accounted for 10 of 13 real passives in a tracked sample. Detection now covers 13 of 13 with no hit on six active-voice controls.
- The scanner derives the sentence length cap per document from Tukey's upper fence, and `SENTENCE_VARIATION_LIMIT` moved from 0.32 to 0.16, the measured p05 of 709 real paragraphs. The old value sat near the median and flagged 33.85 percent of ordinary writing.
- The scanner masks headings and setext underlines before running the phrase rules. It also masks list-item labels so titles no longer count as prose.

### Measured and not shipped

- `hooks/lib/slop_semantic.py` stays unwired, and a test fails if it reaches the scanner. Nearest-exemplar cosine caught at most 1 of 273 regex-confirmed pattern sentences at any cutoff whose hit rate on the other 2393 stayed under 1 percent. A general embedding measures topic and these patterns are topic-free structures, so no threshold separates them. `evals/measure_slop_semantic.py` reproduces the numbers.

## 0.17.8 (2026-08-26)

### Changed

- `config_seal` no longer blocks every edit to an existing `.agent-discipline.json`. It reads the pending content and blocks only a write that would weaken the gates, so adding a path exemption or turning one family off is the human's to make again. A write whose body the gate cannot read still fails closed, and so does a delete or a truncate.

### Fixed

- `grants_escape` missed two ways to silence the watcher through its own config. A `kill_switches` entry for every family reaches the gates through a key the gate map never reads. A tree-wide `exempt_paths` or `exempt_families` glob suppresses every scanned file. The blanket seal was the only check that caught either case. `grants_escape` now detects both directly.

## 0.17.7 (2026-08-26)

### Added

- `hooks/lib/findings.py` holds the finding value objects. The frozen, slotted `Finding` and `Rule` dataclasses validate their own invariants and raise on an empty family, a line below one, an empty action, or an unsupported key. `Outcome` and `VerdictKind` are string enums, so ledger rows still serialize and compare as bare strings for consumers outside the process. Serialization preserves the output and key order.
- `hooks/lib/shell_syntax.py` carries tokenizing, segmentation, pipeline grouping, and interpreter resolution, split out of `hooks/lib/shell_parse.py` along the dependency direction. Write and heredoc detection stay behind, because heredoc bodies and write targets are mutually dependent and separating them would create an import cycle. `shell_parse.py` re-exports every moved name, so existing imports keep resolving.
- `session_state.read_state_strict` and `session_state.update_state_strict`. `advance_turn` now uses the strict path, so a corrupt state file raises instead of silently returning an empty dict and erasing unresolved blockers.
- Parameter objects for the wide hook signatures: `StorageRoots`, `BlockerScope`, `McpRunContext`, `DecisionRecord`, `HeartbeatRecord`, `LedgerInvocation`, `Adjudication`, `ShapedWrite`, and the per-hook run contexts.

### Changed

- Every comment and docstring in non-test source now states why the code is the way it is, or is gone. That closed 70 `what_docstring`, 2 `what_comment`, and 2 `prose_comment_block` findings in the watcher's own source.
- Guard clauses and named helpers remove deep nesting from 18 non-test functions, including the parsers behind the write and opaque-write gates, while preserving behaviour.
- Every non-test library function declares its return type.
- Prose findings fixed in `README.md`, `CHANGELOG.md`, `tasks/plan.md`, and `tasks/spec-bash-write-guard.md`.

### Removed

- A duplicate command line interface in `hooks/lib/reporting.py`. `_main`, `_observe_report_command`, and `_adjudicate_command` were unreachable, nothing invoked `python3 -m lib.reporting`, and `bin/agent-discipline` already exposes all three commands.

### Known remaining

- 11 functions still take four or more parameters. Two cannot change shape because behavioural tests call them positionally, `pre_commit.run` and `scan_input.int_setting`. Review found no benefit from a parameter object for the rest.
- Two `long_sentence` findings in `LICENSE`. The MIT text is verbatim and rewording it would change its legal meaning, so it needs an `exempt_families` entry rather than an edit.
- `hooks/batch.py` and `hooks/lib/scanner.py` carry a file length warning.

## 0.17.6 (2026-08-26)

### Changed

- Self-protection no longer polices file access across a client home. Two narrower rules replace `live_client_surface`, which blocked every path under `~/.claude`, `~/.codex`, `~/.pi`, `~/.omp`, `~/.agents/skills`, and `~/.config/opencode`. `watcher_install_surface` blocks writes to the watcher's own install directories and to `~/.local/bin/agent-discipline*`. `watcher_wiring_removal` blocks a write to a client settings file only when it drops the watcher's hook entries, so unrelated edits to those files now pass. Which files an agent may touch is a host permission setting, not a watcher rule. The watcher no longer protects `~/.claude/CLAUDE.md` or shell rc files.
- The install block message states that `ADW_ALLOW_PROTECTED_EDIT` releases every self-protection rule rather than presenting it as a routine escape.

### Fixed

- A read argument in a shell segment is no longer treated as a write target. `python3 ~/.claude/plugins/x/audit.py doc.md > report.json` blocked because the redirect made every path in the segment count as a write, which stopped agents from running audit scripts that live under a client home. Shell write targets now resolve through the same verb-aware rules the live-path check already used, so a copy source, a grep root, and a script argument stay reads.

## 0.17.5 (2026-08-24)

### Fixed

- `pi/install.sh --remove` no longer deletes a real directory or a symlink owned by another install at `~/.omp/agent/extensions/agent-discipline-watcher`. Removal now matches the Claude legacy-link guard. It only removes a symlink pointing to this installation.

## 0.17.4 (2026-08-24)

### Added

- OMP (`oh-my-pi`) gains an `ExtensionAPI` extension at `pi/extensions/agent-discipline-watcher/`. It calls the same `hooks/run.sh` engine as Claude Code and Codex. It gates `write`/`bash` on `tool_call`, rescans touched files on `tool_result` (including hashline `[path#TAG]` and `MV` destinations), injects the SessionStart contract on the next turn, and blocks unresolved findings on `session_stop`.
- The dedicated OMP installer at `pi/install.sh` symlinks the extension into `~/.omp/agent/extensions/agent-discipline-watcher`, registers it in `settings.json` via `pi/merge-settings.py`, supports `--remove`, and honors `PI_CODING_AGENT_DIR`.
- Main `install.sh` gains `--omp` / `--no-omp` flags and delegates OMP wiring to `pi/install.sh`. Selective installs (`--claude`, `--codex`, `--omp`) no longer touch the other harnesses.
- Installer tests for OMP target isolation, idempotent registration, and profile-aware agent directories.

### Fixed

- `hooks/lib/protected.py` now treats `~/.omp` as a protected client home alongside `.codex` and `.pi`, so agents cannot disable the watcher by editing OMP's live config.
- OMP `session_stop` accepts both `stop_hook_active` and `stopHookActive` for retry-pass state.
- OMP `PostToolUse` payloads send only `{ file_path }` for resolved paths, while bash keeps `{ command }` for write-path detection. Raw write content and hashline patch text are no longer forwarded.

## 0.17.3 (2026-08-23)

### Fixed

- A shell script with a `case`/`test` glob pattern like `"$root"/*)` or `== */*` no longer gets its whole tail treated as one unterminated comment. The block-comment scanner opens on any literal slash-star and, finding no matching star-slash closer in the script, used to fall back to end-of-file, turning every remaining line into one giant narrating comment block and flagging ordinary code as prose. Block-comment scanning is now skipped for `.sh`, `.bash`, `.zsh`, and `.ksh` files. `#`-style comment blocks in those files are still caught exactly as before.

## 0.17.2 (2026-08-23)

### Fixed

- `python3 -c`, `node -e`, and similar inline payloads no longer block on a read-only `open()`. The 0.17.1 rule flagged every `open(` call regardless of mode, treating `open("x.txt").read()` and `open("x.txt", "r")` the same as a write. The check now reads the mode argument. A missing mode (Python defaults to `'r'`) or a literal made only of `r`, `b`, `t`, or `U` clears the call. A write-capable literal (`w`, `a`, `x`, `+`), a mode built at runtime, or an unterminated call still blocks exactly as before.

## 0.17.1 (2026-08-20)

Agents were sneaking file writes past the watcher by going through Bash instead of the Write and Edit tools. This release closes those routes.

### Added

- Seven new blocking rules that no project config can turn off.

  Code the watcher cannot read before it runs:
  - Inline interpreter code that can write files, like `python -c`, `node -e`, or `php -r` with a write call inside. Harmless one-liners like `python3 -c 'print(1)'` still work.
  - Scripts fed into an interpreter through a heredoc or a pipe, like `python3 <<EOF` or `echo "..." | sh`. The watcher checks content piped into a shell as if you had run it directly.
  - Nested shells, meaning `sh -c` and quoted commands passed through `env -S`. The watcher unwraps and checks them all the way down.

  Content that reaches a file without passing a readable stage:
  - Heredocs aimed at a file whose content the watcher cannot read, for example when the body contains variables that only expand at run time.
  - Decode pipes that land bytes in a file, like `base64 -d`, `openssl enc -d -out`, or `uudecode`. Decoding to the screen stays allowed.
  - Opaque copy sources like `dd of=` and process substitution.

  Edits that bypass the Edit tool:
  - In-place editors, meaning `sed -i` in all its spellings, `perl -pi`, and `awk` or `gawk` with the inplace extension. Plain `sed` and `awk` transforms to the screen stay allowed.
- Regular Bash writes now get the same treatment as the Write and Edit tools. Overwriting a committed file reports old debt without blocking you for it. Appending only checks the lines you add, and the watcher blocks appends that push a file past the length limit.
- Every block message names the rule and tells the agent to use the Write or Edit tool instead.

### Fixed

- The watcher now catches previously missed spellings. It recognizes quoted or versioned interpreter names (`'python3'`, `python3.12`) and fused flags (`bash -lc`, `sed -Ei`). It also recognizes wrappers like `sudo` and `env` in front of the command, and redirects placed before the command. The checks reach interpreters in the middle of a pipeline and write calls split across adjacent quoted strings.
- Fewer false alarms: `sed -fi` (a script file, not in-place), `xxd -r -o 16` (an offset, not an output file), `gawk -i somelib` (a library, not in-place), and appending to a file without a trailing newline no longer miscounts the file length.

### Notes

- The tests document the remaining gaps for the next hardening pass. They cover echoing an expanded variable into a file and `curl` piped into `tee`, plus `python3 -m module` runs and stream transforms into a new file.
- Setting `ADW_ALLOW_PROTECTED_EDIT=1` in your own shell still releases all of these rules.

## 0.17.0 (2026-08-18)

### Fixed

- Narrowed `config.record_state_transitions` to catch only `(OSError, json.JSONDecodeError)`
  instead of a broad exception handler, and made a ledger write failure block the turn
  as undecidable instead of silently swallowing the error.
- Made `record.run` fail closed (block) instead of returning an empty response when
  `session_state.update_state` or `update_state_strict` raises on a write failure.
- Named the parse error and path on stderr when parsing `.agent-discipline.json` fails,
  instead of falling back to defaults without any signal.
- Included the exit code and stderr detail in the `gitnexus` probe's degraded-state
  message instead of a bare "error" string.
- Fixed a non-atomic write in `merge-claude-settings.py` by reusing the same
  write-to-temp-then-rename pattern already used in `merge-codex-config.py`.
- Unified the two divergent trust predicates in `prompt_submit.py` (`prompt_firewall_mode`
  and `data_boundary`) so both checks consistently treat a dict-subclass config
  object as untrusted.
- Removed `hooks/claude-settings.snippet.json`. The Claude settings merge now writes
  its merged JSON directly and atomically instead of merging in a separate snippet file.

### Changed

- Split `hooks/lib/scanner.py` into `hooks/lib/comment_rules.py` and
  `hooks/lib/prose_structure.py`, and moved inline-code and hidden-text stripping
  into `hooks/lib/markup.py`, to keep the scanner module cohesive and avoid an
  import cycle across the split.
- Split shell-command parsing out of `hooks/pre_bash.py` into `hooks/lib/shell_parse.py`.
- Extracted `hooks/lib/canonical.py` and `hooks/lib/mcp_paths.py` from `hooks/batch.py`
  and `hooks/pre_mcp.py`, and consolidated duplicate test fixtures
  (`HostileDict`, `HostileString`, `CollidingKey`, batch test setup helpers) into
  shared `hooks/testing.py` and `hooks/conftest.py` modules.
- Extracted `scripts/eval_scoring.py` out of `scripts/run_evals.py`.
- Deleted the unused `_exact_string_dict` alias from `hooks/pre_mcp.py`.
- Reworked `hooks/lib/config.py` and removed `ALWAYS_ON_RULES`. Added
  `project_config_path()` and split gate/rule state resolution into
  `_gate_state_from` and `_rule_state_from`.

### Tests

- Added `hooks/test_batch_canonical.py`, `hooks/test_batch_correlation.py`, and
  `hooks/test_batch_race.py` to cover the batch module split.
- Added coverage for `gitnexus` degradation states, malformed `.agent-discipline.json`
  diagnostics, and ledger write failures.
- Updated `test_success_state_write_failure_preserves_record_response` in
  `hooks/test_failure.py` to assert the new fail-closed block response instead of
  the old empty-response behavior.

### Verification

- Passed 1,157 tests and 227 subtests after review triage.
- Passed pylint at 10.00/10 on all tracked Python files.
- Ran the repository's own review against itself. This change set introduces
  no blocking findings.
- Triaged 39 automated PR review findings. Reproduced and fixed 32 with
  regression tests. Declined the other 7 with stated reasons.

## 0.16.3 (2026-08-17)

### Fixed

- Named `ADW_ALLOW_PROTECTED_EDIT` in the `live_client_surface` block message, so a
  blocked `.claude/settings*.json` write no longer reads as unconditionally
  unblockable. The override already existed and stays env-var only.
- Masked Python string content before comment scanning, matching existing
  JS and TS behavior. The scanner misread a string literal starting with `//`
  or `/*` after whitespace as a real comment. An unclosed `/*` inside
  a string, such as a glob fixture like `"generated/*"`, made the block comment
  regex swallow the rest of the file, corrupting every line after it.

### Verification

- Passed 1,055 tests and 213 subtests.
- pylint was not available in this environment and was not run.

## 0.16.2 (2026-08-14)

### Fixed

- Updated the Claude `PreToolUse` response to the current documented
  `permissionDecision: "deny"` shape without the deprecated top-level block.
- Enabled `continueOnBlock` for Claude `PostToolUse` hooks in plugin and legacy
  settings, so findings return to the agent for correction instead of ending the turn.
- Kept internal hard-block responses unchanged for tests and non-Claude clients.

### Verification

- Passed 1,026 tests and 212 subtests.
- Passed pylint at 10.00/10 and strict Claude plugin validation.
- Verified in a real Claude Code session. The hook denied the first Write.
  Claude corrected the comment and retried successfully, then completed without user input.

## 0.16.1 (2026-08-13)

### Fixed

- Restored a non-blocking file-length reminder at 500 lines.
- Added a stronger non-blocking file-length reminder at 750 lines.
- Kept the 1000-line source-file limit as an unconditional hard block.
- Made all three tiers survive clean-code switches, rule gates, kill switches,
  path exemptions, committed baselines, byte-scan caps, and staged-blob scans.

### Verification

- Passed 1,022 tests and 212 subtests.
- Passed pylint at 10.00/10 with `hooks/lib/scanner.py` at exactly 1000 lines.
- Verified live `run.sh PreToolUse` responses at 499, 500, 749, 750, 999,
  1000, and 1001 lines.

## 0.16.0 (2026-08-13)

### Changed

- Restored the complete pre-rewrite hard-block behavior while preserving later
  security and mixed-language fixes, along with packaging and pylint fixes.
- Enforced one strict WHY line for code comments and docstrings.
- Made WHAT comments, weak reasons, consecutive prose comments, and multi-line
  docstrings unconditional blockers that config and model output cannot release.
- Restored `Stop` and `SubagentStop` lifecycle routes and turn accounting.

### Fixed

- Removed semantic adjudication and cached release paths from write, post-write,
  and batch enforcement.
- Blocked strict findings in HTML comments and JavaScript block comments.
  Checks also cover malformed Python. Tagged leading comments and vague causal wording block too.
- Preserved JavaScript strings and structured license headers during comment scans.
- Kept Bash post-write scanning aligned across plugin and legacy Claude installs.

### Verification

- Passed 1,016 tests and 212 subtests.
- Passed pylint at 10.00/10 with the unchanged repository-wide command.
- Passed plugin validation, Python compilation, shell syntax, and black-box
  strict-policy probes.

## 0.15.0+shame.2 (2026-08-13)

### Fixed

- Restored the fixed repository-wide pylint gate to 10.00/10 without disabling
  messages, lowering thresholds, narrowing checked files, or pinning an older
  linter.
- Made `hooks/lib` an explicit package and aligned tests with production imports.
- Split scanner input policy and batch CLI tests into focused modules.
- Preserved exact built-in payload type checks without coercion.

### Verification

- Passed pylint at 10.00/10 with the unchanged CI command.
- Passed 1,007 tests and 202 subtests.

## 0.15.0+shame.1 (2026-08-13)

### Changed

- Restored deterministic hard blocking for enforce-mode findings.
- Limited semantic adjudication to ambiguous comment and docstring findings.
- Added content-addressed verdict reuse across write hook phases.
- Capped adjudication below the Claude hook deadline and bounded hook responses.
- Replaced language-specific mixed-file scanning with canonical source regions.
- Kept the existing Codex `PreToolUse` route and `PreCommit` compatibility alias.

### Fixed

- Rejected malformed hook payloads instead of allowing sensitive writes.
- Preserved unconditional blockers during baseline subtraction.
- Excluded script strings from source-comment scans.
- Scanned ANSI-C quoted commit messages containing escaped apostrophes.
- Resolved relative write baselines against the payload working directory.
- Made post-write checks honor releases for ambiguous findings.
- Removed automatic source, post-write, and commit-message mutation.

### Archived

- Moved the OpenCode adapter and its tests to `archive/integrations/opencode/`.
- Moved the Pi extension, tests, and settings merger to `archive/integrations/pi/`.
- Removed OpenCode and Pi from active installation, CI, release, and support claims.

### Removed

- Removed the rewrite engine and its tests.
- Removed embedding-based review and tool-report lifecycle code.
- Removed active Pi settings merge and adapter installation paths.

### Verification

- Passed 1,007 tests and 202 subtests in the main worktree.
- Passed the direct release matrix for deterministic blocks, ambiguous verdicts,
  timeout denial, cache invalidation, mutation protection, response limits, and
  sandboxed Codex routing.
