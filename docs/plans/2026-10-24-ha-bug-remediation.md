# Remediation of the Home Assistant bug list, 2026-10-24

This plan covers `homeassistant/adw-bug.md` as of 2026-10-24 18:30. Every rule keeps its strength. Each fix makes detection more exact, and none adds an exemption, a lower gate, or a per-project cap.

## Evidence

1. Claude Code runs ADW 0.30.0 from `~/.claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher/4023bd77fe98`. Codex runs it from `~/.adw/install/agent-discipline-watcher`. Both hold the same `hooks/` tree as `main`.
2. Claude Desktop also loads ADW 0.17.1 as an account plugin. The copy sits in `~/Library/Application Support/Claude/local-agent-mode-sessions/.../rpm/plugin_01PUSed8hxbyy4ohXWvWgWVc` (manifest date 2026-08-21). It runs every hook beside 0.30.0 in each Desktop Code session and in Cowork, and it writes to `~/.claude/plugins/data/agent-discipline-watcher-inline/`.
3. The HA session `7abebee8` got 8 Stop blocks in a row at 16:30 and 9 more at 16:39 on 2026-10-24. The agent changed nothing between them, and Michael had to interrupt. All nine reports have the same content and the name `session-turn-*`, which only the 0.17.1 copy writes.
4. A replay of the same Stop through 0.30.0 `stop.run` blocks five times and releases at the sixth Stop with the stall notice.
5. A replay of 28 commands from the bug list through 0.30.0 `pre_tool.run` denies 20 of them. The same replay through 0.17.1 denies 3.
6. A replay of 17 content samples through 0.30.0 `scan_all` still blocks on 6 of them.

The replay scripts are `/tmp/adw-repro/replay_gates.py`, `/tmp/adw-repro/replay_rules.py`, and `/tmp/adw-repro/repro_stop_loop.py`. Each takes the `hooks/` folder of a copy as its only argument.

## Severity scale

- Critical means an agent cannot end its turn, or ADW burns tokens with no change in state.
- High means a read-only or scratch action blocks, so agents route around the gate or stop work.
- Medium means a finding on text the agent did not write or cannot change, which costs a rewrite or a wrong edit.
- Low means wording, report shape, or a gap outside ADW.

## Phase 0, the Stop loop

1. Critical. Remove the 0.17.1 account plugin from Claude Desktop, or publish 0.30.x to that marketplace. Its `stop.py` blocks on every Stop while a finding stays, with no stall breaker. Michael does this in the claude.ai plugin settings, because an agent must not change account settings.
2. Critical. Detect a second ADW copy. `session_start.py` and `bin/adw-config status` list every ADW install on the machine, including the Desktop `rpm` folder, with its version. A copy older than the running one gets named in the SessionStart notice, so drift shows up on the first turn.
3. Critical, latent in 0.30.0. A held reviewer block has no stall breaker. `claude_luna.keep_held` turns every held verdict into a Stop block, also when the payload sets `stop_hook_active`, and only an edit or a new turn ends it (`hooks/lib/claude_sonnet.py:311`, `hooks/lib/claude_luna.py:387`). An agent that cannot fix the text loops for good. Route the held texts through `stop_stall.guarded` with the same fingerprint rule and the own-finding limit of 5. The release writes `stop_stall` to the ledger like a deterministic release does. A retry still cannot clear the block early, so the bypass that held verdicts closed stays closed.
4. Critical. Count each copy in one test. A regression test runs `stop.run` and the Sonnet Stop handler together on an unchanged held finding and asserts a release with notice after the limit.
5. High. The account copy hides the `adw-test-writer` agent. It carries the same plugin name and no `agents/` folder, and in a Desktop session the Agent tool lists no `adw-test-writer`. So no agent in that session can write a test under `tests=deny`.

Status on 2026-10-24 evening:

- Item 1 waits for a claude.ai login in the browser pane. Computer use cannot drive the Desktop app.
- Item 2 landed in `hooks/lib/adw_copies.py`, `hooks/session_start.py`, and `adw-config status`. Both name the 0.17.1 copy on this machine.
- Item 3 landed in `hooks/lib/held_release.py`, with the stall key moved into `StopCall`.
- Item 4 waits for `adw-test-writer`, which item 5 hides. The full suite runs 5655 passed and 10 failed. Nine failures sit in `hooks/lib/test_held_blocks.py` until it reads the new `Held` return value. `hooks/test_task4_codex.py::test_session_and_subagent_start_use_one_short_model_channel_without_readable_skill` reads the real home folder, so it needs `session_start.run({}, drift=lambda: "")`.
- Until the dedupe exists, the account plugin stays off. A 0.30.x account copy would run every hook twice next to the Claude Code plugin and advance the turn twice per Stop. Cowork runs without ADW until then.

## Phase 1, gates on read-only and scratch commands (0.30.0, reproduced)

Each item keeps the gate closed for every real write. The fix teaches the parser what the command reads.

1. High. `sed -n 1,200p test/x.test.ts` blocks as `test_write_gate` (entries 8q, 13i, 13k item 1). A `sed` without `-i`, `w`, or `W` writes nothing.
2. High. `sed -n '1,65p' ".agents/skills/$file/SKILL.md"` blocks as `dynamic_write_target` (13q). An input file of a read command is no write destination.
3. High. `sed "s|^|$f:|"` and `xargs -I{} sed -n '{}p'` block as `dynamic_write_target` (8t). A `|` delimiter in a substitute is no pipe, and a fed `sed -n` reads only.
4. High. `git restore --staged client/docs/*.png` blocks as `test_write_gate` (13k). `--staged` touches the index only, and the glob holds no test. The 0.30.0 `git ls-files` lookup covers `git checkout --` but not this form.
5. High. `tar -xOf a.tgz member | grep` blocks as `test_write_gate` (8k). `-O` writes to stdout.
6. High. `tar x -C dir`, `unzip -d dir`, `curl | tar xz -C dir`, `patch -o file`, and `git apply` block as `test_write_gate` (8a, 8c, 8e, 8f, 8n). Stream F items 1 and 3 of the archive section planned a bounded member list check. It did not land in 0.30.0.
7. High. Read-only inline Python blocks as `inline_interpreter_write` on `continue`, `import yaml`, `next(...)`, and `try` (6b, 8j). Read-only `node -e` with `require("./x.json")` blocks too (6a). Stream F planned `next` and the JSON `require`. Neither landed.
8. High. `python3 tools/watcher-scan.py ... > .build/x/scan.txt` blocks as `opaque_source_write` (8e, 13n). A literal scratch destination resolves before the run, and its content gets scanned after it.
9. Medium. `unscannable_file` fires on `/dev/null`, `/dev/stdout`, unexpanded `$O/...` paths, NumPy subscripts in a `-c` string, files on a remote host behind `ssh`, files the same command deleted, and a background log that was still empty (8, 8h, 8i, 8l, 8m, 8o, 8r, 13h, 13m). 0.30.0 reports from 2026-10-24 confirm the `/dev/null` and empty log cases. A device, an unresolved name, or a vanished file is no written file, and a background log gets its scan when the command ends.
10. Medium. `test_write_gate` blocked `adw-test-writer` when it ran as a named teammate (13r). `tests_policy.gate_open` reads only `agent_type` from the payload. The fix maps `agent_id` to the type that `SubagentStart` recorded. Capture one teammate payload first to confirm that the field is missing.

Status on 2026-10-25, release 0.30.2:

- Items 1, 2, 4, 5, 6, 7, 8 and 9 landed. A replay of 60 commands matches the expected verdict on each, 24 of them writes that must keep blocking.
- Item 3 stays blocked by design. A run-time expansion in a sed script and a fed `xargs sed` can both gain a `w` command, so the gate cannot prove them read-only.
- Item 6 keeps `curl | tar` and an unzip pattern that also matches a test member blocked, because the gate cannot list a piped archive and unzip lets `*` cross `/`.
- Item 10 got a fallback record and a clearer block row. A named subagent and a main-thread agent both carried `agent_type` in a captured payload, so the in-process teammate case of 13r stays unreproduced.
- Review found a hole while fixing item 1. A sed `w` command wrote any file unseen, and 0.30.2 closes it.

## Phase 2, prose and code rules (0.30.0, reproduced)

1. Medium. `banned_dash` flags the minus sign U+2212 in prose and UI code (13c, 13d). U+2212 is a minus, not a dash. The en dash and em dash stay banned.
2. Medium. `passive_voice` flags "its shelf is open" (13p). "open" after "is" is an adjective. Add the adjective check and measure the rule again.
3. Medium. Saved tool output reads as authored prose. A Vitest log, `rg` matches, a Playwright log, and a `diff -u` file get `banned_dash` and `prose_colon` (8e, 11a, 13j, 13o). Stream F item 1 of the prose section planned one content masker for diffs, match lines, log lines, and JSON. It did not land.
4. Medium. Verbatim upstream copies count as the agent's own text. This covers the HA core copy, the Blender API page, the GeoBasis catalogue, the Better Thermostat source, and the Claude Design files (8d, 8p, 8r of the commit section, 13e). Stream F planned to record files that arrive through `curl -o`, `tar`, `unzip`, and `git clone` in `imported_baseline`. It did not land. The HA repository has no commit yet, so every file there counts as new. This raises the cost of the gap.
5. Low. `three_item_list` and `oversized_list` now observe only, so 8g and 13 no longer block. The sharper triad detector from stream F stays open.
6. Low. `de_modal_verb` now observes only. Its action text still pushes a requirement into a claim (4a). Change the text as stream F item 3 says.
7. Low. The shared reviewer prompt lacks the list marker sentence from stream F item 4 (12a).
8. 0.30.0 fixed entries 1 (Jinja), 3, 4, 5, 6, 7, 9, 10, 12, 13a, and 13b, and the replay confirms each fix.

## Phase 3, decisions for Michael

1. 13e and 13s. A verbatim design file and the castle placeholder U+2013 hold an en dash that the build must match. Either the file arrives as an imported baseline (phase 2 item 4), or the design gets a different glyph. The rule stays as it is.
2. Entry 2. The 80 character comment cap stays. The 0.30.0 reviewer prompt names the cap, so the Sonnet review no longer asks for longer comments.

## Test hygiene

1. Low. Tests write into the real ledger at `~/.adw/ledger/ledger.jsonl`. On 2026-10-25 it held 158 rows with session `s1`, 10 with `sonnet`, and 6 with `session-1`. A `conftest.py` fixture that points `HOME` or the ledger root at `tmp_path` for every test keeps them out. The new held breaker tests already do this.

## Outside ADW

- 14 and 14a belong to Craftsman (`WARN-PY001`, `WARN-TS001`).
- 15 to 15c belong to the knowledge-based-search gate. Its fix reads `agent_transcript_path` or records a PostToolUse `Skill` event.

## Order of work

1. Phase 0 items 1 and 2 first, because they end the observed loop.
2. Phase 0 items 3 and 4, then a release.
3. Phase 1 items 1 to 5 and 7, because agents hit them every hour.
4. Phase 1 items 6, 8, 9, and 10.
5. Phase 2, then a fresh measurement of each touched rule against `ENFORCE_PRECISION`.

Each fix lands with a regression test from the `adw-test-writer` agent. Before each release, the replay scripts run against `hooks/`.
