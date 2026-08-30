# 01: Shell-parse primitives for bash write shapes

**What to build:** The shell-parse layer gives the Bash gate every fact it needs to judge a command. It identifies literal writes and whether each overwrites or appends. It detects command-position interpreter invocations with inline-code flags and distinguishes literal from dynamic payloads. It identifies heredocs by pipeline group while preserving each consumer and dynamic status. It also detects process substitution. Existing callers of the old write-target listing keep working unchanged.

**Blocked by:** None, can start immediately.

**Status:** ready-for-agent

- [ ] Overwrite and append redirects (including tee and its append flag) are distinguished in the literal-write listing, old listing API unchanged
- [ ] Interpreter invocation detection is command-position keyed, returns the payload token when literal and no token when dynamic, and never matches quoted mentions inside other commands
- [ ] Heredoc events expose body, dynamic flag (including unterminated), consumer segment, and whether the pipeline group has a file write target
- [ ] Detailed design in tasks/plan.md Task 1, full suite green
