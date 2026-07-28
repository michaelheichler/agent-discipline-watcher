"""Protected-path policy so an agent cannot edit a live client install or seal off the project gate config."""
from __future__ import annotations

import os
from pathlib import Path

CONFIG_SEAL_BASENAME = ".agent-discipline.json"
AUTH_ENV = "ADW_ALLOW_PROTECTED_EDIT"
AUTH_KEY = "protected_paths_authorized"
TRUTHY = frozenset({"1", "true", "yes", "on"})

# Scratch, transcripts, and installed plugins sit under the Claude home without being wiring, so that they stay writable.
CLAUDE_EXEMPT_DIRS = frozenset({
    "jobs", "projects", "plugins", "todos", "shell-snapshots",
    "statsig", "logs", "ide", "tool-results", "downloads",
})
CLAUDE_WIRING_DIRS = frozenset({"skills", "agents", "hooks", "commands"})
CLIENT_HOME_DIRS = frozenset({".codex", ".pi"})

LIVE_ACTION = "Change the repo source and reinstall instead of editing the live install."
SEAL_ACTION = "Fix the reported finding instead of changing the gate config."


def authorized(config: dict | None = None) -> bool:
    """Return whether a human granted the protected-path escape, checked before any finding so that the grant stays outside gate state."""
    if os.environ.get(AUTH_ENV, "").strip().lower() in TRUTHY:
        return True
    return bool((config or {}).get(AUTH_KEY))


def path_findings(path: str, config: dict | None = None, home: str | os.PathLike[str] | None = None) -> list[dict]:
    """Return blocking findings for a pending write target, empty when the path carries no policy."""
    if not path or path == "<pending>":
        return []
    if authorized(config):
        return []
    resolved = _resolve(path, home)
    if resolved is None:
        return []
    root = Path(home).expanduser() if home is not None else Path.home()
    rule = _live_client_rule(resolved, _normalize(root))
    if rule is not None:
        return [_finding(rule, path, "Live client install path in " + path, LIVE_ACTION)]
    if _is_config_seal(resolved):
        return [_finding("config_seal", path, "Gate config edit in " + path, SEAL_ACTION)]
    return []


def is_live_client_path(path: str, home: str | os.PathLike[str] | None = None) -> bool:
    """Return whether a raw token names a live client install, used by the Bash gate where no tool_input path exists."""
    resolved = _resolve(path, home)
    if resolved is None:
        return False
    root = Path(home).expanduser() if home is not None else Path.home()
    return _live_client_rule(resolved, _normalize(root)) is not None


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


def _resolve(path: str, home: str | os.PathLike[str] | None) -> Path | None:
    """Expand and absolutize a target without touching the filesystem, because the path may not exist yet."""
    try:
        candidate = Path(path)
    except (TypeError, ValueError):
        return None
    if str(candidate).startswith("~"):
        base = Path(home).expanduser() if home is not None else Path.home()
        candidate = base / str(candidate).lstrip("~").lstrip("/")
    if not candidate.is_absolute():
        candidate = Path(os.getcwd()) / candidate
    return _normalize(candidate)


def _normalize(path: Path) -> Path:
    """Collapse dot segments without resolving symlinks, so that a sandbox HOME under a symlinked temp dir still matches."""
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == ".." and parts and parts[-1] not in ("", os.sep):
            parts.pop()
            continue
        parts.append(part)
    return Path(*parts) if parts else path


def _relative_parts(path: Path, home: Path) -> list[str] | None:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return None
    return [part.lower() for part in relative.parts]


def _live_client_rule(path: Path, home: Path) -> str | None:
    parts = _relative_parts(path, home)
    if not parts:
        return None
    top = parts[0]
    if top == ".claude":
        return _claude_rule(parts)
    if top in CLIENT_HOME_DIRS and len(parts) > 1:
        return "live_client_surface"
    if parts[:2] == [".agents", "skills"] and len(parts) > 2:
        return "live_client_surface"
    if parts[:2] == [".config", "opencode"] and len(parts) > 2:
        return "live_client_surface"
    if parts[:2] == [".local", "bin"] and len(parts) > 2 and parts[2].startswith("agent-discipline"):
        return "live_client_surface"
    return None


def _claude_rule(parts: list[str]) -> str | None:
    if len(parts) < 2:
        return None
    entry = parts[1]
    if entry in CLAUDE_EXEMPT_DIRS:
        return None
    if entry in CLAUDE_WIRING_DIRS and len(parts) > 2:
        return "live_client_surface"
    if entry.startswith("settings") and entry.endswith(".json"):
        return "live_client_surface"
    if entry == "claude.md":
        return "live_client_surface"
    return None


def _is_config_seal(path: Path) -> bool:
    """Seal an existing gate config, allowing first creation, and treat a stat error as present so that the gate fails closed."""
    if path.name.lower() != CONFIG_SEAL_BASENAME:
        return False
    try:
        return path.exists()
    except OSError:
        return True
