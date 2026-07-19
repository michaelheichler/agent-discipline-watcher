# Agent Discipline Watcher

Agent Discipline Watcher is one hook package for keeping agent output and edits direct, plain, and reviewable. It replaces the older punctuation-discipline, english-for-agents, and clean-coder-discipline packages with one scanner, one compact report path, and one Pi extension.

It exists to catch deterministic low-level drift before it lands in files: banned punctuation, inflated prose, deferred-work comments, noisy code comments, hollow tests, and oversized code shapes.

## What It Installs

`install.sh` can install three live surfaces:

| Surface | Live files |
| --- | --- |
| Claude | `~/.claude/settings.json`, `~/.claude/skills/agent-discipline-watcher` |
| Codex | `~/.codex/config.toml`, `~/.codex/skills/agent-discipline-watcher` |
| Pi | `~/.pi/agent/settings.json` |

The Pi surface loads `pi/extensions/agent-discipline-watcher/index.ts`.

The installer creates timestamped backups before changing existing Claude, Codex, or Pi settings. It also links `bin/agent-discipline` into `~/.local/bin/agent-discipline`.

## Installation

From this directory:

```bash
./install.sh
```

Non-interactive install:

```bash
./install.sh -y
```

Install only selected surfaces:

```bash
./install.sh --no-claude --codex --no-pi -y
./install.sh --claude --no-codex --no-pi -y
./install.sh --no-claude --no-codex --pi -y
```

## Codex Activation

After installing or changing Codex hooks, run `/hooks` in Codex and review the new hook commands. Trust the Agent Discipline Watcher hooks there before relying on them.

The Codex hook commands are installed into `~/.codex/config.toml` and call:

```bash
hooks/run.sh SessionStart
hooks/run.sh PreToolUse
hooks/run.sh PreCommit
hooks/run.sh PostToolUse
```

## Usage

The hooks run automatically after installation and client activation.

Use the CLI to view or set per-project checks:

```bash
agent-discipline status
agent-discipline status /path/to/project
agent-discipline configure
agent-discipline configure /path/to/project
agent-discipline configure --checks punctuation,english,clean_code
agent-discipline configure --checks punctuation,clean_code /path/to/project
```

`agent-discipline configure` opens an interactive selector. Choose numbered checks, `all`, `none`, or Enter to keep the current state.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root:

```json
{
  "checks": {
    "clean_code": true,
    "english": true,
    "punctuation": true
  }
}
```

The hook code searches upward from the current working directory for `.agent-discipline.json`. If no file is found, punctuation, English, and clean-code checks are enabled.

The Craftsman suppression marker is always blocked on every scanned file. Project check switches and path exemptions cannot disable this rule. Fix the reported issue instead.

Supported checks:

| Check | Purpose |
| --- | --- |
| `punctuation` | Blocks banned dash marks, double hyphen breaks, semicolon splices, incorrect apostrophe forms, and related punctuation tells. HTML `code`, `pre`, `script`, and `style` blocks are exempt, so inline CSS and generated markup never read as prose. |
| `english` | Blocks or reports inflated diction, filler, wordiness, AI tells, and plain-English issues. |
| `clean_code` | Blocks deferred-work comments, prose comment blocks, commented-out code, hollow tests, long functions, and related code hygiene issues. |

`max_rows` can be set in `.agent-discipline.json` to change how many compact report rows are shown before the full local report path.

`max_scan_bytes` can be set in `.agent-discipline.json`, or through the `ADW_MAX_SCAN_BYTES` environment variable, to cap how large a file the hooks will read. Files over the cap and files that look binary are skipped. The default is 1000000 bytes.

## Hook Lifecycle

| Event | Behavior |
| --- | --- |
| `SessionStart` | Injects the compact watcher reminder. |
| `PreToolUse` | Scans pending write or patch content and blocks forced deterministic findings before the write runs. |
| `PreCommit` | Watches Bash `git commit` commands, scans staged ACM files, and blocks forced deterministic findings before the commit runs. |
| `PostToolUse` | Rescans written files and immediately blocks agent continuation when forced findings remain. |

PreCommit parses the shell command heuristically. Commits launched through `sh -c`, `xargs`, shell aliases, or wrapper scripts are not scanned.

PreToolUse prevents a direct write before it runs. PostToolUse cannot undo a completed write, so a forced finding returns a blocking error that requires the agent to repair the file before continuing.

## Pi Behavior

The Pi extension:

1. Adds a short policy prompt before the agent starts.
2. Scans write, edit, and multiedit tool results through the Python scanner.
3. Turns a result with forced findings into an immediate error result that requires correction.

## Verification

Run the full test tree from `hooks/`:

```bash
cd hooks && python3 -m pytest . lib -q
```

Syntax-check the shell entry points from this directory:

```bash
bash -n install.sh hooks/run.sh
```

The hook code holds itself to its own contract: every function stays under the length cap and the scanner reports zero forced findings on its own files.

Useful manual checks:

```bash
agent-discipline status
agent-discipline configure --checks punctuation,english,clean_code /path/to/project
python3 hooks/merge-codex-config.py --help
python3 hooks/merge-claude-settings.py --help
python3 hooks/merge-pi-settings.py --help
```

## Troubleshooting

If hooks do not run in Codex, run `/hooks` and verify the Agent Discipline Watcher commands are trusted. Codex can require trust review after hook commands are added or changed.

If a project needs fewer checks, run `agent-discipline configure` in that project and disable only the unwanted check families.

If output is too short for diagnosis, open the `Full report:` JSON path printed by the hook. The agent-facing message is intentionally compact.

If Pi does not steer after edits, verify that `~/.pi/agent/settings.json` includes the extension path under `pi/extensions/agent-discipline-watcher/index.ts`.

## License And Contact

This package lives in the local skills workspace. Use the surrounding repository license and maintainer process.
