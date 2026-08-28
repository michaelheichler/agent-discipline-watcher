# Task 1 report: runtime selection and bounded storage

## Implementation

- Added one shell resolver at `hooks/resolve-python.sh`. It honours `ADW_PYTHON`, probes candidates, and picks the newest interpreter meeting `.python-version`. Hook dispatch, the main installer, and the OMP installer source it.
- Added session leases, renewed by hook ledger wrapping and created at SessionStart. Leases expire after 900 seconds; Stop releases them.
- Added a SessionStart retention sweep with a 30-day cutoff. It cleans stale inactive session state, compacts ledger JSONL by streaming into an atomic replacement, retains malformed ledger rows conservatively, keeps reports referenced by retained rows, and removes stale orphan reports/cache/log files. Runtime and models are outside the sweep scope.

## Files

- `hooks/resolve-python.sh`, `hooks/run.sh`, `install.sh`, `pi/install.sh`
- `hooks/lib/session_state.py`, `hooks/lib/retention.py`, `hooks/lib/reporting.py`
- `hooks/session_start.py`, `hooks/stop.py`
- Runtime and retention test modules plus adjusted existing resolver stubs.

## TDD evidence

RED commands and observed output:

- `./.venv/bin/python -m pytest hooks/test_run_dispatch.py::RunDispatchTests::test_newest_compatible_interpreter_wins_across_path_entries -q` -> `1 failed`; selected `python3.9` instead of `python3.14`.
- `./.venv/bin/python -m pytest hooks/test_install_runtime.py -q` -> `1 failed`; installer exited `97` through stale `python3`.
- `./.venv/bin/python -m pytest hooks/test_install_runtime.py::test_omp_installer_uses_newest_compatible_python_instead_of_stale_python3 -q` -> `1 failed`; OMP installer exited `97`.
- `./.venv/bin/python -m pytest hooks/lib/test_session_state.py::SessionStateTests::test_sweep_stale_keeps_an_old_session_with_a_live_lease -q` -> `1 failed`; `acquire_session_lease` missing.
- `./.venv/bin/python -m pytest hooks/lib/test_session_state.py::SessionStateTests::test_released_session_lease_no_longer_protects_stale_session -q` -> `1 failed`; `release_session_lease` missing.
- `./.venv/bin/python -m pytest hooks/lib/test_ledger_reporting.py::HeartbeatTests::test_run_with_ledger_renews_the_session_lease -q` -> `1 failed`; live lease set was empty.
- `./.venv/bin/python -m pytest hooks/test_stop.py::test_stop_releases_the_session_lease -q` -> `1 failed`; lease remained live.
- `./.venv/bin/python -m pytest hooks/lib/test_retention.py -q` -> collection error; `lib.retention` missing.
- `./.venv/bin/python -m pytest hooks/test_session_start.py::ReadableOutputInjectionTests::test_session_start_runs_retention_and_acquires_a_lease -q` -> `1 failed`; SessionStart had no retention module.

GREEN commands and observed output:

- `./.venv/bin/python -m pytest hooks/test_install_runtime.py hooks/test_run_dispatch.py -q` -> `21 passed, 22 subtests passed`.
- `./.venv/bin/python -m pytest hooks/lib/test_session_state.py -q` -> `28 passed, 7 subtests passed`.
- `./.venv/bin/python -m pytest hooks/test_stop.py::test_stop_releases_the_session_lease hooks/lib/test_ledger_reporting.py::HeartbeatTests::test_run_with_ledger_renews_the_session_lease -q` -> `2 passed`.
- `./.venv/bin/python -m pytest hooks/lib/test_retention.py -q` -> `3 passed`.
- `./.venv/bin/python -m pytest hooks/test_plugin_wiring.py::PluginCommandExecutionTests::test_a_plugin_root_with_spaces_still_resolves hooks/test_install_runtime.py hooks/test_run_dispatch.py -q` -> `22 passed, 22 subtests passed`.
- Focused suite: `./.venv/bin/python -m pytest hooks/test_install_runtime.py hooks/test_run_dispatch.py hooks/lib/test_session_state.py hooks/lib/test_ledger_reporting.py hooks/lib/test_retention.py hooks/test_session_start.py hooks/test_stop.py -q` -> `124 passed, 34 subtests passed`.

## Full suite

- `./.venv/bin/python -m pytest hooks/lib -q` -> `604 passed, 17 skipped, 50 subtests passed`.
- `./.venv/bin/python -m pytest hooks/test_*.py -q` -> `959 passed, 1 skipped, 218 subtests passed`.
- `./.venv/bin/python -m pytest pi/test_merge_settings.py -q` -> `11 passed`.

Combined: 1,574 passed, 18 skipped.

## Self-review

- Ran `git diff --check` with no whitespace errors.
- Confirmed installed hook copies retain the resolver under `hooks/`, including plugin roots with spaces.
- Confirmed retention never enumerates `runtime` or `models`, and ledger compaction iterates source lines rather than calling `read_text`/`readlines`.
- Concern: report records currently appear only in any string-valued ledger fields; report retention also protects conventional live-session report filenames. Malformed ledger rows are retained rather than discarded to avoid evidence loss.

## Fix round 1

### Changes

- Stop now retains the active lease. A new `SessionEnd` hook releases it, and both the dispatcher and Claude manifest route `SessionEnd` to that entrypoint.
- SessionStart acquires the current lease before retention, so a resumed old session survives its own startup cleanup. Repeated startup cleanup is covered with real filesystem state.
- Ledger appends and compaction now use the same cross-process `.ledger.lock`, so an append cannot target the inode being atomically replaced. The retention helper no longer uses a mutable default argument.

### RED commands and output

- `./.venv/bin/python -m pytest hooks/test_stop.py::test_stop_keeps_the_session_lease_for_the_active_session -q` -> `1 failed`; the lease set was empty.
- `./.venv/bin/python -m pytest hooks/test_session_end.py -q` -> collection error; `session_end` was missing.
- `./.venv/bin/python -m pytest hooks/test_run_dispatch.py::RunDispatchTests::test_no_event_routes_to_an_empty_script -q` -> `1 failed`; `SessionEnd` dispatcher entry was absent.
- `./.venv/bin/python -m pytest hooks/test_plugin_wiring.py::PluginManifestTests::test_session_end_releases_the_active_session_lease -q` -> `1 failed`; manifest had no SessionEnd command.
- `./.venv/bin/python -m pytest hooks/test_session_start.py::ReadableOutputInjectionTests::test_resumed_old_session_is_protected_before_startup_cleanup -q` -> `1 failed`; the resumed state directory was removed.
- `./.venv/bin/python -m pytest hooks/lib/test_retention.py::test_append_waits_for_ledger_compaction_and_is_not_lost -q` -> `1 failed`; append completed while compaction was paused.

### GREEN commands and output

- `./.venv/bin/python -m pytest hooks/test_session_end.py hooks/test_stop.py::test_stop_keeps_the_session_lease_for_the_active_session hooks/test_plugin_wiring.py::PluginManifestTests::test_session_end_releases_the_active_session_lease -q` -> `3 passed`.
- `./.venv/bin/python -m pytest hooks/test_run_dispatch.py -q` -> `19 passed, 24 subtests passed`.
- `./.venv/bin/python -m pytest hooks/test_session_start.py -q` -> `9 passed`.
- `./.venv/bin/python -m pytest hooks/lib/test_retention.py::test_append_waits_for_ledger_compaction_and_is_not_lost -q` -> `1 passed`.
- Focused suite: `./.venv/bin/python -m pytest hooks/test_session_end.py hooks/test_stop.py hooks/test_session_start.py hooks/test_run_dispatch.py hooks/test_plugin_wiring.py hooks/lib/test_retention.py hooks/lib/test_ledger_reporting.py -q` -> `122 passed, 64 subtests passed`.

### Full suite

- `./.venv/bin/python -m pytest hooks/lib -q` -> `605 passed, 17 skipped, 50 subtests passed`.
- `./.venv/bin/python -m pytest hooks/test_*.py -q` -> `963 passed, 1 skipped, 223 subtests passed`.
- `./.venv/bin/python -m pytest pi/test_merge_settings.py -q` -> `11 passed`.

Combined: 1,579 passed, 18 skipped.

### Self-review

- Verified `SessionEnd` is a supported manifest event, dispatcher route, and a real entrypoint that releases only the session lease.
- Verified SessionStart protects its own session before sweeping.
- Verified the deterministic append-versus-compaction test blocks append until replacement completes, then retains the appended row.
