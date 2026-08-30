# Implementation Plan: Bash Write Guard

## Overview

Close the Bash workaround gap in ADW. Agents dodge the Write/Edit hooks by writing file content through Bash (heredocs piped into interpreters, `python -c`, decode pipes, in-place editors, dynamic heredocs). Every statically scannable literal Bash write body runs through the full scanner with hard block on findings, mirroring the write-shape versus edit-shape split from `pre_write.py`. Content ADW cannot statically scan is hard blocked outright with a deny message directing the agent to the Write or Edit tool. All new rules join the always-blocking tier so no config gate can weaken them.

## Architecture Decisions

- Seven new rules join `SELF_PROTECTION_RULES` in `hooks/lib/config.py`: `inline_interpreter_write`, `shell_payload_block`, `interpreter_heredoc_write`, `dynamic_heredoc_write`, `decode_pipe_write`, `inplace_edit_write`, `opaque_source_write`. The derived `ALWAYS_BLOCKING_RULES` union and `grants_escape` cover anti-overrule automatically. Only the human env escape `ADW_ALLOW_PROTECTED_EDIT` releases them.
- Literal interpreter payloads stay allowed when free of write-capable tokens (`open(`, `write`, `exec`, `eval`, `__`, `subprocess`, `os`/`shutil`/`pathlib` imports, `fs.`, `File.`, `IO.`, `decode(`, backtick, and peers). Blocking all inline code would push users to the env escape.
- Bash overwrite (`>`, `>|`, plain `tee`) is write shape: full scan plus `baseline.split_committed`, inherited debt reports without blocking. Append (`>>`, `tee -a`) is edit shape: scan the appended body alone, all lines are new by construction, plus a `file_too_long` check on resulting length.
- No scratch-path carve-out for the opaque rules. An unscannable body to any path is a laundering step.
- Parsing primitives stay pure functions in `hooks/lib/shell_parse.py`. Detection and gate wiring stay in `hooks/pre_bash.py`.

## Task List

### Phase 1: Foundation (parallel)
- [ ] Task 1 (T1): shell_parse primitives
- [ ] Task 2 (T2): always-blocking tier membership plus invariants

### Checkpoint: Foundation
- [ ] `cd hooks && python3 -m pytest . lib -q` green

### Phase 2: Detection and shape split (sequential, same file)
- [ ] Task 3 (T3): opaque detection plus gate wiring
- [ ] Task 4 (T4): write/edit shape split for Bash writes

### Checkpoint: Core
- [ ] Full suite green, each of the seven rules blocks its trigger through `pre_bash.run`

### Phase 3: Hardening
- [ ] Task 5 (T5): false-positive regression sweep plus docs

### Checkpoint: Complete
- [ ] Full suite plus pylint green, FP table fully pinned by tests

## Tasks

## Task 1: shell_parse primitives

**Description:** Add pure parsing primitives to `hooks/lib/shell_parse.py`.

- `LiteralWrite(path, text, append)` NamedTuple with `literal_writes(command)`. The old `write_targets` API stays as a projection over it.
- `_payload_command_index` steps past assignments and the wrappers `env sudo nohup time command exec`, never past an interpreter.
- `interpreter_invocation(segment)` returns the interpreter name, the code flag, and the payload token, or None when dynamic. It is keyed on command position so a quoted mention cannot match.
- `heredoc_events(command)` exposes per-pipeline-group rows `(consumer_segment, body, dynamic, group_has_write_target)` without discarding the dynamic flag.
- `has_process_substitution(segment)`.

**Acceptance criteria:**
- [ ] `literal_writes` distinguishes `>` from `>>` and `tee` from `tee -a`, old `write_targets` callers unchanged
- [ ] `interpreter_invocation` returns None payload for `python3 -c "$CODE"` and a token for `python3 -c 'print(1)'`, and does not match `grep 'python -c' docs/`
- [ ] `heredoc_events` reports dynamic and unterminated heredocs with their consumer and write-target context

**Verification:**
- [ ] Tests pass: `cd hooks && python3 -m pytest test_bash_write_scan.py lib/test_regions.py -q`
- [ ] Full suite: `cd hooks && python3 -m pytest . lib -q`

**Dependencies:** None

**Files likely touched:**
- `hooks/lib/shell_parse.py`
- `hooks/test_bash_write_scan.py`

**Estimated scope:** S

## Task 2: Always-blocking tier membership plus invariants

**Description:** Add the seven rule names to `SELF_PROTECTION_RULES` in `hooks/lib/config.py` with a one-line why-comment matching existing style. Add invariant tests: each new rule is in `ALWAYS_BLOCKING_RULES`, and a heredoc writing a config containing `{"rule_gates": {"inline_interpreter_write": "off"}}` trips `config_seal`.

**Acceptance criteria:**
- [ ] All seven names present in `ALWAYS_BLOCKING_RULES`
- [ ] Config downgrade attempt for any new rule is blocked as an escape attempt
- [ ] No existing config test regresses

**Verification:**
- [ ] Tests pass: `cd hooks && python3 -m pytest test_self_protection_invariants.py lib/test_config_schema.py -q`
- [ ] Full suite: `cd hooks && python3 -m pytest . lib -q`

**Dependencies:** None (rule names fixed by this plan)

**Files likely touched:**
- `hooks/lib/config.py`
- `hooks/test_self_protection_invariants.py`

**Estimated scope:** XS

## Task 3: Opaque detection plus gate wiring

**Description:** Extend `RULES` in `hooks/pre_bash.py` with the seven entries. Action strings end with "Use the Write or Edit tool for file content."

Add the pure function `opaque_write_findings(command, config)`, guarded by `authorized(config)`. It hosts the write-capable token regex and one level of `sh -c` recursion. A literal payload re-enters the full pre_bash pipeline. A non-literal payload blocks as `shell_payload_block`.

Wire it into `_gate` alongside `command_findings` and `target_findings`, denying through the existing `compact_block` plus `deny` path with `force: True`. Create `hooks/test_bash_opaque_write.py`.

**Acceptance criteria:**
- [ ] Each of the seven rules blocks its trigger through `pre_bash.run` with rule name and "Write or Edit" in the reason
- [ ] `ADW_ALLOW_PROTECTED_EDIT` releases each rule, a config key does not
- [ ] Read-only idioms in the FP table stay allowed (literal `python3 -c 'print(...)'`, `base64` to stdout, `sed` without `-i`, display heredocs, dynamic heredoc into `psql`)

**Verification:**
- [ ] Tests pass: `cd hooks && python3 -m pytest test_bash_opaque_write.py test_pre_bash.py -q`
- [ ] Full suite: `cd hooks && python3 -m pytest . lib -q`

**Dependencies:** Task 1, Task 2

**Files likely touched:**
- `hooks/pre_bash.py`
- `hooks/test_bash_opaque_write.py`

**Estimated scope:** M

## Task 4: Write/edit shape split for Bash writes

**Description:** Rework `write_findings` in `hooks/pre_bash.py`. Overwrite shape (`>`, `>|`, plain `tee`): scan full body then `baseline.split_committed`, inherited debt surfaces through `reporting.inherited_advice` without blocking, `_gate` gains the notice plumbing `pre_write` has. Append shape (`>>`, `tee -a`): scan appended body alone, relabel "(line N of appended text)" reusing the `_label_pending_text` pattern, and emit `file_too_long` when disk line count plus body lines crosses the `file_length_policy` limit. Pass `cwd` down from `_gate`, mirroring `pre_write._resolved_path`. Split `test_undeterminable_content_is_allowed_silently`: dynamic or unterminated heredoc to a file moves to blocked, `curl | tee` and `echo "$VAR" >` stay allowed.

**Acceptance criteria:**
- [ ] `>>` with clean body allowed, with offending body blocked and labeled as appended text
- [ ] `>` to a committed file with pre-existing debt reports inherited findings without blocking
- [ ] Append growing a file past the length limit blocks with `file_too_long`

**Verification:**
- [ ] Tests pass: `cd hooks && python3 -m pytest test_bash_write_scan.py test_bash_opaque_write.py -q`
- [ ] Full suite: `cd hooks && python3 -m pytest . lib -q`

**Dependencies:** Task 1, Task 3 (same file as Task 3, serialize)

**Files likely touched:**
- `hooks/pre_bash.py`
- `hooks/test_bash_write_scan.py`

**Estimated scope:** M

## Task 5: False-positive regression sweep plus docs

**Description:** Pin every row of the must-stay-allowed FP table with a test (inline interpreter read-only idioms, `python3 -m` module runs, decode-to-stdout, `sed`/`awk` without in-place, display heredocs, dynamic heredoc into non-interpreter consumers, quoted mentions of trigger tokens, `sh -c 'ls -la'`, `bash script.sh`). Re-audit existing FP protections (exempt paths, markup masking, CSS `#` collision, URL and table exclusions) and add gap tests where missing. Document residual gaps (`echo "$VAR" > file`, `curl | tee`, `sed 's/x/y/' in > out`, `python3 -m module`, `xargs tee`) in the new test file docstring. Update README rule list and skill text.

**Acceptance criteria:**
- [ ] Every FP table row has a named test proving allow
- [ ] Residual gaps documented in `hooks/test_bash_opaque_write.py` docstring
- [ ] README and skill text list the seven new rules

**Verification:**
- [ ] Full suite: `cd hooks && python3 -m pytest . lib -q`
- [ ] Lint: `pylint $(git ls-files '*.py')` and `bash -n install.sh hooks/run.sh`

**Dependencies:** Task 3, Task 4

**Files likely touched:**
- `hooks/test_bash_opaque_write.py`
- `hooks/test_bash_write_scan.py`
- `README.md`
- skill text under the plugin

**Estimated scope:** M

## Parallelization

- Safe to parallelize: Task 1 with Task 2 (disjoint files).
- Must be sequential: Task 3 then Task 4 (both edit `hooks/pre_bash.py`), Task 5 last.
- Execution: Workflow with Sonnet 5 coder agents (effort high) and Opus 5 QA agents (effort medium), one QA review per task, final integration QA pass. Coders must use Write/Edit tools only, never Bash-mediated file writes, never touch `.agent-discipline.json` or hook wiring to unblock themselves. QA rejects any deviation.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Token heuristic misses an obfuscated write API | High | `__` catch-all covers dunder dispatch, non-literal payloads block outright, residual gaps documented for the next pass |
| FP friction pushes users to the env escape | Med | FP table pinned by tests before release, read-only idioms stay allowed |
| T3/T4 merge conflicts in pre_bash.py | Low | Serialized, same agent stream |
| Baseline diffing wrong for bash overwrite of uncommitted file | Med | Mirror `_write_shape_findings` semantics exactly, tmp git repo tests |

## Open Questions

None. Policy decisions were made by the user before planning.
