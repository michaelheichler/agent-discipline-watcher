"""Hard-blocked here because an agent that can edit its own watcher's live config or install can also disable the watcher."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    # Relative first because every hook entry script imports this module as lib.protected, where a bare name cannot resolve.
    from .config import ALWAYS_BLOCKING_RULES, GATE_FAMILIES, flatten_settings
    from .findings import Finding
    from .payloads import exact_string_dict
except ImportError:
    from config import ALWAYS_BLOCKING_RULES, GATE_FAMILIES, flatten_settings
    from findings import Finding
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


@dataclass(frozen=True, slots=True)
class ProtectedWrite:
    path: str
    home: str | os.PathLike[str] | None
    content: str | None


@dataclass(frozen=True, slots=True)
class ResolvedProtectedWrite:
    resolved: Path
    requested: ProtectedWrite


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
    return _silences_every_family(settings)


UNIVERSAL_GLOBS = frozenset({"*", "**", "*/*", "**/*", "*/**", "**/**", "/**", "./**"})


def _silences_every_family(settings: dict) -> bool:
    return (
        _gated_off_everywhere(settings)
        or _killed_everywhere(settings)
        or _exempted_everywhere(settings)
    )


def _gated_off_everywhere(settings: dict) -> bool:
    family_gates = exact_string_dict(settings.get("gates"))
    return all(
        family_gates.get(family) == "off" if family in family_gates else settings.get(family) is False
        for family in GATE_FAMILIES
    )


def _killed_everywhere(settings: dict) -> bool:
    switches = exact_string_dict(settings.get("kill_switches"))
    return all(bool(switches.get(family)) for family in GATE_FAMILIES)


def _exempted_everywhere(settings: dict) -> bool:
    paths = settings.get("exempt_paths")
    if isinstance(paths, list) and any(
        isinstance(entry, str) and entry.strip() in UNIVERSAL_GLOBS for entry in paths
    ):
        return True
    families = exact_string_dict(settings.get("exempt_families"))
    for glob, listed in families.items():
        if glob.strip() not in UNIVERSAL_GLOBS or not isinstance(listed, list):
            continue
        if all(family in listed for family in GATE_FAMILIES):
            return True
    return False


def _protected_write(path: str, values: tuple[object, ...], fields: dict[str, object]) -> ProtectedWrite:
    if len(values) > 3:
        raise TypeError("path_findings accepts at most four legacy arguments")
    names = ("config", "home", "content")
    legacy = dict(zip(names, values, strict=False))
    for name, value in fields.items():
        if name not in names or name in legacy:
            raise TypeError(f"path_findings got an invalid keyword: {name}")
        legacy[name] = value
    home = legacy.get("home")
    content = legacy.get("content")
    if home is not None and not isinstance(home, (str, os.PathLike)):
        raise TypeError("path_findings home must be a path or None")
    if content is not None and not isinstance(content, str):
        raise TypeError("path_findings content must be a string or None")
    return ProtectedWrite(path, home, content)


def path_findings(write: ProtectedWrite | str, *values: object, **fields: object) -> list[dict]:
    """Return blocking findings for a pending write target, with config inert because only the environment can release these rules."""
    if isinstance(write, str):
        write = _protected_write(write, values, fields)
    elif values or fields:
        raise TypeError("ProtectedWrite cannot be combined with legacy arguments")
    if not write.path or write.path == "<pending>":
        return []
    try:
        resolved = _resolve(write.path, write.home)
    except UnresolvableTildePath:
        if _env_authorized():
            return []
        return [_finding(Finding(family="self_protection", rule="watcher_install_surface", line=1, detail="Unresolvable ~user path in " + write.path, force=True, snippet=write.path.strip()[:180], action=INSTALL_ACTION, path=None, severity=None, tool_use_id=None))]
    if resolved is None or _env_authorized():
        return []
    return _write_target_findings(ResolvedProtectedWrite(resolved, write))


def _write_target_findings(write: ResolvedProtectedWrite) -> list[dict]:
    resolved = write.resolved
    path = write.requested.path
    home = write.requested.home
    content = write.requested.content
    if _is_gate_config(resolved) and grants_escape(content):
        return [_finding(Finding(family="self_protection", rule="config_seal", line=1, detail="Self-granted gate escape in " + path, force=True, snippet=path.strip()[:180], action=GRANT_ACTION, path=None, severity=None, tool_use_id=None))]
    if _is_state_path(resolved, home):
        return [_finding(Finding(family="self_protection", rule="state_mutation", line=1, detail="Watcher state path in " + path, force=True, snippet=path.strip()[:180], action=STATE_ACTION, path=None, severity=None, tool_use_id=None))]
    if _reaches_install_surface(_literal(path, home), resolved, home):
        return [_finding(Finding(family="self_protection", rule="watcher_install_surface", line=1, detail="Live watcher install path in " + path, force=True, snippet=path.strip()[:180], action=INSTALL_ACTION, path=None, severity=None, tool_use_id=None))]
    if _unwires_watcher(resolved, _normalize(_home_root(home)), content):
        return [_finding(Finding(family="self_protection", rule="watcher_wiring_removal", line=1, detail="Write drops the watcher hooks from " + path, force=True, snippet=path.strip()[:180], action=WIRING_ACTION, path=None, severity=None, tool_use_id=None))]
    return (
        [_finding(Finding(family="self_protection", rule="config_seal", line=1, detail="Gate config edit in " + path, force=True, snippet=path.strip()[:180], action=SEAL_ACTION, path=None, severity=None, tool_use_id=None))]
        if _is_unreadable_config_write(resolved, content)
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


def _finding(finding: Finding) -> dict:
    return finding.to_dict()


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
    """The legacy root stays guarded because an unmigrated machine still keeps its state there."""
    base = _home_root(home)
    for root in (base / ".adw", base / ".agent-discipline"):
        try:
            path.relative_to(_normalize(root))
        except ValueError:
            continue
        return True
    return False


def _is_unreadable_config_write(path: Path, content: str | None) -> bool:
    """Fails closed on an unreadable body against an existing config because it could carry any escape, while a readable benign edit stays the human's to make."""
    if not _is_gate_config(path) or (content is not None and content.strip()):
        return False
    try:
        return path.exists()
    except OSError:
        return True
