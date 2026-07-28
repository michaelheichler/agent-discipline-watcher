"""Central gate-state schema and resolution helpers shared by the discipline hooks."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path


ALWAYS_ON_RULES = (
    "Two rules ignore every switch below: suppression_escape_hatch and what_comment. "
    "Neither clean_code nor exempt_paths suppresses them, because scanner.scan_all emits both "
    "from _unconditional_findings, before the exemption check and outside the clean_code guard. "
    "Turning clean_code off still leaves what_comment blocking on every scanned code file."
)
# Paired with scanner._unconditional_findings because resolve_outcome and the emitter must agree on which rules bypass every gate.
SCANNER_ALWAYS_BLOCKING_RULES = frozenset({"suppression_escape_hatch", "what_comment"})
# Kept apart from the scanner set because protected.py and pre_bash.py emit these from a path and a command, not from file content.
SELF_PROTECTION_RULES = frozenset({
    "live_client_surface", "config_seal", "install_without_sandbox_home",
    "commit_gate_bypass", "cap_override", "state_deletion",
})
ALWAYS_BLOCKING_RULES = SCANNER_ALWAYS_BLOCKING_RULES | SELF_PROTECTION_RULES

GATE_STATES = ("off", "observe", "enforce")

# Scoped to families a live hook already emits, because defining a gate state before the family exists is speculative schema creep.
GATE_FAMILIES = ("punctuation", "english", "clean_code")

DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    "max_rows": 8,
    "exempt_paths": [],
    # Path glob to family list, so that one surface drops one family instead of exempt_paths silencing them all.
    "exempt_families": {},
    # git subtracts findings the committed file already had, because an agent must answer for its own edit only.
    "baseline": "git",
    # Absent families fall back to the legacy boolean above because existing single-key configs must keep working.
    "gates": {},
    # Bypassed by ALWAYS_BLOCKING_RULES because those rules must stay unsuppressable.
    "kill_switches": {},
    # Inert without the trust grant (D12) because command-bearing config must not run before a user-owned grant exists.
    "verify": {},
    # Off until the E7-H policy gate clears it because redaction needs a human decision on identifier classes and key custody.
    "data_boundary": {"enabled": False},
}
CONFIG_NAME = ".agent-discipline.json"


def _project_settings(cwd: str | os.PathLike[str]) -> dict:
    """Flatten the nearest project config, treating an absent or non-object file as no settings."""
    path = _find_project_config(Path(cwd))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    checks = data.get("checks")
    settings = dict(checks) if isinstance(checks, dict) else {}
    settings.update({key: value for key, value in data.items() if key != "checks"})
    return settings


def effective_config(config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> dict:
    """Return the merged config as a deep copy so callers can mutate it without aliasing DEFAULTS."""
    merged = copy.deepcopy(DEFAULTS)
    if cwd is not None:
        merged.update(_project_settings(cwd))
    if config:
        merged.update(config)
    return merged


def _find_project_config(cwd: Path) -> Path:
    """Return the nearest project config path, existing or not, walking from cwd upward."""
    current = cwd.resolve()
    if current.is_file():
        current = current.parent
    for parent in (current, *current.parents):
        candidate = parent / CONFIG_NAME
        if candidate.exists():
            return candidate
    return current / CONFIG_NAME


def gate_state(family: str, config: dict | None = None) -> str:
    """Resolve a family to off, observe, or enforce, honoring kill switch then gates then the legacy boolean."""
    cfg = effective_config(config)
    if (cfg.get("kill_switches") or {}).get(family):
        return "off"
    state = (cfg.get("gates") or {}).get(family)
    if state in GATE_STATES:
        return state
    return "enforce" if cfg.get(family, True) else "off"


def resolve_outcome(finding: dict, config: dict | None = None) -> str:
    """Return what a finding does: block, would_block, or release."""
    rule = finding.get("rule", "") if isinstance(finding, dict) else ""
    if rule in ALWAYS_BLOCKING_RULES:
        return "block"
    family = finding.get("family", "") if isinstance(finding, dict) else ""
    state = gate_state(family, config)
    if state == "enforce":
        return "block"
    if state == "observe":
        return "would_block"
    return "release"


def record_state_transitions(
    session_id: str,
    config: dict | None = None,
    state_root: str | os.PathLike[str] | None = None,
    ledger_root: str | os.PathLike[str] | None = None,
) -> list[dict]:
    """Append one ledger row per family whose state changed since the last snapshot, swallowing state and ledger errors so a hook never fails."""
    if not session_id:
        return []
    try:
        return _record_transitions(session_id, config, state_root, ledger_root)
    except Exception as exc:
        sys.stderr.write(f"agent-discipline-watcher: state-transition log failed: {exc}\n")
        return []


def _ledger_modules():
    """Return the reporting and session_state modules, imported late to keep config load free of fcntl and the ledger."""
    try:
        # Relative first because every hook entry script imports this module as lib.config, where a bare name cannot resolve.
        from . import reporting, session_state
    except ImportError:
        import reporting
        import session_state
    return reporting, session_state


def _record_transitions(
    session_id: str,
    config: dict | None,
    state_root: str | os.PathLike[str] | None,
    ledger_root: str | os.PathLike[str] | None,
) -> list[dict]:
    """Diff the current gate states against the session snapshot and persist the new snapshot."""
    reporting, session_state = _ledger_modules()
    cfg = effective_config(config)
    current = {family: gate_state(family, cfg) for family in GATE_FAMILIES}
    captured: list[dict] = []

    def diff_and_snapshot(state: dict) -> dict:
        # Diffs run inside the flock because two concurrent hooks could otherwise both read the old snapshot and emit duplicate transition rows.
        previous = state.get("gate_states") or {}
        captured.extend(_transition_rows(session_id, previous, current))
        return {**state, "gate_states": current}

    session_state.update_state(session_id, diff_and_snapshot, state_root)
    for row in captured:
        reporting.append_row(row, ledger_root)
    return captured


def _transition_rows(session_id: str, previous: dict, current: dict) -> list[dict]:
    """Return one row per family whose state differs from the recorded snapshot."""
    reporting, _ = _ledger_modules()
    rows: list[dict] = []
    # Only a previously recorded state counts as a change, because the first resolution seeds the baseline silently.
    for family in GATE_FAMILIES:
        old = previous.get(family)
        if old is None or old == current[family]:
            continue
        rows.append({
            "ts": reporting.now_iso(),
            "session_id": session_id,
            "hook": "config",
            "event": "state_transition",
            "family": family,
            "outcome": "",
            "from_state": old,
            "to_state": current[family],
        })
    return rows
