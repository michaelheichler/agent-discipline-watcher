# Settled decisions for the per-host runtime split

Grilling session on 2026-08-30. These answers supersede the matching claims in
`plan-host-runtime-split-2026-08.md`. Rewrite that plan once the open questions close.

## D0. No solution weakens a hook or a block

This constraint outranks every decision below it and every convenience argument.

A host that cannot enforce a rule does not get an exemption for that rule. It gets a
harder path, an upstream fix, or a refusal to run. Ease of implementation never justifies
reduced coverage.

Shapes that count as weakening and stay banned, ranked by how quietly they pass review.

**Policy edits.** Moving a rule from `enforce` to `observe` or `off`. Removing a name from
`SELF_PROTECTION_RULES` or `ALWAYS_BLOCKING_RULES`. Raising a threshold so fewer findings
trip. Widening `exempt_paths` or `exempt_families` to route around a gate.

**Coverage loss.** Deleting a test, skipping one, or hollowing its assertions.

**Wiring removal.** Unwiring a hook event, narrowing a matcher, or downgrading a block to
an advisory notice.

**Judge loosening.** Relaxing the haiku screen or the judge availability gate.

**Suppression.** Any marker added to clear a finding rather than fix it.

Documenting a gap counts as weakening whenever a harder option exists. Naming a hole and
shipping it is the last resort, never the first answer.

A separate audit covers whether any commit since 2026-07-30 already introduced one of
these shapes.

## D1. Four runtime folders, not three

`hosts/claude` covers the terminal CLI and the Desktop Code tab. `hosts/codex`,
`hosts/omp`, and `hosts/cowork` each stand alone. Cowork ships prepped rather than
verified, because nobody has confirmed what runs inside its VM.

Evidence for folding Desktop into the Claude runtime.

- The hooks reference states Claude Code fires the same hook events in the terminal,
  IDE extensions, the Desktop app, and on the web.
- The Desktop quickstart states Desktop and the CLI share CLAUDE.md files, MCP servers,
  hooks, skills, and settings.
- `codesign -d --entitlements` on `/Applications/Claude.app` returns no
  `com.apple.security.app-sandbox` key, and no container exists under
  `~/Library/Containers`. A hook there reaches `~/.adw` without obstruction.
- `~/.claude/plugins/installed_plugins.json` points the installed plugin at
  `~/.claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher/c61ca234d605`,
  one cache shared by both surfaces.

Evidence for giving Cowork its own runtime.

- The Cowork overview states it does not read the Claude Code CLI `~/.claude` directory.
- Connected folders mount at `/sessions/<session-id>/mnt/<folder-name>/`, so a
  host-absolute path never matches.
- Cowork plugins sync from the claude.ai account through its Customize panel.

## D2. Frontmatter masking joins Phase 2 as Task 4b

`markup._mask_markup` masks non-prose syntax for `.tex`, `.adoc`, `.org`, and `.typ`.
It leaves a YAML frontmatter block in `.md` untouched, so every `name:` and
`description:` line trips `prose_colon`.

The fix lands in the shared core and gets verified identical across all four runtimes.
Scope covers memory files, every `SKILL.md`, and any static-site page carrying
frontmatter.

**Acceptance.** A leading `---` delimited block produces no punctuation finding, a colon
in the body still blocks, and line numbers stay correct because the mask keeps newlines.

**Done on 2026-08-30.** `markup._mask_frontmatter` masks a leading block for `.md`,
`.markdown`, and `.mdx`. An opener anywhere but line 1 does not count. An opener with no
`---` or `...` closer masks nothing, because a bare `---` in Markdown is a rule or a setext
underline. Seven tests in `test_regions.py` drive `scan_all` rather than the mask. They cover
both terminators plus the two negative cases. Suite moved 1810 to 1817.

## D3. The configure catalog lives in Python

`AdwRuleMetadata` in `adw-bridge.ts` carries `name`, `states`, and `locked`. No title and
no description exist anywhere in the codebase, which is why `adw-config.ts` renders
`banned_adverb` and `max_rows` raw.

A catalog beside `config.py` gains a title, a one-line description, and per-state wording
for 33 configurable rules, 23 always-blocking rules, 3 families, and 3 thresholds. The
bridge serves it and the TUI renders what arrives. Screens keep their current shape.

One source of truth feeds OMP today and any future Claude screen.

## D4. The root installer stays and routes per folder

`install.sh` keeps its place as the entrypoint. It stops knowing how to install anything
and starts deciding where to send the work. Each host folder owns its own installer, and
`hosts/claude` carries none, because the plugin is that path.

Humans get an interactive multi-select. Arrows move, space toggles, Enter installs, and a
mouse click selects a row. Agents and CI keep a flag path that skips the picker.

A Python module under `hooks/` draws the picker and parses SGR mouse input, then prints
the chosen hosts back to bash. Bash resolves the interpreter first through
`adw_resolve_python` against the 3.11 floor in `.python-version`, the same call it already
makes at line 114. The existing pytest suite covers the picker, which no bash harness
could do today.

**Acceptance.** The picker renders every host with a plain description of what it writes.
A flag path installs without a terminal. Selecting nothing exits without touching disk.
Each host installer writes only under `~/.adw` and its own host directory.

## D5. Each runtime declares its own config roots

No shared resolver branches on a host name. The core takes a root list as an argument, and
each runtime supplies the one list it needs. A resolver that skips a step for one host
rebuilds the coupling this split exists to remove.

`lib/collector.py` reads `config.json` and `models.json` from whatever roots arrive. A test
asserts that file carries no host name and no `.adw` string. `lib/config_roots.py` holds the
mapping until Phase 2 moves each entry into its host directory.

Claude, Codex, and OMP read their own directory then the shared one. Cowork reads the copy
shipped inside the plugin and never touches the home directory.

## Phase 1 complete on 2026-08-30

- Task 1. `lib/host.py` resolves four hosts in a fixed order and raises `UnknownHostError`
  rather than falling back. `SUPPORTED` pins the roster.
- Task 2. `lib/collector.py` plus `lib/config_roots.py`, tolerant of an absent tree and
  refusing an unknown key or unreadable JSON by name.
- Task 3. `lib/judge_provider.py` owns the only `claude -p` in the tree. None of the three
  judges imports `subprocess`, and a test fails if one does again.

Suite moved from 1762 to 1803 passing. All twelve touched files scan with zero findings.

## Phase 2 progress on 2026-08-30

I measured before moving anything. The tree sits closer to split than the plan assumed.

- 65 library modules, 9 of them host-named.
- Zero core-to-host import edges. That direction was already clean.
- Four entry scripts touch a host module, not the dozens the plan feared.
- Two host-to-host edges existed, both running from `codex_luna` into Claude modules. Codex
  could not install without Claude on disk.

I cut both edges, and a repeat of the measurement now reports zero.

- `claude_journal.py` became `journal.py`. Its own docstring already called the data shared,
  and only the filename carried a host. `STATE_KEY` keeps its old value, because a rename
  would orphan every journal already written to disk.
- `_comment_feedback` and `_document_feedback` moved into `luna_feedback.py`. Both format a
  Luna verdict and emit "ADW Luna", so neither belonged to a host. Both hosts import one copy
  now, and I deleted the duplicate definitions.

Task 4b closed the same day. D6 reversed the same day, and the section below carries the
evidence. Suite sat at 1817 passing and 18 skipped at that point.

## Phase 2 complete on 2026-08-30

Tasks 4 to 7 landed together, because the four runtimes are one build step over one core
rather than four hand-maintained trees.

**Task 4, the core names no host.** `lib/test_core_boundary.py` parses every module and every
shared entry script with the AST and refuses an import into a host adapter. It derives the
roster from `host.SUPPORTED`, so an adapter cannot dodge the check by going unlisted.

That test caught a real edge the earlier measurement missed. `stop.py` and `session_end.py`
both imported `codex_luna`. That made Codex mandatory for Claude, OMP, and Cowork alike.

A failing test then forced the better cut. `retry_turn_id` and `clear_retry_identity` touch
session state and nothing else. Both moved to `lib/turn_retry.py`. `RETRY_KEY` keeps its
old string value, because renaming it would orphan state already written to disk. Only
`review` is host-specific. So `lib/turn_adapter.py` is the single declared seam, and a test
asserts it is the only one. Three raw `ADW_CODEX_HOOK` reads now go through
`host.is_codex_host`, leaving that name in `host.py` alone.

**Tasks 5 to 7, one build step per host.** `hosts/<name>/host.json` declares the adapters,
entry scripts, installer, and extra paths. It also names the write surface the picker reads.
`lib/vendor.py` writes a runtime from the repo root. `hooks/build_runtime.py` is the entry
point. Ownership splits a filename on separators rather than matching a substring, because
`prompt_submit.py` is not an OMP file.

**Checkpoint one, isolation.** `test_runtime_isolation.py` vendors each host, then runs that
host's own tests inside the tree with the other three absent. It caught two real defects. The
vendored layout had to mirror the repo, and a runtime needs `bin`, `scripts`, `skills`, and
`.python-version`, not the hooks tree alone. Nine Claude tests failed until those travelled.

**Checkpoint two, parity.** `test_runtime_parity.py` scans one fixture through all four
vendored runtimes. It compares serialized findings byte for byte. The test checks each
runtime against the other three and against the source tree.

`lib/parity_fixture.py` builds its two worst characters with `chr`.
`banned_dash` and `decade_apostrophe` read raw source, so a plainly written fixture blocks
its own file.

Suite moved 1817 to 1959 passing, 18 skipped. Build output is 202, 196, 201, and 191 files
for Claude, Codex, OMP, and Cowork.

**Left for Phase 3.** Each manifest names an installer that does not exist yet. `hosts/codex`
and `hosts/omp` declare `install.sh`, and Phase 3 Task 8 writes them.

## D6. Luna runs through the SDK, and the scratch home stays

Reversed on 2026-08-30. The earlier version had Codex pin the real `~/.codex` through an
ambient runtime. I deleted that work, and the reasons follow.

**Codex has no agent handler.** Claude runs the `haiku`, `mixed`, and `sonnet` presets as
`{"type": "agent"}` hooks in `claude_native.generated_hooks`. Codex cannot copy that shape.
The Codex hooks reference at https://learn.chatgpt.com/docs/hooks lists `command` and
`mcp_tool` as the supported handlers, then states that Codex parses a `prompt` or `agent`
handler and skips it. An agent handler there dies without a message.

**The SDK is the better mechanism regardless.** An agent hook spawns a full agent turn,
because its prompt tells the agent to inspect the written file. The SDK call sends only the
candidates and a rubric. It forces a JSON reply through `output_schema`, and it runs
ephemeral, read only, and deny all. `_reject_tool_items` fails the verdict on any tool item.
One request, one structured answer, no tool loop. That costs fewer tokens than the agent hook.

**The scratch home already does the whole job.** Luna needs the login and nothing else.
`luna_storage._link_verified_auth` hardlinks `auth.json` into a 0o500 call directory, so
nothing copies the secret. The scratch `config.toml` carries an empty `[mcp_servers]` table.
Pointing at the real `~/.codex` would load every MCP server the user configured there into
each judge call, which D0 forbids.

**The price, stated.** The SDK path needs `~/.adw/runtime/codex/venv` carrying the pinned
`openai-codex` release. An agent hook needs no install. That burden buys the token saving and
the tighter sandbox.

### Judge mechanism per host

- Claude, presets `haiku`, `mixed`, and `sonnet`. Native agent hooks.
- Claude, preset `luna`. Command handler into the SDK, because a Claude agent hook carries no
  OpenAI model.
- Codex. The same SDK path. Luna belongs to the account, so nothing crosses a boundary.
- OMP. Native through `completeSimple` in process. A coder platform already orchestrates its
  models, so an SDK detour there would cost more than it saves.

### Deleted on reversal

- `codex_ambient.py`, which had no caller.
- `luna_types.py`, which existed only so that module could share types without importing a
  host. `LunaProviderFailure` and `RuntimePaths` moved back into `luna_storage.py`.
- `SdkLaunch.home_confined` and the two worker payload keys that carried it.

### Kept from the reversed work

`codex_runtime.py` became `luna_runtime.py`, because it resolves the Luna worker interpreter
rather than anything Codex owns. That cut the last core-to-host edge and stands on its own.

## D7. Claude carries an installer after all, for its CLI only

D4 said `hosts/claude` carries none, because the plugin is that path. Building Phase 3 showed
that leaves one artifact homeless.

`bin/adw-judge` takes a Claude preset, namely `mixed`, `luna`, `haiku`, `sonnet`, or `status`.
Nothing else uses it. The old `install.sh` linked it on every run, along with a PATH block in
`~/.zshrc` and `~/.bashrc`. Those three writes landed whether or not the user picked Claude,
which breaks the D4 acceptance that an installer writes only its own surface.

Three options existed. Link it always, which is the write D4 forbids. Drop the CLI, which
removes a working capability nobody asked to lose. Or give Claude an installer for the CLI
alone.

Claude therefore owns `hosts/claude/install.sh`. It writes the launcher link, the rc block,
and the legacy settings cleanup. It writes no hook wiring, and it prints the plugin commands
instead. D4 holds everywhere it matters, because a user who does not pick Claude gets none of
those three paths.

`--claude-legacy` survives inside that installer rather than in the router, so the path-based
wiring keeps its test rather than disappearing with the old script.

## Phase 3 complete on 2026-08-30

`install.sh` routes and no longer installs. It resolves the interpreter, asks
`hooks/host_picker.py` for a selection, deploys the isolated copy, then runs each chosen
`hosts/<name>/install.sh` with `ADW_SKILL_DIR` and `ADW_PYTHON`.

The picker runs before the router copies anything, so cancelling leaves the disk untouched.

`lib/picker_state.py` holds the pure state machine. Arrows, space, Enter, the SGR mouse
release, and every refusal each have a test. A press without a release does nothing, a click
on a detail line selects nothing, and a right button does nothing.

Two defects surfaced only because the checkpoint ran the real thing. A vendored runtime
shipped no `install.sh`, so it could not install itself. And `host_manifest.load_all` demanded
all four manifests, which crashed inside a vendored runtime that by design carries one. The
reader now skips an absent manifest and still raises on a malformed one.

## D8. The plugin cache gets a nuclear refresh, and the state tree never does

Ported from the user's VBW `update` command on 2026-08-30. The need was concrete rather than
theoretical. The cache held two revisions, `75f7111e0b54` and `c61ca234d605`, and Claude Code
loaded the older one.

**The boundary.** The wipe touches
`~/.claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher` and
`~/.claude/commands/adw`. It never touches `~/.adw`, which holds the settings, the ledger, the
reports, the session leases, and the pinned Codex runtime. A test seeds a config file there
and asserts it survives.

**The guards.** `lib/claude_cache.py` checks the path tail rather than trusting the join,
because one wrong variable moves the whole target. It refuses a path outside the config root
and refuses a symlink rather than following it.

**Three differences from VBW, each forced by ADW.** ADW ships no version file, so the check
compares `git ls-remote` against the recorded `gitCommitSha`. ADW has no statusline, so that
step drops. And `plugin.json` keeps no version field, because
`test_manifest_uses_commit_sha_updates` pins ADW to commit-based updates. Adding one broke
that test, and the test won.

**Carried over unchanged.** Every `claude plugin` call needs `unset CLAUDECODE` first, and the
marketplace refreshes before the install so a stale checkout cannot re-cache old code.

A Claude install now performs this by default. `ADW_SKIP_PLUGIN=1` opts out, which the test
suite uses so it never reaches the plugin system.

## The deployment gap this exposed

Task 4b fixed the frontmatter mask in the checkout, and the live gate kept blocking every
`name:` line for hours afterwards. Claude Code runs the plugin cache, not the working tree.

That made ADW unable to write a Claude Code command file for itself, because a command needs
frontmatter and frontmatter tripped `prose_colon`. `commands/update.md` shipped without
frontmatter for exactly that reason.

The loop closed after the push. Cache went from two revisions to `53fed2c982d5`, and the three
parked memory files wrote cleanly on the first try.

**The lesson worth keeping.** A fix that is green in the checkout is not a fix the gate
applies. Deployment is a separate step, and now it has a command.

## Known debt in the three files this touched

`claude_luna.py`, `codex_luna.py`, and `journal.py` carry pre-existing findings and twelve
oversized functions between them. None of it came from this change, and none of it blocks the
split. It earns its own pass rather than a drive-by.

## Blocked on research

- What the shared core delivery looks like, waiting on the Cowork VM runtime facts.
- What parity level the OMP contract demands, waiting on the Pi subagent event facts.

## Memory facts, written on 2026-08-30

All three landed once the plugin cache carried the frontmatter mask. They live under the
project memory directory and appear in `MEMORY.md`.

1. `questions-must-carry-suggestions`. Every question put to the user carries concrete
   options and a named recommendation. Finding facts and framing choices is my job.
   Picking is theirs.
2. `global-claude-md-is-binding`. The global CLAUDE.md shape rules are hard requirements.
   The user has ADHD and depression, so a dense paragraph blocks reading outright.
3. `research-agents-use-deepseek-or-sonnet`. Explore and research subagents run DeepSeek
   v4 Flash first and Sonnet 5 second. Never Haiku, which hallucinates on research. Pass
   the model on every call, because the default can resolve to Haiku silently.
