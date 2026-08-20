# 04: Write and edit shape split for literal bash writes

**What to build:** Literal bash writes get the same shape semantics as the Write and Edit tools. An overwrite redirect scans the full body and splits findings against the committed baseline, so inherited debt is reported without blocking and owned findings hard block. An append redirect scans only the appended body, labels findings as appended text, and hard blocks on any finding. An append that grows a file past the length limit blocks as a file-length violation. Dynamic or unterminated heredoc content aimed at a file no longer passes silently (moves under ticket 03's rule), while variable-expansion echoes and network-to-file pipes stay allowed as documented residual gaps.

**Blocked by:** 01 shell-parse primitives, 03 opaque detection (same gate module, serialize).

**Status:** ready-for-agent

- [ ] Append with a clean body is allowed, append with an offending body blocks and labels the finding as appended text
- [ ] Overwrite of a committed file with pre-existing debt reports inherited findings without blocking
- [ ] Append crossing the file-length limit blocks as a length violation
- [ ] Detailed design in tasks/plan.md Task 4, full suite green
