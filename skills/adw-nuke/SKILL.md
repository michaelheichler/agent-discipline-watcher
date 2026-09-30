---
name: adw-nuke
description: Remove every ADW trace from this machine and install ADW again from a clean state, or remove it for good.
disable-model-invocation: true
argument-hint: <--dry-run|--yes|--uninstall>
---

# adw-nuke

## Goal

The user wants a clean ADW. With `--yes`, ADW runs again on every host it ran on before. It runs from a fresh copy, with no old state. With `--uninstall`, the result is a machine with no ADW at all. With `--dry-run` or no argument, the result is the list of what a removal touches, and nothing changes.

Only the user can start this skill, because its frontmatter sets `disable-model-invocation`. The argument the user typed is the user's decision. Carry it out in this turn. If a step fails, stop and ask.

## Tools you use

- The removal runs `"$HOME/.adw/bin/adw-nuke"`. Call it by this full path, because the shell often lacks `~/.adw/bin` on `PATH`.
- The reinstall runs `./install.sh` in a checkout of `michaelheichler/agent-discipline-watcher`.

## Steps for `--dry-run` or no argument

1. Run `"$HOME/.adw/bin/adw-nuke" --dry-run`.
2. Show every line it prints, unchanged, one path per line.
3. Tell the user the two next commands. `/agent-discipline-watcher:adw-nuke --yes` removes and reinstalls. `/agent-discipline-watcher:adw-nuke --uninstall` removes only.
4. Stop.

## Steps for `--yes`

Do these steps in this order. The order matters, because step 4 deletes `~/.adw/install`, and after that no copy of the installer stays on disk.

1. Find the checkout first.
   - If the current directory holds `install.sh` and `.claude-plugin/plugin.json` with `"name": "agent-discipline-watcher"`, use it. Run `git pull --ff-only` there, so the reinstall gets the newest release.
   - Otherwise, clone a fresh copy with `git clone --depth 1 https://github.com/michaelheichler/agent-discipline-watcher "$(mktemp -d)/adw"`. Use that directory.
2. Run `"$HOME/.adw/bin/adw-nuke" --dry-run`. Show every line it prints, unchanged.
3. Read the hosts from that list. A line under `.claude` means `--claude`. A line under `.codex` means `--codex`. A line under `.omp` means `--omp`. If the list names no host, use every host whose command exists, from `claude`, `codex`, and `omp`.
4. Run `"$HOME/.adw/bin/adw-nuke" --yes`. Keep its output for the report.
5. In the checkout, run `./install.sh` with the host flags from step 3, for example `./install.sh --claude --codex --omp`. The flags skip the interactive picker. The installer builds the principle text in `~/.adw/cache/principles.sqlite`, and it puts `~/.adw/bin` on `PATH` in the startup file of the login shell.
6. Check the result with the checks below.
7. Report in the shape of the example below.

### Checks after `--yes`

Each check is one command.

- `ls "$HOME/.adw/bin"` lists `adw`, `adw-config`, `adw-judge`, and `adw-nuke`.
- For Claude, `~/.claude/plugins/installed_plugins.json` names `agent-discipline-watcher`.
- For Codex, `~/.codex/hooks.json` names `agent-discipline-watcher`, and `~/.codex/agents/adw-test-writer.toml` exists.
- For OMP, `~/.omp/agent/settings.json` names `agent-discipline-watcher`.
- `~/.adw/cache/principles.sqlite` exists.

If a step fails, stop at that step. Show the command and its error output unchanged, and name the steps that did not run. A half-done reinstall that you report as done leaves the user with no gates and no warning.

## Steps for `--uninstall`

1. Run `"$HOME/.adw/bin/adw-nuke" --dry-run` and show every line unchanged.
2. Run `"$HOME/.adw/bin/adw-nuke" --yes`.
3. Report the edited files it prints. Tell the user to restart Claude Code, Codex, and OMP. Name `./install.sh` in a checkout as the way back.

## Actions only the user can take

Name these in every report after `--yes`, because an agent cannot run them.

1. In Claude Code, type `/reload-plugins`.
2. Restart Codex, then open `/hooks` and trust the new hooks.
3. Restart OMP.
4. Open a new terminal, so the shell reads the new `PATH` line.

## Example report after `--yes`

```text
Removed and installed again.

Removed:
- ~/.adw
- ~/.claude/plugins/cache/agent-discipline-watcher
- ~/.omp/agent/extensions/agent-discipline-watcher

Edited:
- ~/.claude/settings.json
- ~/.codex/hooks.json
- ~/.omp/agent/settings.json

Installed from ~/Development/projects/agent-discipline-watcher at b32157c for claude, codex, omp.
Checks passed: bin links, Claude plugin record, Codex hooks and test writer role, OMP extension, principle text.

Your steps:
1. Claude Code: /reload-plugins
2. Codex: restart, then /hooks and trust the new hooks
3. OMP: restart
4. Open a new terminal
```

## What `adw-nuke --yes` removes

It deletes the whole `~/.adw` tree. That includes state, the ledger, reports, caches, the principle text, and the embedding model. It removes the Claude plugin records through the `claude` CLI. If that CLI is absent or fails, it edits the JSON files directly. It strips ADW entries from the Claude, Codex, and OMP configuration files and from `~/.zshrc` and `~/.bashrc`. It keeps every other entry.
