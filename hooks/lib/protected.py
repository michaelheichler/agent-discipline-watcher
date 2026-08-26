"""Hard-blocked here because an agent that can edit its own watcher's live config or install can also disable the watcher."""
from __future__ import annotations

import json
import os
import re
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

WATCHER_NAME_PREFIX = "agent-discipline"
# Scoped to client install roots, because a working checkout carries the same name and must stay editable.
CLIENT_HOME_DIRS = frozenset({".claude", ".codex", ".pi", ".omp", ".agents", ".config", ".local"})
# Mirrors the files install.sh and pi/install.sh write hook entries into, because those are the only host files that can unwire the watcher.
WIRING_FILES = frozenset({
    (".claude", "settings.json"),
    (".claude", "settings.local.json"),
    (".codex", "config.toml"),
    (".codex", "hooks.json"),
    (".pi", "agent", "settings.json"),
    (".omp", "agent", "settings.json"),
})
# Text-level so that one pattern covers the JSON and TOML wirings alike, since both name the package or its hook runner.
WATCHER_WIRING_RE = re.compile(r"agent-discipline|/hooks/run\.sh")

INSTALL_ACTION = (
    "Change the repo source and reinstall instead of editing the live install. If this edit "
    "is intentional, ask the human to export "
    + AUTH_ENV
    + " in the hook environment, which releases every self-protection rule, not just this one."
)
WIRING_ACTION = (
    "Keep the agent-discipline-watcher hook entries in place. Edit this file around them, "
    "or reinstall to change how the watcher is wired."
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
        return [_finding("watcher_install_surface", path, "Unresolvable ~user path in " + path, INSTALL_ACTION)]
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
    if _reaches_install_surface(_literal(path, home), resolved, home):
        return [_finding("watcher_install_surface", path, "Live watcher install path in " + path, INSTALL_ACTION)]
    if _unwires_watcher(resolved, _normalize(_home_root(home)), content):
        return [_finding("watcher_wiring_removal", path, "Write drops the watcher hooks from " + path, WIRING_ACTION)]
    return (
        [_finding("config_seal", path, "Gate config edit in " + path, SEAL_ACTION)]
        if _is_config_seal(resolved)
        else []
    )


def is_install_surface_path(
    path: str,
    home: str | os.PathLike[str] | None = None,
) -> bool:
    """Needed because the Bash gate only has a raw command string, not a parsed tool_input path, so it must resolve install paths from text instead."""
    try:
        literal = _literal(path, home)
        resolved = _resolve(path, home)
    except UnresolvableTildePath:
        return True
    if resolved is None:
        return False
    return _reaches_install_surface(literal, resolved, home)


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


def _literal(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    """Expanded but not resolved, because the install rule reads the route the human typed rather than the checkout a symlink points at."""
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
    return candidate


def _resolve(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    candidate = _literal(path, home)
    return None if candidate is None else _normalize(candidate)


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


def _reaches_install_surface(literal: Path | None, resolved: Path, home: str | os.PathLike[str] | None) -> bool:
    """Judged on the typed route as well as the resolved one, because every install is a symlink whose target is the checkout the human still has to edit, while a symlink aimed into an install must not slip past."""
    if literal is not None and _is_install_surface(literal, _home_root(home)):
        return True
    return _is_install_surface(resolved, _normalize(_home_root(home)))


def _is_install_surface(path: Path, home: Path) -> bool:
    parts = _relative_parts(path, home)
    if not parts or parts[0] not in CLIENT_HOME_DIRS:
        return False
    return any(part.startswith(WATCHER_NAME_PREFIX) for part in parts[1:])


def _unwires_watcher(resolved: Path, home: Path, content: str | None) -> bool:
    """Judged by content rather than by path, because these files also carry host settings the agent is entitled to change."""
    parts = _relative_parts(resolved, home)
    if parts is None or tuple(parts) not in WIRING_FILES:
        return False
    if not _has_watcher_wiring(resolved):
        return False
    return content is None or not WATCHER_WIRING_RE.search(content)


def _has_watcher_wiring(path: Path) -> bool:
    """Treats an unreadable file as wired, because a write that cannot be compared against the current wiring cannot be cleared."""
    try:
        return bool(WATCHER_WIRING_RE.search(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError):
        return True


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
