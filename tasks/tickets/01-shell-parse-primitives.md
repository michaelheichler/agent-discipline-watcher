# 01: Shell-parse primitives for bash write shapes

**What to build:** The shell-parse layer can tell the Bash gate everything it needs to judge a command: which literal writes exist and whether each is an overwrite or an append, whether the command position invokes an interpreter with an inline-code flag and whether that payload is literal or dynamic, which heredocs exist per pipeline group with their consumer and dynamic status preserved, and whether a segment uses process substitution. Existing callers of the old write-target listing keep working unchanged.

**Blocked by:** None, can start immediately.

**Status:** ready-for-agent

- [ ] Overwrite and append redirects (including tee and its append flag) are distinguished in the literal-write listing, old listing API unchanged
- [ ] Interpreter invocation detection is command-position keyed, returns the payload token when literal and no token when dynamic, and never matches quoted mentions inside other commands
- [ ] Heredoc events expose body, dynamic flag (including unterminated), consumer segment, and whether the pipeline group has a file write target
- [ ] Detailed design in tasks/plan.md Task 1, full suite green
