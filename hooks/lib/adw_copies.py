"""Because Claude Desktop loads account plugins beside the Claude Code plugin, an older ADW copy can run every hook a second time without the fixes of the running one."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import NamedTuple

PLUGIN_NAME = "agent-discipline-watcher"
RELEASE_RE = re.compile(r"^## (\d+)\.(\d+)\.(\d+)\b", re.MULTILINE)
HEAD_BYTES = 4096
MAX_ACCOUNT_PLUGINS = 200
ACCOUNT_PLUGINS = "Library/Application Support/Claude/local-agent-mode-sessions/*/*/rpm/*"
CLI_RECORD = ".claude/plugins/installed_plugins.json"
SHARED_INSTALL = ".adw/install/agent-discipline-watcher"
ACCOUNT_LABEL = "Claude account plugin (Desktop and Cowork)"
CLI_LABEL = "Claude Code plugin"
SHARED_LABEL = "Codex and OMP install"
Release = tuple[int, int, int]


class Copy(NamedTuple):
    root: Path
    release: Release
    label: str


def release_of(root: Path) -> Release | None:
    """Read from the changelog, because the plugin manifest of older copies names no version."""
    try:
        with (root / "CHANGELOG.md").open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(HEAD_BYTES)
    except OSError:
        return None
    match = RELEASE_RE.search(head)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def own_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_adw(root: Path) -> bool:
    try:
        manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")[:HEAD_BYTES])
    except (OSError, ValueError):
        return False
    return type(manifest) is dict and manifest.get("name") == PLUGIN_NAME


def _cli_roots(home: Path) -> list[Path]:
    """Taken from the install record, because the cache keeps old copies that Claude Code no longer loads."""
    try:
        record = json.loads((home / CLI_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = record.get("plugins") if type(record) is dict else None
    entries = plugins.get(f"{PLUGIN_NAME}@{PLUGIN_NAME}") if type(plugins) is dict else None
    paths = [entry.get("installPath") for entry in entries or [] if type(entry) is dict]
    return [Path(path) for path in paths if isinstance(path, str) and path]


def _account_roots(home: Path) -> list[Path]:
    found = []
    for index, root in enumerate(home.glob(ACCOUNT_PLUGINS)):
        if index >= MAX_ACCOUNT_PLUGINS:
            break
        if _is_adw(root):
            found.append(root)
    return found


def copies(home: Path | None = None) -> list[Copy]:
    base = home if home is not None else Path.home()
    labelled = [(root, CLI_LABEL) for root in _cli_roots(base)]
    labelled += [(base / SHARED_INSTALL, SHARED_LABEL)]
    labelled += [(root, ACCOUNT_LABEL) for root in _account_roots(base)]
    found = []
    for root, label in labelled:
        version = release_of(root)
        if version is not None:
            found.append(Copy(root, version, label))
    return found


def stale(home: Path | None = None, own: Path | None = None) -> list[Copy]:
    """Older than the running copy only, because an equal copy runs the same gates."""
    running = own if own is not None else own_root()
    current = release_of(running)
    if current is None:
        return []
    resolved = running.resolve()
    return [copy for copy in copies(home) if copy.release < current and copy.root.resolve() != resolved]


def _dotted(version: Release) -> str:
    return ".".join(map(str, version))


def notice(found: list[Copy], own: Path | None = None) -> str:
    """Named by host and path, because the user removes the copy where it was installed."""
    if not found:
        return ""
    current = release_of(own if own is not None else own_root())
    running = _dotted(current) if current else "this release"
    listed = "\n".join(f"- {_dotted(copy.release)} as the {copy.label} at {copy.root}" for copy in found)
    return (
        f"agent-discipline-watcher: an older ADW copy runs on this machine beside {running}. "
        f"It runs every hook a second time without the fixes of {running}. Remove or update it.\n{listed}"
    )


def status_lines(home: Path | None = None) -> list[str]:
    """Versions shown per copy, because two copies at different releases block on different rules."""
    rows = [f"  {_dotted(copy.release)} {copy.label}: {copy.root}" for copy in copies(home)]
    return ["ADW copies on this machine:", *rows] if rows else ["ADW copies on this machine: none found"]
