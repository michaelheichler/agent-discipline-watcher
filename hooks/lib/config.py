from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULTS = {
    "punctuation": True,
    "english": True,
    "clean_code": True,
    "max_rows": 8,
}
CONFIG_NAME = ".agent-discipline.json"


def effective_config(config: dict | None = None, cwd: str | os.PathLike[str] | None = None) -> dict:
    merged = dict(DEFAULTS)
    if cwd is not None:
        path = _find_project_config(Path(cwd))
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                checks = data.get("checks")
                if isinstance(checks, dict):
                    merged.update(checks)
                merged.update({k: v for k, v in data.items() if k != "checks"})
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


def enabled(config: dict, family: str) -> bool:
    return bool(effective_config(config).get(family, False))
