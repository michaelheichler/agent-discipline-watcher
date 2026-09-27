# Open policy items after 0.22.1

Written on 2026-09-27 after the codebase review, the eight leftover fixes, and the `adw-nuke` release. Each item names the code, the current behavior, the options, and a recommendation.

Decided on 2026-09-28. The owner took the recommendation on every item. Items 1 to 3 shipped in 0.23.0. Items 4 and 5 stay as they are by choice. The sections below record the state before that decision.

Two facts came out during the 0.23.0 work that the sections below do not say. `DEFAULTS` sets `ai_closer` to `observe`. So an upheld `ai_closer` row now reports by default on every host. Stop releases the embedding lease every turn. So the Codex warm-up runs at each prompt, not only at SessionStart. A write in the first seconds of a Codex turn still gets no vote.

## 1. Voted pattern rows ignore per-rule `observe`

Code. `hooks/lib/pattern_vote.py` and the OMP judge path in `pi/extensions/agent-discipline-watcher`.

Current behavior. When the embedding vote writes a `pattern` row and a model reviewer upholds it, OMP blocks on measured precision and the english family. It never reads `rule_gates` from `.agent-discipline.json`, so a rule the project set to `observe` still blocks once a reviewer upholds it.

Options.

1. Honor `rule_gates`. A rule set to `observe` reports, and never blocks, on every host.
2. Keep the current behavior and document that a reviewed pattern row always blocks.

Recommendation. Option 1. A project setting that the deterministic path respects and the voted path ignores reads as a bug to the person who wrote the setting.

## 2. The `luna` preset judges document rows only

Code. `hooks/lib/claude_presets.py`, the `luna` command hooks, and `hooks/claude_luna.py`.

Current behavior. The `luna` preset reads `document` rows from the session journal and sends them to Codex Luna. It skips the `pattern` rows that the embedding vote writes, so a Claude session on `luna` gets no sentence-level review.

Options.

1. Extend the `luna` command handler to read `pattern` rows the way the `haiku` Stop reviewer does.
2. Leave `luna` as a document-only preset and say so in the README preset table.

Recommendation. Option 1. The 0.21.0 change made pattern rows the token filter for every advisor. A preset that skips them undoes that saving.

## 3. Codex gets no embedding vote on a cold model

Code. `hooks/lib/pattern_vote.py` and `hooks/session_start.py` on the Codex route.

Current behavior. Codex cannot run an async hook, so the vote runs inline inside the PostToolUse budget of 9 seconds. The 709 MB model takes longer than that to load. So the first prose write in a Codex session gets no vote. If the worker stayed warm, a later write gets one.

Options.

1. Warm the model at Codex SessionStart, in the background, so the first write finds a loaded worker.
2. Raise the Codex hook timeout and accept a slow first write.
3. Accept the gap and document that Codex votes only on a warm worker.

Recommendation. Option 1. SessionStart already registers the consumer and takes the lease. Starting the worker there costs nothing on the write path.

## 4. `judge_status` keeps a copy of the cache constants

Code. `hooks/lib/judge_status.py` and `hooks/lib/claude_cache.py`.

Current behavior. `judge_status` copies `CACHE_PARTS`, `CONFIG_ENV`, and `PLUGIN_ROOT_ENV` and walks the cache roots itself. Importing them from `claude_cache` fails `test_no_core_module_imports_a_host_module`, because the test counts `judge_status` as core and `claude_cache` as a Claude adapter.

Options.

1. Rename the module to `claude_judge_status` and add it to `KNOWN_ADAPTERS`, then import from `claude_cache`.
2. Leave the copy in place.

Recommendation. Option 2. The copy is four constants and one loop. A rename for that is churn.

## 5. CHANGELOG entries before 0.22.0 fail the STE lint

Code. `CHANGELOG.md`.

Current behavior. The simple-english lint reports 74 hits in entries from 0.21.0 and older. The 0.22.0 and 0.22.1 entries pass.

Options.

1. Rewrite the old entries to pass the lint, keeping every fact.
2. Leave release history as written.

Recommendation. Option 2. Release notes are a record of what shipped at the time.

## Done and verified on 2026-09-27

1. Release 0.22.0. Seven of the eight review leftovers, the `adw-nuke` command, and the `max_rows` default of 5.
2. Release 0.22.1. `adw-nuke` and `adw update` remove read-only Luna sandbox directories.
3. Clean reinstall on the MacBook for Claude Code, Codex, and OMP, and on tux for Claude Code and Codex. Both run 0.22.1 at revision `8de2d5a4908d`.
4. On tux, two stray checkouts and one old backup link are gone. The OpenCode plugin at `~/.config/opencode/plugins/agent-discipline-watcher.ts` now runs `~/.adw/install/agent-discipline-watcher/hooks/run.sh`.

## Done and verified on 2026-09-28

1. Release 0.23.0. Items 1 to 3 above, through three agents in parallel worktrees, plus one hand commit that wires `rule_blocks` into the Claude `luna` pattern path.
2. On merged main, pytest 3029 passed, pylint 10.00, bun 207 passed.
