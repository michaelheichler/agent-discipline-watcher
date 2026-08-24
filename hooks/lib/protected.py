"""Hard-blocked here because an agent that can edit its own watcher's live config or install can also disable the watcher."""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    # Relative first because every hook entry script imports this module as lib.protected, where a bare name cannot resolve.
    from .config import ALWAYS_BLOCKING_RULES, GATE_FAMILIES, flatten_settings
    from .payloads import exact_string_dict
except ImportError:
    from config import ALWAYS_BLOCKING_RULES, GATE_FAMILIES, flatten_settings
    from payloads import exact_string_dict

CONFIG_SEAL_BASENAME = ".agent-discipline.json"
AUTH_ENV = "ADW_ALLOW_PROTECTED_EDIT"
AUTH_KEY = "protected_paths_authorized"
TRUTHY = frozenset({"1", "true", "yes", "on"})

CLAUDE_EXEMPT_DIRS = frozenset({
    "jobs", "projects", "todos", "shell-snapshots",
    "statsig", "logs", "ide", "tool-results", "downloads",
})
CLAUDE_WIRING_DIRS = frozenset({"skills", "agents", "hooks", "commands"})
CLIENT_HOME_DIRS = frozenset({".codex", ".pi", ".omp"})

LIVE_ACTION = (
    "Change the repo source and reinstall instead of editing the live install. If this edit "
    "is intentional, ask the human to export "
    + AUTH_ENV
    + " in the hook environment, which is the only supported escape."
)
SEAL_ACTION = "Fix the reported finding instead of changing the gate config."
STATE_ACTION = "Leave watcher state under host control and repair the reported finding."
GRANT_ACTION = (
    "The config key no longer grants anything. Ask the human to export "
    + AUTH_ENV
    + " in the hook environment, which is the only supported escape."
)


class UnresolvableTildePath(ValueError):
    """Raised when a ~user token cannot be expanded, since the target cannot be verified as safe."""


def _env_authorized() -> bool:
    return os.environ.get(AUTH_ENV, "").strip().lower() in TRUTHY


def authorized(config: dict | None = None) -> bool:
    """Return whether a human granted the escape. The config argument is inert because a config file is a file the agent can write."""
    del config
    return _env_authorized()


def grants_escape(text: str | None) -> bool:
    """Checked because a rule kill switch or self-authorization key written to the gate config would let an agent turn off its own hard blocks."""
    if not text:
        return False
    try:
        settings = flatten_settings(json.loads(text))
    except (ValueError, TypeError):
        return False
    if settings.get(AUTH_KEY):
        return True
    gates = exact_string_dict(settings.get("rule_gates"))
    if any(rule in ALWAYS_BLOCKING_RULES and state != "enforce" for rule, state in gates.items()):
        return True
    if "state_root" in settings or "ledger_root" in settings:
        return True
    family_gates = exact_string_dict(settings.get("gates"))
    return all(
        family_gates.get(family) == "off" if family in family_gates else settings.get(family) is False
        for family in GATE_FAMILIES
    )


def path_findings(
    path: str,
    config: dict | None = None,
    home: str | os.PathLike[str] | None = None,
    content: str | None = None,
) -> list[dict]:
    """Return blocking findings for a pending write target, with config inert because only the environment can release these rules."""
    if not path or path == "<pending>":
        return []
    try:
        resolved = _resolve(path, home)
    except UnresolvableTildePath:
        if _env_authorized():
            return []
        return [_finding("live_client_surface", path, "Unresolvable ~user path in " + path, LIVE_ACTION)]
    if resolved is None or _env_authorized():
        return []
    return _write_target_findings(resolved, path, home, content)


def _write_target_findings(
    resolved: Path,
    path: str,
    home: str | os.PathLike[str] | None,
    content: str | None,
) -> list[dict]:
    if _is_gate_config(resolved) and grants_escape(content):
        return [_finding("config_seal", path, "Self-granted gate escape in " + path, GRANT_ACTION)]
    if _is_state_path(resolved, home):
        return [_finding("state_mutation", path, "Watcher state path in " + path, STATE_ACTION)]
    rule = _live_client_rule(resolved, _normalize(_home_root(home)))
    if rule is not None:
        return [_finding(rule, path, "Live client install path in " + path, LIVE_ACTION)]
    return (
        [_finding("config_seal", path, "Gate config edit in " + path, SEAL_ACTION)]
        if _is_config_seal(resolved)
        else []
    )


def is_live_client_path(path: str, home: str | os.PathLike[str] | None = None) -> bool:
    """Needed because the Bash gate only has a raw command string, not a parsed tool_input path, so it must resolve live-client paths from text instead."""
    try:
        resolved = _resolve(path, home)
    except UnresolvableTildePath:
        return True
    if resolved is None:
        return False
    return _live_client_rule(resolved, _normalize(_home_root(home))) is not None


def _finding(rule: str, path: str, detail: str, action: str) -> dict:
    return {
        "family": "self_protection",
        "rule": rule,
        "line": 1,
        "detail": detail,
        "force": True,
        "snippet": path.strip()[:180],
        "action": action,
    }


def _home_root(home: str | os.PathLike[str] | None) -> Path:
    return Path(home).expanduser() if home is not None else Path.home()


def _resolve(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    try:
        candidate = Path(path)
    except (TypeError, ValueError):
        return None
    text = str(candidate)
    if text == "~" or text.startswith("~/"):
        candidate = _home_root(home) / text[2:]
    elif text.startswith("~"):
        candidate = _expand_other_user(text)
    if not candidate.is_absolute():
        candidate = Path(os.getcwd()) / candidate
    return _normalize(candidate)


def _expand_other_user(text: str) -> Path:
    expanded = os.path.expanduser(text)
    if expanded == text:
        raise UnresolvableTildePath(text)
    return Path(expanded)


def _normalize(path: Path) -> Path:
    """Resolve symlinks and ".." together via realpath, since popping ".." textually before resolving symlinks lets a symlink plus ".." land outside the intended target."""
    return Path(os.path.realpath(path))


def _relative_parts(path: Path, home: Path) -> list[str] | None:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return None
    return [part.lower() for part in relative.parts]


NESTED_CLIENT_DIRS = ([".agents", "skills"], [".config", "opencode"])


def _reaches_into_a_client_home(parts: list[str]) -> bool:
    if parts[0] in CLIENT_HOME_DIRS:
        return True
    if len(parts) < 3:
        return False
    head = parts[:2]
    if head == [".local", "bin"]:
        return parts[2].startswith("agent-discipline")
    return head in NESTED_CLIENT_DIRS


def _live_client_rule(path: Path, home: Path) -> str | None:
    parts = _relative_parts(path, home)
    if not parts:
        return None
    if parts[0] == ".claude":
        return _claude_rule(parts)
    return "live_client_surface" if _reaches_into_a_client_home(parts) else None


def _claude_rule(parts: list[str]) -> str | None:
    if len(parts) == 1:
        return "live_client_surface"
    entry = parts[1]
    if entry in CLAUDE_EXEMPT_DIRS:
        return None
    nested_wiring = (
        entry == "plugins" or entry in CLAUDE_WIRING_DIRS
    ) and len(parts) > 2
    protected_file = (
        entry.startswith("settings") and entry.endswith(".json")
    ) or entry == "claude.md"
    return "live_client_surface" if nested_wiring or protected_file else None


def _is_gate_config(path: Path) -> bool:
    return path.name.lower() == CONFIG_SEAL_BASENAME


def _is_state_path(path: Path, home: str | os.PathLike[str] | None) -> bool:
    override = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    root = Path(override).expanduser() if override else _home_root(home) / ".agent-discipline"
    try:
        path.relative_to(_normalize(root))
    except ValueError:
        return False
    return True


def _is_config_seal(path: Path) -> bool:
    """Seal an existing gate config, allowing first creation, and treat a stat error as present so that the gate fails closed."""
    if not _is_gate_config(path):
        return False
    try:
        return path.exists()
    except OSError:
        return True
