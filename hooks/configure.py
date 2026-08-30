"""Bounded bridge for the OMP ADW policy screen.

This route exposes only policy metadata, known policy values, and redacted
runtime status. It owns compare-and-swap writes while the shared config module
remains the policy-resolution authority.
"""
from __future__ import annotations
# pylint: disable=unidiomatic-typecheck

import copy
import fcntl
import hmac
import json
import os
import pwd
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    from .lib import config
except ImportError:
    from lib import config


CONFIGURE_EVENT = "Configure"
CAPABILITY_ENV = "ADW_CONFIG_CAPABILITY"
CAPABILITY_FILE_ENV = "ADW_CONFIG_CAPABILITY_FILE"
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_CAPABILITY_BYTES = 4096
MAX_CWD_CHARS = 4096
MAX_VALUE_STRING_CHARS = 4096
MAX_LIST_ITEMS = 512
MAX_MAPPING_ITEMS = 512
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

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
_MISSING = object()


class ConfigureError(ValueError):
    """Represent a client, capability, conflict, or persistence failure."""

    def __init__(self, code: str, message: str) -> None:
        """Store a stable machine-readable error code beside the safe message."""
        super().__init__(message)
        self.code = code


def _error(code: str, message: str, operation: str | None = None) -> dict[str, object]:
    """Build the fixed error envelope without returning input or file contents."""
    response: dict[str, object] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if operation is not None:
        response["operation"] = operation
    return response


def _bounded_text(value: object, field: str, limit: int = MAX_VALUE_STRING_CHARS) -> str:
    """Validate a bounded text value and reject control characters that could corrupt a UI."""
    if type(value) is not str:
        raise ConfigureError("invalid_value", f"{field} must be a string")
    if not value or len(value) > limit:
        raise ConfigureError("invalid_value", f"{field} has an invalid length")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ConfigureError("invalid_value", f"{field} contains a control character")
    return value


def _bounded_cwd(request: dict[str, object], *, optional: bool = False) -> Path:
    """Resolve a bounded caller cwd while keeping path selection outside policy values."""
    value = request.get("cwd", ".")
    if optional and value is None:
        value = "."
    text = _bounded_text(value, "cwd", MAX_CWD_CHARS)
    try:
        return Path(text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ConfigureError("invalid_cwd", "cwd cannot be resolved") from exc


def _mapping(value: object, field: str) -> dict[str, object]:
    """Require a plain JSON object with bounded entry count."""
    if type(value) is not dict:
        raise ConfigureError("invalid_value", f"{field} must be an object")
    if len(value) > MAX_MAPPING_ITEMS:
        raise ConfigureError("invalid_value", f"{field} has too many entries")
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ConfigureError("invalid_value", f"{field} has a non-string key")
        _bounded_text(key, f"{field} key")
        result[key] = item
    return result


def _string_list(value: object, field: str) -> list[str]:
    """Validate a bounded list of display-safe strings."""
    if type(value) is not list or len(value) > MAX_LIST_ITEMS:
        raise ConfigureError("invalid_value", f"{field} must be a bounded list")
    return [_bounded_text(item, f"{field} entry") for item in value]


def _validate_family_booleans(values: dict[str, object], field: str) -> None:
    """Require exact booleans for legacy family switches, including the checks alias."""
    for family in LEGACY_FAMILY_KEYS:
        if family in values and type(values[family]) is not bool:
            raise ConfigureError("invalid_value", f"{field}.{family} must be a JSON boolean")


def _validate_policy_values(values: object) -> dict[str, object]:  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Validate only fields the OMP screen may write and lock protected rules."""
    fields = _mapping(values, "values")
    for key in fields:
        if key in PROTECTED_POLICY_KEYS:
            raise ConfigureError("protected_field", f"{key} is not editable policy")
        if key not in EDITABLE_KEY_SET and key != "checks":
            raise ConfigureError("unknown_field", f"{key} is not an editable policy field")

    _validate_family_booleans(fields, "values")
    if "checks" in fields:
        checks = _mapping(fields["checks"], "values.checks")
        unknown = set(checks) - LEGACY_FAMILY_KEYS
        if unknown:
            raise ConfigureError("unknown_field", "values.checks contains an unknown family")
        _validate_family_booleans(checks, "values.checks")
        fields["checks"] = checks

    for key in ("max_rows", "sentence_word_cap", "list_item_cap"):
        if key not in fields:
            continue
        value = fields[key]
        if type(value) is not int or isinstance(value, bool) or not 1 <= value <= 10000:
            raise ConfigureError("invalid_value", f"{key} must be an integer from 1 through 10000")
    if "adw_model" in fields:
        model = fields["adw_model"]
        if type(model) is not str or len(model) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in model):
            raise ConfigureError("invalid_value", "values.adw_model has an invalid value")
    if "exempt_paths" in fields:
        fields["exempt_paths"] = _string_list(fields["exempt_paths"], "values.exempt_paths")
    if "baseline" in fields:
        baseline = _bounded_text(fields["baseline"], "values.baseline", 32)
        if baseline not in BASELINE_MODES:
            raise ConfigureError("invalid_value", "baseline is not supported")

    if "gates" in fields:
        gates = _mapping(fields["gates"], "values.gates")
        if set(gates) - set(config.GATE_FAMILIES):
            raise ConfigureError("unknown_field", "values.gates contains an unknown family")
        if any(type(state) is not str or state not in config.GATE_STATES for state in gates.values()):
            raise ConfigureError("invalid_value", "family gates must use off, observe, or enforce")
        fields["gates"] = gates

    if "kill_switches" in fields:
        switches = _mapping(fields["kill_switches"], "values.kill_switches")
        if set(switches) - set(config.GATE_FAMILIES):
            raise ConfigureError("unknown_field", "values.kill_switches contains an unknown family")
        if any(type(enabled) is not bool for enabled in switches.values()):
            raise ConfigureError("invalid_value", "kill switches must be JSON booleans")
        fields["kill_switches"] = switches

    if "rule_gates" in fields:
        rule_gates = _mapping(fields["rule_gates"], "values.rule_gates")
        if set(rule_gates) - KNOWN_RULES:
            raise ConfigureError("unknown_field", "values.rule_gates contains an unknown rule")
        for rule, state in rule_gates.items():
            if rule in config.ALWAYS_BLOCKING_RULES and state != "enforce":
                raise ConfigureError("protected_rule", f"{rule} is always blocking")
            if type(state) is not str or state not in config.RULE_GATE_STATES:
                raise ConfigureError("invalid_value", "rule gates use off, observe, enforce, or judged")
        fields["rule_gates"] = rule_gates

    if "exempt_families" in fields:
        family_exemptions = _mapping(fields["exempt_families"], "values.exempt_families")
        for pattern, families in family_exemptions.items():
            family_list = _string_list(families, f"values.exempt_families.{pattern}")
            if set(family_list) - set(config.GATE_FAMILIES):
                raise ConfigureError("unknown_field", "exempt_families contains an unknown family")
            family_exemptions[pattern] = family_list
        fields["exempt_families"] = family_exemptions

    if "data_boundary" in fields:
        boundary = _mapping(fields["data_boundary"], "values.data_boundary")
        if set(boundary) - {"enabled"}:
            raise ConfigureError("unknown_field", "data_boundary contains an unknown field")
        if "enabled" in boundary and type(boundary["enabled"]) is not bool:
            raise ConfigureError("invalid_value", "data_boundary.enabled must be a JSON boolean")
        fields["data_boundary"] = boundary
    return fields


def _known_values(settings: object) -> dict[str, object]:  # pylint: disable=too-many-branches
    """Project parsed settings to the known OMP surface and exclude opaque keys."""
    fields = config.exact_string_dict(settings) if hasattr(config, "exact_string_dict") else {}
    if not fields and type(settings) is dict:
        fields = {key: value for key, value in settings.items() if type(key) is str}
    result: dict[str, object] = {}
    for key in EDITABLE_KEYS:
        if key not in fields:
            continue
        value = fields[key]
        if key in LEGACY_FAMILY_KEYS:
            result[key] = copy.deepcopy(value)
        elif key in {"gates", "kill_switches"}:
            if type(value) is not dict:
                result[key] = copy.deepcopy(value)
            else:
                result[key] = {
                    family: item
                    for family, item in value.items()
                    if family in LEGACY_FAMILY_KEYS
                }
        elif key == "rule_gates":
            if type(value) is not dict:
                result[key] = copy.deepcopy(value)
            else:
                result[key] = {rule: item for rule, item in value.items() if rule in KNOWN_RULES}
        elif key == "data_boundary":
            if type(value) is not dict:
                result[key] = copy.deepcopy(value)
            else:
                result[key] = {"enabled": value["enabled"]} if "enabled" in value else {}
        elif key == "exempt_families":
            if type(value) is not dict:
                result[key] = copy.deepcopy(value)
            else:
                filtered: dict[str, object] = {}
                for pattern, families in value.items():
                    if type(families) is list:
                        filtered[pattern] = [
                            family for family in families if family in LEGACY_FAMILY_KEYS
                        ]
                    else:
                        filtered[pattern] = copy.deepcopy(families)
                result[key] = filtered
        else:
            result[key] = copy.deepcopy(value)
    return _validate_policy_values(result)


def _runtime_status() -> dict[str, object]:
    """Return environment-only status without exposing URLs, userinfo, queries, or secrets."""
    python_value = os.environ.get("ADW_PYTHON", "")
    python_name = os.path.basename(python_value) if python_value else ""
    python_name = "".join(char for char in python_name if 32 <= ord(char) < 127)[:128]
    embedding_configured = bool(
        os.environ.get("ADW_EMBEDDING_URL", "").strip()
        or os.environ.get("ADW_EMBEDDING_URLS", "").strip()
    )
    return {
        "python": {"configured": bool(python_value), "executable": python_name},
        "embedding": {"configured": embedding_configured},
        "embedding_model": {"configured": bool(os.environ.get("ADW_EMBEDDING_MODEL", "").strip())},
    }


def _metadata() -> dict[str, object]:
    """Describe editable families and rules without exposing project-specific opaque data."""
    families = [
        {
            "name": family,
            "legacy_boolean": True,
            "states": list(config.GATE_STATES),
            "locked": False,
        }
        for family in config.GATE_FAMILIES
    ]
    rules = []
    for rule in sorted(KNOWN_RULES):
        locked = rule in config.ALWAYS_BLOCKING_RULES
        rules.append({
            "name": rule,
            "states": ["enforce"] if locked else list(config.RULE_GATE_STATES),
            "locked": locked,
        })
    return {
        "editable_fields": list(EDITABLE_KEYS),
        "families": families,
        "rules": rules,
        "always_blocking_rules": sorted(config.ALWAYS_BLOCKING_RULES),
    }


def _read_state(cwd: Path) -> dict[str, object]:
    """Read one canonical project file and return only the bridge's known values."""
    target = config.project_config_path(cwd)
    try:
        loaded = config.load_project_config(target)
    except config.ConfigLoadError as exc:
        raise ConfigureError("invalid_project_config", "project config could not be read safely") from exc
    values = _known_values(loaded.settings)
    effective_cfg = config.effective_config(values)
    effective = _known_values(effective_cfg)
    family_states = {family: config.gate_state(family, effective_cfg) for family in config.GATE_FAMILIES}
    rule_states = {
        rule: "enforce" if rule in config.ALWAYS_BLOCKING_RULES else (
            config.rule_state(rule, effective_cfg) or family_states.get("clean_code", "enforce")
        )
        for rule in sorted(KNOWN_RULES)
    }
    return {
        "project_path": str(target.parent),
        "config_path": str(target),
        "digest": loaded.digest,
        "exists": loaded.exists,
        "values": values,
        "effective": effective,
        "family_states": family_states,
        "rule_states": rule_states,
        "runtime": _runtime_status(),
        **_metadata(),
    }


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold a sidecar advisory lock for the complete read, compare, and replace transaction."""
    lock_path = Path(f"{path}.lock")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise ConfigureError("lock_failed", "could not open the configuration lock") from exc
    try:
        with os.fdopen(descriptor, "r+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise ConfigureError("lock_failed", "could not acquire the configuration lock") from exc
            try:
                yield
            finally:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError as exc:
        raise ConfigureError("lock_failed", "could not use the configuration lock") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace a project config atomically after writing and syncing a same-directory temporary file."""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory = -1
        if directory >= 0:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as exc:
        raise ConfigureError("write_failed", "project config could not be replaced") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _merge_values(current: dict[str, object], values: dict[str, object]) -> dict[str, object]:
    """Merge known edits into freshly reread data while retaining every opaque key."""
    merged = copy.deepcopy(current)
    checks = merged.get("checks")
    checks_mapping = dict(checks) if type(checks) is dict else {}
    for key, value in values.items():
        if key == "checks":
            checks_mapping.update(copy.deepcopy(value))
            merged["checks"] = checks_mapping
        elif key in LEGACY_FAMILY_KEYS:
            if key in merged or type(merged.get("checks")) is not dict:
                merged[key] = value
            else:
                checks_mapping[key] = value
                merged["checks"] = checks_mapping
        elif key in {"gates", "rule_gates", "kill_switches", "exempt_families", "data_boundary"}:
            previous = merged.get(key)
            mapping = dict(previous) if type(previous) is dict else {}
            mapping.update(copy.deepcopy(value))
            merged[key] = mapping
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _expected_digest(request: dict[str, object]) -> str | None:
    """Validate the compare-and-swap digest, using null only for an absent file."""
    expected = request.get("expected_digest", _MISSING)
    if expected is _MISSING:
        raise ConfigureError("expected_digest_required", "write requires expected_digest")
    if expected is None:
        return None
    if type(expected) is not str or DIGEST_RE.fullmatch(expected) is None:
        raise ConfigureError("invalid_digest", "expected_digest must be a SHA-256 hex digest or null")
    return expected


def _read_parent_process(parent_pid: str, output_format: str) -> str | None:
    """Read one parent process field through the fixed system ps binary."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", parent_pid, "-o", output_format],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()

def _omp_parent_is_trusted() -> bool:
    """Require OMP identity, including the Bun launcher, before accepting a write token."""
    parent_pid = str(os.getppid())
    executable_text = _read_parent_process(parent_pid, "comm=")
    if executable_text is None:
        return False
    executable = Path(executable_text).name.lower()
    if executable in {"omp", "pi"}:
        return True
    if executable != "bun":
        return False
    command_line = _read_parent_process(parent_pid, "command=") or ""
    try:
        arguments = shlex.split(command_line)
    except ValueError:
        return False
    try:
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        account_home = None
    expected_launchers = (
        {
            (account_home / ".bun/bin/omp").resolve(),
            (account_home / ".bun/bin/pi").resolve(),
        }
        if account_home is not None
        else set()
    )
    for argument in arguments[1:]:
        candidate = Path(argument)
        if not candidate.is_absolute() or candidate.name.lower() not in {"omp", "pi"}:
            continue
        try:
            if candidate.resolve() in expected_launchers:
                return True
        except (OSError, RuntimeError):
            continue
    return False

def _consume_capability() -> None:  # pylint: disable=too-many-boolean-expressions
    """Consume an owner-only one-shot token file before allowing a policy write."""
    token = os.environ.get(CAPABILITY_ENV, "")
    path_text = os.environ.get(CAPABILITY_FILE_ENV, "")
    if (  # pylint: disable=too-many-boolean-expressions
        not isinstance(token, str)
        or not token.strip()
        or len(token) > MAX_CAPABILITY_BYTES
        or not isinstance(path_text, str)
        or not path_text
        or len(path_text) > MAX_CWD_CHARS
    ):
        raise ConfigureError("capability_required", "write requires the OMP capability")
    if not _omp_parent_is_trusted():
        raise ConfigureError("capability_required", "write requires the OMP capability")
    try:
        capability_path = Path(path_text)
        if not capability_path.is_absolute():
            raise ConfigureError("capability_required", "write requires the OMP capability")
        owner = os.getuid()
        parent_stat = capability_path.parent.stat()
        if parent_stat.st_uid != owner or parent_stat.st_mode & 0o022:
            raise ConfigureError("capability_required", "write requires the OMP capability")
        lock_path = Path(f"{capability_path}.lock")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "r+") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            try:
                capability_fd = os.open(
                    capability_path,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                )
                with os.fdopen(capability_fd, "rb") as capability_stream:
                    metadata = os.fstat(capability_stream.fileno())
                    path_metadata = os.stat(capability_path, follow_symlinks=False)
                    if (
                        path_metadata.st_dev != metadata.st_dev
                        or path_metadata.st_ino != metadata.st_ino
                    ):
                        raise ConfigureError("capability_required", "write requires the OMP capability")
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_uid != owner
                        or metadata.st_mode & 0o077
                        or metadata.st_nlink != 1
                    ):
                        raise ConfigureError("capability_required", "write requires the OMP capability")
                    body = capability_stream.read(MAX_CAPABILITY_BYTES + 1)
                expected = token.encode("utf-8")
                if len(body) > MAX_CAPABILITY_BYTES or not hmac.compare_digest(body, expected):
                    raise ConfigureError("capability_required", "write requires the OMP capability")
                os.unlink(capability_path)
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)
    except (OSError, UnicodeEncodeError) as exc:
        raise ConfigureError("capability_required", "write requires the OMP capability") from exc


def _write_state(request: dict[str, object]) -> dict[str, object]:
    """Perform one capability-gated compare-and-swap write under the canonical config lock."""
    _consume_capability()
    cwd = _bounded_cwd(request)
    expected = _expected_digest(request)
    values = _validate_policy_values(request.get("values", _MISSING))
    target = config.project_config_path(cwd)
    with _locked(target):
        try:
            current = config.load_project_config(target)
        except config.ConfigLoadError as exc:
            raise ConfigureError("invalid_project_config", "project config could not be read safely") from exc
        if current.digest != expected:
            raise ConfigureError("digest_conflict", "project config changed since it was read")
        merged = _merge_values(current.data, values)
        serialized = json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        if len(serialized) > config.MAX_PROJECT_CONFIG_BYTES:
            raise ConfigureError("size_limit", "project config exceeds the size limit")
        try:
            candidate = config._parse_project_config(target, serialized)
        except config.ConfigLoadError as exc:
            raise ConfigureError("invalid_project_config", "project config could not be written safely") from exc
        _known_values(candidate.settings)
        _atomic_write(target, serialized)
        response = _read_state(cwd)
        response["written"] = True
        return response


def run(request: object) -> dict[str, object]:  # pylint: disable=too-many-return-statements
    """Dispatch describe, read, validate, or write and convert failures to a fixed response."""
    if type(request) is not dict:
        return _error("invalid_request", "Configure expects a JSON object")
    fields = {key: value for key, value in request.items() if type(key) is str}
    operation = fields.get("operation")
    if type(operation) is not str or operation not in {"describe", "read", "validate", "write"}:
        return _error("invalid_operation", "operation must be describe, read, validate, or write")
    try:
        if operation == "describe":
            response: dict[str, object] = {"ok": True, "operation": operation, **_metadata(), "runtime": _runtime_status()}
            if "cwd" in fields:
                cwd = _bounded_cwd(fields, optional=True)
                target = config.project_config_path(cwd)
                response.update({"project_path": str(target.parent), "config_path": str(target)})
            return response
        if operation == "validate":
            values = _validate_policy_values(fields.get("values"))
            return {"ok": True, "operation": operation, "values": values}
        cwd = _bounded_cwd(fields)
        if operation == "read":
            response = _read_state(cwd)
            response.update({"ok": True, "operation": operation})
            return response
        response = _write_state(fields)
        response.update({"ok": True, "operation": operation})
        return response
    except ConfigureError as exc:
        return _error(exc.code, str(exc), operation)
    except (OSError, ValueError, TypeError, RuntimeError):
        return _error("bridge_failure", "Configure could not complete the requested operation", operation)


def _read_request() -> dict[str, object] | None:
    """Read a bounded JSON request and return null after emitting no untrusted parse details."""
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
    """Serve one fixed Configure request on stdin and emit one bounded JSON response."""
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
