---
phase: 1
plan: "01-01"
title: protected.py path classification hardening
status: complete
commits:
  - 738b967
  - ab24cf5
  - 53325ad
tasks:
  - name: Remove the plugins exemption from CLAUDE_EXEMPT_DIRS
    status: complete
    commit: 738b967
  - name: Dereference existing symlinks in _resolve before classification
    status: complete
    commit: ab24cf5
  - name: Classify mutating commands on a bare client-home root
    status: complete
    commit: 53325ad
files_modified:
  - hooks/lib/protected.py
  - hooks/lib/test_protected.py
  - hooks/test_pre_bash.py
ac_results:
  plugin_cache_writes_block: pass
  symlinked_wiring_paths_block: pass
  client_home_root_deletes_block: pass
  sandbox_home_root_write_stays_allowed: pass
  full_suite_baseline_failure_only: pass
verification:
  - command: PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks/lib/test_protected.py -q
    result: 53 passed
  - command: PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks/lib/test_protected.py hooks/test_pre_bash.py -q
    result: 143 passed
  - command: PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks/test_pre_bash.py hooks/lib/test_protected.py hooks/test_self_protection_invariants.py -q
    result: 164 passed
  - command: PYTHONPATH="hooks:hooks/lib" python3 -m pytest hooks -q
    result: 987 passed, 1 pre-existing failure
  - command: direct plugin-cache and symlink classifier replay
    result: passed
pre_existing_issues:
  - '{"test":"hooks/test_plugin_wiring.py::PluginValidatorTests::test_official_validator_accepts_the_manifests","file":"hooks/test_plugin_wiring.py","error":"claude plugin validate --strict returned 1 because the root CLAUDE.md is not loaded as project context"}'
deviations: []
---

## What Was Built
- Removed the plugin cache exemption for all Claude plugins.
- Resolved existing symlinks before protected-path classification.
- Classified destructive commands against bare Claude, Codex, and Pi client roots.
- Grounding: d03-wp-semantics-of-the-language and d04-termination-and-euclid (Postcondition: normalized paths classify by realpath. Invariant: parts normalize the processed prefix. Variant: unprocessed path parts.)

## Files Modified
- hooks/lib/protected.py
- hooks/lib/test_protected.py
- hooks/test_pre_bash.py
