# ADW Update $ARGUMENTS

Update ADW to the latest commit with a clean plugin cache. Pass `--check` to report without
changing anything.

## What this touches

It clears `~/.claude/plugins/cache/agent-discipline-watcher` and reinstalls from a clean
cache. It never touches `~/.adw`, which holds the settings, the ledger, the reports, and the
pinned Codex runtime.

ADW ships commit revisions rather than a version file, so every check below compares commits.

## Step 1, read the installed revision

```bash
"$CLAUDE_PLUGIN_ROOT/hooks/claude_cache_nuke.py" --revision
```

Store the result as `installed`. An empty answer means no recorded install, so treat this run
as a first install rather than an update.

## Step 2, handle the check flag

With `--check`, print the installed revision and the cached directories, then stop.

```bash
"$CLAUDE_PLUGIN_ROOT/hooks/claude_cache_nuke.py" --dry-run
```

## Step 3, read the remote revision

```bash
git ls-remote https://github.com/michaelheichler/agent-discipline-watcher refs/heads/main
```

Store the first field as `remote`. A failure here stops the run. Report that GitHub was
unreachable rather than guessing that the install is current.

When `remote` starts with `installed`, say so and continue anyway. A matching revision with a
stale cache is the exact case this command exists to repair.

## Step 4, clear the cache

```bash
"$CLAUDE_PLUGIN_ROOT/hooks/claude_cache_nuke.py"
```

It refuses a symlinked cache, and it refuses any path outside the config root. A refusal stops
the run, and the message names the path.

## Step 5, reinstall

Every `claude plugin` call needs `unset CLAUDECODE` first. Without it, Claude Code spots the
parent session and refuses the nested launch.

Refresh the marketplace before installing, because a stale checkout re-caches old code.

```bash
unset CLAUDECODE && claude plugin marketplace update agent-discipline-watcher
unset CLAUDECODE && claude plugin install agent-discipline-watcher@agent-discipline-watcher
```

When the install fails, try uninstall then install. When that fails too, print both commands
for the user to run, then stop.

## Step 6, verify

```bash
"$CLAUDE_PLUGIN_ROOT/hooks/claude_cache_nuke.py" --revision
```

Compare against `installed`. Report the old and the new revision. An unchanged revision after
an expected upgrade means the update did not apply, so say that plainly.

## Step 7, report

Name the old revision, the new revision, and every directory this run cleared. Tell the user
to run `/reload-plugins`, because the hooks load at session start.

## Refusing to guess

Report the real revisions. Never claim an update landed without the Step 6 read.
