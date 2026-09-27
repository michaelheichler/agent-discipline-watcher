---
name: adw-nuke
description: Remove every ADW trace from this machine so a fresh install starts clean.
disable-model-invocation: true
argument-hint: <--dry-run|--yes>
---

Run the installed `adw-nuke` executable exactly once with the one argument supplied after this skill name.

Use the normal Bash tool with the argument quoted as one value:

```sh
adw-nuke "$ARGUMENTS"
```

The executable accepts only `--dry-run` or `--yes`. With no argument it prints the list and refuses.

Run `--dry-run` first. Show the user the full list it prints, one path per line, unchanged. Run `--yes` only after the user reads that list and asks for `--yes` in their own message. Never pick `--yes` on your own.

`--yes` deletes the whole `~/.adw` tree, including state, ledger, reports, caches, and the embedding model. It removes the Claude plugin records through the `claude` CLI and edits the JSON files directly when the CLI is absent or fails. It strips ADW entries from Claude, Codex, and OMP config files and from `~/.zshrc` and `~/.bashrc`, and keeps every other entry.

After `--yes`, relay the list of edited files it prints. Tell the user to restart Claude Code, Codex, and OMP, then run `./install.sh` from a checkout.
