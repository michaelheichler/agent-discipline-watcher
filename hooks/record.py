from __future__ import annotations

import re
from pathlib import Path

from lib.config import effective_config
from lib.hookio import read_payload, write_payload
from lib.ledger import record_findings
from lib.scanner import scan_all

PATCH_FILE = re.compile(r"^\*\*\*\s+(?:Add|Update)\s+File:\s+(.+)$", re.MULTILINE)


def edited_paths(payload: dict) -> list[str]:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if path:
        return [path]
    patch = tool_input.get("patch") or tool_input.get("command") or tool_input.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    if isinstance(patch, str):
        return [match.strip().strip('"') for match in PATCH_FILE.findall(patch)]
    return []


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payload.get("cwd") or None)
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    cwd = Path(payload.get("cwd") or ".")
    for raw_path in edited_paths(payload):
        path = Path(raw_path)
        if not path.is_absolute():
            path = cwd / path
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        record_findings(str(path), scan_all(str(path), text, cfg), cfg)
    return {}


if __name__ == "__main__":
    write_payload(run(read_payload()))
