"""Expose only known policy names because a screen must never widen a gate or leak a project path."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from .lib import catalog, config, configure_capability, configure_policy, configure_store
except ImportError:
    from lib import catalog, config, configure_capability, configure_policy, configure_store

CONFIGURE_EVENT = "Configure"
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
OPERATIONS = frozenset({"describe", "read", "validate", "write"})

CAPABILITY_ENV = configure_capability.CAPABILITY_ENV
CAPABILITY_FILE_ENV = configure_capability.CAPABILITY_FILE_ENV
ConfigureError = configure_policy.ConfigureError
EDITABLE_KEYS = configure_policy.EDITABLE_KEYS
KNOWN_RULES = configure_policy.KNOWN_RULES
BASELINE_MODES = configure_policy.BASELINE_MODES


def _error(code: str, message: str, operation: str | None = None) -> dict[str, object]:
    """Return a fixed envelope because echoing input would leak the file that failed."""
    response: dict[str, object] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if operation is not None:
        response["operation"] = operation
    return response


def _bounded_cwd(request: dict[str, object], *, optional: bool = False) -> Path:
    """Resolve the caller directory here because path choice must stay outside policy values."""
    value = request.get("cwd", ".")
    if optional and value is None:
        value = "."
    text = configure_policy.bounded_text(value, "cwd", configure_policy.MAX_CWD_CHARS)
    try:
        return Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigureError("invalid_cwd", "cwd cannot be resolved") from exc


def _safe_executable_name(python_value: str) -> str:
    name = os.path.basename(python_value) if python_value else ""
    return "".join(char for char in name if 32 <= ord(char) < 127)[:128]


def _runtime_status() -> dict[str, object]:
    """Report presence only because a URL, a userinfo pair, or a query would leak a secret."""
    python_value = os.environ.get("ADW_PYTHON", "")
    embedding_configured = bool(
        os.environ.get("ADW_EMBEDDING_URL", "").strip()
        or os.environ.get("ADW_EMBEDDING_URLS", "").strip()
    )
    return {
        "python": {
            "configured": bool(python_value),
            "executable": _safe_executable_name(python_value),
        },
        "embedding": {"configured": embedding_configured},
        "embedding_model": {"configured": bool(os.environ.get("ADW_EMBEDDING_MODEL", "").strip())},
    }


def _worded(entry: catalog.Entry) -> dict[str, object]:
    return {"title": entry.title, "description": entry.description}


def _state_wording() -> dict[str, object]:
    return {
        "rule_states": {
            name: _worded(catalog.state_entry(name, locked=False))
            for name in config.RULE_GATE_STATES
        },
        "locked_state": _worded(catalog.LOCKED_STATE),
        "family_state_wording": {
            name: _worded(catalog.family_state_entry(name)) for name in config.GATE_STATES
        },
        "baseline_wording": {
            name: _worded(catalog.baseline_entry(name)) for name in sorted(BASELINE_MODES)
        },
        "thresholds": {
            name: _worded(catalog.threshold_entry(name)) for name in sorted(catalog.THRESHOLDS)
        },
    }


def _family_rows() -> list[dict[str, object]]:
    return [
        {
            "name": family,
            "legacy_boolean": True,
            "states": list(config.GATE_STATES),
            "locked": False,
            **_worded(catalog.family_entry(family)),
        }
        for family in config.GATE_FAMILIES
    ]


def _rule_rows() -> list[dict[str, object]]:
    rows = []
    for rule in sorted(KNOWN_RULES):
        locked = rule in config.ALWAYS_BLOCKING_RULES
        rows.append({
            "name": rule,
            "states": ["enforce"] if locked else list(config.RULE_GATE_STATES),
            "locked": locked,
            **_worded(catalog.rule_entry(rule)),
        })
    return rows


def _metadata() -> dict[str, object]:
    """Send only known policy names because the screen must never carry project data."""
    return {
        "editable_fields": list(EDITABLE_KEYS),
        "families": _family_rows(),
        "rules": _rule_rows(),
        "always_blocking_rules": sorted(config.ALWAYS_BLOCKING_RULES),
        "wording": _state_wording(),
    }


def _rule_state_value(rule: str, effective_cfg: object, family_states: dict[str, object]) -> object:
    """Kept whole, because collapsing a surface map to one state loses it on the next write."""
    if rule in config.ALWAYS_BLOCKING_RULES:
        return "enforce"
    configured = config.gate_map(config.effective_config(effective_cfg), "rule_gates").get(rule)
    if isinstance(configured, dict):
        return configured
    return config.rule_state(rule, effective_cfg) or family_states.get("clean_code", "enforce")


def _rule_states(effective_cfg: object, family_states: dict[str, object]) -> dict[str, object]:
    return {rule: _rule_state_value(rule, effective_cfg, family_states) for rule in sorted(KNOWN_RULES)}


def _load(target: Path):
    try:
        return config.load_project_config(target)
    except config.ConfigLoadError as exc:
        raise ConfigureError("invalid_project_config", "project config could not be read safely") from exc


def _read_state(cwd: Path) -> dict[str, object]:
    """Read one canonical file because a merged view would hide which project owns a value."""
    target = config.project_config_path(cwd)
    loaded = _load(target)
    values = configure_policy.known_values(loaded.settings)
    effective_cfg = config.effective_config(values)
    family_states = {
        family: config.gate_state(family, effective_cfg) for family in config.GATE_FAMILIES
    }
    return {
        "project_path": str(target.parent),
        "config_path": str(target),
        "digest": loaded.digest,
        "exists": loaded.exists,
        "values": values,
        "effective": configure_policy.known_values(effective_cfg),
        "family_states": family_states,
        "rule_states": _rule_states(effective_cfg, family_states),
        "runtime": _runtime_status(),
        **_metadata(),
    }


def _serialized(merged: dict[str, object]) -> bytes:
    data = json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(data) > config.MAX_PROJECT_CONFIG_BYTES:
        raise ConfigureError("size_limit", "project config exceeds the size limit")
    return data


def _reject_unwritable(target: Path, serialized: bytes) -> None:
    try:
        candidate = config._parse_project_config(target, serialized)
    except config.ConfigLoadError as exc:
        raise ConfigureError("invalid_project_config", "project config could not be written safely") from exc
    configure_policy.known_values(candidate.settings)


def _write_state(request: dict[str, object]) -> dict[str, object]:
    """Gate on a capability because the screen must never become an unauthenticated write path."""
    configure_capability.consume_capability()
    cwd = _bounded_cwd(request)
    expected = configure_store.expected_digest(request)
    values = configure_policy.validate_policy_values(request.get("values", configure_policy.MISSING))
    target = config.project_config_path(cwd)
    with configure_store.locked(target):
        current = _load(target)
        if current.digest != expected:
            raise ConfigureError("digest_conflict", "project config changed since it was read")
        serialized = _serialized(configure_policy.merge_values(current.data, values))
        _reject_unwritable(target, serialized)
        configure_store.atomic_write(target, serialized)
        response = _read_state(cwd)
        response["written"] = True
        return response


def _describe(fields: dict[str, object]) -> dict[str, object]:
    response: dict[str, object] = {
        "ok": True, "operation": "describe", **_metadata(), "runtime": _runtime_status(),
    }
    if "cwd" in fields:
        target = config.project_config_path(_bounded_cwd(fields, optional=True))
        response.update({"project_path": str(target.parent), "config_path": str(target)})
    return response


def _dispatch(operation: str, fields: dict[str, object]) -> dict[str, object]:
    if operation == "describe":
        return _describe(fields)
    if operation == "validate":
        values = configure_policy.validate_policy_values(fields.get("values"))
        return {"ok": True, "operation": operation, "values": values}
    cwd = _bounded_cwd(fields)
    response = _read_state(cwd) if operation == "read" else _write_state(fields)
    response.update({"ok": True, "operation": operation})
    return response


def run(request: object) -> dict[str, object]:
    """Convert every failure to a fixed envelope because a traceback would leak project paths."""
    if type(request) is not dict:
        return _error("invalid_request", "Configure expects a JSON object")
    fields = {key: value for key, value in request.items() if type(key) is str}
    operation = fields.get("operation")
    if type(operation) is not str or operation not in OPERATIONS:
        return _error("invalid_operation", "operation must be describe, read, validate, or write")
    try:
        return _dispatch(operation, fields)
    except ConfigureError as exc:
        return _error(exc.code, str(exc), operation)
    except (OSError, ValueError, TypeError, RuntimeError):
        return _error("bridge_failure", "Configure could not complete the requested operation", operation)


def _read_request() -> dict[str, object] | None:
    """Emit no parse detail because the request came from a surface ADW does not trust."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(MAX_REQUEST_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_REQUEST_BYTES:
        return None
    if not raw.strip():
        return {}
    try:
        config._check_json_depth(raw)
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=config._reject_duplicate_keys)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return request if type(request) is dict else None


def main() -> int:
    """Bound the response because an oversized payload would break the caller that reads it."""
    request = _read_request()
    if request is None:
        response = _error("invalid_request", "Configure received invalid or oversized JSON")
    else:
        response = run(request)
    encoded = json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        response = _error("response_limit", "Configure response exceeds the output limit")
        encoded = json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(encoded + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
