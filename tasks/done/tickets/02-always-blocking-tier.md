# 02: Always-blocking tier membership for the seven bash write rules

**What to build:** The seven new rule names (inline_interpreter_write, shell_payload_block, interpreter_heredoc_write, dynamic_heredoc_write, decode_pipe_write, inplace_edit_write, opaque_source_write) belong to the self-protection tier. No project config can gate, exempt, or kill them. A config that tries to downgrade any of them is itself blocked as an escape attempt. Only the human-held environment escape releases them.

**Blocked by:** None, can start immediately. Rule names are fixed by tasks/plan.md.

**Status:** ready-for-agent

- [ ] All seven names are members of the always-blocking set
- [ ] A pending config that sets any of them to off trips the config seal
- [ ] Invariant tests cover both facts, existing config tests stay green
- [ ] Detailed design in tasks/plan.md Task 2, full suite green
