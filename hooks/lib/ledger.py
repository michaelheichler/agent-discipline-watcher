from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def ledger_path(config: dict | None = None) -> Path:
    if config and config.get("ledger_path"):
        return Path(config["ledger_path"])
    session = "default"
    if config and config.get("session_id"):
        session = "".join(ch for ch in str(config["session_id"]) if ch.isalnum() or ch in "_-")[:64]
    return Path(tempfile.gettempdir()) / f"agent-discipline-watcher-{session}.json"


def clear_ledger(config: dict | None = None) -> None:
    path = ledger_path(config)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def record_findings(path: str, findings: list[dict], config: dict | None = None) -> None:
    ledger = read_ledger(config)
    kept = [entry for entry in ledger if entry.get("path") != path]
    kept.append({"path": path, "findings": findings, "touched": True})
    _write_ledger(kept, config)


def read_ledger(config: dict | None = None) -> list[dict]:
    path = ledger_path(config)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def touched_files(config: dict | None = None) -> list[str]:
    rows = []
    for entry in read_ledger(config):
        path = entry.get("path")
        if entry.get("touched") and isinstance(path, str) and path:
            rows.append(path)
    return rows


def _write_ledger(rows: list[dict], config: dict | None = None) -> None:
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=True, indent=2)
