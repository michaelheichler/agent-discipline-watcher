"""PostToolUse edit journal and scan gate."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lib.config import effective_config
from lib.hookio import read_payload, write_payload
from lib.reporting import append_row, compact_block, now_iso
from lib.scanner import read_scannable, scan_all

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


def _journal_edits(payload: dict, paths: list[str], root) -> None:
    """Record one journal row per edited path, swallowing write errors."""
    tool = str(payload.get("tool_name") or "")
    stamp = now_iso()
    for path in paths:
        append_row(
            {
                "ts": stamp,
                "session_id": str(payload.get("session_id") or ""),
                "hook": "record",
                "event": "edit",
                "family": "",
                "rule": "",
                "path": path,
                "tool": tool,
                "tool_use_id": str(payload.get("tool_use_id") or ""),
                "turn_id": "",
                "outcome": "",
            },
            root,
        )


def _scan_paths(paths: list[str], cwd: Path, cfg: dict) -> list[dict]:
    """Scan each edited path and return findings."""
    findings = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = cwd / path
        if not path.exists() or not path.is_file():
            continue
        text = read_scannable(path, cfg)
        if text is None:
            continue
        for finding in scan_all(str(path), text, cfg):
            item = dict(finding)
            item["path"] = str(path)
            findings.append(item)
    return findings


def run(payload: dict, config: dict | None = None) -> dict:
    cfg = effective_config(config, payload.get("cwd") or None)
    if payload.get("session_id"):
        cfg["session_id"] = payload["session_id"]
    cwd = Path(payload.get("cwd") or ".")
    paths = edited_paths(payload)
    # Gate the journal on session_id because a sessionless invocation cannot be attributed and must not write the production ledger.
    if payload.get("session_id"):
        _journal_edits(payload, paths, cfg.get("ledger_root"))
    findings = _scan_paths(paths, cwd, cfg)
    if findings:
        reason, _ = compact_block(findings, cfg)
        return {"decision": "block", "reason": reason}
    return {}


if __name__ == "__main__":
    payload = read_payload()
    response = run(payload)
    if response.get("decision") == "block":
        sys.stderr.write(response["reason"] + "\n")
        raise SystemExit(2)
    write_payload(response)
