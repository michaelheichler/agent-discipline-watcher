# Changelog

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
- On this repository the tightened rules report 239 findings across 69 of 147 files: 148 over the character cap, 75 narrating docstrings, 16 narrating comments.

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
- The reader behind the meaning layer and the judged gate is Sonnet, not Haiku. Haiku blocked two ordinary technical sentences as `ai_closer` on two of four runs over one document, where Sonnet cleared the same document four times out of four. Re-measured after the reader: `ai_closer` and `utilize` 1.0000, `inflated_diction` 0.9595 with recall up from 0.7067 to 0.9467, `vague_quantity` 0.9406, `business_jargon` 0.8507. All five stay above the 0.85 floor and keep their block.
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

- Every hook except `SessionStart` crashed on a machine whose only `python3` was the macOS system build. `hooks/run.sh` hardcoded `PYTHON=python3` and checked only that the name resolved, so a 3.9 interpreter was accepted and then died importing `enum.StrEnum`. Claude Code reported "failed with non-blocking status code" on `PreToolUse`, `PostToolUse` and `PostToolBatch` while the contract still loaded, so the watcher went on announcing rules it had stopped enforcing. `run.sh` now probes every candidate on PATH and runs the first that meets the floor.
- An exported `CDPATH` corrupted the paths `run.sh` derives from its own location, because `cd` echoes the directory when it resolves one through `CDPATH`. `run.sh` unsets it before resolving anything.

### Changed

- The interpreter floor is Python 3.14, declared once in `.python-version`. `run.sh`, `.pylintrc` and the CI workflow all read that file, and `hooks/test_run_dispatch.py` fails when any of them drifts from it.
- A missing or too-old interpreter now exits 2 and names the version it needs. Failing loudly beats a watcher that loads its contract and enforces nothing.

### Added

- `ADW_PYTHON` names the interpreter to run the hooks with, for a qualifying build that is not on the PATH the client starts with. It is probed against the same floor, and one below it fails rather than falling back.

## 0.18.5 (2026-08-27)

### Added

- The watcher reads meaning, not only exact words. `hooks/lib/pattern_semantic.py` embeds each prose sentence, votes it against one pattern's own violating and clean neighbours, and sends the survivors to Haiku, which decides whether the sentence instantiates the named pattern. A rule speaks only where that pipeline has been measured, and blocks only where the measurement reached 0.85 precision. `ai_closer` and `utilize` measured 1.0000, `vague_quantity` 0.9519, `inflated_diction` 0.9381, `business_jargon` 0.9344.
- `hooks/lib/pattern_judge.py`, a judge for any named pattern. It receives the rule, the fix the rule asks for, and real examples of both sides, and returns one verdict per sentence. An absent judge confirms nothing, a skipped index reads as clean, and no candidates costs no call. Rules run in parallel because one call each in series cost a file scan 228 seconds.
- `hooks/lib/pattern_exemplars.jsonl`, 2099 real sentences over 27 rules with their source recorded, drawn only from the development split so a later measurement stays honest. Their vectors are cached under the exemplar digest, which took a warm scan from 40 seconds to 11.
- A human baseline the rules never had. `evals/build_human_corpus.py` draws 60000 sentences from news, encyclopedia and pre-1930 books, and `evals/measure_human_hit_rate.py` scores every rule against prose no model wrote. The AI tell rules fire on 1 sentence in 20000 or fewer there, and `passive_voice` fires on 1 in 4.
- An assistant corpus. `evals/build_ai_corpus.py` draws 88148 sentences from `allenai/WildChat-4.8M` and `lmarena-ai/arena-human-preference-100k` across 69 models. Rules that name an AI tell fire zero times on human prose, so without this side they had no violating class and could not be measured at all.
- `evals/build_pattern_benchmark.py` and `evals/qualify_embeddings.py`. The clean side is drawn half from human prose and half from assistant replies, because a human-only clean side lets provenance stand in for the pattern. 27 rules reach the row count where 15 did before.

### Changed

- The long sentence finding no longer asks for fragments. It said "Split it into shorter sentences", which is the instruction that produced the fragmentation the other rules then punished. It now says to cut a clause or break at one clause boundary.
- Every watcher path lives under `~/.adw`. State, ledger, reports, leases, models and caches share one root, an existing `~/.agent-discipline` is migrated once, and a host-supplied data directory no longer splits reports away from the rest.
- The embedding runtime is provisioned rather than assumed. `hooks/lib/model_artifacts.py` resolves the platform to its own build, `hooks/lib/model_store.py` downloads and verifies it by pinned sha256, and `hooks/lib/embedding_server.py` starts it on a free port and stops it by pid. The hard-coded host addresses are gone.
- The turn bracket is opt-in behind `ADW_EMBEDDING_ENABLED`.

### Fixed

- `process_alive` treated a killed child as running, because a zombie answers a signal probe. Unload reported success while the process was still there.
- The test suite could provision a model into the user's home and leave servers running. Every test now points at a temporary root and cannot start or stop a real one.

## 0.18.0 (2026-08-27)

### Added

- The 98 stop-slop patterns are detected. `hooks/lib/slop_phrase.py` carries the weighted marker and formulaic phrase rules, `hooks/lib/slop_structure.py` carries the ten structural categories, and `prose_structure.py` gained the rhythm statistics. Coverage was 6 of 98 before this release.
- A judgement layer for the comments the deterministic rules cannot decide. `hooks/lib/narration_candidates.py` selects lines that open on a behaviour verb and still carry a why marker, which is exactly the set `_has_strong_why_marker` lets through today. `hooks/lib/judge.py` sends them to Haiku through the Claude Code session login, with `ANTHROPIC_API_KEY` stripped from the subprocess so no key is spent, and `ADW_JUDGE_ACTIVE` set so a nested hook cannot recurse. 22 such lines exist in this repository and the judge calls 21 of them narration.
- `hooks/judge_review.py` on the `JudgeReview` route, registered as a second `PostToolUse` group over `Write|Edit|MultiEdit` with `async` and `asyncRewake`. It returns no permission decision, so it delays no write and weakens no gate. It wakes the session on exit 2 with one line per finding. Every deny-capable route still fails the merge-config async guard.
- `hooks/lib/embedding_client.py` and `hooks/lib/embedding_lease.py`. The client speaks the OpenAI embeddings contract over an ordered host list, so the MLX server on a Mac and the GGUF server on an x86 box answer the same call and the first reachable host wins. An absent server returns None rather than raising, a 5xx is retried, and a 4xx raises because a wrong model or route is a configuration defect. The lease is refcounted per session, so the model loads once per machine rather than once per subagent, and a crashed session frees it through a dead-pid probe and a 900 second sweep.
- The model is loaded and released around each turn. `UserPromptSubmit` takes the session lease and probes the hosts, and `Stop` releases it, so the model is resident while a turn runs and the last live session unloads it. The probe is one short attempt per host, because a retry ladder inside a prompt hook would stall the turn. The lease records the Claude Code process as its owner rather than the hook's own pid, since a hook exits within the second and its lease would be swept as dead. `ADW_EMBEDDING_DISABLED` turns the whole bracket off, and an absent server costs the turn nothing.
- Both embedding hosts are verified. The Mac serves `LFM2.5-Embedding-350M-bf16` under MLX on port 8000, and the x86 box serves `LFM2.5-Embedding-350M-Q8_0.gguf` under llama.cpp on port 8014, woken on demand by its router at `/embed/v1/embeddings`. Both return 1024 dimensions, so the two hosts share one vector space and failover between them is sound. Each server binds loopback, so a remote host is reached through a locally forwarded port and no address is baked into the release.
- `hooks/lib/slop_exemplars.jsonl`, 86 phrase exemplars rebuilt deterministically from the stop-slop reference files by `evals/build_slop_exemplars.py`. Single-word entries stay in the regex layer, where an exact literal belongs.

### Changed

- `passive_voice` catches the irregular participles. `be` plus an `ed` or `en` suffix is blind to `was built`, `is set`, `is read` and `was rebuilt`, which carried 10 of 13 real passives in a tracked sample. Detection is now 13 of 13 with no hit on six active-voice controls.
- The sentence length cap is derived per document from Tukey's upper fence rather than fixed, and `SENTENCE_VARIATION_LIMIT` moved from 0.32 to 0.16, the measured p05 of 709 real paragraphs. The old value sat near the median and flagged 33.85 percent of ordinary writing.
- Headings, setext underlines, and list-item labels are masked before the phrase rules run, so a title is no longer scanned as prose.

### Measured and not shipped

- `hooks/lib/slop_semantic.py` stays unwired, and a test fails if it reaches the scanner. Nearest-exemplar cosine caught at most 1 of 273 regex-confirmed pattern sentences at any cutoff whose hit rate on the other 2393 stayed under 1 percent. A general embedding measures topic and these patterns are topic-free structures, so no threshold separates them. `evals/measure_slop_semantic.py` reproduces the numbers.

## 0.17.8 (2026-08-26)

### Changed

- `config_seal` no longer blocks every edit to an existing `.agent-discipline.json`. It reads the pending content and blocks only a write that would weaken the gates, so adding a path exemption or turning one family off is the human's to make again. A write whose body the gate cannot read still fails closed, and so does a delete or a truncate.

### Fixed

- `grants_escape` missed two ways to silence the watcher through its own config. A `kill_switches` entry for every family reaches the gates through a key the gate map never reads, and a tree-wide `exempt_paths` or `exempt_families` glob suppresses every scanned file. Both were caught only by the blanket seal, so both are now detected on their own terms.

## 0.17.7 (2026-08-26)

### Added

- `hooks/lib/findings.py` holds the finding value objects. `Finding` and `Rule` are frozen slotted dataclasses that validate their own invariants and raise on an empty family, a line below one, an empty action, or an unsupported key. `Outcome` and `VerdictKind` are string enums, so ledger rows still serialize and compare as bare strings for consumers outside the process. Serialized output is unchanged, key order included.
- `hooks/lib/shell_syntax.py` carries tokenizing, segmentation, pipeline grouping, and interpreter resolution, split out of `hooks/lib/shell_parse.py` along the dependency direction. Write and heredoc detection stay behind, because heredoc bodies and write targets are mutually dependent and separating them would create an import cycle. `shell_parse.py` re-exports every moved name, so existing imports keep resolving.
- `session_state.read_state_strict` and `session_state.update_state_strict`. `advance_turn` now uses the strict path, so a corrupt state file raises instead of silently returning an empty dict and erasing unresolved blockers.
- Parameter objects for the wide hook signatures: `StorageRoots`, `BlockerScope`, `McpRunContext`, `DecisionRecord`, `HeartbeatRecord`, `LedgerInvocation`, `Adjudication`, `ShapedWrite`, and the per-hook run contexts.

### Changed

- Every comment and docstring in non-test source now states why the code is the way it is, or is gone. That closed 70 `what_docstring`, 2 `what_comment`, and 2 `prose_comment_block` findings in the watcher's own source.
- Deep nesting is gone from non-test source. 18 functions were flattened with guard clauses and named helpers, including the parsers behind the write and opaque-write gates, with behaviour held identical.
- Return types are declared on every non-test library function.
- Prose findings fixed in `README.md`, `CHANGELOG.md`, `tasks/plan.md`, and `tasks/spec-bash-write-guard.md`.

### Removed

- A duplicate command line interface in `hooks/lib/reporting.py`. `_main`, `_observe_report_command`, and `_adjudicate_command` were unreachable, nothing invoked `python3 -m lib.reporting`, and `bin/agent-discipline` already exposes all three commands.

### Known remaining

- 11 functions still take four or more parameters. Two cannot change shape because behavioural tests call them positionally, `pre_commit.run` and `scan_input.int_setting`. The rest are judged not to improve from a parameter object.
- Two `long_sentence` findings in `LICENSE`. The MIT text is verbatim and rewording it would change its legal meaning, so it needs an `exempt_families` entry rather than an edit.
- `hooks/batch.py` and `hooks/lib/scanner.py` carry a file length warning.

## 0.17.6 (2026-08-26)

### Changed

- Self-protection no longer polices file access across a client home. The `live_client_surface` rule, which blocked every path under `~/.claude`, `~/.codex`, `~/.pi`, `~/.omp`, `~/.agents/skills`, and `~/.config/opencode`, is replaced by two narrower rules. `watcher_install_surface` blocks writes to the watcher's own install directories and to `~/.local/bin/agent-discipline*`. `watcher_wiring_removal` blocks a write to a client settings file only when it drops the watcher's hook entries, so unrelated edits to those files now pass. Which files an agent may touch is a host permission setting, not a watcher rule. `~/.claude/CLAUDE.md` and shell rc files are no longer protected.
- The install block message states that `ADW_ALLOW_PROTECTED_EDIT` releases every self-protection rule rather than presenting it as a routine escape.

### Fixed

- A read argument in a shell segment is no longer treated as a write target. `python3 ~/.claude/plugins/x/audit.py doc.md > report.json` blocked because the redirect made every path in the segment count as a write, which stopped agents from running audit scripts that live under a client home. Shell write targets now resolve through the same verb-aware rules the live-path check already used, so a copy source, a grep root, and a script argument stay reads.

## 0.17.5 (2026-08-24)

### Fixed

- `pi/install.sh --remove` no longer deletes a real directory or a symlink owned by another install at `~/.omp/agent/extensions/agent-discipline-watcher`. Removal now matches the Claude legacy-link guard: only unlink when the path is our own symlink target.

## 0.17.4 (2026-08-24)

### Added

- OMP (`oh-my-pi`) support: `pi/extensions/agent-discipline-watcher/` is an `ExtensionAPI` extension that calls the same `hooks/run.sh` engine as Claude Code and Codex. It gates `write`/`bash` on `tool_call`, rescans touched files on `tool_result` (including hashline `[path#TAG]` and `MV` destinations), injects the SessionStart contract on the next turn, and blocks unresolved findings on `session_stop`.
- Dedicated OMP installer at `pi/install.sh`: symlinks the extension into `~/.omp/agent/extensions/agent-discipline-watcher`, registers it in `settings.json` via `pi/merge-settings.py`, supports `--remove`, and honors `PI_CODING_AGENT_DIR`.
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

- `python3 -c`, `node -e`, and similar inline payloads no longer block on a read-only `open()`. The 0.17.1 rule flagged every `open(` call regardless of mode, so `open("x.txt").read()` and `open("x.txt", "r")` were treated the same as a write. The check now reads the mode argument: a missing mode (Python defaults to `'r'`), a literal made only of `r`, `b`, `t`, or `U`, clears the call. A write-capable literal (`w`, `a`, `x`, `+`), a mode built at runtime, or an unterminated call still blocks exactly as before.

## 0.17.1 (2026-08-20)

Agents were sneaking file writes past the watcher by going through Bash instead of the Write and Edit tools. This release closes those routes.

### Added

- Seven new blocking rules that no project config can turn off.

  Code the watcher cannot read before it runs:
  - Inline interpreter code that can write files, like `python -c`, `node -e`, or `php -r` with a write call inside. Harmless one-liners like `python3 -c 'print(1)'` still work.
  - Scripts fed into an interpreter through a heredoc or a pipe, like `python3 <<EOF` or `echo "..." | sh`. Content piped into a shell is checked as if you had run it directly.
  - Nested shells, meaning `sh -c` and quoted commands passed through `env -S`, which are unwrapped and checked all the way down.

  Content that reaches a file without passing a readable stage:
  - Heredocs aimed at a file whose content the watcher cannot read, for example when the body contains variables that only expand at run time.
  - Decode pipes that land bytes in a file, like `base64 -d`, `openssl enc -d -out`, or `uudecode`. Decoding to the screen stays allowed.
  - Opaque copy sources like `dd of=` and process substitution.

  Edits that bypass the Edit tool:
  - In-place editors, meaning `sed -i` in all its spellings, `perl -pi`, and `awk` or `gawk` with the inplace extension. Plain `sed` and `awk` transforms to the screen stay allowed.
- Regular Bash writes now get the same treatment as the Write and Edit tools. Overwriting a committed file reports old debt without blocking you for it. Appending only checks the lines you add, and appends that push a file past the length limit are blocked.
- Every block message names the rule and tells the agent to use the Write or Edit tool instead.

### Fixed

- Many trick spellings that used to slip through are now caught: quoted or versioned interpreter names (`'python3'`, `python3.12`), fused flags (`bash -lc`, `sed -Ei`), wrappers like `sudo` and `env` in front of the command, redirects placed before the command, interpreters in the middle of a pipeline, and write calls split across adjacent quoted strings.
- Fewer false alarms: `sed -fi` (a script file, not in-place), `xxd -r -o 16` (an offset, not an output file), `gawk -i somelib` (a library, not in-place), and appending to a file without a trailing newline no longer miscounts the file length.

### Notes

- Known remaining gaps are written down in the test suite so the next hardening pass starts from an honest list: echoing an expanded variable into a file, `curl` piped into `tee`, `python3 -m module` runs, and stream transforms into a new file.
- The human escape hatch is unchanged: setting `ADW_ALLOW_PROTECTED_EDIT=1` in your own shell releases all of these rules.

## 0.17.0 (2026-08-18)

### Fixed

- Narrowed `config.record_state_transitions` to catch only `(OSError, json.JSONDecodeError)`
  instead of a broad exception handler, and made a ledger write failure block the turn
  as undecidable instead of silently swallowing the error.
- Made `record.run` fail closed (block) instead of returning an empty response when
  `session_state.update_state` or `update_state_strict` raises on a write failure.
- Named the parse error and path on stderr when `.agent-discipline.json` is malformed,
  instead of falling back to defaults without any signal.
- Included the exit code and stderr detail in the `gitnexus` probe's degraded-state
  message instead of a bare "error" string.
- Fixed a non-atomic write in `merge-claude-settings.py` by reusing the same
  write-to-temp-then-rename pattern already used in `merge-codex-config.py`.
- Unified the two divergent trust predicates in `prompt_submit.py` (`prompt_firewall_mode`
  and `data_boundary`) so a dict-subclass config object is treated as untrusted
  consistently by both checks.
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
- Reworked `hooks/lib/config.py`: removed `ALWAYS_ON_RULES`, added
  `project_config_path()`, and split gate/rule state resolution into
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
- Ran the repository's own review against itself. No blocking findings remain
  that were introduced by this change set.
- Triaged 39 automated PR review findings. 32 were confirmed by reproduction
  and fixed with regression tests, 7 were declined with stated reasons.

## 0.16.3 (2026-08-17)

### Fixed

- Named `ADW_ALLOW_PROTECTED_EDIT` in the `live_client_surface` block message, so a
  blocked `.claude/settings*.json` write no longer reads as unconditionally
  unblockable. The override already existed and stays env-var only.
- Masked Python string content before comment scanning. `.py` files were never
  string-masked the way JS and TS files are. A string literal starting with `//`
  or `/*` after whitespace was misread as a real comment. An unclosed `/*` inside
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
- Verified with a real Claude Code session: the first Write was denied, Claude
  corrected the comment, retried successfully, and completed without user input.

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
  security, mixed-language, packaging, and pylint fixes.
- Enforced one strict WHY line for code comments and docstrings.
- Made WHAT comments, weak reasons, consecutive prose comments, and multi-line
  docstrings unconditional blockers that config and model output cannot release.
- Restored `Stop` and `SubagentStop` lifecycle routes and turn accounting.

### Fixed

- Removed semantic adjudication and cached release paths from write, post-write,
  and batch enforcement.
- Blocked strict findings in HTML comments, JavaScript block comments, malformed
  Python, tagged leading comments, and vague causal wording.
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
- Prevented script strings from being scanned as source comments.
- Scanned ANSI-C quoted commit messages containing escaped apostrophes.
- Resolved relative write baselines against the payload working directory.
- Prevented released ambiguous findings from being blocked again after writing.
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
