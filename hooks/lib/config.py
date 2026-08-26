"""Centralized here because every hook and the CLI must agree on one gate-resolution order, or a rule could block in one surface and pass in another."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

try:
    # Relative first because every hook entry script imports this module as lib.config, where a bare name cannot resolve.
    from .payloads import exact_string_dict
except ImportError:
    from payloads import exact_string_dict


# Bypass every switch and exemption because scanner._unconditional_findings and resolve_outcome must always agree here.
SCANNER_ALWAYS_BLOCKING_RULES = frozenset({
    "suppression_escape_hatch",
    "file_too_long",
    "unscannable_file",
})
FIXED_OBSERVE_RULES = frozenset({"file_length_warning", "file_length_critical"})
STRICT_HARD_BLOCK_RULES = frozenset({
    "what_comment",
    "what_docstring",
    "weak_why_comment",
    "prose_comment_block",
    "docstring_narration",
})
# Kept apart from the scanner set because protected.py and pre_bash.py emit these from a path and a command, not from file content.
SELF_PROTECTION_RULES = frozenset({
    "watcher_install_surface", "watcher_wiring_removal", "config_seal", "install_without_sandbox_home",
    "commit_gate_bypass", "cap_override", "state_deletion", "state_mutation",
    # Joined here so that an observed agent cannot gate these open through project config to smuggle a write around the scanner.
    "inline_interpreter_write", "shell_payload_block", "interpreter_heredoc_write",
    "dynamic_heredoc_write", "decode_pipe_write", "inplace_edit_write", "opaque_source_write",
})
ALWAYS_BLOCKING_RULES = (
    SCANNER_ALWAYS_BLOCKING_RULES | STRICT_HARD_BLOCK_RULES | SELF_PROTECTION_RULES
)

GATE_STATES = ("off", "observe", "enforce")

# Scoped to families a live hook already emits, because defining a gate state before the family exists is speculative schema creep.
GATE_FAMILIES = ("punctuation", "english", "clean_code")

DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    "max_rows": 8,
    "sentence_word_cap": 40,
    "list_item_cap": 8,
    "exempt_paths": [],
    # Path glob to family list, so that one surface drops one family instead of exempt_paths silencing them all.
    "exempt_families": {},
    # report holds an agent to its own edit while still naming the debt it inherited, because silent removal is how old files stay broken.
    "baseline": "report",
    # Absent families fall back to the legacy boolean above because existing single-key configs must keep working.
    "gates": {},
    # Per-rule states beat the family because a lexical rule can burn in without demoting the family, and enforce always means a hard block.
    "rule_gates": {
        "ai_closer": "observe",
        "greeting_opener": "observe",
        "hedge_stack": "observe",
        "corporate_idiom": "observe",
        "long_sentence": "observe",
        "oversized_list": "observe",
        "file_length_warning": "observe",
        "file_length_critical": "observe",
    },
    # Bypassed by ALWAYS_BLOCKING_RULES because those rules must stay unsuppressable.
    "kill_switches": {},
    # Off until the E7-H policy gate clears it because redaction needs a human decision on identifier classes and key custody.
    "data_boundary": {"enabled": False},
}
CONFIG_NAME = ".agent-discipline.json"


def flatten_settings(data: object) -> dict:
    """Flattened once here so that every caller checks one namespace instead of guessing whether a setting lives at the top level or under checks."""
    fields = exact_string_dict(data)
    settings = exact_string_dict(fields.get("checks"))
    settings.update({key: value for key, value in fields.items() if key != "checks"})
    return settings


def _project_settings(cwd: str | os.PathLike[str]) -> dict:
    path = _find_project_config(Path(cwd))
    try:
        if not path.exists():
            return {}
        return flatten_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        # Named on stderr, because a config that silently fails closed still costs the user their exemptions and gates.
        sys.stderr.write(f"agent-discipline-watcher: could not read project config at {path}: {exc}\n")
        return {}


def effective_config(config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> dict:
    """Deep-copied here so that a caller mutating the merged result never corrupts the shared DEFAULTS dict for every other caller."""
    merged = copy.deepcopy(DEFAULTS)
    if cwd is not None:
        merged.update(_project_settings(cwd))
    if config:
        merged.update(config)
    return merged


def effective_hook_config(config: object, cwd: str | os.PathLike[str] | None) -> dict:
    caller = exact_string_dict(config)
    scan_config = {key: value for key, value in caller.items() if key not in {"state_root", "ledger_root"}}
    merged = effective_config(scan_config, cwd)
    for key in ("state_root", "ledger_root"):
        value = caller.get(key)
        merged[key] = value if isinstance(value, str) else None
    return merged


def _find_project_config(cwd: Path) -> Path:
    current = cwd.resolve()
    if current.is_file():
        current = current.parent
    for parent in (current, *current.parents):
        candidate = parent / CONFIG_NAME
        if candidate.exists():
            return candidate
    return current / CONFIG_NAME


def project_config_path(cwd: str | os.PathLike[str]) -> Path:
    """Expose the upward search publicly, because the CLI must resolve the same config file the gate would read."""
    return _find_project_config(Path(cwd))


def gate_map(cfg: dict, key: str) -> dict:
    """Coerced to exact string keys here so that a malformed gate value reads as empty and the family falls back to the safer enforce state."""
    return exact_string_dict(cfg.get(key))


def _gate_state_from(cfg: dict, family: str) -> str:
    if gate_map(cfg, "kill_switches").get(family):
        return "off"
    state = gate_map(cfg, "gates").get(family)
    if state in GATE_STATES:
        return state
    return "enforce" if cfg.get(family, True) else "off"


def gate_state(family: str, config: dict | None = None) -> str:
    """Merge DEFAULTS here, because a standalone caller has no already-merged cfg the way resolve_outcome does."""
    return _gate_state_from(effective_config(config), family)


def _rule_state_from(cfg: dict, rule: str) -> str | None:
    if not rule:
        return None
    state = gate_map(cfg, "rule_gates").get(rule)
    return state if state in GATE_STATES else None


def rule_state(rule: str, config: dict | None = None) -> str | None:
    """Merge DEFAULTS here, because a standalone caller has no already-merged cfg the way resolve_outcome does."""
    return _rule_state_from(effective_config(config), rule)


def _outcome_for(state: str) -> str:
    if state == "enforce":
        return "block"
    return "would_block" if state == "observe" else "release"


def resolve_outcome(finding: dict, config: dict | None = None) -> str:
    """Centralized here because every gate, family, per-rule, and always-blocking, must resolve through the same order or hooks would disagree on precedence."""
    rule = finding.get("rule", "") if isinstance(finding, dict) else ""
    if rule in ALWAYS_BLOCKING_RULES:
        return "block"
    if rule in FIXED_OBSERVE_RULES:
        return "would_block"
    # Merged once here because gate_state and rule_state each re-merging DEFAULTS doubled the cost of every finding.
    cfg = effective_config(config)
    own = _rule_state_from(cfg, rule)
    if own is not None:
        return _outcome_for(own)
    family = finding.get("family", "") if isinstance(finding, dict) else ""
    return _outcome_for(_gate_state_from(cfg, family))


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
    except (OSError, json.JSONDecodeError) as exc:
        # Narrowed to storage failures, because a defeat-to-off transition is exactly the kind of change an observed agent wants unlogged.
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
    reporting, session_state = _ledger_modules()
    cfg = effective_config(config)
    current = {family: gate_state(family, cfg) for family in GATE_FAMILIES}
    captured: list[dict] = []

    def diff_and_snapshot(state: dict) -> dict:
        # Diffs run inside the flock because two concurrent hooks could otherwise both read the old snapshot and emit duplicate transition rows.
        previous = state.get("gate_states") or {}
        captured.extend(_transition_rows(session_id, previous, current))
        return {**state, "gate_states": current}

    session_state.update_state_strict(session_id, diff_and_snapshot, state_root)
    for row in captured:
        reporting.append_row(row, ledger_root)
    return captured


def _transition_rows(session_id: str, previous: dict, current: dict) -> list[dict]:
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
