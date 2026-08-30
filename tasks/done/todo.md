# Todo: Bash Write Guard

Source plan: tasks/plan.md. Spec: tasks/spec-bash-write-guard.md. Tickets: tasks/tickets/.

## Phase 1: Foundation (parallel)
- [x] T1 shell_parse primitives (`hooks/lib/shell_parse.py`, `hooks/test_bash_write_scan.py`)
- [x] T2 always-blocking tier membership plus invariants (`hooks/lib/config.py`, `hooks/test_self_protection_invariants.py`)
- [x] Checkpoint: full suite green

## Phase 2: Detection and shape split (sequential)
- [x] T3 opaque detection plus gate wiring (`hooks/pre_bash.py`, `hooks/lib/opaque_write.py`, new `hooks/test_bash_opaque_write.py`)
- [x] T4 write/edit shape split for Bash writes (`hooks/pre_bash.py`, `hooks/lib/write_shape.py`, `hooks/test_bash_write_scan.py`)
- [x] Checkpoint: seven rules block through `pre_bash.run`, full suite green

## Phase 3: Hardening
- [x] T5 false-positive regression sweep plus docs
- [x] Checkpoint: full suite plus pylint green, FP table pinned by tests
- [x] Integration QA approved after three rounds (node require writes, php write APIs, shell-consumer heredocs and pipes re-enter the gate, awk/gawk in-place blocked)

## Standing constraints
- Coders use Write/Edit tools only. No Bash-mediated file writes. No edits to `.agent-discipline.json` or hook wiring to unblock work.
- One commit per ticket, `{type}({scope}): {description}`, only when the user asks.
