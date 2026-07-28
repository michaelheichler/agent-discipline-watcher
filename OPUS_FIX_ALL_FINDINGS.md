# Opus Command: Fix All ADW and Hookify Findings

Copy the prompt below into a fresh Claude Code session using Opus.

```text
You are the primary implementation agent for this repository:

/Users/michael/dev/skills/agent-discipline-watcher

Work autonomously through the entire task. Fix every confirmed defect, bypass, false positive, dead integration, and incomplete installation path described below. Do not stop after fixing only the first issue. Do not merely write a plan. Inspect, implement, test, document, and report the completed result.

## Context (carry forward)

A prior read-only investigation found:

1. Eight project-level Hookify rules were added under `.claude/`:
   - `live-client-config`
   - `live-config-via-shell`
   - `sandbox-install`
   - `no-verify-commit`
   - `discipline-bypass`
   - `project-config-silencing`
   - `claude-wiring-checklist`
   - `commit-message-shape`
2. `.claude/hookify-rules-check.py` reportedly exercised Hookify's real `pretooluse.py` and `stop.py` engine with 37 payloads.
3. The repository suite reportedly had 594 passing tests and the ADW scanner reported no findings on those new files.
4. `.claude/` is currently untracked and may contain valuable project-discipline work. Treat it as existing user work, not disposable output.
5. A real false positive remains in `live-config-via-shell`: it can interpret stderr redirection such as `2>/dev/null` as a write to a protected live-client path. Write redirections must still be blocked, but harmless stderr redirections such as `2>/dev/null` and `2>&1` must not be treated as mutations.
6. `hook-change-needs-pytest` may over-block because merely mentioning or reading `hooks/*.py` can count as touching it. Replace transcript-mention heuristics with the most reliable evidence available from tool activity. It must block only when relevant hook implementation was actually changed without the required verification, not when files were only read.
7. `hooks/run.sh` reportedly uses:
   `DISPATCH="SessionStart:session_start.py PreToolUse:pre_write.py PreCommit:pre_commit.py PostToolUse:record.py Stop:"`
   This leaves `stop.py` unreachable despite registering the Stop event.
8. These modules were also reported as unreachable:
   - `hooks/subagent_stop.py`
   - `hooks/batch.py`
   - `hooks/failure.py`
   - `hooks/prompt_submit.py`
9. The associated Claude hook configuration reportedly does not register all required events.
10. `hooks/claude-settings.snippet.json` reportedly uses:
    `"if": "Bash(git commit *)"`
    Its compatibility with the real Claude hook matcher is unproven. Installed plugins reportedly use forms such as `Bash(git commit:*)` or `Bash(git push*)`. Do not guess which syntax is correct. Verify it against current official Claude Code documentation and, where possible, the real matcher/runtime.
11. The ledger reportedly contains PostToolUse entries but no confirmed PreCommit entries. This is evidence requiring investigation, not proof by itself.
12. ADW currently has no general path-policy or Bash-command-policy layer corresponding to several Hookify protections.
13. Existing architectural constraints reportedly include:
    - all emitted ADW findings block
    - a warn/advisory tier was deliberately removed
    - command-bearing configuration must remain inert until user-owned authorization exists
    - planned tamper seals must prevent an agent from weakening its own quality configuration
14. Existing Love Projects planning artifacts reportedly mention related work such as:
    - `E2-W-T0`
    - `E2-W-T1`
    - `E3-W-T1`
    - `E4-S1`
    - `E4-S2`
    - `E6-S8`
    - `E10-T0`
    These identifiers are leads only. Verify their actual definitions and statuses.
15. Claude installation currently substitutes `__SKILL_DIR__` with an absolute checkout path through `merge-claude-settings.py`. Moving the checkout can therefore break installed hooks.
16. The desired Claude installation mechanism is the official Claude plugin flow, using current supported plugin manifests and commands, conceptually:
    - `/plugin marketplace add ...`
    - `/plugin install agent-discipline-watcher@...`
17. The intended plugin layout may include:
    - `.claude-plugin/plugin.json`
    - marketplace metadata where genuinely required
    - `hooks/hooks.json`
    - `skills/agent-discipline-watcher/SKILL.md`
    - optional commands only if they are directly required
    - `${CLAUDE_PLUGIN_ROOT}` in hook commands instead of absolute paths
18. The following plugin questions were not yet proven:
    - whether a local directory is accepted as a marketplace source
    - whether installed plugins are copied or linked
    - which desired hook events are currently supported
    - how legacy path-based Claude wiring is removed safely during migration
19. `install.sh` must continue to support Codex, OpenCode, and Pi. The Claude branch should migrate to the official plugin installation route rather than eliminating non-Claude installation support.
20. The working tree already contains unrelated or in-progress changes, including `.love-projects/adw-hooks/runs/run-e1s1t1/run.json` and the untracked `.claude/` tree. Preserve them.

## Mandatory first phase: repository and planning archaeology

Before editing implementation files:

1. Inspect `git status` and the complete relevant diff/untracked files.
2. Read all applicable repository instructions.
3. Discover and inspect the existing `.love-projects/` tree, including archived/old planning files, task records, requirement decisions, acceptance criteria, run records, and status markers.
4. Do NOT reinstall, initialize, regenerate, upgrade, or replace Love Projects. The existing files are historical evidence.
5. Search for every task or requirement that supports, anticipates, contradicts, or duplicates the findings above.
6. Build a private traceability matrix containing:
   - finding
   - verified current behavior
   - backing Love Projects requirement/task and its status
   - whether the finding is expected/planned but outstanding, incorrectly marked complete, partially implemented, an unplanned gap, or a false report
   - severity: normal backlog gap or major miss
   - implementation and verification required
7. Treat a completed task whose acceptance criteria are not live/reachable as a major miss unless repository evidence proves that the task intentionally covered only scaffolding.
8. Do not use planning status as an excuse to leave a confirmed defect unfixed. The goal of this session is to fix all confirmed findings, including planned-but-outstanding work that directly backs them.
9. If task scope conflicts with an immutable architectural decision, preserve the decision and implement the protection coherently rather than silently reintroducing a rejected design.

## Implementation requirements

### A. Repair and verify the Hookify project rules

1. Read every rule and its test harness under `.claude/`.
2. Preserve the useful rules and make them suitable for project version control.
3. Fix `live-config-via-shell` so:
   - real mutations through `>`, `>>`, `tee`, `sed -i`, `cp`, `mv`, `ln`, `rm`, and equivalent covered operations remain blocked when they target protected live-client surfaces
   - harmless stderr handling such as `2>/dev/null`, `2>>...`, `2>&1`, and equivalent non-mutating forms does not trigger solely because it contains `>`
   - mixed commands that genuinely mutate a protected path remain blocked even when they also contain harmless stderr redirection
4. Fix `hook-change-needs-pytest` so reads, searches, transcript mentions, and path references alone cannot trigger it. Base "changed" on actual mutating tool activity or another reliable repository/runtime signal. Add positive and negative regression tests.
5. Keep protected path patterns narrow enough not to block Claude's session scratchpad, memory directory, ordinary project `.claude/` files, or read-only inspection.
6. Decide from repository policy whether these project-discipline rules belong in version control. If yes, make the minimum `.gitignore` adjustment needed. Do not ignore or delete them merely because Hookify also supports personal `*.local.md` rules.
7. Run the test harness through Hookify's real engine, not a reimplementation of its matching behavior.

### B. Make every existing ADW hook module reachable

1. Audit the complete hook module set, dispatcher, Claude hook configuration, installer wiring, and tests.
2. Correct `hooks/run.sh` so Stop dispatches to `stop.py`.
3. Wire every currently intended module to its proper supported event:
   - `stop.py`
   - `subagent_stop.py`
   - `batch.py`
   - `failure.py`
   - `prompt_submit.py`
4. Do not invent unsupported Claude events. Verify each event name and payload contract against current official Claude Code documentation and the real installed/runtime behavior where feasible.
5. If an ADW module targets an event Claude Code does not support:
   - do not leave it silently dead
   - adapt it to the closest semantically correct supported integration only if behavior remains correct
   - otherwise keep it explicitly non-Claude, document the limitation, and classify it accurately in the final report
6. Add dispatcher tests for every valid route, unknown events, malformed invocations, and fail-safe behavior.
7. Add integration-style tests proving that configuration registration reaches the intended module, not merely that a string literal exists.
8. Ensure no unknown hook key can make the entire plugin/configuration fail to parse.

### C. Prove and repair the commit gate

1. Verify the correct current Claude matcher syntax for `git commit` Bash calls using official documentation and real behavior where feasible.
2. Replace the existing `Bash(git commit *)` filter if it is invalid or incomplete.
3. Test common forms, including:
   - `git commit`
   - `git commit -m "..."`
   - `git commit --amend`
   - global git options where applicable
   - commands that are not commits, such as `git log -n 5`
4. Prove that a commit attempt reaches `pre_commit.py`.
5. Prove that a staged known finding blocks the commit and produces the expected ledger evidence.
6. Prove that a clean commit attempt is allowed.
7. Use an isolated temporary repository and sandboxed HOME. Do not create a real project commit merely to test the gate.

### D. Bring justified Hookify protections into ADW coherently

Implement ADW-native coverage for the protections represented by the project Hookify rules where ADW lacks an equivalent:

- direct file writes to protected live-client configuration/install surfaces
- shell-mediated writes to those same surfaces
- unsandboxed installer or merge-script execution
- `git commit --no-verify` and `git commit -n`
- discipline-cap/kill-switch overrides used as bypasses
- deletion of watcher state used as a bypass
- edits that silence `.agent-discipline.json`
- hook wiring changes that require synchronized dispatcher/configuration/documentation/sandbox proof
- commit-message shape enforcement if backed by the repository's active requirements

Requirements:

1. Reuse existing ADW architecture and finding types where possible.
2. Do not add a general-purpose command execution facility.
3. Do not execute user-authored command-bearing configuration.
4. Do not reintroduce a warn/advisory finding tier if the repository deliberately forbids it.
5. Rules that can block must be built-in or loaded only through a user-owned, tamper-resistant trust boundary.
6. The agent must not be able to weaken or edit its own blocking quality policy during a session.
7. Implement the planned tamper-seal work needed to make this safe if the relevant Love Projects tasks are outstanding and directly support these findings.
8. Keep reads and legitimate sandbox operations allowed.
9. Add precise positive, negative, bypass, quoting, path-normalization, and false-positive tests.
10. Only implement protections justified by the findings and active requirements. Do not create an unrelated generic policy framework or speculative feature set.

### E. Migrate Claude installation to the official plugin mechanism

1. Use current official Claude Code plugin documentation as the source of truth. Installed third-party plugins may be supporting evidence but are not authoritative.
2. Create the minimum valid plugin structure required for ADW.
3. Use `${CLAUDE_PLUGIN_ROOT}` for plugin hook commands. No checkout-specific absolute paths may be embedded.
4. Convert the existing Claude hook configuration into the supported plugin `hooks/hooks.json` format while preserving all valid behavior.
5. Include the existing ADW skill in the plugin through the supported plugin layout.
6. Add marketplace metadata only where required for the selected installation/update flow.
7. Establish a reproducible development-validation path. Explicitly verify whether local marketplace sources are supported and whether installation copies or links plugin content.
8. Update README/install documentation with exact official commands and clearly distinguish:
   - local development/testing
   - marketplace installation
   - updating
   - uninstalling
   - legacy migration
9. Change `install.sh` so:
   - Claude users are directed through the official plugin mechanism
   - Codex, OpenCode, and Pi installation continues to work
   - automated/noninteractive behavior remains clear and testable
   - it does not pretend that typing an interactive `/plugin` command can be done by an ordinary shell script if Claude does not support that
10. Handle upgrades from legacy path-based Claude wiring:
    - detect the old ADW entries
    - remove only ADW-owned legacy entries
    - preserve unrelated user settings exactly
    - make the migration idempotent
    - prove it against sandbox HOME fixtures
11. Do not mutate `~/.claude/settings.json` or any other live client installation during this task.
12. Do not publish a marketplace, push a repository, or install the plugin into the live user profile. Prepare and verify the repository implementation, then provide the exact commands the user can run.
13. If a requested plugin behavior is not supported by current Claude Code, document the verified limitation and implement the safest supported alternative rather than fabricating support.

### F. Synchronize Love Projects records and documentation

1. Update existing `.love-projects/` task/status/acceptance records only when their repository format expects implementation sessions to do so.
2. Never rewrite history or regenerate old records.
3. Mark a task complete only when all its acceptance criteria are implemented and verified.
4. Reopen or correct a task that is marked complete but demonstrably nonfunctional, preserving an audit trail in the project's established format.
5. Link newly discovered unplanned gaps to the closest existing epic/story rather than inventing duplicate work.
6. Ensure README statements, installation instructions, hook-event tables, dispatcher mappings, tests, and planning status all agree.

## Safety and working-tree constraints

- Preserve all pre-existing tracked and untracked user changes.
- Never use `git reset --hard`, `git clean`, blanket checkout/restore, or destructive equivalents.
- Never discard or overwrite `.claude/` or `.love-projects/`.
- Do not stash user work.
- Do not edit live client configuration under the real HOME.
- Use the session scratchpad and sandbox HOME directories for temporary data.
- Do not install dependencies unless already declared and genuinely required. Stop and ask before adding a new dependency.
- Stop and ask before deleting files, changing public compatibility guarantees, publishing anything, pushing, or making a live installation.
- Do not commit. Leave the complete verified diff for review.
- Only make changes directly required by this task. Do not perform unrelated refactors or add speculative abstractions.
- If existing unrelated changes overlap a required file, merge carefully and preserve their intent. Do not assume the entire current diff belongs to this task.

## Verification requirements

Run all applicable checks, including:

1. Focused tests for every repaired or added behavior.
2. The complete repository test suite.
3. The Hookify real-engine payload suite, expanded with regressions for:
   - stderr redirection
   - actual protected-path redirection
   - reads versus writes
   - hook file read versus mutation
   - mutation with and without subsequent pytest evidence
4. ADW's own scanner against every changed source, test, configuration, documentation, and planning file.
5. Plugin structure/manifest validation using the current official validator or supported validation method.
6. Sandbox installation and legacy migration tests.
7. Dispatcher and hook-event integration tests.
8. A sandbox commit-gate smoke test proving actual `pre_commit.py` invocation.
9. Idempotency: repeat installation/migration validation and prove the second run creates no duplicate entries or unintended changes.
10. Search the final repository for stale `__SKILL_DIR__`, obsolete absolute-path Claude wiring, dead dispatch mappings, and contradictory installation instructions.

Do not weaken or delete tests merely to obtain a green result. If a check fails, investigate and fix the cause. If an external limitation makes a check impossible, report the exact command, output, and limitation.

## Definition of done

Do not stop until all of the following are true:

- Every finding above has been investigated and classified.
- Every confirmed, repository-fixable issue has been fixed.
- Every intended supported hook module is demonstrably reachable.
- The commit gate has runtime evidence, not only a literal-string test.
- Hookify false positives have regression coverage.
- ADW has coherent native protection for the justified bypass/path policies.
- Claude installation is represented as a valid official plugin with no hardcoded checkout path.
- Non-Claude installers remain supported.
- Legacy Claude wiring migration is safe and idempotent.
- Love Projects records accurately reflect implementation reality.
- Full tests and scanners pass.
- No live user configuration was changed.
- No commit or push was made.
- No pre-existing work was lost.

## Final response format

Lead with the outcome. Then provide:

1. **Implemented fixes**: concise bullets with file references.
2. **Love Projects traceability**: a table with:
   - finding
   - task/requirement
   - prior status
   - classification
   - severity (`normal backlog` or `major miss`)
   - final status
3. **Plugin migration**: resulting layout, verified official installation/update/uninstall commands, and legacy migration behavior.
4. **Verification evidence**: exact commands and pass/fail counts.
5. **Working-tree summary**: changed/new files and confirmation that unrelated changes were preserved.
6. **Remaining limitations**: only externally blocked or genuinely unsupported items. Do not list repository-fixable work as "future work."
7. **User actions**: only actions that require explicit user control, such as installing the plugin in the live Claude profile.

Do not claim completion without test evidence. Do not hide skipped checks.
```

> **Agentic-access warning:** This prompt is for Claude Code with real system access. Review its scope locks, forbidden actions, and stop conditions before running it.
