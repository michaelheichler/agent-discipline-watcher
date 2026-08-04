# agent-discipline-watcher

A Claude Code hook package that keeps agent output and file edits direct, plain, and reviewable by scanning for banned punctuation, inflated diction, deferred-work comments, WHAT-vs-WHY comment violations, hollow tests, and oversized code shapes.

**Core value:** Catch deterministic low-level drift in agent output and edits before it lands in files, and resist an agent under observation trying to disable the watcher itself.

## Requirements

### Validated
None yet. See REQUIREMENTS.md for Milestone 1 scope.

### Active
- [ ] See REQUIREMENTS.md REQ-01 through REQ-07

### Out of Scope
- OpenCode adapter hardening: not separately audited by the source review
- Pi/Codex adapter hardening: not separately audited by the source review

## Constraints
- **No third-party runtime dependency except one optional package**: `anthropic`, used only for the Haiku escalation path, with a raw HTTPS fallback when absent
- **Self-tamper resistance**: the watcher must not trust an agent it is observing to leave its own config, state, or installed files alone

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Scope Milestone 1 to the Claude Code hook path only | The source review covered `hooks/` and `bin/`, not the OpenCode or Pi/Codex adapters | OpenCode and Pi/Codex findings deferred to backlog (REQ-08) |
