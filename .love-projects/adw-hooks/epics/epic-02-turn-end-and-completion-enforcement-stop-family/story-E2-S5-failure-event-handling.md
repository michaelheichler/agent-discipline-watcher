<!-- love-render src=plan.json sha=28c6dd7d do not hand-edit -->

# E2-S5 Failure-event handling

Epic E2: Turn-end and completion enforcement (Stop family). Sprint 2. Gate unit-testing.

## Why
As an operator, I want repeated tool failures met with deterministic guidance and unhealthy MCP servers short-circuited, so that the agent neither weakens changes to dodge errors nor burns turns on dead providers.

## Done when
- failure.py records per-tool and per-target failure streaks (error, is_interrupt, duration_ms) in session state
- a streak threshold injects a fix-the-root-cause instruction naming the repeated failure
- MCP substate: a server is marked unhealthy on failure with 30s base exponential backoff capped at 10min, and a PreToolUse consult blocks calls to known-unhealthy servers until backoff expiry

## Execution
- [ ] E2-S5-T1: failure.py plus MCP circuit breaker

