# 05: False-positive regression sweep and documentation

**What to build:** Every must-stay-allowed idiom from the spec is pinned by a named regression test, so future hardening cannot silently break legitimate commands. Existing false-positive protections (path exemptions, markup masking, the CSS hash collision guard, URL and table exclusions) are re-audited and any gaps get tests. Residual known gaps are documented in the docstring of the opaque-write test module. The README rule list and the plugin skill text name the seven new rules and the redirect to the Write and Edit tools.

**Blocked by:** 03 opaque detection, 04 shape split.

**Status:** ready-for-agent

- [ ] Every row of the spec's allowed table has a named passing test
- [ ] Residual gaps are listed in the opaque-write test module docstring
- [ ] README and skill text list the seven rules
- [ ] Full suite plus pylint plus bash -n green
