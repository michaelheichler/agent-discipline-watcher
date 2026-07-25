from __future__ import annotations

import json
import os
from pathlib import Path


ALWAYS_ON_RULES = (
    "Two rules ignore every switch below: suppression_escape_hatch and what_comment. "
    "Neither clean_code nor exempt_paths suppresses them, because scanner.scan_all emits both "
    "from _unconditional_findings, before the exemption check and outside the clean_code guard. "
    "Turning clean_code off still leaves what_comment blocking on every scanned code file."
)
DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    "max_rows": 8,
    "exempt_paths": [],
}
CONFIG_NAME = ".agent-discipline.json"


def _project_settings(cwd: str | os.PathLike[str]) -> dict:
    """Flatten the nearest project config, treating an absent or non-object file as no settings."""
    path = _find_project_config(Path(cwd))
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    checks = data.get("checks")
    settings = dict(checks) if isinstance(checks, dict) else {}
    settings.update({key: value for key, value in data.items() if key != "checks"})
    return settings


def effective_config(config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> dict:
    merged = dict(DEFAULTS)
    if cwd is not None:
        merged.update(_project_settings(cwd))
    if config:
        merged.update(config)
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
