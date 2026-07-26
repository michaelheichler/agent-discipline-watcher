<!-- love-render src=plan.json sha=966c7260 do not hand-edit -->

# E1-S1 Core libraries: dispatch, payloads, and gate config

Epic E1: Foundation: dispatcher, state, payload contracts, ledger. Sprint 1. Gate simplification.

## Why
As the ADW maintainer, I want one dispatch table, one payload contract, one state store, and one ledger, so that eleven new hooks share tested plumbing instead of reinventing it.

## Done when
- run.sh routes events from a single data-driven table, one entry script per event-and-matcher pair (D11), and unknown events still exit 2 with usage
- lib/payloads.py exposes typed accessors for every documented field the plan consumes (session_id, cwd, tool_name, last_assistant_message, stop_hook_active, agent_id, agent_type, agent_transcript_path, prompt, source, file_path, error, is_interrupt, duration_ms, tool_calls, task_id, task_subject), each with a contract test
- lib/config.py carries the central gate-state schema: every gate family resolves to off, observe, or enforce, with observe running the full check and writing would_block rows without blocking (D7)
- every new hook module follows the existing pattern: an importable module exposing run(payload, config) with I/O only via the hookio helpers, so test files import it directly and call run() the way test_hooks.py already does

## Execution
- [x] E1-S1-T1: Data-driven run.sh dispatcher
- [x] E1-S1-T3: Payload contract module (lib/payloads.py)
- [x] E1-S1-T5: Central gate-state config schema (lib/config.py)

