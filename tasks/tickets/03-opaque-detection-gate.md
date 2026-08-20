# 03: Opaque bash write detection wired into the gate

**What to build:** The Bash gate hard blocks every opaque write path with a reason naming the rule and directing the agent to the Write or Edit tool. Inline interpreter payloads containing write-capable tokens, or non-literal payloads, block. Heredocs and pipes feeding an interpreter's stdin are judged the same way. Dynamic or unterminated heredocs aimed at a file block. Decode pipes ending in a file write, in-place editors, dd file outputs, and process-substitution copy sources block. A literal shell -c payload re-enters the full gate one level deep, a non-literal one blocks. Read-only idioms stay allowed: literal print-only one-liners, decode to stdout, sed without in-place, display heredocs, dynamic heredocs into non-interpreter consumers. The environment escape releases each rule, config keys do not.

**Blocked by:** 01 shell-parse primitives, 02 always-blocking tier.

**Status:** ready-for-agent

- [ ] Each of the seven rules blocks its trigger end to end through the gate's run entry, reason names the rule and the Write or Edit tool
- [ ] The environment escape releases each rule, a config key releases none
- [ ] Every read-only idiom in the spec's allowed table has a passing allow test
- [ ] Detailed design in tasks/plan.md Task 3, full suite green
