# Agent Discipline Watcher

Agent Discipline Watcher is a Claude Code plugin that keeps agent output disciplined. Deterministic findings block at the configured gate, and only ambiguous comment findings use bounded Haiku adjudication. The main session model never changes.

## How It Works

Every tool call goes through `hooks/pre_tool.py`, which dispatches to the write, Bash, commit, or MCP gate. One process owns the permission result.

Pending writes are scanned before execution. Certain findings block without a model call. The ambiguous allowlist is `what_comment`, `what_docstring`, and `weak_why_comment`. Claude Code sends each such finding one bounded source request to the configured Haiku adjudicator. A confirmed violation blocks, a release allows the write, and an unavailable or malformed adjudication blocks with a retry-specific reason.

PostToolUse rescans the written file and can block continuation. It never mutates the file. Commit messages are scanned in place and are never rewritten.

The scanner uses one region extractor for mixed-language files. Markup, attributes, embedded style, embedded script, fenced code, and visible prose keep their original host line numbers.

## Comment Policy

Ordinary code comments are scanned by deterministic rules. Ambiguous WHAT and WHY classifications go through the bounded adjudicator. A concrete WHY comment can be released, while a confirmed narration comment blocks.

## Install

### Claude Code

```text
/plugin marketplace add michaelheichler/agent-discipline-watcher
/plugin install agent-discipline-watcher@agent-discipline-watcher
/reload-plugins
```

### Codex

`install.sh` wires Codex from this checkout. Codex uses deterministic blockers and does not use semantic adjudication.

```bash
./install.sh
./install.sh -y
./install.sh --no-claude --codex -y
```

## Requirements

Python 3, a Unix shell, and recent Claude Code. No minimum version is pinned in this repository. If a hook fails to register, update Claude Code and retry.

## Configuration

Project configuration lives in `.agent-discipline.json` at the project root. The hook code searches upward from the current working directory for it. See `hooks/lib/config.py` for the supported keys.

## Self Protection

The `self_protection` family blocks routes around the gates. It covers live client config, installer commands without a sandboxed `HOME`, no-verify commits, cap overrides, state deletion, and protected configuration edits. These rules cannot be disabled by project configuration.

## Active Integrations

Claude Code is the primary plugin surface. Codex support is deterministic and uses the checked-in `hooks/codex-config.snippet.toml` routes for `SessionStart`, `PreToolUse`, and `PostToolUse`. The installer merges those routes into `~/.codex/config.toml` without replacing unrelated settings.

Pi and OpenCode adapters are archived under `archive/integrations/`. They are retained as historical implementation references only. The installer, CI, release verification, and active documentation do not test or claim support for them.

## Verification

```bash
cd hooks && python3 -m pytest . lib -q
bash -n install.sh hooks/run.sh
claude plugin validate . --strict
```
