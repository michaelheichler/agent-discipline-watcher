# Agent Discipline Watcher

Agent Discipline Watcher is one hook package for keeping agent output and edits direct, plain, and reviewable. It replaces the older punctuation-discipline, english-for-agents, and clean-coder-discipline packages with one scanner, one ledger, one compact report path, and one Pi extension.

It exists to catch low-level agent drift before it lands in files or final replies: banned punctuation, inflated prose, deferred-work comments, noisy code comments, hollow tests, oversized code shapes, reflexive flattery, and empty agreement.

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
hooks/run.sh Stop
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
| `SessionStart` | Clears stale ledger state and injects the compact watcher reminder. |
| `PreToolUse` | Scans pending write or patch content and blocks forced deterministic findings before the write runs. |
| `PreCommit` | Watches Bash `git commit` commands, scans staged ACM files, and blocks forced deterministic findings before the commit runs. |
| `PostToolUse` | Records findings from written files into the session ledger. |
| `Stop` | Reads ledger findings, runs optional model juries, and emits one compact block or advisory message. |

PreCommit parses the shell command heuristically. Commits launched through `sh -c`, `xargs`, shell aliases, or wrapper scripts are not scanned.

## Stop And Model Jury Behavior

Stop always runs deterministic ledger findings. When the related checks are enabled and model resources can load, Stop also runs the model-backed English jury over touched prose files and the model-backed Clean Coder jury over touched code files.

Model failures fail soft. If a model cannot load, is out of capacity, or raises an exception, deterministic findings still report and the session continues with the model jury skipped. If the jury fails in an unexpected way, Stop prints a warning to stderr and keeps going.

Reports are compact and token-lean. Hook output shows a bounded set of rows and writes full finding detail to a local temp JSON report. Model and host resources are released after Stop, including English pipeline unload, Clean Coder unload, and skill-model-loader turn release when available.

`hooks/run.sh` selects one Python runtime for all hook events. It prefers executable `SML_PYTHON`, then the sibling `skill-model-loader/.venv/bin/python`, then Clean Coder venvs, before falling back to `python3`. Set `ADW_SKILLS_ROOT` to point both run.sh and the Python model jury at a different skills workspace.

## Pi Behavior

The Pi extension:

1. Clears its in-memory ledger on `session_start`.
2. Adds a short policy prompt before the agent starts.
3. Scans write, edit, and multiedit tool results through the Python scanner.
4. Keeps findings in memory for the session.
5. Sends one compact steer message at `agent_end` when forced findings remain.

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

If Stop reports only deterministic findings, that can be expected. Model juries run only when the corresponding check is enabled and model loading is available.

If output is too short for diagnosis, open the `Full report:` JSON path printed by the hook. The model-facing message is intentionally compact.

If Pi does not steer after edits, verify that `~/.pi/agent/settings.json` includes the extension path under `pi/extensions/agent-discipline-watcher/index.ts`.

## License And Contact

This package lives in the local skills workspace. Use the surrounding repository license and maintainer process.
