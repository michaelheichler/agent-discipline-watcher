"""Shared ADW policy resolution and bounded project-config loading.

Hook entry points and the configuration bridge use this module so they resolve
the same project file, defaults, and gate precedence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import operator
import os
import re
import stat
import sys
from functools import cache
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

try:
    # Relative first because every hook entry script imports this module as lib.config, where a bare name cannot resolve.
    from .findings import Outcome
    from .payloads import exact_string_dict
except ImportError:
    from findings import Outcome
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
JUDGED_STATE = "judged"
SURFACE_PROSE = "prose"
SURFACE_COMMIT = "commit"
SURFACES = (SURFACE_PROSE, SURFACE_COMMIT)
SURFACE_ALL = "all"
# WHY: A family carries no exemplars, so only a single rule can be sent to a reader instead of blocking on its own.
RULE_GATE_STATES = (*GATE_STATES, JUDGED_STATE)

# Scoped to families a live hook already emits, because defining a gate state before the family exists is speculative schema creep.
GATE_FAMILIES = ("punctuation", "english", "clean_code")

DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    "max_rows": 8,
    "sentence_word_cap": 40,
    "list_item_cap": 8,
    "adw_model": "",
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
        # Observe because 2 held-out true positives in AI Generated Essays Dataset.csv (n=40) yielded 1.0000 precision.
        "weighted_slop_marker": "observe",
        # Observe because 1 held-out true positive in AI Generated Essays Dataset.csv (n=40) yielded 1.0000 precision.
        "formulaic_opener": "observe",
        # Observe because 1 held-out true positive in AI Generated Essays Dataset.csv (n=40) yielded 1.0000 precision.
        "formulaic_filler": "observe",
        # Observe because 24 in-sample true positives in AI Generated Essays Dataset.csv (n=82) yielded 0.8000 precision.
        "low_sentence_variance": "observe",
        # Observe because the pattern is commoner in human literature (4.92 percent) than in assistant replies (0.55).
        "uniform_paragraph_endings": "observe",
        # Judged because 278 of 60000 human sentences carry an ordinary three-item series.
        "three_item_list": "judged",
        # Enforce because an agent writing these must rewrite them, and baseline reporting keeps inherited debt from blocking.
        "throat_clearing_opener": "enforce",
        "emphasis_crutch": "enforce",
        "meta_commentary": "enforce",
        "telling_not_showing": "enforce",
        "vague_declarative": "enforce",
        "performative_emphasis": "enforce",
        "business_jargon": "enforce",
        "filler_phrase": "enforce",
        "binary_contrast": "enforce",
        "negative_listing": "enforce",
        "dramatic_fragmentation": "enforce",
        "formulaic_construction": "enforce",
        "false_agency": "enforce",
        "narrator_distance": "enforce",
        "rhetorical_setup": "enforce",
        "lazy_extreme": "enforce",
        "passive_voice": "enforce",
        "banned_adverb": "enforce",
        "weak_sentence_starter": "enforce",
        "file_length_warning": "observe",
        "file_length_critical": "observe",
    },
    # Bypassed by ALWAYS_BLOCKING_RULES because those rules must stay unsuppressable.
    "kill_switches": {},
    # Off until the E7-H policy gate clears it because redaction needs a human decision on identifier classes and key custody.
    "data_boundary": {"enabled": False},
}


class RuleCalibration(NamedTuple):
    corpus: str
    sample_size: int
    true_positive: int
    precision: float
    sample_kind: str


RULE_CALIBRATIONS: dict[str, RuleCalibration] = {
    "weighted_slop_marker": RuleCalibration("AI Generated Essays Dataset.csv", 40, 2, 1.0000, "held-out"),
    "formulaic_opener": RuleCalibration("AI Generated Essays Dataset.csv", 40, 1, 1.0000, "held-out"),
    "formulaic_filler": RuleCalibration("AI Generated Essays Dataset.csv", 40, 1, 1.0000, "held-out"),
    "low_sentence_variance": RuleCalibration("~/dev markdown p05 of 709 paragraphs", 709, 0, 0.0, "unmeasurable"),
    "three_item_list": RuleCalibration("benchmark_patterns.jsonl", 121, 90, 1.0000, JUDGED_STATE),
}


@cache
def _slop_phrase_candidate_re() -> re.Pattern[str]:
    try:
        from .slop_phrase import _FORMULAIC_PATTERNS, WEIGHTED_MARKERS
    except ImportError:
        from slop_phrase import _FORMULAIC_PATTERNS, WEIGHTED_MARKERS
    weighted = "|".join(re.escape(marker.phrase) for marker in WEIGHTED_MARKERS)
    formulaic = "|".join(
        f"(?:{pattern.pattern})"
        for patterns in _FORMULAIC_PATTERNS.values()
        for pattern in patterns
    )
    return re.compile(r"\b(?:" + weighted + r")\b|(?:" + formulaic + r")", re.IGNORECASE)


def slop_phrase_candidate(text: str) -> bool:
    return _slop_phrase_candidate_re().search(text) is not None


CONFIG_NAME = ".agent-discipline.json"
MAX_PROJECT_CONFIG_BYTES = 256 * 1024
MAX_PROJECT_CONFIG_DEPTH = 32


@dataclass(frozen=True, slots=True)
class StorageRoots:
    state: str | os.PathLike[str] | None
    ledger: str | os.PathLike[str] | None


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Hold the parsed project document and its content digest for one read."""

    path: Path
    data: dict[str, object]
    settings: dict[str, object]
    digest: str | None
    exists: bool


class ConfigLoadError(ValueError):
    """Report a project config that cannot be safely read or validated."""


def _reject_json_constant(value: str) -> object:
    """Reject NaN and Infinity so the bridge accepts JSON rather than Python extensions."""
    raise ValueError(f"non-standard JSON constant {value}")


def _reject_duplicate_keys(pairs: list[tuple[object, object]]) -> dict[object, object]:
    """Reject duplicate object keys so a later value cannot hide an earlier policy value."""
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _check_json_depth(raw: bytes) -> None:
    """Reject deeply nested JSON before the standard decoder walks attacker data."""
    stack: list[int] = []
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
            continue
        if byte == 34:
            in_string = True
        elif byte in (91, 123):
            stack.append(byte)
            if len(stack) > MAX_PROJECT_CONFIG_DEPTH:
                raise ConfigLoadError("project config nesting exceeds the limit")
        elif byte in (93, 125):
            if not stack or (byte == 93 and stack[-1] != 91) or (byte == 125 and stack[-1] != 123):
                raise ConfigLoadError("project config has mismatched delimiters")
            stack.pop()


def _read_project_bytes(path: Path) -> bytes | None:
    """Read at most the configured project-file limit, including a race-safe second bound."""
    descriptor = -1
    try:
        if path.stat().st_size > MAX_PROJECT_CONFIG_BYTES:
            raise ConfigLoadError("project config exceeds the size limit")
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigLoadError("project config is not a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_PROJECT_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigLoadError(f"project config is unreadable: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > MAX_PROJECT_CONFIG_BYTES:
        raise ConfigLoadError("project config exceeds the size limit")
    return raw


def _validate_legacy_family_values(fields: dict[str, object]) -> None:
    """Require literal JSON booleans for legacy family switches in either namespace."""
    namespaces = [fields]
    checks = fields.get("checks")
    if operator.is_(type(checks), dict):
        namespaces.append(checks)
    for namespace in namespaces:
        for family in GATE_FAMILIES:
            if family in namespace and not operator.is_(type(namespace[family]), bool):
                raise ConfigLoadError(f"legacy family {family} must be a JSON boolean")


def _parse_project_config(path: Path, raw: bytes) -> ProjectConfig:
    """Decode one bounded project document and return its flattened policy settings."""
    _check_json_depth(raw)
    try:
        text = raw.decode("utf-8")
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ConfigLoadError(f"project config is not valid JSON: {exc}") from exc
    if not operator.is_(type(data), dict):
        raise ConfigLoadError("project config must contain a JSON object")
    fields = exact_string_dict(data)
    _validate_legacy_family_values(fields)
    return ProjectConfig(path, fields, flatten_settings(fields), hashlib.sha256(raw).hexdigest(), True)


def load_project_config(path: str | os.PathLike[str]) -> ProjectConfig:
    """Load a bounded project config, returning an empty record when the file is absent."""
    target = Path(path)
    raw = _read_project_bytes(target)
    if raw is None:
        return ProjectConfig(target, {}, {}, None, False)
    return _parse_project_config(target, raw)


def _safe_settings(data: object) -> dict[str, object]:
    """Drop malformed legacy booleans from caller-provided settings so hooks fail closed."""
    if data is not None and not operator.is_(type(data), dict):
        raise ValueError("configuration must be a mapping")
    settings = flatten_settings(data)
    for family in GATE_FAMILIES:
        if family in settings and not operator.is_(type(settings[family]), bool):
            settings.pop(family)
    return settings

def flatten_settings(data: object) -> dict:
    """Flattened once here so that every caller checks one namespace instead of guessing whether a setting lives at the top level or under checks."""
    fields = exact_string_dict(data)
    settings = exact_string_dict(fields.get("checks"))
    settings.update({key: value for key, value in fields.items() if key != "checks"})
    return settings


def _project_settings(cwd: str | os.PathLike[str]) -> dict:
    """Return validated project settings while converting malformed files into a safe default."""
    path = _find_project_config(Path(cwd))
    try:
        return load_project_config(path).settings
    except (OSError, ValueError, TypeError) as exc:
        # Named on stderr, because a config that silently fails closed still costs the user their exemptions and gates.
        sys.stderr.write(f"agent-discipline-watcher: could not read project config at {path}: {exc}\n")
        return {}


def effective_config(config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> dict:
    """Deep-copied here so that a caller mutating the merged result never corrupts the shared DEFAULTS dict for every other caller."""
    merged = copy.deepcopy(DEFAULTS)
    if cwd is not None:
        merged.update(_project_settings(cwd))
    if config is not None:
        merged.update(_safe_settings(config))
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


def _surface_state(gate: dict, surface: str | None) -> str | None:
    """Untagged counts as prose, because a prose rule set to off would otherwise keep blocking."""
    chosen = gate.get(surface or SURFACE_PROSE)
    if chosen is None:
        chosen = gate.get(SURFACE_ALL)
    return chosen if chosen in RULE_GATE_STATES else None


def _rule_state_from(cfg: dict, rule: str, surface: str | None = None) -> str | None:
    if not rule:
        return None
    gate = gate_map(cfg, "rule_gates").get(rule)
    if isinstance(gate, dict):
        return _surface_state(exact_string_dict(gate), surface)
    return gate if gate in RULE_GATE_STATES else None


def rule_state(rule: str, config: dict | None = None, surface: str | None = None) -> str | None:
    """Merge DEFAULTS here, because a standalone caller has no already-merged cfg the way resolve_outcome does."""
    return _rule_state_from(effective_config(config), rule, surface)


def calibration_detail(rule: str) -> str | None:
    calibration = RULE_CALIBRATIONS.get(rule)
    if calibration is None:
        return None
    return (
        "Calibration: "
        f"{calibration.precision:.4f} precision, {calibration.true_positive} true positives, "
        f"{calibration.corpus}, n={calibration.sample_size}, {calibration.sample_kind}."
    )


def calibrated_findings(findings: list[dict]) -> list[dict]:
    calibrated: list[dict] = []
    for finding in findings:
        detail = calibration_detail(finding["rule"])
        calibrated.append(finding if detail is None else {**finding, "detail": finding["detail"] + " " + detail})
    return calibrated


def _outcome_for(state: str) -> Outcome:
    if state == "enforce":
        return Outcome.BLOCK
    return Outcome.WOULD_BLOCK if state == "observe" else Outcome.RELEASE


def resolve_outcome(finding: dict, config: dict | None = None) -> Outcome:
    """Centralized here because every gate, family, per-rule, and always-blocking, must resolve through the same order or hooks would disagree on precedence."""
    rule = finding.get("rule", "") if isinstance(finding, dict) else ""
    if rule in ALWAYS_BLOCKING_RULES:
        return Outcome.BLOCK
    if rule in FIXED_OBSERVE_RULES:
        return Outcome.WOULD_BLOCK
    # Merged once here because gate_state and rule_state each re-merging DEFAULTS doubled the cost of every finding.
    cfg = effective_config(config)
    surface = finding.get("surface") if isinstance(finding, dict) else None
    own = _rule_state_from(cfg, rule, surface if isinstance(surface, str) else None)
    if own is not None:
        return _outcome_for(own)
    family = finding.get("family", "") if isinstance(finding, dict) else ""
    return _outcome_for(_gate_state_from(cfg, family))


def _storage_roots(values: tuple[object, ...], named: dict[str, object]) -> StorageRoots:
    if len(values) == 1 and isinstance(values[0], StorageRoots) and not named:
        return values[0]
    if len(values) > 2:
        raise TypeError("record_state_transitions accepts at most two root values")
    roots: dict[str, object] = dict(zip(("state_root", "ledger_root"), values, strict=False))
    for name, value in named.items():
        if name not in {"state_root", "ledger_root"} or name in roots:
            raise TypeError(f"record_state_transitions got an invalid keyword: {name}")
        roots[name] = value
    state = roots.get("state_root")
    ledger = roots.get("ledger_root")
    if state is not None and not isinstance(state, (str, os.PathLike)):
        raise TypeError("state_root must be a path or None")
    if ledger is not None and not isinstance(ledger, (str, os.PathLike)):
        raise TypeError("ledger_root must be a path or None")
    return StorageRoots(state, ledger)


def record_state_transitions(
    session_id: str,
    config: dict | None,
    *roots: object,
    **named_roots: object,
) -> list[dict]:
    """Append one ledger row per family whose state changed since the last snapshot, swallowing state and ledger errors so a hook never fails."""
    if not session_id:
        return []
    storage = _storage_roots(roots, named_roots)
    try:
        return _record_transitions(session_id, config, storage)
    except (OSError, json.JSONDecodeError) as exc:
        # Narrowed to storage failures, because a defeat-to-off transition is exactly the kind of change an observed agent wants unlogged.
        sys.stderr.write(f"agent-discipline-watcher: state-transition log failed: {exc}\n")
        return []


def _ledger_modules() -> tuple[ModuleType, ModuleType]:
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
    roots: StorageRoots,
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

    session_state.update_state_strict(session_id, diff_and_snapshot, roots.state)
    for row in captured:
        reporting.append_row(row, roots.ledger)
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
