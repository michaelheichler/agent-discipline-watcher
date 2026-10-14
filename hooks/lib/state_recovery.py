"""Kept apart from session_state, because the agent may not repair state and would otherwise loop on a damaged file."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

BACKUP_SUFFIX = ".bak"
CORRUPT_SUFFIX = ".corrupt-"
RECOVERY_KEY = "state_recovered"


def atomic_write(path: Path, payload: str) -> None:
    """Replace the file atomically because separate hook processes must never observe partial JSON."""
    descriptor, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def parsed(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid session state object: {path}")
    return data


def _backup(path: Path) -> dict | None:
    try:
        return parsed(backup_path(path))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def restored(path: Path) -> dict | None:
    """Copied aside, not moved, so a recovery cut off before the restore leaves the damaged file for the next read to recover."""
    backup = _backup(path)
    if backup is None:
        return None
    try:
        return parsed(path)
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    aside = path.with_name(f"{path.name}{CORRUPT_SUFFIX}{time.time_ns()}")
    shutil.copyfile(path, aside)
    notice = (
        f"agent-discipline-watcher: the session state file was unreadable. It was moved to {aside} "
        "and the last good copy was restored. Changes after that copy are lost."
    )
    state = {**backup, RECOVERY_KEY: notice}
    atomic_write(path, json.dumps(state, ensure_ascii=True))
    return state
