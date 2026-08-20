# Implementation Plan: Fix ADW settings.json override + hook ejection, clean up stale worktrees

## Context

Another agent (Kilo Code) ran a parallel "restore intelligent hard blockers" effort in
`.kilo/worktrees/`, on six branches all forked from commit `86a0db9`. Meanwhile this repo's
`main` branch did its own, independent line of fixes for the same problem
(`2a05b47` restore strict hard blockers, then `75a9cd5`, `7f0ddbc`, `d7e36db`, `6348314`, and
`328d498` preserve blockers through agent loop). `86a0db9` is an ancestor of `main`, so the
Kilo effort is fully superseded and orphaned. That is the "mess."

On top of the cleanup, two concrete bugs were reported:

1. The self-protection gate blocks writes to a live `.claude/settings*.json`, but the block
   message gives no way out, so it reads as unconditionally unblockable.
2. Hooks were reported as ejecting the agent out of the write loop instead of blocking one
   write and letting the agent retry within the same turn.

Research against the official Claude Code hooks reference
(`code.claude.com/docs/en/hooks`, "exit code 2 behavior per event" section) and this repo's
own source was done before proposing fixes, per your instruction.

## Finding 1: settings.json block already has an override, but it is not advertised

`hooks/lib/protected.py` blocks writes to `~/.claude/settings*.json` (and nested
skills/agents/hooks/commands under a live `~/.claude`) as `live_client_surface`, one of the
`ALWAYS_BLOCKING_RULES` (`hooks/lib/config.py:41-43`) that no `.agent-discipline.json` gate
can weaken.

An override already exists and is well designed:

- `ADW_ALLOW_PROTECTED_EDIT=1` (env var, `protected.py:17-39`) short-circuits `path_findings()`
  entirely (`protected.py:80`).
- It is deliberately env-var only, never a config-file flag. `authorized()` ignores its
  `config` argument on purpose, because a config file is something the agent itself can edit
  (`protected.py:42-45`).
- The agent is separately blocked from setting this env var inline in a Bash command by a
  hookify rule (`.claude/hookify.discipline-bypass.local.md`), so only a human exporting it in
  their own shell can grant the escape.

The actual bug: the block message the user sees for this rule, `LIVE_ACTION`
(`protected.py:28`), says only "Change the repo source and reinstall instead of editing the
live install." It never mentions `ADW_ALLOW_PROTECTED_EDIT`. Compare `GRANT_ACTION`
(`protected.py:31-35`), used for the sibling `config_seal` rule, which does name the env var.
So the override works, but nothing tells the user (or the agent) it exists. "Must be
unblocked" was reported because the escape hatch is invisible, not missing.

Fix: update `LIVE_ACTION` to name `ADW_ALLOW_PROTECTED_EDIT` the same way `GRANT_ACTION` does.
No change to the blocking logic itself. It should stay a hard block by default.

## Finding 2: no ejection path in current hook source, but the live install is stale

Per the official reference, three mechanisms matter here:

- `PreToolUse` via `hookSpecificOutput.permissionDecision: "deny"` always feeds the reason back
  to Claude and continues the turn. No `continueOnBlock` needed. `hooks/lib/hookio.py`'s
  `deny()` plus `claude_pretool_response()` already emit exactly this shape (the legacy
  top-level `"decision"` field is stripped before writing).
- `PostToolUse`'s legacy `decision: "block"` ends the turn unless `continueOnBlock: true` is
  set on the hook. Current `record.py` never emits a raw `decision: "block"` for `PostToolUse`.
  `claude_feedback_response()` converts everything to `advise()` (systemMessage plus
  `additionalContext`, no `decision` key), which cannot end a turn.
- `PostToolBatch` has no `continueOnBlock` escape at all, per the reference's per-event table.
  The turn always ends if it blocks. `batch.py` as of `328d498` also routes through
  `advise()`-only output for the same reason. That is why `"continueOnBlock": true` was
  removed from `hooks.json`'s `PostToolUse` entry in that commit: nothing left emits a raw
  block there, so the flag had become dead config.
- `Stop` and `SubagentStop` returning `decision: "block"` is their documented, native way to
  keep Claude working past a stop attempt. This is the correct block-and-resume pattern, not
  ejection. `stop.py` and `subagent_stop.py` already use it via the `blocker_state` and
  `end_turn.unresolved_reason()` machinery added in `328d498`.

Grepping all of `hooks/*.py` and `hooks/lib/*.py` found no `exit()`, `os._exit`, or other
session-terminating call outside the documented hook JSON protocol.

However: the actually-installed plugin cache
(`~/.claude/plugins/cache/agent-discipline-watcher/agent-discipline-watcher/328d498dfc12`) is
missing `hooks/lib/blocker_state.py` even though its directory is tagged with that exact commit
hash. The live runtime does not faithfully match this repo's `main` at that commit. The
marketplace clone (`~/.claude/plugins/marketplaces/agent-discipline-watcher`) does match `main`
correctly. Only the plugin cache snapshot is short a file. This means what the user has been
observing live may be older, pre-`328d498` hook behavior, not what is in source now.

Fix: no source change is indicated by the design review above. Instead:
- Reinstall or refresh the live plugin cache from the current marketplace source so the running
  hooks match `main`.
- Run a live probe (one blocked write, one retry that resolves it, one Stop-hook forced
  continuation) to confirm the turn survives a block end to end.
- If the live probe still reproduces ejection after the cache is fresh, that is a real,
  currently unknown regression and needs a follow-up debugging pass. Flag it rather than
  guessing further.

## Cleanup: stale Kilo worktrees

Per your answer, remove the 4 clean worktrees and branches (`86a0db9`, no local edits):
`audit-pre-autorewrite-matrix`, `review-strict-hardblock-final`, `test-pre-autorewrite-parity`,
`fix-restore-pre-autorewrite-standard`. Leave `fix-strict-hardblock-contract` and
`test-strict-hardblock-contract` in place. They carry uncommitted edits (an earlier, superseded
rewrite of `scanner.py`, `adjudication.py`, and `config.py`, plus a new test file) for you to
review by hand before anything touches them.

## Task List

### Phase 1: Fix the settings.json override message
- [ ] Task 1: Update `LIVE_ACTION` in `hooks/lib/protected.py` to name `ADW_ALLOW_PROTECTED_EDIT`
      as the supported escape, matching `GRANT_ACTION`'s pattern.
- [ ] Task 2: Add or extend a test in `hooks/test_self_protection_invariants.py` (or
      `hooks/lib/test_protected.py`) asserting the `live_client_surface` finding's action text
      names the env var, mirroring the existing `config_seal` coverage.

### Checkpoint: Phase 1
- [ ] `python -m pytest hooks -k protected or self_protection` passes.
- [ ] Full repo test suite and pylint still clean.

### Phase 2: Verify the turn-continuation fix live
- [ ] Task 3: Refresh the installed plugin (reinstall from the marketplace source or run the
      update command) so the live cache matches `main` at `328d498`, confirming
      `blocker_state.py` is present in the active cache snapshot.
- [ ] Task 4: Run a live Claude Code probe: one write that trips a hard block, one retry that
      resolves it in the same turn, and one case that forces a Stop-hook continuation. Confirm
      none of them end the turn early.

### Checkpoint: Phase 2
- [ ] Live probe confirms block-then-continue with no premature turn end.
- [ ] Any surviving ejection behavior is written up as a new, separately scoped bug, not patched
      speculatively.

### Phase 3: Repo cleanup
- [ ] Task 5: Remove the 4 clean stale worktrees and their branches
      (`git worktree remove`, `git branch -D`).

### Phase 4: Review
- [ ] Task 6: Run `/code-review-and-quality` over the Phase 1 diff via `Workflow`, using an
      Opus 5 pass at medium effort for the broad multi-axis review and a Sonnet 5 pass at high
      effort for focused checkups, per your instruction. Apply any confirmed findings.

### Checkpoint: Complete
- [ ] All acceptance criteria met, full suite green, review findings resolved or explicitly
      deferred with reason.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Live probe still reproduces ejection after cache refresh | Medium. The reported bug is real and not just stale-install confusion | Stop and scope a fresh debugging task instead of patching blind |
| Widening `LIVE_ACTION`'s wording accidentally softens the block itself | Low but self-protection-sensitive | Change only the message text. Do not touch `path_findings` or `_claude_rule` matching logic |
| Deleting the clean worktrees turns out to also lose something | Low. Confirmed ancestor-only, no unique commits | Run `git branch -D` only after `git worktree remove`. Branches stay recoverable via reflog until GC if this is wrong |

## Open Questions
- None blocking. The two clean-vs-dirty worktrees to leave alone are already decided.
