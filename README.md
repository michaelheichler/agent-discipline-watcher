# Agent Discipline Watcher

Deterministic discipline gates for agent output across **Claude Code**, **Codex**, and **OMP** (`oh-my-pi`). Current release: **0.17.5**.

Findings block at their configured gate. Strict code-comment findings always block.

## How It Works

Every tool call goes through `hooks/pre_tool.py`, which dispatches to the write, Bash, commit, or MCP gate. One process owns the permission result.

Pending writes are scanned before execution. The scanner is deterministic and never asks another model to release a finding.

PostToolUse rescans the written file and can block continuation. It never mutates the file. Commit messages are scanned in place and are never rewritten.

The scanner uses one region extractor for mixed-language files. Markup, attributes, embedded style, embedded script, fenced code, and visible prose keep their original host line numbers.

## Comment Policy

Code comments and docstrings may contain one strict WHY line. WHAT narration, weak reasons, consecutive prose comments, and multi-line docstrings block. Config, exemptions, and model output cannot release these rules.

## Install

### Claude Code

```text
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

### Codex

`install.sh` wires Codex from this checkout. Codex uses the same deterministic blockers.

```bash
./install.sh
./install.sh -y
./install.sh --no-claude --codex -y
```

### OMP (`oh-my-pi`)

`pi/install.sh` is the dedicated OMP installer. It symlinks the extension into `~/.omp/agent/extensions/agent-discipline-watcher` and registers `pi/extensions/agent-discipline-watcher/index.ts` in `~/.omp/agent/settings.json`. The main installer delegates to it when OMP is selected.

```bash
./install.sh                      # Claude + Codex + OMP
./install.sh --omp -y             # OMP only
./pi/install.sh -y                # OMP only (direct)
./pi/install.sh --remove -y       # uninstall OMP extension
./install.sh --no-claude --no-codex --omp -y
```

Set `PI_CODING_AGENT_DIR` to target a non-default OMP agent directory. Restart OMP after install, or pass `--extension` to load immediately.

## Requirements

Python 3, a Unix shell, and recent Claude Code. No minimum version is pinned in this repository. If a hook fails to register, update Claude Code and retry.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root. The hook code searches upward from the current working directory for it. See `hooks/lib/config.py` for the supported keys.

## Self Protection

The `self_protection` family blocks routes around the gates. It covers live client config, installer commands without a sandboxed `HOME`, no-verify commits, cap overrides, state deletion, and protected configuration edits. These rules cannot be disabled by project configuration.

Seven more rules in this family close the Bash write path: `inline_interpreter_write`, `shell_payload_block`, `interpreter_heredoc_write`, `dynamic_heredoc_write`, `decode_pipe_write`, `inplace_edit_write`, and `opaque_source_write`. Each blocks a Bash-mediated write the scanner cannot read through, such as `python3 -c` writing a file, a heredoc piped into an interpreter, a dynamic heredoc aimed at a file, a decode pipe ending in a write, `sed -i`, or `dd`. A literal write body the watcher can read, such as a clean `echo` or heredoc, is scanned like a Write or Edit tool call instead of blocked. Every deny message names the rule and points to the Write or Edit tool for the file content.

## Active Integrations

Claude Code is the primary plugin surface. Codex support is deterministic and uses the checked-in `hooks/codex-config.snippet.toml` routes for `SessionStart`, `PreToolUse`, and `PostToolUse`. The installer merges those routes into `~/.codex/config.toml` without replacing unrelated settings.

OMP (`oh-my-pi`) loads `pi/extensions/agent-discipline-watcher/index.ts` via `pi/install.sh`. The extension calls the same `hooks/run.sh` engine as Claude and Codex. `session_start` injects the SessionStart contract on the next turn. Pre-tool checks run on `tool_call` for `write` and `bash` and return `{ block: true, reason }`. Post-tool feedback is appended to `tool_result` content (path-only payloads; the engine rescans from disk). Unresolved findings block on `session_stop`. Self-protection covers `~/.omp/agent/` settings, extensions, and config.

OpenCode adapters are archived under `archive/integrations/`. They are retained as historical implementation references only. The installer, CI, release verification, and active documentation do not test or claim support for them.

## Verification

```bash
cd hooks && python3 -m pytest . lib -q
python3 -m pytest pi/test_merge_settings.py -q
bash -n install.sh hooks/run.sh pi/install.sh
bun test pi/extensions/agent-discipline-watcher/index.test.ts
claude plugin validate . --strict
```
