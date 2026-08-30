"""Policy validation for the configuration bridge, kept apart because a screen must never widen a gate."""
from __future__ import annotations

import copy

try:
    from . import config
except ImportError:
    import config

MAX_CWD_CHARS = 4096
MAX_VALUE_STRING_CHARS = 4096
MAX_LIST_ITEMS = 512
MAX_MAPPING_ITEMS = 512

EDITABLE_KEYS = (
    "punctuation",
    "english",
    "clean_code",
    "max_rows",
    "sentence_word_cap",
    "list_item_cap",
    "adw_model",
    "exempt_paths",
    "exempt_families",
    "baseline",
    "gates",
    "rule_gates",
    "kill_switches",
    "data_boundary",
)
EDITABLE_KEY_SET = frozenset(EDITABLE_KEYS)
LEGACY_FAMILY_KEYS = frozenset(config.GATE_FAMILIES)
KNOWN_RULES = frozenset(config.DEFAULTS["rule_gates"]) | frozenset(config.ALWAYS_BLOCKING_RULES)
BASELINE_MODES = frozenset({"git", "report", "none"})
PROTECTED_POLICY_KEYS = frozenset({
    "state_root",
    "ledger_root",
    "protected_paths_authorized",
})
THRESHOLD_KEYS = ("max_rows", "sentence_word_cap", "list_item_cap")
MAPPING_MERGE_KEYS = frozenset({
    "gates", "rule_gates", "kill_switches", "exempt_families", "data_boundary",
})
MISSING = object()


class ConfigureError(ValueError):
    """Carry a code because a caller must branch on the failure without parsing the message."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code apart because the message wording may change without breaking a client."""
        super().__init__(message)
        self.code = code


def bounded_text(value: object, field: str, limit: int = MAX_VALUE_STRING_CHARS) -> str:
    """Reject a control character because it would corrupt the terminal that renders it."""
    if type(value) is not str:
        raise ConfigureError("invalid_value", f"{field} must be a string")
    if not value or len(value) > limit:
        raise ConfigureError("invalid_value", f"{field} has an invalid length")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigureError("invalid_value", f"{field} contains a control character")
    return value


def mapping(value: object, field: str) -> dict[str, object]:
    """Bound the entry count because an unbounded object would exhaust the response limit."""
    if type(value) is not dict:
        raise ConfigureError("invalid_value", f"{field} must be an object")
    if len(value) > MAX_MAPPING_ITEMS:
        raise ConfigureError("invalid_value", f"{field} has too many entries")
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ConfigureError("invalid_value", f"{field} has a non-string key")
        bounded_text(key, f"{field} key")
        result[key] = item
    return result


def string_list(value: object, field: str) -> list[str]:
    """Bound the length because an unbounded list would exhaust the response limit."""
    if type(value) is not list or len(value) > MAX_LIST_ITEMS:
        raise ConfigureError("invalid_value", f"{field} must be a bounded list")
    return [bounded_text(item, f"{field} entry") for item in value]


def _family_booleans(values: dict[str, object], field: str) -> None:
    for family in LEGACY_FAMILY_KEYS:
        if family in values and type(values[family]) is not bool:
            raise ConfigureError("invalid_value", f"{field}.{family} must be a JSON boolean")


def _thresholds(fields: dict[str, object]) -> None:
    for key in THRESHOLD_KEYS:
        if key not in fields:
            continue
        value = fields[key]
        if type(value) is not int or isinstance(value, bool) or not 1 <= value <= 10000:
            raise ConfigureError("invalid_value", f"{key} must be an integer from 1 through 10000")


def _judge_model(fields: dict[str, object]) -> None:
    if "adw_model" not in fields:
        return
    model = fields["adw_model"]
    if type(model) is not str or len(model) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ConfigureError("invalid_value", "values.adw_model has an invalid value")


def _editable_keys(fields: dict[str, object]) -> None:
    for key in fields:
        if key in PROTECTED_POLICY_KEYS:
            raise ConfigureError("protected_field", f"{key} is not editable policy")
        if key not in EDITABLE_KEY_SET and key != "checks":
            raise ConfigureError("unknown_field", f"{key} is not an editable policy field")


def _checks(fields: dict[str, object]) -> None:
    if "checks" not in fields:
        return
    checks = mapping(fields["checks"], "values.checks")
    if set(checks) - LEGACY_FAMILY_KEYS:
        raise ConfigureError("unknown_field", "values.checks contains an unknown family")
    _family_booleans(checks, "values.checks")
    fields["checks"] = checks


def _baseline(fields: dict[str, object]) -> None:
    if "baseline" not in fields:
        return
    if bounded_text(fields["baseline"], "values.baseline", 32) not in BASELINE_MODES:
        raise ConfigureError("invalid_value", "baseline is not supported")


def _gates(fields: dict[str, object]) -> None:
    if "gates" not in fields:
        return
    gates = mapping(fields["gates"], "values.gates")
    if set(gates) - set(config.GATE_FAMILIES):
        raise ConfigureError("unknown_field", "values.gates contains an unknown family")
    if any(type(state) is not str or state not in config.GATE_STATES for state in gates.values()):
        raise ConfigureError("invalid_value", "family gates must use off, observe, or enforce")
    fields["gates"] = gates


def _kill_switches(fields: dict[str, object]) -> None:
    if "kill_switches" not in fields:
        return
    switches = mapping(fields["kill_switches"], "values.kill_switches")
    if set(switches) - set(config.GATE_FAMILIES):
        raise ConfigureError("unknown_field", "values.kill_switches contains an unknown family")
    if any(type(enabled) is not bool for enabled in switches.values()):
        raise ConfigureError("invalid_value", "kill switches must be JSON booleans")
    fields["kill_switches"] = switches


def _rule_gates(fields: dict[str, object]) -> None:
    if "rule_gates" not in fields:
        return
    rule_gates = mapping(fields["rule_gates"], "values.rule_gates")
    if set(rule_gates) - KNOWN_RULES:
        raise ConfigureError("unknown_field", "values.rule_gates contains an unknown rule")
    for rule, state in rule_gates.items():
        _rule_gate_value(rule, state)
    fields["rule_gates"] = rule_gates


def _rule_gate_state(rule: str, state: object) -> None:
    if rule in config.ALWAYS_BLOCKING_RULES and state != "enforce":
        raise ConfigureError("protected_rule", f"{rule} is always blocking")
    if type(state) is not str or state not in config.RULE_GATE_STATES:
        raise ConfigureError("invalid_value", "rule gates use off, observe, enforce, or judged")


def _rule_gate_value(rule: str, value: object) -> None:
    """Checked key by key, because one bad surface would otherwise pass under a good one."""
    if type(value) is not dict:
        _rule_gate_state(rule, value)
        return
    if not value:
        raise ConfigureError("invalid_value", "a rule gate map names at least one surface")
    allowed = set(config.SURFACES) | {config.SURFACE_ALL}
    for surface, state in value.items():
        if type(surface) is not str or surface not in allowed:
            raise ConfigureError("invalid_value", "rule gate surfaces are prose, commit, or all")
        _rule_gate_state(rule, state)


def _exempt_families(fields: dict[str, object]) -> None:
    if "exempt_families" not in fields:
        return
    exemptions = mapping(fields["exempt_families"], "values.exempt_families")
    for pattern, families in exemptions.items():
        family_list = string_list(families, f"values.exempt_families.{pattern}")
        if set(family_list) - set(config.GATE_FAMILIES):
            raise ConfigureError("unknown_field", "exempt_families contains an unknown family")
        exemptions[pattern] = family_list
    fields["exempt_families"] = exemptions


def _data_boundary(fields: dict[str, object]) -> None:
    if "data_boundary" not in fields:
        return
    boundary = mapping(fields["data_boundary"], "values.data_boundary")
    if set(boundary) - {"enabled"}:
        raise ConfigureError("unknown_field", "data_boundary contains an unknown field")
    if "enabled" in boundary and type(boundary["enabled"]) is not bool:
        raise ConfigureError("invalid_value", "data_boundary.enabled must be a JSON boolean")
    fields["data_boundary"] = boundary


_VALIDATORS = (
    _checks, _thresholds, _judge_model, _baseline,
    _gates, _kill_switches, _rule_gates, _exempt_families, _data_boundary,
)


def validate_policy_values(values: object) -> dict[str, object]:
    """Lock protected rules here because every write path funnels through this one call."""
    fields = mapping(values, "values")
    _editable_keys(fields)
    _family_booleans(fields, "values")
    for validator in _VALIDATORS:
        validator(fields)
    if "exempt_paths" in fields:
        fields["exempt_paths"] = string_list(fields["exempt_paths"], "values.exempt_paths")
    return fields


def _family_filtered(value: object) -> object:
    if type(value) is not dict:
        return copy.deepcopy(value)
    return {family: item for family, item in value.items() if family in LEGACY_FAMILY_KEYS}


def _rule_filtered(value: object) -> object:
    if type(value) is not dict:
        return copy.deepcopy(value)
    return {rule: item for rule, item in value.items() if rule in KNOWN_RULES}


def _boundary_filtered(value: object) -> object:
    if type(value) is not dict:
        return copy.deepcopy(value)
    return {"enabled": value["enabled"]} if "enabled" in value else {}


def _exemption_filtered(value: object) -> object:
    if type(value) is not dict:
        return copy.deepcopy(value)
    filtered: dict[str, object] = {}
    for pattern, families in value.items():
        if type(families) is list:
            filtered[pattern] = [family for family in families if family in LEGACY_FAMILY_KEYS]
        else:
            filtered[pattern] = copy.deepcopy(families)
    return filtered


_PROJECTORS = {
    "gates": _family_filtered,
    "kill_switches": _family_filtered,
    "rule_gates": _rule_filtered,
    "data_boundary": _boundary_filtered,
    "exempt_families": _exemption_filtered,
}


def _source_fields(settings: object) -> dict[str, object]:
    fields = config.exact_string_dict(settings) if hasattr(config, "exact_string_dict") else {}
    if not fields and type(settings) is dict:
        fields = {key: value for key, value in settings.items() if type(key) is str}
    return fields


def known_values(settings: object) -> dict[str, object]:
    """Drop every opaque key because the bridge must not echo data it cannot validate."""
    fields = _source_fields(settings)
    result: dict[str, object] = {}
    for key in EDITABLE_KEYS:
        if key not in fields:
            continue
        projector = _PROJECTORS.get(key)
        result[key] = projector(fields[key]) if projector else copy.deepcopy(fields[key])
    return validate_policy_values(result)


def _merged_mapping(previous: object, value: object) -> dict[str, object]:
    entry = dict(previous) if type(previous) is dict else {}
    entry.update(copy.deepcopy(value))
    return entry


def _apply_legacy_family(merged: dict, checks: dict, item: tuple[str, object]) -> None:
    key, value = item
    if key in merged or type(merged.get("checks")) is not dict:
        merged[key] = value
        return
    checks[key] = value
    merged["checks"] = checks


def _merge_checks(merged: dict, checks: dict, item: tuple[str, object]) -> None:
    checks.update(copy.deepcopy(item[1]))
    merged["checks"] = checks


def _merge_mapping_key(merged: dict, _checks: dict, item: tuple[str, object]) -> None:
    key, value = item
    merged[key] = _merged_mapping(merged.get(key), value)


def _merge_plain(merged: dict, _checks: dict, item: tuple[str, object]) -> None:
    key, value = item
    merged[key] = copy.deepcopy(value)


def _merge_handler(key: str):
    if key == "checks":
        return _merge_checks
    if key in LEGACY_FAMILY_KEYS:
        return _apply_legacy_family
    if key in MAPPING_MERGE_KEYS:
        return _merge_mapping_key
    return _merge_plain


def merge_values(current: dict[str, object], values: dict[str, object]) -> dict[str, object]:
    """Retain every opaque key because a write must not discard what it never read."""
    merged = copy.deepcopy(current)
    existing = merged.get("checks")
    checks = dict(existing) if type(existing) is dict else {}
    for item in values.items():
        _merge_handler(item[0])(merged, checks, item)
    return merged
