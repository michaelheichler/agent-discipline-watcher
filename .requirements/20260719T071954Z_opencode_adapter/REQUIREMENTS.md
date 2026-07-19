# OpenCode Adapter

## As Is

Agent Discipline Watcher has one regex-only scanner and hook adapters for Claude Code, Codex, and Pi. OpenCode loads standard skills and Agentic Love plugins, but it does not invoke the watcher lifecycle.

## To Be

OpenCode forwards relevant tool and session events to the existing watcher hook runner. The adapter remains thin, keeps the Python scanner as the source of truth, and installs from the repository into the user OpenCode plugin directory.

## Requirements

1. Map OpenCode write-like `tool.execute.before` events to watcher `PreToolUse` payloads and block forced findings.
2. Map completed write-like `tool.execute.after` events to watcher `PostToolUse` payloads and block continuation when forced findings remain.
3. Map `session.created` to watcher `SessionStart` and `session.idle` to watcher `Stop` without creating an idle notification loop.
4. Resolve the watcher runner from an explicit environment override or the standard installed shared-skill path.
5. Install the adapter for OpenCode without changing the existing Claude, Codex, or Pi adapters.

## Acceptance Criteria

1. A mocked blocking `PreToolUse` response throws before a write-like tool runs, while read-only tools do not invoke the watcher.
2. A mocked blocking `PostToolUse` response throws after a write-like tool runs, while successful empty responses pass.
3. Session creation invokes `SessionStart`. A changed idle response is injected once, and an identical response is not injected repeatedly.
4. Runner resolution honors `AGENT_DISCIPLINE_WATCHER_HOME` first and otherwise uses `~/.agents/skills/agent-discipline-watcher/hooks/run.sh`.
5. The installer copies the adapter to `~/.config/opencode/plugins/agent-discipline-watcher.ts`, and existing test suites continue to pass.

## Testing Plan

- Add Bun unit tests for write-tool filtering, payload mapping, blocking responses, runner resolution, and idle deduplication.
- Run the adapter tests first.
- Run the complete existing Python watcher tests.
- Install locally and run an OpenCode startup smoke test.
- Fast-forward the workstation source, install from its Linux path, and run the same startup smoke test.

## Implementation Plan

1. Add failing unit tests for pure adapter helpers and event behavior.
2. Implement the smallest OpenCode plugin adapter that satisfies those tests.
3. Extend the installer with one targeted OpenCode copy step and test its resulting path.
4. Run focused and complete tests, then install and smoke-test on both machines.
