# Tickets for the Code Check family

The plan lives in [plan-code-check-2026-09.md](plan-code-check-2026-09.md). The spec lives in [spec-code-check-2026-09.md](spec-code-check-2026-09.md). Each ticket names its module id from the capability map in the spec.

Every ticket shares one set of test commands. Run them before you mark a ticket done.

```bash
cd hooks && uvx --python 3.11 --with pytest pytest . lib -q
pylint $(git ls-files '*.py')
```

## Phase 1. Foundations

### Task 1. Luna resolves to the newest model

Module `model-currency`. Size S. Dependencies none.

Status on 2026-09-30. Done on branch `worktree-agent-a90dea7a2ffb69fff`, commits `6937efa` and `e715395`, not merged. The cache remembers the last resolved model, so reads and writes use the same key.

Luna picks the highest `gpt-N-luna` from `session.models()` that is not hidden and supports high effort. The pinned `LUNA_MODEL` constant becomes the fallback floor.

- [ ] The version order is numeric, so `gpt-6-luna` beats `gpt-5.6-luna` and `gpt-10-luna` beats `gpt-6-luna`
- [ ] `JudgeResult.model` and the judge cache key carry the resolved id
- [ ] The availability error names the models it saw

Files are `hooks/lib/luna_provider.py` and `hooks/lib/test_luna_provider.py`. If the cache key lives in `hooks/lib/luna_storage.py`, that file changes too.

### Task 2. Claude judge model aliases

Module `model-currency`. Size S. Dependencies none.

Status on 2026-09-30. Done on branch `worktree-agent-a870c789f1d3b7c14`, commits `df942d2` and `738ecbd`, not merged. The hook `model` field rejects aliases with a 404. Sonnet moved to `claude-sonnet-5-5`, and Haiku keeps the dateless pointer `claude-haiku-4-5`.

Find out whether a Claude Code agent hook accepts `haiku` and `sonnet` as the `model` value. Run one managed hook with each alias in a scratch project and read the transcript for the model that answered.

- [ ] The result and the transcript evidence sit in `docs/research/2026-09-30-claude-hook-model-alias.md`
- [ ] If the alias works, `claude_presets.py` renders the alias and the managed hook digest changes
- [ ] If the alias fails, the pins move to the newest ids in the Claude Code model list. The ticket records why the alias failed

Files are `hooks/lib/claude_presets.py` and `hooks/lib/test_claude_presets.py`.

### Task 3. Measure one embedding load cycle

Module `embedding-cost`. Size S. Dependencies none.

Status on 2026-09-30. Done on branch `worktree-agent-aa0e656b03c868157`, commit `9d8ca0c`, not merged. One cold load costs 0.8 seconds, 0.85 CPU seconds, and 850 MB RSS on an M5 Pro. The per-turn reload is too cheap to explain the reported load, so Task 4 waits for a session profile.

Measure what one turn costs the Mac today. Each cycle starts the worker cold and embeds 20 sentences before it stops the worker. The script runs three cycles.

- [ ] `evals/embedding_cost.json` records time and memory per cycle, with the machine model
- [ ] The script lives in `evals/` and runs with one command
- [ ] The numbers go to the user before Task 4 merges

### Task 4. Idle timeout for the embedding worker

Module `embedding-cost`. Size M. Dependencies Task 3.

Status on 2026-09-30. On hold. A 30 minute sample from 12:53 to 13:23 found the embedding worker at 0.4 percent CPU on average and 858 MB peak RSS. Four worker pids appeared in that window. Agent test and pylint runs caused the CPU peaks. The window held no normal user session, so the sample proves nothing about the reported load. Release 0.23.1 already stops orphaned workers, and those orphans are the likeliest past cause.

Stop no longer releases the embedding lease. The lease expires after an idle timeout with a default of 600 seconds, set through the ADW configuration.

- [ ] Two turns within the timeout reuse one worker pid
- [ ] The worker exits within 30 seconds after the timeout runs out with no live session
- [ ] SessionEnd still releases the lease at once
- [ ] Task 3 reruns, and `evals/embedding_cost.json` gains the after numbers

Files are `hooks/stop.py`, `hooks/lib/embedding_session.py`, `hooks/lib/embedding_lease.py`, `hooks/lib/config.py`, and their tests.

### Task 5. Split the rule families

Module `rule-families`. Size M. Dependencies none.

Status on 2026-09-30. Done on branch `worktree-agent-a6e6f3ce4516fc8ac`, commits `db8f600` and `432a74a`, not merged. Two gaps remain in the OMP screen. It hides an old `gates.english` override, and the exemption box in `adw-config.ts` rejects the old names.

`catalog.FAMILIES` gains `prose`, `comment`, and `code`. Comment rules emit `comment`. Dead code, hollow tests, function length, and file length emit `code`. `punctuation` and `english` stay as subfamilies of `prose`.

- [ ] A configuration that names `clean_code` enables and disables both `comment` and `code`
- [ ] A configuration that names `punctuation` or `english` keeps working unchanged
- [ ] `pi/extensions/agent-discipline-watcher/adw-bridge.ts` and its tests use the new names, and the parity test passes
- [ ] `configure.py` lists the three families with their descriptions

Files are `hooks/lib/catalog.py`, `hooks/lib/config.py`, `hooks/lib/comment_rules.py`, `hooks/lib/scanner.py`, and `pi/extensions/agent-discipline-watcher/adw-bridge.ts`. The other twelve files from the plan evidence only rename strings.

## Checkpoint A

Status on 2026-09-30. Main holds Tasks 1, 2, 3, and 5 at merge `791051a`. Task 4 stays on hold, because one cold load costs under one CPU second. A 30 minute process sample under `~/.adw/profile/` looks for the real load.

- [x] Hook suite, pylint, and `bun test` pass. The merged state ran 3081 tests, pylint 10.00/10, and 208 bun tests
- [x] The user reviews the embedding numbers

## Phase 2. Static test rules and explanations

### Task 6. Test function extraction and the self-audit runner

Module `test-audit-static`. Size S. Dependencies Task 5.

One extractor yields each test function with its path, name, span, and body for Python and Rust. One runner applies every Code Check rule to a directory and writes a JSON report.

- [x] Python uses `ast`, and Rust uses `brace_functions.py` with the `#[test]` attribute
- [x] The runner on `hooks/` reports the count of test functions. It found 2043 in 147 files on 2026-09-30
- [x] The runner never blocks and never writes outside its report path
- [x] With the `code` family on, the scanner calls one entry point for test files. Rule tickets then never touch `scanner.py`
- [x] Each rule module registers itself in one registry, and a rule without a measurement starts at observe

Files are `hooks/lib/test_units.py`, `hooks/lib/test_rules/__init__.py`, `hooks/lib/scanner.py`, `evals/code_check_audit.py`, and one test file.

Rule module contract for Tasks 7 and 8.
1. Create one new file in `hooks/lib/test_rules/`. Discovery imports it, so no other file needs an import line.
2. Export `RULE_SET = RuleSet(rules=(Rule(name, detail, action), ...), check=check)`.
3. `check(unit, text)` returns `Hit(rule, line, snippet)` rows. The unit is a `test_units.Unit`, and the text is the whole file.
4. Import only from `hooks/lib/test_rules`. The `config` module imports the registry, so an import of `config` or `scanner` creates a cycle.
5. Every registered rule starts at observe through `config.DEFAULTS["rule_gates"]`. Add the wording to `catalog.RULES`, because `test_catalog.py` fails without it.

### Task 7. The two user rules and the loop rule

Module `test-audit-static`. Size M. Dependencies Task 6.

Add `hardcoded_name_presence`, `hardcoded_literal_in_source`, and `assert_in_loop`. Each starts at observe. The Khorikov catalog gives the definition and the fixtures.

Status on 2026-09-30. Done on branch `worktree-agent-ae229f525a232abc5`, not merged. The audit on `hooks/` read 2048 tests. The loop rule hit 104 of them. The two literal rules hit 24 for source text and 13 for names. Rust parsing lives in `test_rules/_rust_literals.py`. Python test files without `def test_` now skip the extractor parse, so the scanner still parses a plain file once.

- [x] The Rust example from the spec yields `assert_in_loop`
- [x] `assert "ai_closer" in RULES` yields `hardcoded_name_presence`, and a test that asserts a computed value against a literal does not
- [x] A test that reads a source file and asserts a literal in its text yields `hardcoded_literal_in_source`

Files are `hooks/lib/test_rules/literals.py`, `hooks/lib/catalog.py`, and one test file.

### Task 8. The remaining static Khorikov rules

Module `test-audit-static`. Dependencies Task 6.

The catalog marks 16 entries STATIC. Two of them are definitions and no rule, `four_pillars_and_tradeoff` and `mocks_vs_stubs_definition`. The existing `hollow_test` rule covers `assertion_free_test`. Task 7 covers three more. The remaining entries split into three tickets. Each rule in them has one violating and one clean fixture from the catalog, starts at observe, and has an entry in `catalog.py`.

#### Task 8a. Test structure rules

Size S. The rules are `if_statements_in_tests`, `multiple_act_sections_in_unit_test`, `aaa_pattern`, and `test_fixture_reuse_via_constructor`. The file is `hooks/lib/test_rules/structure.py`.

Status on 2026-09-30. Done on branch `worktree-agent-a702873532d4a865b`, commits `c2f6563`, `4c90170`, `9643d83`, `cea8b11`, `28d3390`, not merged. `aaa_pattern` stays dropped, and the catalog entry explains why. On hooks/, 0 hits for `if_statements_in_tests` and `multiple_act_sections_in_unit_test`, 2 hits for `test_fixture_reuse_via_constructor`, both sampled true positives.

#### Task 8b. Private access rules

Size S. The rules are `exposing_private_methods_for_testing`, `exposing_private_state_for_testing`, and `code_pollution`. The file is `hooks/lib/test_rules/private_access.py`.

Status on 2026-09-30. Done on branch `worktree-agent-afc4bee7b19625656`, commit `6e470d4`, not merged. `code_pollution` stays CONTEXT, no test-side signal found in hooks/. On hooks/, 176 method hits and 16 state hits, sampled true except one accepted stdlib false positive.

#### Task 8c. Mock and ambient context rules

Size S. The rules are `mocking_concrete_classes`, `incomplete_mock_call_verification`, `time_as_ambient_context`, and `reusing_database_context_across_sections`. The file is `hooks/lib/test_rules/doubles.py`. If a rule needs other files to decide, record it as CONTEXT in the catalog and skip it.

Status on 2026-09-30. Done on branch `worktree-agent-acf8d806c07267418`, not merged. Kept `mocking_concrete_classes`, `incomplete_mock_call_verification`, and `time_as_ambient_context`. Dropped `reusing_database_context_across_sections` as CONTEXT, because no AAA-section marker exists in the AST to tell fixture reuse from a real defect. The audit found 0, 3, and 34 hits on `hooks/`, and a sample of 8 hits checked true.

### Task 9. Knowledge base build step

Module `principle-kb`. Size M. Dependencies Task 5.

Install and update build `~/.adw/cache/principles.sqlite`. The build reads `NimblePros/deviq-hugo` and `webpro/programming-principles` at pinned commits. Each row holds the source, the entry id, the title, and the first paragraph as plain text, with links and markup removed.

- [x] A second build with the same commits leaves the file unchanged
- [x] No DevIQ or programming-principles text enters git, and a test scans the tracked files for it
- [x] With no network, the build reports the skip and the gates still run

Files are `hooks/lib/principle_kb.py`, the update path that already fetches release data, and one test file. The build runs from the update path or its own command, never from a hook.

### Task 10. Explanation text in findings

Module `principle-kb`. Size M. Dependencies Task 9.

`principle_map.json` maps each Code Check rule to one entry. The finding output appends that entry's text once per rule per session.

- [x] The text holds at most 80 words and no URL
- [x] The second finding of the same rule in one session shows the rule line only
- [x] A missing database or a missing entry leaves the finding unchanged
- [x] Claude Code, Codex, and OMP show the same text

Files are `hooks/lib/principle_map.json`, `hooks/lib/finding_output.py`, `hooks/lib/session_state.py`, and one test file.

### Task 11. Self-audit measurement on the ADW suite

Module `test-audit-static`. Size M. Dependencies Tasks 7 and 8.

Status on 2026-09-30. Sonnet proposed 131 labels in `evals/code_check_labels.jsonl`. Only `assert_in_loop` clears 0.85 on a real sample, at 0.9615 on 26 hits. The two user rules score 0.38 and 0.33, because Sonnet judged absence guards as justified. The user decides whether an absence guard counts as a bogus test.

Run the audit on `hooks/`. Label up to 30 hits per rule as true or false. A Sonnet agent proposes each label with a reason, and the user approves the labels.

- [ ] `evals/code_check_precision.json` holds hits, labeled sample, and precision per rule
- [ ] Rules at 0.85 or above move to block only after the user agrees
- [ ] The list of flagged ADW tests goes to the user, and nothing gets deleted without approval

## Checkpoint B

- [ ] The Rust example yields both findings with explanations
- [ ] The user decides the gate state per rule and the fate of flagged tests

## Phase 3. Semantic rules and clean code

### Task 12. Spike on test embeddings

Module `test-audit-semantic`. Size S. Dependencies Tasks 4 and 11.

Embed the violating and clean fixtures of each SEMANTIC catalog entry. Measure whether the vote separates them.

- [ ] `docs/research/` records the AUC per rule and the decision to go on or stop
- [ ] Below AUC 0.8, the rule goes to Luna on static candidates only, and Task 13 records that

### Task 13. Semantic test rules through the journal and Luna

Module `test-audit-semantic`. Size M. Dependencies Tasks 1, 10, and 12.

Surviving test functions land in the journal as `pattern` rows. The Stop reviewer judges them with a test rubric and the principle text.

- [ ] Luna judges a test row against four violating and four clean examples of its rule
- [ ] The rows carry the explanation text from Task 10
- [ ] Each rule stays at observe until it has a precision measurement

### Task 14. Clean code principle catalog

Module `principle-kb`. Size S. Dependencies none.

Status on 2026-09-30. Done and reviewed, 196 entries. The review changed 11 rows and left 26 STATIC entries. `murphys-law` moved to NONE. ADW has no secrets rule, so `kerckhoffs-principle` keeps "none" as its ADW rule.

Classify each programming-principles entry and each DevIQ code smell and antipattern as STATIC, SEMANTIC, or CONTEXT, the same way as the Khorikov catalog. Detection work for them gets its own tickets after the user reads this catalog.

- [ ] `docs/research/2026-09-30-clean-code-catalog.md` lists every entry with class and signal
- [ ] The catalog marks entries that an existing ADW rule already covers

### Task 15. README and CHANGELOG

Size S. Dependencies Tasks 5, 10, and 11.

- [ ] The README describes three families and the explanation text
- [ ] The CHANGELOG names the family aliases and the new Luna selection

## Phase 2b. Test write policy

The user approved these tickets on 2026-09-30. A project denies test writes, and only a dedicated test writer agent can write tests. That agent reads the Khorikov catalog before it writes.

### Task 16. Skip files in temp directories

Size S. Dependencies none.

A scan of a text dump under `/tmp` produced 2700 findings on 2026-09-30. Files under the system temp roots are no project output.

- [x] For a file outside the project root, a write under `/tmp`, `/private/tmp`, `$TMPDIR`, or `/var/folders` gets no content findings
- [x] A copy or move from a temp root into the project still gets the full scan
- [x] Self-protection checks still run on every path

### Task 17. Small policy CLI

Size M. Dependencies none.

The old `adw-cli` repository shipped `bin/agent-discipline` with `configure`, `status`, and `exempt-family`. A new `bin/adw-config` brings back the small subset the user needs now.

- [x] `adw-config status` prints the effective policy for the current project
- [x] `adw-config tests allow|deny` and `adw-config family NAME on|off` write the project policy file
- [x] An agent that runs `adw-config` through a tool call gets a block, because the agent must not widen its own gate

### Task 18. Research on test writer identity per host

Size S. Dependencies none.

- [ ] `docs/research/` records which hook payload field names the calling subagent on Claude Code, Codex, and OMP, with evidence
- [ ] The note records how each host sets model and effort for a named agent, and which Luna ids Codex lists

### Task 19. Test write gate

Size M. Dependencies Tasks 17 and 18.

- [x] With `tests: deny`, a write that adds or changes a test function gets a block that names the test writer agent
- [x] The test writer agent passes the gate on Claude Code and Codex through `agent_type`
- [x] The default stays `allow` until the user changes it
- [x] `adw-config tests allow --for 30m` opens a timed window that only the user can set. OMP needs it, because its tool events name no agent
- [x] An agent write to any `adw-test-writer` definition file gets a block, in project scope and user scope

Status on 2026-09-30. Codex 0.159.2 carries `agent_type` on subagent tool calls, and an unregistered name aborts the spawn. OMP carries no agent field, so OMP relies on the timed window.

### Task 20. Test writer agent

Size M. Dependencies Task 18. The book summary lives in the skill `unit-testing-principles`, and the agent files load it.

- [ ] Claude Code ships `adw-test-writer` on Opus 5.5 with high effort
- [ ] Codex ships the same mission on `gpt-6-luna`, and OMP ships it with a model the user picks
- [ ] The required reading covers every essential idea of the Khorikov book in our own words. It keeps the depth of the book, because a thin digest loses the knowledge
- [ ] Each chapter gets its core argument, its reasoning, and worked bad and good examples. No sentence comes from the book
