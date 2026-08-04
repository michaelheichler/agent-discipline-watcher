# Requirements

Defined: 2026-08-04

## Requirements

### REQ-01: Fix both Critical self-tamper bypasses in protected.py (plugin-root exemption, symlink and path-traversal bypass) and make malformed JSON fail closed on every PreToolUse hook (hookio.py)
**Must-have**

### REQ-02: Fix escalation and scanner config-merge correctness bugs: rule_gates shallow merge, kill-switch truthy-value check, escalation cache staleness, escalation budget scope, silent escalation failure visibility, escalation prompt injection risk, and markup.py currency false-positive
**Must-have**

### REQ-03: Fix state, reporting, and ledger integrity bugs: baseline mislabeling new violations as inherited, two commit-review fail-open paths, false-signal rate denominator collision, ledger append corruption recovery, and the adjudicate CLI reporting success on write failure
**Must-have**

### REQ-04: Fix hook entry script correctness bugs
**Must-have**

Covers: apply-patch delete bypassing the protected-path gate. Conditional `cd` parsing in commit review. HOME scope leak in installer sandboxing. Missing success and backoff wiring for non-write PostToolUse events. The first-turn turn-ID bug. Unbounded ledger rescans in PostToolBatch.

### REQ-05: Fix CLI and install-time config merge safety bugs
**Must-have**

Covers: unscoped legacy-settings pruning that can delete unrelated config. The TOML inline-table parser that can silently drop unrelated hooks. Unquoted shell interpolation of the install path. Missing atomic writes in two of three mergers. Unvalidated duplicate false-signal labels.

### REQ-06: Document the ANTHROPIC_API_KEY requirement for escalation in the README
**Should-have**

### REQ-07: Add a dedicated test_escalate.py for the Haiku escalation module
**Should-have**

### REQ-08: Defer any OpenCode or Pi/Codex adapter-specific findings to the backlog, out of scope for this milestone
**Out of scope**

## Out of Scope

- OpenCode adapter (`opencode/agent-discipline-watcher.ts`) hardening: the review scoped to the Claude Code hook path, this adapter was not separately audited
- Pi/Codex adapter (`pi/extensions/`) hardening: same reason, not separately audited

