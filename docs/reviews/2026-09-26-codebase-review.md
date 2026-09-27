# Codebase Review, Agent Discipline Watcher 0.20.24

| Field | Value |
| --- | --- |
| Date | 2026-09-26 |
| Revision | `eeb2d1d`, clean `main` |
| Reviewer | Claude (Fable 5.1) consolidating six read-only reviewers on Opus 5.5 and Sol |
| Project type | Hook plugin for Claude Code, Codex, and OMP |
| Stack | Python 3.11 floor, POSIX shell dispatch, TypeScript extension on Bun, GitHub Actions |

## Overall Grade, B-

ADW has a strong deterministic core. The regex gates, the Bash parser, protected paths, egress controls, and the updater all carry bounded input and fail-closed defaults. A large test suite backs them (2771 pytest, 201 bun, pylint 10.00). The model side does not match that quality or the README. The embedding layer loads a 709 MB model on every prompt and no host reads a vector. Two commits in late August removed its consumer and stubbed its judge. The live advisors on Claude Code read whole files two to three times per turn with no candidate filter. Presets stack a second reviewer on top of the shipped one, and the Stop journal has no aggregate cap. Two bugs in the deterministic core silently change policy or lock a session. The codebase reflects a solo maintainer moving fast across four hosts, with tests that cover the intended behavior and miss the regressions.

## Dimension Scores

| # | Dimension | Grade | Summary |
| --- | --- | --- | --- |
| 1 | Data Integrity and Validation | B- | Strong bounds on hook input, but a shallow config merge rewrites policy and a malformed Bash payload can pass. |
| 2 | Test Coverage and Quality | B+ | 131 Python and 11 TypeScript test files, all green. None of the bugs below has a test. No coverage gate. |
| 3 | Security Posture | B- | Egress, protected paths, and updater extraction are careful. Data boundary differs by host, a stale pid can receive signals, no release signer. |
| 4 | Error Handling and Resilience | C+ | A single `record.py` crash blocks Stop for the session. Embedding failure is silent. Codex fails open where OMP fails closed. |
| 5 | Code Organization and DRY | C+ | About 2000 lines of dead judge and embedding path, a 530-line orphan CLI, five copies of one check, 43 dual-import blocks, one 805-line module. |
| 6 | Type Safety | C+ | Good runtime checks, no mypy, pyright, or tsconfig, nothing static in CI. |
| 7 | Performance and Scalability | C | Model loads per turn for nothing. Claude sends each file three times per turn. Stop scans each file four times. PreToolUse starts Python on every Read. |
| 8 | Accessibility | I | Not applicable to a hook plugin with no visual surface. |
| 9 | Build and Deploy Pipeline | B | Three Python versions, shell syntax, bun, pylint 10.00. Unpinned tools, no coverage, no type check, no dependency audit. |
| 10 | Documentation and Onboarding | C+ | README is long and detailed, and five of its claims about the model layer are false today. The documented test command fails on a fresh machine. |

GPA over nine graded dimensions. 2.7 + 3.3 + 2.7 + 2.3 + 2.3 + 2.3 + 2.0 + 3.0 + 2.3 = 22.9. Divided by 9 gives 2.54, which maps to B-.

## Dimension Deep Dives

### 1. Data Integrity and Validation, B-

`hooks/lib/hookio.py:40-55` caps hook input at one million characters and requires an exact JSON object. `hooks/lib/config.py:211-290` rejects oversized, deep, or duplicate-key config. Two gaps lower the grade. `hooks/lib/config.py:333` merges project config with a shallow `dict.update`. A project file that sets one `rule_gates` entry therefore replaces the whole default map and turns `observe` rules into `enforce`. The OMP config screen writes exactly that shape. `hooks/pre_tool.py:32-37` lets a Bash payload with any nonempty `tool_input` through. If the command field is absent, `hooks/pre_bash.py:132-134` returns allow.

### 2. Test Coverage and Quality, B+

The suites are large and failure-oriented. `hooks/test_batch_race.py` covers filesystem races, `hooks/lib/test_scanner.py` runs 968 lines of rule boundaries, and the OMP lifecycle has 542 lines of integration tests. Every suite passed in this review through `uvx --python 3.11`. The gap is regression coverage. The dead embedding consumer, the config merge, the `<record-error>` blocker, the preset stacking, and the Python read-probe rejection all pass the suite. No coverage number exists.

### 3. Security Posture, B-

Protected-write grants come only from the environment (`hooks/lib/protected.py:76-101`). Embedding egress is local-only by default with an HTTPS allowlist (`hooks/lib/embedding_client.py:48-140`). Release downloads pin a host, resolve tags to commits, and refuse traversal (`hooks/lib/update_release.py:67-240`). Three issues remain. The `data_boundary` switch gates OMP and the dead Python path but not the native Claude reviewers or Luna (`hooks/lib/omp_review.py:128`, `hooks/lib/claude_luna.py`). The same project policy therefore means different egress per host. `hooks/lib/embedding_server.py:362-381` trusts a recorded pid without an identity check. After a reboot ADW can POST prompt text to an unrelated loopback process and later SIGKILL it. No release signer or checksum manifest exists.

### 4. Error Handling and Resilience, C+

Critical dispatch fails closed (`hooks/pre_tool.py:91-96`, `hooks/stop.py:36-79`). The degradation paths do not. `hooks/record.py:337` writes a `<record-error>` blocker on any exception, and `hooks/lib/end_turn.py:105` never clears it, so one transient OSError blocks every later Stop in that session. `hooks/lib/embedding_session.py:43-54` reports an embedding failure with no consequence and no action. `hooks/lib/codex_luna.py:357-381` passes the turn after a Luna timeout while `pi/.../omp-review.ts:69-85` blocks on the same failure. The repo has 27 `except Exception` and 23 `except BaseException` sites, and `hooks/judge_review.py:131-133` swallows the embedding vote crash with no log.

### 5. Code Organization and DRY, C+

The layering is clear, with entry scripts in `hooks/`, shared logic in `hooks/lib/`, and the OMP bridge in `pi/`. The dead weight is large. `hooks/lib/judge_provider.py:65-67` always returns no provider since commit `7bf4397`. That leaves five judge modules and the whole embedding stack running with no effect. `review.py`, `bm25.py`, and `render.py` (530 lines) lost their caller in `da82975`. The data-boundary check exists in five places. 43 modules carry a `try/except ImportError` dual import. `hooks/lib/claude_native.py` is 805 lines, above the plugin's own critical threshold. `hooks/hooks.json` and `hooks/lib/claude_presets.py` hold two diverging copies of the judge prompts.

### 6. Type Safety, C+

The boundary layer uses `TypedDict`, dataclasses, and exact runtime type checks (`hooks/lib/payloads.py:17-123`). Tracked Python has no `Any` annotations. Nothing checks any of it statically. There is no mypy or pyright config, `pi/package.json` has no type-check script and no `tsconfig`, and `.github/workflows/pylint.yml` runs lint and tests only.

### 7. Performance and Scalability, C

Every hook starts a fresh Python process through `hooks/run.sh`. `hooks/hooks.json:27` gives PreToolUse no matcher. Read, Grep, and Glob each pay about 160 ms for a handler that returns `{}`. `hooks/lib/embedding_session.py:43` loads the 709 MB model on every prompt. `hooks/stop.py:52` unloads it on every Stop, with no reader in between. On Claude Code a 300-line prose write reaches Haiku three times. It appears in the raw Write event, in the agent's own Read, and again at Stop. That costs roughly 25k to 35k input tokens. `hooks/lib/journal.py:20-21` allows the Stop reviewer 24 documents at 24k chars each with no turn filter. Unchanged documents therefore replay every Stop. `hooks/lib/end_turn.py:98-99` scans each file twice at Stop. Each scan runs two git processes.

### 8. Accessibility, I

Not applicable. The plugin has no visual surface. The Documentation dimension and the UX findings cover readability of its terminal output.

### 9. Build and Deploy Pipeline, B

`.github/workflows/pylint.yml` runs pylint at 10.00, shell syntax, pytest on 3.11, 3.12, and 3.13, and bun tests. Releases carry a tag and the updater checks commit identity. The pipeline lacks pinned tool versions, a coverage gate, a static type check, a dependency audit, and a release signer.

### 10. Documentation and Onboarding, C+

`README.md` runs 345 lines and `evals/README.md` explains the corpora with care. Five README claims about the model layer are false in the current tree. The meaning layer does not run on any route. Stop does not skip unchanged documents. The journal records scratchpad files. Presets add reviewers rather than replace them. Comment review under Luna covers `.py` only, not the listed languages. The documented `cd hooks && python -m pytest` fails on a machine whose `python` is 3.14 without pytest. There is no contributor guide.

## Focus Area Findings

### A. How agents interact with ADW

1. ADW scans tool input on PreToolUse and the file on disk on PostToolUse and Stop. It never scans the assistant reply. Commit `ffca55c` removed that, and the session contract at `hooks/lib/hookio.py:32` still says "Fix the named file or reply text".
2. When it is correct, the deterministic finding row is actionable. It names path, line, rule, and action. It omits the matched phrase. `hooks/lib/scanner.py:330-360` stores the whole source line as `snippet`, and `hooks/lib/finding_output.py:75-83` drops even that from the terminal row.
3. The Python read-only checker rejects ordinary read probes. `json.load(...)` gets an opaque kind at `hooks/lib/python_payload.py:348`, so `.get()` and comprehensions fail. The denial text at `hooks/pre_python.py:9-14` recommends `-I -S`, which the checker already applies. ADW blocked four such probes during this review.
4. `passive_voice` at `hooks/lib/slop_structure.py:73` lists `read` as an irregular participle. Any sentence with the verb "are" followed by the adjective "read" (as in read-only mode) blocks. The scanner masks quoted text for line regexes only, not for structure rules or punctuation.

### B. How the user perceives ADW

1. The strongest format in the tree is the OMP document finding at `hooks/lib/omp_review_findings.py:33-48`. It shows quote, problem, fix, path, and line. The default compact row shows none of the evidence.
2. Compact output defaults to eight unnumbered rows and clips the whole message at 4096 bytes, so a long row can remove the report path.
3. Session start injects a 13-line contract on startup, resume, clear, and compact. It carries no current state or action.
4. Error messages send readers to "repair the gate config" for an unreadable hook payload. The action does not match the cause.
5. The native Haiku judge returned prose instead of StructuredOutput during this review, and the host displayed that prose as a blocking error. ADW has no adapter between the model and the host.
6. While I wrote this review file, the Haiku judge asked for the words `should` and `verify` in two sentences. The simple-english lint on the same file bans `should` and flags `verify` as synonym rotation. Two hooks on one file gave opposite orders, and neither cited a rule the writer can look up.

### C. Bugs that disable or block features

1. `hooks/lib/embedding_session.py:43` loads a model no path reads. Commits `4499399` and `7bf4397` removed the consumer.
2. `hooks/lib/config.py:333` shallow-merges `rule_gates` and wipes defaults.
3. `hooks/record.py:337` and `hooks/lib/end_turn.py:105` leave `<record-error>` set forever.
4. `hooks/pre_commit.py:476` uses `--diff-filter=ACM` and skips renamed files. The same call breaks on non-ASCII paths without `-z`.
5. `hooks/lib/scanner.py:172-178` runs `function_too_long` on `.py` only. A 262-line TS function ships unchecked.
6. `hooks/lib/claude_native.py:503-515` appends preset hooks while the plugin's own agent hooks stay active, so `mixed` runs two Haiku agents per write.
7. `hooks/lib/embedding_lease.py:15` never renews a lease, so a turn over 15 minutes loses the model.
8. `hooks/stop.py:52` can spend up to 20 s terminating a worker inside a 10 s hook timeout.

### D. Embedding loading

The model loads in the background on every prompt and unloads on every Stop. Only a lock with no timeout and the Stop termination above sit on a blocking path. No consumer reads the vectors. The exemplar cache key covers the exemplar file alone, not the model, and the writer skips the temp-file step. `pattern_semantic.py` itself is the right shape. It emits a short list of (rule, line, sentence) from up to 200 sentences against 27 rules with exemplars. That list is the input an advisor must read.

### E. Review agents and their configuration

1. Eleven judge definitions exist. Three live in dead Python. Two ship as Claude agent hooks. Two come from presets and duplicate them. Two run on Luna. Three run on OMP.
2. Every prompt, schema, model ID, timeout, and matcher lives in Python, JSON, or TypeScript constants. Only pattern exemplars and project gates load from files.
3. `judged` rules never reach a reviewer on Claude, and OMP forces them to `blocking=False`, so the judged gate is inert on both.
4. Three sources disagree on `three_item_list` precision. The manifest says unmeasured, `config.py:142-148` and the README say 1.0.
5. The `luna` and Codex paths cost about 6k to 7k tokens per prose write. The default Claude path costs about 25k to 35k because it sends the file three times and has no candidate filter.

## Top 10 Improvement Plan

| # | Priority | Effort | Dimension | What | Why It Matters |
| --- | --- | --- | --- | --- | --- |
| 1 | Critical | 0.5 d | Data Integrity | Deep-merge `rule_gates`, `gates`, `kill_switches`, `exempt_families`, and `data_boundary` in `hooks/lib/config.py:331-338`. | One project rule setting silently turns observe rules into hard blocks. |
| 2 | Critical | 0.5 d | Error Handling | When every touched path rescans clean, clear `<record-error>` in `hooks/lib/end_turn.py:105`. Unify the policy with `batch.py:447`. | One transient crash blocks the agent for the rest of the session. |
| 3 | Critical | 0.25 d | Performance | Gate `open_turn` in `hooks/lib/embedding_session.py:43` until a consumer exists. | 709 MB loads per prompt with nothing reading the result. |
| 4 | High | 4 d | Performance | Wire the embedding candidate list into the journal and make the Stop, OMP, and Codex advisors read only those candidates. Keep whole-document review opt-in. | This is the token saving the meaning layer exists for. Cuts Claude per-turn cost from about 30k to about 1.5k tokens. |
| 5 | High | 1 d | Organization | Render `hooks/hooks.json` agent hooks from `claude_presets.py`. When a preset is set, drop the plugin copies. Add a golden equality test. | Presets currently add a second reviewer and change timeouts and matchers silently. |
| 6 | High | 1 d | Data Integrity | Filter `read_stop` in `hooks/lib/journal.py:431-444` by current turn and reviewed digest, and add one aggregate character budget. | Stop can send 144k tokens of unchanged documents to Haiku every turn. |
| 7 | High | 1 d | Security | Apply one `data_boundary` gate to Claude native, Luna, and OMP, and check the recorded pid identity in `embedding_server.py:362-381` before signaling. | Same policy means different egress per host, and a stale pid can receive prompt text or a kill signal. |
| 8 | High | 1 d | Error Handling | Give `_ReadOnlyChecker` in `hooks/lib/python_payload.py` a `json` kind with `get`, `keys`, `items`, and route comprehensions through `generator()`. Put the rejected node in the denial detail. | Read-only probes block the agent and the denial text points at the wrong fix. |
| 9 | Medium | 1.5 d | Organization | Delete the dead judge stack, `review.py`, `bm25.py`, `render.py`, and the twelve dead symbols the code health reviewer listed. Keep `request_for`, `build_prompt`, and `rule_prompt`. | About 2500 lines run with no effect and mislead every reader of the README and the code. |
| 10 | Medium | 1 d | Documentation | Rewrite the compact finding row to show the matched phrase and the catalog title, number the rows, and cap at five with a report pointer. Fix the five false README claims. | A human watching the session cannot see what matched or why, and the README describes a model layer that does not run. |

## Reviewer Coverage Limits

1. No reviewer ran a live Claude Code session. Token figures are character-count estimates. One reviewer claimed that `${CLAUDE_PLUGIN_ROOT}` stays unexpanded in the Stop agent's tool shell. I did not check that claim, and the transcript it cited shows other plugins.
2. No reviewer started the embedding worker or called a model.
3. Three reviewers did not open `hooks/lib/update_*.py`, `shell_syntax.py`, `shell_parse.py`, or the OMP `tool-adapter.ts` and `watcher.ts` internals beyond dead-code checks.
4. Bugs 4 and 5 in section C come from reading the code, not from running git.
5. The six reviewers ran at medium effort, not the high effort written in their agent files. This session registered its agent list before the files existed.

## Appendix, Files Reviewed

Entry and wiring. `hooks/hooks.json`, `hooks/run.sh`, `hooks/resolve-python.sh`, `hooks/codex-hooks.json`, `hooks/pre_tool.py`, `hooks/pre_write.py`, `hooks/pre_bash.py`, `hooks/pre_commit.py`, `hooks/pre_mcp.py`, `hooks/pre_python.py`, `hooks/record.py`, `hooks/batch.py`, `hooks/failure.py`, `hooks/stop.py`, `hooks/session_start.py`, `hooks/session_end.py`, `hooks/prompt_submit.py`, `hooks/judge_review.py`, `hooks/read_claude_journal.sh`, `hooks/read_claude_journal.py`.

Library. `config.py`, `hookio.py`, `payloads.py`, `scan_input.py`, `scanner.py`, `slop_structure.py`, `comment_rules.py`, `findings.py`, `finding_output.py`, `render.py`, `reporting.py`, `catalog.py`, `journal.py`, `end_turn.py`, `blocker_state.py`, `session_state.py`, `protected.py`, `python_payload.py`, `python_shell.py`, `judge.py`, `judge_provider.py`, `judge_contracts.py`, `pattern_judge.py`, `pattern_semantic.py`, `regex_judge.py`, `document_review.py`, `narration_candidates.py`, `claude_presets.py`, `claude_native.py`, `claude_luna.py`, `claude_cache.py`, `codex_luna.py`, `codex_luna_documents.py`, `luna_provider.py`, `luna_feedback.py`, `omp_review.py`, `omp_review_requests.py`, `omp_review_findings.py`, `embedding_client.py`, `embedding_server.py`, `embedding_worker.py`, `embedding_lease.py`, `embedding_session.py`, `model_store.py`, `update_release.py`, `review.py`, `bm25.py`, `pattern_exemplars.json`, `pattern_exemplars.jsonl`.

OMP. `index.ts`, `lifecycle.ts`, `lifecycle-handlers.ts`, `adw-bridge.ts`, `adw-config.ts`, `omp-provider.ts`, `omp-review.ts`, `omp-review-bridge.ts`, `watcher.ts`, `hashline.ts`, `tool-adapter.ts`, `lifecycle.integration.test.ts`.

Tests, evals, and docs. `hooks/test_batch_race.py`, `hooks/test_pre_tool.py`, `hooks/test_plugin_wiring.py`, `hooks/lib/test_scanner.py`, `hooks/lib/test_embedding*.py`, `hooks/lib/test_slop_semantic.py`, `evals/measure_judge_stage.py`, `evals/judge_stage.json`, `evals/regex_judge.json`, `evals/rubric.md`, `evals/README.md`, `README.md`, `CHANGELOG.md`, `docs/plans/2026-08-28-adw-native-judges.md`, `.github/workflows/pylint.yml`, `.pylintrc`, `.python-version`, `pi/package.json`, `skills/*/SKILL.md`.
